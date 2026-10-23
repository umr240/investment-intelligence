from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _find_env_file() -> str:
    """Walk up from cwd to find .env — supports running from project root or repo root."""
    for candidate in [Path(".env"), Path("../.env")]:
        if candidate.exists():
            return str(candidate)
    return ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_find_env_file(),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # OpenAI is the PRIMARY provider for narrative.py and conversation.py.
    # Anthropic is the fallback when OpenAI rate-limits / quota-exceeds.
    # The data-fetch and screener paths require zero LLM keys — they are
    # fully deterministic (EDGAR XBRL + regex + HTML table parsing + yfinance).
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")
    # Provider preference. "openai" (default) uses OpenAI first then Anthropic;
    # "anthropic" reverses; "openai_only" / "anthropic_only" disables fallback.
    narrative_provider: str = Field(
        default="openai", validation_alias="NARRATIVE_PROVIDER",
    )
    # Model IDs — kept cheap/fast for narrative MVP. Override per-call if needed.
    openai_narrative_model: str = Field(
        default="gpt-4o-mini", validation_alias="OPENAI_NARRATIVE_MODEL",
    )
    # Default to Sonnet-4-6: empirically Haiku-4-5 dropped required fields
    # (one_liner / bull / bear) under tool-use even with strict schema —
    # Sonnet fills the structured-output reliably. Override per-user via
    # ANTHROPIC_NARRATIVE_MODEL in .env if cost vs quality is a concern.
    anthropic_narrative_model: str = Field(
        default="claude-sonnet-4-6", validation_alias="ANTHROPIC_NARRATIVE_MODEL",
    )

    # FMP key is used ONLY by data/api/fmp_client.py (screener Tier 2 metadata).
    # ONE bulk call per screener run — see ADR-016. Free tier 250/day; we use ~4/year.
    # Per-ticker fundamentals stay SEC EDGAR-only (DEC-09 frames, DEC-03 companyfacts).
    fmp_api_key: str = Field(default="", validation_alias="FMP_API_KEY")

    # Polygon key is being evaluated as a fallback source for dive-data gaps
    # per ADR-018 §6.4. NOT yet wired into any production code path.
    polygon_api_key: str = Field(default="", validation_alias="POLYGON_API_KEY")

    # SEC EDGAR fair-use identity (User-Agent header). No key, just a name and
    # email. Deliberately has no usable default — see require_edgar_identity().
    edgar_identity: str = Field(default="", validation_alias="EDGAR_IDENTITY")

    database_url: str = Field(
        default="sqlite:///./investment_intelligence.db",
        validation_alias="DATABASE_URL",
    )
    # Name of a registered exclusion policy (screener/policies). Unknown names
    # fail at first use with the list of registered ones.
    exclusion_policy: str = Field(default="none", validation_alias="EXCLUSION_POLICY")

    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")

    # Cache TTLs (seconds)
    cache_ttl_financial_statements: int = 86_400   # 24h — EDGAR filings never change post-filing
    cache_ttl_price_data: int = 3_600              # 1h
    cache_ttl_yfinance_snapshot: int = 21_600      # 6h — info() and ownership snapshot


settings = Settings()


def get_settings() -> Settings:
    """Return the singleton Settings instance. Used by alembic/env.py."""
    return settings


class MissingEdgarIdentityError(RuntimeError):
    """Raised when an EDGAR request is attempted without a configured identity."""


# The literal from .env.example; `cp .env.example .env` is the documented first
# step, so an unedited copy is a likely failure path, not an unlikely one.
_EDGAR_IDENTITY_PLACEHOLDER = "your name your.email@example.com"

_EDGAR_IDENTITY_HELP = (
    "EDGAR_IDENTITY is not set to your own contact details.\n\n"
    "SEC EDGAR's fair-use policy requires a User-Agent that identifies the "
    "requester, and rate-limits per identity. Set it in .env:\n\n"
    '    EDGAR_IDENTITY="Your Name your.email@example.com"\n\n'
    "See .env.example."
)


def require_edgar_identity() -> str:
    """Return the configured EDGAR User-Agent, or raise explaining how to set it.

    Never falls back to a shared default: SEC rate-limits per identity, so a
    baked-in one would make every operator share one budget (SECURITY §1).
    """
    identity = get_settings().edgar_identity.strip()
    if not identity or identity.lower() == _EDGAR_IDENTITY_PLACEHOLDER:
        raise MissingEdgarIdentityError(_EDGAR_IDENTITY_HELP)
    if "@" not in identity:
        raise MissingEdgarIdentityError(
            f"EDGAR_IDENTITY ({identity!r}) has no email address. SEC expects a "
            'name and a contact email, e.g. "Jane Doe jane@example.com".'
        )
    return identity
