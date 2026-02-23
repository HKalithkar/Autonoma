#!/usr/bin/env python3
"""
fetch_url.py - security-first URL fetch helper for Codex CLI tools.

Key safety features:
- Optional allowlist for hostnames / domains
- Blocks localhost + private IP ranges by default (SSRF mitigation)
- Enforces timeouts, max bytes, and redirect limits
- Returns either raw body or JSON envelope
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import sys
import time
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple
from urllib.parse import urlparse

import requests

PRIVATE_NETS = [
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network("10.0.0.0/8"),  # private
    ipaddress.ip_network("172.16.0.0/12"),  # private
    ipaddress.ip_network("192.168.0.0/16"),  # private
    ipaddress.ip_network("169.254.0.0/16"),  # link-local
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 unique local
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


@dataclass
class Allowlist:
    hosts: Tuple[str, ...] = ()
    domains: Tuple[str, ...] = ()

    def is_allowed(self, hostname: str) -> bool:
        hostname = hostname.lower().strip(".")
        if not hostname:
            return False

        # Exact host allowlist
        if self.hosts and hostname in {h.lower().strip(".") for h in self.hosts}:
            return True

        # Domain suffix allowlist (e.g. example.com allows a.example.com)
        if self.domains:
            for d in self.domains:
                d = d.lower().strip(".")
                if hostname == d or hostname.endswith("." + d):
                    return True

        # If no allowlist configured, treat as allowed (but SSRF blocks may still apply)
        return not (self.hosts or self.domains)


def parse_allowlist(path: Optional[str]) -> Allowlist:
    if not path:
        return Allowlist()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    hosts = tuple(data.get("hosts", []) or [])
    domains = tuple(data.get("domains", []) or [])
    return Allowlist(hosts=hosts, domains=domains)


def resolve_host_ips(hostname: str) -> Iterable[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    # Resolve A/AAAA. If DNS fails, raise.
    infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
    seen = set()
    for info in infos:
        ip_str = info[4][0]
        if ip_str in seen:
            continue
        seen.add(ip_str)
        yield ipaddress.ip_address(ip_str)


def is_private_ip(ip_obj: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return any(ip_obj in net for net in PRIVATE_NETS)


def validate_url(url: str) -> Tuple[str, str]:
    """
    Returns (scheme, hostname). Raises ValueError on invalid.
    """
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        raise ValueError(f"Only http/https are allowed (got: {p.scheme!r})")
    if not p.netloc:
        raise ValueError("URL missing hostname")
    hostname = p.hostname or ""
    if not hostname:
        raise ValueError("Could not parse hostname from URL")
    return p.scheme, hostname


def fetch(
    url: str,
    *,
    method: str,
    headers: Dict[str, str],
    data: Optional[str],
    timeout_s: float,
    max_bytes: int,
    max_redirects: int,
    verify_tls: bool,
) -> Tuple[int, Dict[str, str], bytes, str]:
    """
    Returns (status_code, headers, body_bytes, final_url)
    """
    sess = requests.Session()
    sess.max_redirects = max_redirects

    req_headers = dict(headers or {})
    # A conservative default UA helps some servers.
    req_headers.setdefault("User-Agent", "fetch_url/1.0 (+CodexTool)")

    with sess.request(
        method=method,
        url=url,
        headers=req_headers,
        data=data.encode("utf-8")
        if (data is not None and method in ("POST", "PUT", "PATCH"))
        else None,
        timeout=timeout_s,
        allow_redirects=True,
        stream=True,
        verify=verify_tls,
    ) as r:
        r.raise_for_status()  # turn 4xx/5xx into exception
        buf = bytearray()
        for chunk in r.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            buf.extend(chunk)
            if len(buf) > max_bytes:
                raise ValueError(f"Response exceeded max_bytes={max_bytes}")
        return r.status_code, dict(r.headers), bytes(buf), r.url


def main() -> int:
    ap = argparse.ArgumentParser(description="Security-first URL fetch helper.")
    ap.add_argument("url", help="http(s) URL to fetch")
    ap.add_argument(
        "--method", default="GET", choices=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"]
    )
    ap.add_argument(
        "--header", action="append", default=[], help="Header, format: 'Key: Value' (repeatable)"
    )
    ap.add_argument("--data", default=None, help="Request body (for POST/PUT/PATCH)")
    ap.add_argument("--timeout", type=float, default=15.0, help="Timeout seconds (default: 15)")
    ap.add_argument(
        "--max-bytes", type=int, default=1_000_000, help="Max response bytes (default: 1,000,000)"
    )
    ap.add_argument("--max-redirects", type=int, default=3, help="Max redirects (default: 3)")
    ap.add_argument(
        "--no-ssrf-block",
        action="store_true",
        help="Disable private/localhost IP blocking (NOT recommended)",
    )
    ap.add_argument(
        "--allowlist", default=None, help="Path to allowlist JSON: {hosts:[...], domains:[...]}"
    )
    ap.add_argument(
        "--json",
        dest="json_out",
        action="store_true",
        help="Output JSON envelope (default: raw body)",
    )
    ap.add_argument("--output", default=None, help="Write body to file instead of stdout")
    ap.add_argument(
        "--insecure", action="store_true", help="Disable TLS verification (NOT recommended)"
    )
    args = ap.parse_args()

    try:
        _, hostname = validate_url(args.url)
        allowlist = parse_allowlist(args.allowlist)

        if not allowlist.is_allowed(hostname):
            raise ValueError(f"Host not allowed by allowlist: {hostname}")

        if not args.no_ssrf_block:
            # Resolve DNS and block private ranges
            for ip_obj in resolve_host_ips(hostname):
                if is_private_ip(ip_obj):
                    raise ValueError(
                        f"Blocked private/localhost IP for hostname {hostname}: {ip_obj}"
                    )

        # Parse headers
        headers: Dict[str, str] = {}
        for h in args.header:
            if ":" not in h:
                raise ValueError(f"Invalid --header {h!r}, expected 'Key: Value'")
            k, v = h.split(":", 1)
            headers[k.strip()] = v.strip()

        started = time.time()
        status, resp_headers, body, final_url = fetch(
            args.url,
            method=args.method,
            headers=headers,
            data=args.data,
            timeout_s=args.timeout,
            max_bytes=args.max_bytes,
            max_redirects=args.max_redirects,
            verify_tls=not args.insecure,
        )
        elapsed_ms = int((time.time() - started) * 1000)

        if args.json_out:
            out = {
                "ok": True,
                "status": status,
                "final_url": final_url,
                "elapsed_ms": elapsed_ms,
                "content_type": resp_headers.get("Content-Type"),
                "headers": resp_headers,
                "body_base64": None,
                "body_text": None,
                "body_bytes": len(body),
            }

            # Heuristic: treat as text if content-type indicates text/json or body looks like utf-8.
            ct = (resp_headers.get("Content-Type") or "").lower()
            is_text = any(
                x in ct
                for x in ["text/", "application/json", "application/xml", "application/javascript"]
            )
            if is_text:
                try:
                    out["body_text"] = body.decode("utf-8")
                except UnicodeDecodeError:
                    out["body_base64"] = __import__("base64").b64encode(body).decode("ascii")
            else:
                out["body_base64"] = __import__("base64").b64encode(body).decode("ascii")

            sys.stdout.write(json.dumps(out, ensure_ascii=False))
            sys.stdout.write("\n")
            return 0

        # Raw body output
        if args.output:
            with open(args.output, "wb") as f:
                f.write(body)
        else:
            # Write to stdout as bytes
            sys.stdout.buffer.write(body)
        return 0

    except requests.exceptions.RequestException as e:
        sys.stderr.write(f"fetch_url error: HTTP error: {e}\n")
        return 2
    except Exception as e:
        sys.stderr.write(f"fetch_url error: {e}\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
