"""Exclusion classification — the active policy's own warehouse task.

Delegates to `policy.classification_task()`. Under `none`, or any policy without
a task, nothing is pending and the task is a no-op.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

from screener.policies import get_policy
from screener.tasks.base import FilterResult

if TYPE_CHECKING:
    import httpx
    from sqlalchemy.orm import Session

    from data.models.schema import Company
    from data.rate_limit import TokenBucket


class ExclusionClassifyTask:
    name = "exclusion_classify"
    # Rate-limit bucket, cadence and concurrency come from the policy's own task,
    # so a policy that calls an external source is throttled like one.
    source = "in-memory"
    refresh_interval = timedelta(days=30)
    concurrency_override: int | None = None

    def __init__(self) -> None:
        # The warehouse is classified under the configured policy; a staged run's
        # --policy applies its own classify() inline at Tier 3.
        self._inner: Any | None = get_policy().classification_task()
        if self._inner is not None:
            self.source = getattr(self._inner, "source", self.source)
            self.refresh_interval = getattr(self._inner, "refresh_interval", self.refresh_interval)
            self.concurrency_override = getattr(
                self._inner, "concurrency_override", self.concurrency_override
            )

    def select_pending(self, db: Session) -> list[Company]:
        return [] if self._inner is None else list(self._inner.select_pending(db))

    async def fetch_chunk(
        self,
        companies: list[Company],
        client: httpx.AsyncClient,
        bucket: TokenBucket,
    ) -> list[FilterResult]:
        if self._inner is None:
            return []
        return list(await self._inner.fetch_chunk(companies, client, bucket))

    def persist(self, db: Session, results: list[FilterResult]) -> None:
        if self._inner is not None:
            self._inner.persist(db, results)


__all__ = ["ExclusionClassifyTask"]
