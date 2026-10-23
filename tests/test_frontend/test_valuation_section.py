"""ValuationSection rendering contract (ADR-042 in the browser).

Every assertion here pins a defect that was found by LOOKING at the rendered
page and that no API or unit test detected. They were run ad-hoc during
development; committing them is the point — an ad-hoc check that found a bug
once and was then thrown away is a bug that comes back.
"""
from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.browser


def _run_valuation(page):  # noqa: ANN001
    page.get_by_role("button", name="Run Intrinsic Value").click()
    page.wait_for_selector("h3:has-text('Cross-engine reading')", timeout=200_000)
    page.wait_for_timeout(300)
    return page.inner_text("body")


def test_valuation_is_lazy(dive_page):  # noqa: ANN001
    """Nothing computes until the button is clicked.

    Not a performance nicety: an intrinsic value the user did not ask for is an
    anchor they did not choose (`bias/anchoring_bias`). If this fails, the
    section started auto-fetching on mount.
    """
    body = dive_page.inner_text("body")
    assert "Run Intrinsic Value" in body
    assert "Franchise test" not in body
    assert "Cross-engine reading" not in body


def test_banner_and_synthesis_do_not_contradict(dive_page):  # noqa: ANN001
    """Regression: the page said both "usable WITH the caveats" and "not usable".

    The reliability verdict has THREE states; the synthesis collapsed
    `qualified` into `unreliable`, so a qualified ticker rendered a banner and a
    conclusion that disagreed one paragraph apart. Caught only by reading the
    page as a reader would.
    """
    body = _run_valuation(dive_page)
    synthesis = dive_page.locator(
        "h3:has-text('Cross-engine reading') + p"
    ).inner_text()

    if "usable WITH the caveats" in body:          # qualified
        assert "not usable here" not in synthesis, (
            f"banner says qualified/usable, synthesis says not usable: {synthesis!r}"
        )
    elif "is usable." in body:                      # reliable
        assert "not usable here" not in synthesis
    elif "NOT usable as a valuation" in body:       # unreliable
        assert "usable but qualified" not in synthesis


def test_vs_price_column_is_normalised_by_price(dive_page):  # noqa: ANN001
    """Regression: the column showed margin-of-safety, normalised by IV.

    NVDA rendered "-272.5%" under a "vs price" header when the gap to price was
    -73.2%. Same number, wrong denominator, wrong story. Every populated row in
    that column must satisfy (value - price)/price, so rows stay comparable.
    """
    _run_valuation(dive_page)
    rows = dive_page.locator("table").last.locator("tr")
    price = None
    checked = 0

    for i in range(rows.count()):
        cells = [c.inner_text().strip() for c in rows.nth(i).locator("td").all()]
        if len(cells) < 3 or not cells[0]:
            continue
        if cells[0].startswith("Market price"):
            price = float(cells[1].replace(",", ""))
            continue
        if price is None or cells[2] in ("—", "") or cells[1] in ("—", "withheld"):
            continue
        if cells[0].startswith("Market-implied"):
            continue                                  # a growth rate, not a level
        value = float(cells[1].replace(",", ""))
        shown = float(cells[2].rstrip("%"))
        expected = (value - price) / price * 100
        assert shown == pytest.approx(expected, abs=0.2), (
            f"{cells[0]}: 'vs price' shows {shown}% but (value-price)/price is "
            f"{expected:.1f}%. Wrong denominator?"
        )
        checked += 1

    assert checked >= 2, "expected at least two populated vs-price rows to verify"


def test_unusable_iv_is_withheld_not_printed(dive_page):  # noqa: ANN001
    """An `unreliable` verdict must NOT render the forward DCF as a number.

    ADR-030/042's whole premise: a correct calculation on an inapplicable model
    anchors harder than no number. BONEX.ST is tier A_young, so the DCF is not
    quotable and the cell must say so.
    """
    body = _run_valuation(dive_page)
    if "NOT usable as a valuation" in body:
        row = dive_page.locator("tr", has_text="Damodaran forward DCF").first
        assert "withheld" in row.inner_text(), (
            "verdict is unreliable but the forward DCF is still printed as a value"
        )


def test_inflecting_filer_shows_applicability_warning_and_recent_regime(dive_page):  # noqa: ANN001
    """ADR-042's EPV applicability gate must be visible, not just computed.

    BONEX.ST crosses loss→profit, so full-history EPV capitalises a dead regime
    (-8.22/sh) while the recent-regime variant is +35.06/sh. Showing the former
    without the warning would report "value destruction" for a profitable
    company.
    """
    body = _run_valuation(dive_page)
    if "inflecting" in body:
        assert "recent regime" in body, (
            "applicability is 'inflecting' but no recent-regime EPV row rendered"
        )
        assert "pre-inflection" in body or "median is dominated" in body


def test_state_resets_when_ticker_changes(dive_page):  # noqa: ANN001
    """Regression: the section kept the PREVIOUS ticker's valuation.

    Load BONEX.ST → run → switch to NVDA: the scorecard above updated but the
    valuation still showed BONEX's numbers under NVDA's name. Rendering one
    company's intrinsic value under another company's name is the worst failure
    this component can have, and it is invisible to API tests.
    """
    body = _run_valuation(dive_page)
    ratio = re.search(r"EPV / AV = ([\d.]+)×", body)
    first_ratio = ratio.group(1) if ratio else None

    dive_page.get_by_placeholder("NVDA").first.fill("NVDA")
    dive_page.get_by_role("button", name="Load Existing Scorecard").click()
    dive_page.wait_for_selector("h3:has-text('Frameworks')", timeout=60_000)
    dive_page.wait_for_timeout(500)

    after = dive_page.inner_text("body")
    assert dive_page.get_by_role("button", name="Run Intrinsic Value").count() == 1, (
        "switching ticker left the previous valuation rendered — state did not reset"
    )
    assert "Franchise test" not in after
    if first_ratio:
        assert f"EPV / AV = {first_ratio}×" not in after, (
            f"previous ticker's franchise ratio {first_ratio}x still on screen"
        )
    assert not dive_page.js_errors, dive_page.js_errors
