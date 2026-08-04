from pathlib import Path


def test_env_example_does_not_expose_removed_codex_kernel_settings():
    root = Path(__file__).resolve().parents[2]
    text = (root / ".env.example").read_text(encoding="utf-8")

    for name in (
        "IKAROS_KERNEL",
        "IKAROS_CODEX_COMMAND",
        "IKAROS_CODEX_ARGS",
        "IKAROS_CODEX_MODEL",
        "IKAROS_CODEX_EFFORT",
        "IKAROS_CODEX_SANDBOX",
        "IKAROS_CODEX_APPROVAL_POLICY",
        "IKAROS_CODEX_WRITABLE_ROOTS",
        "IKAROS_CODEX_SKILL_ALLOWLIST",
        "IKAROS_CODEX_SKILL_DENYLIST",
        "IKAROS_CODEX_TIMEOUT_SEC",
        "IKAROS_CODEX_REQUEST_TIMEOUT_SEC",
    ):
        assert f"{name}=" not in text
