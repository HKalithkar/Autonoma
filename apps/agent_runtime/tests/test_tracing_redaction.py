from apps.agent_runtime.app.tracing import redact_preview


def test_redact_preview_masks_secrets() -> None:
    sample = (
        "token=abc123 secretkeyref:plugin:vault:kv/langfuse/secret_key "
        "Authorization: Bearer abc.def.ghi sk-1234567890abcdef password=hunter2"
    )
    preview, redacted, truncated = redact_preview(sample, max_chars=1000)
    assert redacted is True
    assert truncated is False
    assert "secretkeyref:[redacted]" in preview
    assert "bearer [redacted]" in preview.lower()
    assert "sk-[redacted]" in preview
    assert "password=[redacted]" in preview


def test_redact_preview_truncates() -> None:
    sample = "a" * 50
    preview, redacted, truncated = redact_preview(sample, max_chars=10)
    assert preview == "a" * 10
    assert redacted is False
    assert truncated is True
