"""Paths, parameters and environment settings. Nothing secret is stored here."""
from __future__ import annotations

import contextvars
import json
import os
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    """Minimal .env loader so we don't need python-dotenv. Real env vars win."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

# Demo mode: separate workspace, never sends, never uses Neon.
DEMO = os.environ.get("KARGO_DEMO") == "1"
# KARGO_HOME relocates the working folders (demo, tests); defaults to the repo.
HOME = Path(os.environ.get("KARGO_HOME") or (ROOT / "demo" if DEMO else ROOT))

APPLICATIONS_DIR = HOME / "applications"
META_DIR = APPLICATIONS_DIR / ".meta"  # sidecar info per CV: source, consent, opt-ins
JDS_DIR = ROOT / "jds"
DATA_DIR = HOME / "data"
OUTBOX_DIR = HOME / "outbox"
BACKUP_DIR = HOME / "backups"
# The identity vault lives in its own folder. The scoring path (llm.py, scoring.py)
# never imports vault.py and never reads this directory.
VAULT_DIR = HOME / "vault"
PARAMS_PATH = ROOT / "rubric_params_v02.json"

DB_PATH = DATA_DIR / "kargo.db"
AUDIT_LOG_PATH = DATA_DIR / "decision_log.jsonl"
PARSE_FAILURES_PATH = DATA_DIR / "parse_failures.json"

# Defaults for the two launch roles. Admins can add roles as new settings versions (versions.py).
ROLES = ("PM", "SPM")
ROLE_NAMES = {"PM": "Product Manager", "SPM": "Senior Product Manager"}

HOLD_REMINDER_DAYS = 7
SPOT_CHECK_SIZE = 3

# USD per million tokens (input, output, cache read). Batch API is 50% of these.
PRICES = {
    "claude-sonnet-5": (2.00, 10.00, 0.20),
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-haiku-4-5": (1.00, 5.00, 0.10),
    "claude-sonnet-4-6": (3.00, 15.00, 0.30),
    # Gemini paid tier (output includes thinking tokens). 3.8 Flash promo price runs to 31 Dec 2026.
    "gemini-3.8-flash": (0.75, 3.75, 0.075),
    "gemini-3.5-flash-lite": (0.30, 2.50, 0.03),
    "gemini-3.1-flash-lite": (0.25, 1.50, 0.025),
    "gemini-3.1-pro-preview": (2.00, 12.00, 0.20),
}


def load_params(path: Path | None = None) -> dict:
    return json.loads(Path(path or PARAMS_PATH).read_text(encoding="utf-8"))


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def env(name: str) -> str | None:
    v = os.environ.get(name, "").strip()
    return v or None


def dry_run() -> bool:
    """DRY_RUN defaults to true. Only an explicit DRY_RUN=false enables sending. Demo never sends."""
    if is_demo():
        return True
    raw = os.environ.get("DRY_RUN")
    if raw is None:
        return True
    return raw.strip().lower() not in ("false", "0", "no", "off")


# ---- demo vs real product -------------------------------------------------------------
# One deployment can serve both. The web app picks the mode per request (the visitor's choice on
# the opening screen, kept in a cookie) and sets it here; the CLI and Streamlit use KARGO_DEMO.
_mode: contextvars.ContextVar[str | None] = contextvars.ContextVar("kargo_mode", default=None)


def available_modes() -> list[str]:
    """Which products this deployment offers: 'demo' (DEMO_DATABASE_URL or KARGO_DEMO=1) and/or
    'real' (DATABASE_URL). KARGO_MODES overrides, e.g. KARGO_MODES=demo,real."""
    explicit = [m.strip() for m in (env("KARGO_MODES") or "").split(",") if m.strip() in ("demo", "real")]
    if explicit:
        return explicit
    modes = []
    if env("DEMO_DATABASE_URL") or os.environ.get("KARGO_DEMO") == "1":
        modes.append("demo")
    if env("DATABASE_URL"):
        modes.append("real")
    return modes or ["real"]


def current_mode() -> str | None:
    return _mode.get()


@contextmanager
def use_mode(mode: str | None):
    token = _mode.set(mode)
    try:
        yield
    finally:
        _mode.reset(token)


def is_demo() -> bool:
    m = _mode.get()
    if m is not None:
        return m == "demo"
    return os.environ.get("KARGO_DEMO") == "1"


def llm_provider() -> str:
    """'anthropic' (Claude) or 'gemini'. Set KARGO_LLM_PROVIDER, or it follows the model name."""
    p = (env("KARGO_LLM_PROVIDER") or "").lower()
    if p in ("anthropic", "claude"):
        return "anthropic"
    if p in ("gemini", "google"):
        return "gemini"
    return "gemini" if (env("KARGO_MODEL") or "").startswith("gemini") else "anthropic"


def model() -> str:
    default = "gemini-3.8-flash" if llm_provider() == "gemini" else "claude-sonnet-5"
    return env("KARGO_MODEL") or default


def api_ready() -> bool:
    if llm_provider() == "gemini":
        return bool(env("GEMINI_API_KEY") or env("GOOGLE_API_KEY"))
    return bool(env("ANTHROPIC_API_KEY") or env("ANTHROPIC_AUTH_TOKEN"))


def test_recipient() -> str | None:
    return env("TEST_RECIPIENT")


def from_email() -> str:
    return env("FROM_EMAIL") or "Kargo Hiring <hiring@example.com>"


def scheduling_link(role: str | None = None) -> str | None:
    """Per-role link (SCHEDULING_LINK_PM, SCHEDULING_LINK_SPM, ...) or the shared SCHEDULING_LINK."""
    return (env(f"SCHEDULING_LINK_{role}") if role else None) or env("SCHEDULING_LINK")


def public_base_url() -> str:
    """Where the careers form / webhook server is reachable (for links in emails)."""
    return (env("PUBLIC_BASE_URL") or "http://localhost:8600").rstrip("/")


def on_vercel() -> bool:
    return bool(os.environ.get("VERCEL"))


def storage_mode() -> str:
    """'files' keeps CVs, the vault and the outbox on local disk (laptop, Streamlit, tests).
    'db' keeps everything in the database: required on Vercel, whose disk is temporary."""
    mode = (os.environ.get("KARGO_STORAGE") or ("db" if on_vercel() else "files")).lower()
    return "db" if mode == "db" else "files"


def ensure_dirs() -> None:
    if storage_mode() == "db":
        return
    for d in (APPLICATIONS_DIR, META_DIR, DATA_DIR, OUTBOX_DIR, VAULT_DIR):
        d.mkdir(parents=True, exist_ok=True)
