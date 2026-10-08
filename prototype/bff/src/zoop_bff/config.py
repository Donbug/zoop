"""Runtime configuration, read from the environment once per app instance."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

BFF_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT_PATH = BFF_ROOT / "fixtures" / "poc-synthetic-inspect.json"
# The sibling layout applies only to source checkouts, not installed package locations.
_SOURCE_CHECKOUT = (
    BFF_ROOT.name == "bff"
    and BFF_ROOT.parent.name == "prototype"
    and Path(__file__).resolve().parent.parent.name == "src"
)
# Preserve the legacy installed-package default; use ZOOP_COMPANY_CATALOG elsewhere.
DEFAULT_COMPANY_CATALOG = (
    BFF_ROOT.parents[2] / "InvestMateLogicTest" / "examples" / "synthetic" / "settings.json"
    if _SOURCE_CHECKOUT
    else Path("/Users/asqi/InvestMateLogicTest/examples/synthetic/settings.json")
)
# Local-only compose credentials documented by the PoC (compose.yaml). The admin ledger is the expansion
# real-news database (docs/evidence/poc-backend.md section 10) inside the same Postgres container; the
# earlier ledger `investmate_zoop_real` is kept untouched (ZOOP_ADMIN_POC_DSN + ZOOP_POC_SETTINGS to use it).
DEFAULT_ADMIN_POC_DSN = (
    "postgresql://investmate:investmate-local-only@127.0.0.1:55432/investmate_zoop_real2"
)
# The expansion ledger projects into its own Neo4j container (docker run, section 10); the PoC compose Neo4j
# on 57687 belongs to the earlier ledger, whose issue ids would otherwise be overwritten.
DEFAULT_NEO4J_URI = "bolt://127.0.0.1:58687"
DEFAULT_NEO4J_USER = "neo4j"
DEFAULT_NEO4J_PASSWORD = "investmate-local-only"
DEFAULT_STATE_DIR = BFF_ROOT / "var"
DEFAULT_POC_SANDBOX = Path.home() / ".local" / "share" / "zoop" / "investmate-sandbox"
DEFAULT_POC_SETTINGS = "zoop-real-expanded-settings.json"  # file name inside the sandbox; sets the policy the jobs run under
DEFAULT_TOSS_BASE_URL = "https://openapi.tossinvest.com"
DEFAULT_YAHOO_BASE_URL = "https://query1.finance.yahoo.com"
DEFAULT_NAVER_URLS = ("https://m.stock.naver.com", "https://api.stock.naver.com", "https://ac.stock.naver.com")
QuoteProviderMode = Literal["auto", "toss", "yahoo", "off"]
_QUOTE_PROVIDERS: tuple[QuoteProviderMode, ...] = ("auto", "toss", "yahoo", "off")


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "on"}


def _number(name: str, default: float, *, minimum: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum:g}")
    return value


def _quote_provider() -> QuoteProviderMode:
    raw = (os.environ.get("ZOOP_QUOTE_PROVIDER") or "auto").strip().lower()
    if raw not in _QUOTE_PROVIDERS:
        raise ValueError(f"ZOOP_QUOTE_PROVIDER must be one of {', '.join(_QUOTE_PROVIDERS)} (got {raw!r})")
    return raw  # type: ignore[return-value]


def _settings_file_name(raw: str | None) -> str:
    """A plain file name inside the sandbox: the job runner never follows a path from the environment."""
    name = (raw or "").strip() or DEFAULT_POC_SETTINGS
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}\.json", name):
        raise ValueError("ZOOP_POC_SETTINGS must be a .json file name inside the sandbox (no directories)")
    return name


DEFAULT_CORS_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
)



@dataclass(frozen=True)
class Settings:
    snapshot_path: Path = DEFAULT_SNAPSHOT_PATH
    company_catalog: Path | None = DEFAULT_COMPANY_CATALOG
    cors_origins: tuple[str, ...] = DEFAULT_CORS_ORIGINS
    cookie_secure: bool = False
    # -- state and admin (requirements 76-82)
    state_dir: Path = DEFAULT_STATE_DIR
    admin_poc_dsn: str = field(default=DEFAULT_ADMIN_POC_DSN, repr=False)
    admin_neo4j_uri: str = DEFAULT_NEO4J_URI
    admin_neo4j_user: str = DEFAULT_NEO4J_USER
    admin_neo4j_password: str = field(default=DEFAULT_NEO4J_PASSWORD, repr=False)
    ledger_connect_timeout_seconds: int = 5
    poc_sandbox: Path = DEFAULT_POC_SANDBOX
    poc_settings_file: str = DEFAULT_POC_SETTINGS
    admin_default_model_calls: int = 50
    admin_max_model_calls: int = 200
    admin_idle_seconds: float = 30 * 60
    admin_absolute_seconds: float = 8 * 60 * 60
    briefing_scheduler: bool = False
    # -- stock quotes (requirements 35-37, 72). The dataclass default stays off so tests never reach
    # the network; the environment default is auto (Toss when keys are set, otherwise Yahoo).
    quote_provider: QuoteProviderMode = "off"
    toss_client_id: str | None = field(default=None, repr=False)
    toss_client_secret: str | None = field(default=None, repr=False)
    toss_base_url: str = DEFAULT_TOSS_BASE_URL
    yahoo_base_url: str = DEFAULT_YAHOO_BASE_URL
    quote_timeout_seconds: float = 5.0
    # Indicators (시가총액·PER·PBR…) from 네이버 증권's public JSON; off by default in code, on from the environment.
    metrics_enabled: bool = False
    naver_urls: tuple[str, str, str] = DEFAULT_NAVER_URLS

    @classmethod
    def from_env(cls) -> Settings:
        # The user-facing graph is always the active published version; the live source is gone.
        if os.environ.get("ZOOP_SOURCE", "").strip().lower() == "live":
            raise ValueError(
                "ZOOP_SOURCE=live was removed: users see the active graph version. "
                "Publish the PoC ledger from the admin API (POST /api/admin/graph/versions)."
            )
        catalog = os.environ.get("ZOOP_COMPANY_CATALOG")
        origins = os.environ.get("ZOOP_CORS_ORIGINS")
        state_dir = os.environ.get("ZOOP_STATE_DIR")
        sandbox = os.environ.get("ZOOP_POC_SANDBOX")
        max_calls = int(_number("ZOOP_ADMIN_MAX_MODEL_CALLS", 200, minimum=1))
        return cls(
            snapshot_path=Path(
                os.environ.get("ZOOP_SNAPSHOT_PATH") or DEFAULT_SNAPSHOT_PATH
            ),
            company_catalog=Path(catalog) if catalog else DEFAULT_COMPANY_CATALOG,
            cors_origins=tuple(o.strip() for o in origins.split(",") if o.strip())
            if origins is not None
            else DEFAULT_CORS_ORIGINS,
            cookie_secure=_flag("ZOOP_COOKIE_SECURE", False),
            state_dir=Path(state_dir) if state_dir else DEFAULT_STATE_DIR,
            admin_poc_dsn=os.environ.get("ZOOP_ADMIN_POC_DSN") or DEFAULT_ADMIN_POC_DSN,
            admin_neo4j_uri=os.environ.get("ZOOP_ADMIN_NEO4J_URI") or DEFAULT_NEO4J_URI,
            admin_neo4j_user=os.environ.get("ZOOP_ADMIN_NEO4J_USER") or DEFAULT_NEO4J_USER,
            admin_neo4j_password=os.environ.get("ZOOP_ADMIN_NEO4J_PASSWORD") or DEFAULT_NEO4J_PASSWORD,
            poc_sandbox=Path(sandbox) if sandbox else DEFAULT_POC_SANDBOX,
            poc_settings_file=_settings_file_name(os.environ.get("ZOOP_POC_SETTINGS")),
            admin_default_model_calls=min(50, max_calls),
            admin_max_model_calls=max_calls,
            admin_idle_seconds=_number("ZOOP_ADMIN_IDLE_SECONDS", 30 * 60, minimum=1),
            admin_absolute_seconds=_number("ZOOP_ADMIN_ABSOLUTE_SECONDS", 8 * 60 * 60, minimum=1),
            briefing_scheduler=_flag("ZOOP_BRIEFING_SCHEDULER", True),
            quote_provider=_quote_provider(),
            toss_client_id=os.environ.get("ZOOP_TOSS_CLIENT_ID") or None,
            toss_client_secret=os.environ.get("ZOOP_TOSS_CLIENT_SECRET") or None,
            toss_base_url=os.environ.get("ZOOP_TOSS_BASE_URL") or DEFAULT_TOSS_BASE_URL,
            yahoo_base_url=os.environ.get("ZOOP_YAHOO_BASE_URL") or DEFAULT_YAHOO_BASE_URL,
            quote_timeout_seconds=_number("ZOOP_QUOTE_TIMEOUT_SECONDS", 5.0, minimum=0.5),
            metrics_enabled=(os.environ.get("ZOOP_METRICS_PROVIDER") or "naver").strip().lower() != "off",
            naver_urls=(
                os.environ.get("ZOOP_NAVER_DOMESTIC_URL") or DEFAULT_NAVER_URLS[0],
                os.environ.get("ZOOP_NAVER_WORLD_URL") or DEFAULT_NAVER_URLS[1],
                os.environ.get("ZOOP_NAVER_AC_URL") or DEFAULT_NAVER_URLS[2],
            ),
        )
