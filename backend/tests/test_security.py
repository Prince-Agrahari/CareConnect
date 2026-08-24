"""Security audit tests: secrets stay out of source, tokens and roles stay server-side."""

from pathlib import Path
import re

from app.main import PLACEHOLDER_JWT_SECRET, _assert_runtime_secrets


ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "dist",
    "__pycache__",
    ".pytest_cache",
    "htmlcov",
    "coverage",
}
SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".example", ".env", ".json", ".yml", ".yaml", ".html", ".css"}

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    re.compile(r"GOCSPX-[A-Za-z0-9_-]+"),
    re.compile(r"ya29\.[A-Za-z0-9._-]+"),
)


def _iter_source_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in SOURCE_SUFFIXES and path.name not in {".env", ".gitignore"}:
            continue
        files.append(path)
    return files


def test_env_files_are_gitignored() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore
    assert "!.env.example" in gitignore
    assert not (ROOT / ".env").exists()
    assert not (ROOT / "backend" / ".env").exists()
    assert not (ROOT / "frontend" / ".env").exists()


def test_example_env_files_do_not_contain_credentials() -> None:
    secret_keys = {
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_CLIENT_ID",
        "GEMINI_API_KEY",
        "SENDGRID_API_KEY",
        "JWT_SECRET_KEY",
        "DATABASE_URL",
    }
    for relative in (".env.example", "backend/.env.example", "frontend/.env.example"):
        path = ROOT / relative
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            if key in secret_keys:
                assert value == "", f"{relative} must not commit a real {key}"


def test_source_tree_has_no_live_provider_secrets() -> None:
    hits: list[str] = []
    for path in _iter_source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                hits.append(f"{path.relative_to(ROOT)}: {pattern.pattern}")
    assert hits == []


def test_placeholder_jwt_secret_is_rejected_in_production(monkeypatch) -> None:
    from app.core import config as config_mod
    from app.main import settings as app_settings

    monkeypatch.setattr(app_settings, "APP_ENV", "production")
    monkeypatch.setattr(app_settings, "JWT_SECRET_KEY", PLACEHOLDER_JWT_SECRET)
    monkeypatch.setattr(config_mod.settings, "APP_ENV", "production")
    monkeypatch.setattr(config_mod.settings, "JWT_SECRET_KEY", PLACEHOLDER_JWT_SECRET)
    try:
        _assert_runtime_secrets()
        raise AssertionError("placeholder JWT secret must not be allowed in production")
    except RuntimeError as exc:
        assert "JWT_SECRET_KEY" in str(exc)
