"""Data-gap lists must never render a duplicate entry.

── Why this file exists ──────────────────────────────────────────────────
A duplicated gap register is not cosmetic. `data_gaps[]` is a first-class
output of this system (CLAUDE.md §"Missing data → data_gaps entry, never a
hallucinated value"), and the reader uses its LENGTH and CONTENT to judge how
much of a dive is trustworthy. A list that says "10 gaps" when there are 5
overstates the uncertainty, and it makes the register look unmaintained, which
is how readers learn to skim it.

── Why it is a BROWSER test and not a unit test ──────────────────────────
The bug it pins was invisible at every other layer:

  * Unit tests passed — each producer emitted its gaps exactly once.
  * The API passed — `/valuation/{ticker}` returned 8 + 5 gaps, no internal
    duplicates. Querying it actively MISLED the diagnosis.
  * Only the rendered page showed the doubling, because the duplication
    happened in `deepdive/orchestrator.py`'s history-retry path
    (`gaps.extend(extra_gaps)` after a second `refresh_ticker`), landed in the
    persisted dive, and surfaced in DivePanel — a different list from the one
    the valuation endpoint returns.

The original diagnosis was wrong for an instructive reason: a duplicate list
appeared right after a new component that concatenates two lists had been
written, so the new code was assumed guilty. It was not. The defect was
pre-existing and merely became VISIBLE because the ESEF adapter (ADR-041)
produces five persistent gaps for Swedish issuers where SEC tickers produce
almost none.

So: assert the rendered DOM, not the payload. `test_behaviour_not_implementation`.
"""
from __future__ import annotations

import collections
import re

import pytest

pytestmark = pytest.mark.browser


def _duplicates(items: list[str]) -> list[str]:
    return [text for text, n in collections.Counter(items).items() if n > 1]


def _gap_items(page, scope: str = "ul.gap-list li") -> list[str]:  # noqa: ANN001
    return [li.inner_text().strip() for li in page.locator(scope).all()]


def test_dive_gap_list_has_no_duplicates(dive_page):  # noqa: ANN001
    """The scorecard's own fetch_data_gaps register.

    Regression: orchestrator retried refresh_ticker on history-unfeasible
    frameworks and appended the identical gap set a second time, so BONEX.ST
    rendered 10 entries for 5 real gaps.
    """
    gaps = _gap_items(dive_page, "h3:has-text('Data gaps') ~ ul.gap-list li")
    assert gaps, "expected a non-empty dive gap register for an ESEF ticker"
    dupes = _duplicates(gaps)
    assert not dupes, (
        f"dive gap register renders {len(gaps)} entries for {len(set(gaps))} unique "
        f"gaps. Duplicated: {dupes}"
    )


def test_valuation_gap_list_has_no_duplicates(dive_page):  # noqa: ANN001
    """The valuation section's own register, after the lazy button is clicked.

    Covers the OTHER duplication source: Greenwald borrows the Damodaran loader
    for WACC, so the ticker's fetch gaps arrive in both engines' lists and were
    rendered twice until deduped in compute_valuation_payload.
    """
    dive_page.get_by_role("button", name="Run Intrinsic Value").click()
    dive_page.wait_for_selector("h3:has-text('Cross-engine reading')", timeout=200_000)
    dive_page.get_by_role("button", name=re.compile("Show data gaps")).click()
    dive_page.wait_for_timeout(300)

    all_gaps = _gap_items(dive_page)
    dupes = _duplicates(all_gaps)
    assert not dupes, (
        f"{len(all_gaps)} gap items rendered, {len(set(all_gaps))} unique. "
        f"Duplicated: {dupes}"
    )
    assert not dive_page.js_errors, dive_page.js_errors


def test_gap_count_label_matches_rendered_items(dive_page):  # noqa: ANN001
    """The "Show data gaps (N)" label must equal the number of <li> rendered.

    A count computed from one list while a different list is rendered is how a
    duplicate register hides in plain sight — the label looked plausible, so
    nobody counted the rows.
    """
    dive_page.get_by_role("button", name="Run Intrinsic Value").click()
    dive_page.wait_for_selector("h3:has-text('Cross-engine reading')", timeout=200_000)

    toggle = dive_page.get_by_role("button", name=re.compile(r"Show data gaps \(\d+\)"))
    claimed = int(re.search(r"\((\d+)\)", toggle.inner_text()).group(1))

    before = set(_gap_items(dive_page))
    toggle.click()
    dive_page.wait_for_timeout(300)
    after = _gap_items(dive_page)
    revealed = [g for g in after if g not in before]

    assert len(revealed) == claimed, (
        f"toggle claims {claimed} valuation gaps but revealed {len(revealed)} "
        f"list items"
    )
