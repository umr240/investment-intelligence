"""Model prices in USD per million tokens (ADR-048 §2.1).

Rows copied from pydantic/genai-prices (MIT), `prices/providers/anthropic.yml`
and `openai.yml` at commit 3279367 (2026-10-26). Copied, not depended on
(owner, 2026-10-27; SECURITY §5). Re-copy when a model is added or a provider
changes its prices; tests/test_llm_calls.py fails for a configured model with
no row. Long-context tiers are not copied: no call here sends 200k tokens.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

logger = logging.getLogger(__name__)

PRICES_AS_OF = date(2026, 10, 26)


@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
    cache_read: float
    cache_write: float | None  # None: the provider does not bill cache writes separately


PRICES: dict[str, ModelPrice] = {
    "claude-sonnet-4-6": ModelPrice(input=3.0, output=15.0, cache_read=0.3, cache_write=3.75),
    "claude-haiku-4-5": ModelPrice(input=1.0, output=5.0, cache_read=0.1, cache_write=1.25),
    "gpt-4o-mini": ModelPrice(input=0.15, output=0.6, cache_read=0.075, cache_write=None),
    "gpt-4o": ModelPrice(input=2.5, output=10.0, cache_read=1.25, cache_write=None),
}


class UnpricedModelError(LookupError):
    """A model with no row in PRICES, refused where spend is budgeted."""


def price_for(model: str) -> ModelPrice | None:
    """The model's price row; dated snapshots ("gpt-4o-mini-2024-07-18") use the base row."""
    if model in PRICES:
        return PRICES[model]
    base = max((m for m in PRICES if model.startswith(m + "-")), key=len, default=None)
    return PRICES[base] if base else None


def require_price(model: str) -> ModelPrice:
    """price_for, or UnpricedModelError: for callers that enforce a budget."""
    price = price_for(model)
    if price is None:
        raise UnpricedModelError(f"no price for model {model!r} in config/llm_prices.py")
    return price


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float | None:
    """Cost of one call; `input_tokens` excludes cached ones. None if the model has no price."""
    price = price_for(model)
    if price is None:
        logger.warning("no price for model %s: cost not recorded", model)
        return None
    total = (
        input_tokens * price.input
        + output_tokens * price.output
        + cache_read_tokens * price.cache_read
        + cache_write_tokens * (price.cache_write if price.cache_write is not None else price.input)
    )
    return round(total / 1_000_000, 6)
