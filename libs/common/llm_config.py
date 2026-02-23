from __future__ import annotations


def validate_api_key_ref(api_key_ref: str | None) -> None:
    if not api_key_ref:
        return
    value = api_key_ref.strip()
    if value.startswith("env:"):
        env_var = value.split("env:", 1)[1].strip()
        if not env_var:
            raise ValueError("invalid_env_ref")
        return
    if value.startswith("secretkeyref:plugin:"):
        parts = value.split(":", 3)
        if len(parts) != 4:
            raise ValueError("invalid_secret_ref")
        plugin_name = parts[2].strip()
        path = parts[3].strip()
        if not plugin_name or not path:
            raise ValueError("invalid_secret_ref")
        return
    raise ValueError("invalid_api_key_ref")
