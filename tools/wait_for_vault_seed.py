import os
import time
import urllib.request


def main() -> int:
    addr = os.getenv("VAULT_ADDR", "http://vault:8200").rstrip("/")
    token = os.getenv("VAULT_TOKEN", "")
    data_url = f"{addr}/v1/kv/data/autonoma"
    headers = {"X-Vault-Token": token} if token else {}

    for _ in range(40):
        try:
            req = urllib.request.Request(data_url, headers=headers)
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return 0
        except Exception:
            pass
        time.sleep(1)
    raise SystemExit("Vault seed not ready")


if __name__ == "__main__":
    raise SystemExit(main())
