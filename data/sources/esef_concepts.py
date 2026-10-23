"""IFRS/ESEF concept → canonical field mapping.

This is DATA, not logic. It mirrors the shape of ``yfinance_fund._val``'s
ordered-label-candidates pattern (``mirror_existing_patterns``): for each
``EdgarFinancialRow`` field, an ORDERED tuple of IFRS taxonomy concepts, most
specific / most-preferred first.

Why an ordered list rather than a single concept: ESEF does not force a single
tag for a given line. Measured on real filings 2026-08-16 —

    BONESUPPORT (SE)  revenue → ifrs-full:RevenueFromSaleOfGoods
    Kempower (FI)     revenue → ifrs-full:Revenue
    ASML (NL)         revenue → ifrs-full:RevenueFromContractsWithCustomers
    Ferrari (NL)      revenue → ifrs-full:Revenue

...all four legitimate. A single-concept map would silently return None for
three of them, which under CLAUDE.md is the worst class of bug: a framework
input that looks absent when it is merely differently tagged.

Company-specific EXTENSION concepts (namespace != ``ifrs-full``, e.g. ``BON:``)
are deliberately NOT mapped. An extension means the filer asserted this line
has no standard equivalent; guessing at its semantics is exactly the
hallucination the data layer forbids. Extensions surface as data gaps.

Sign conventions: IFRS reports expenses and outflows as POSITIVE magnitudes
(CostOfSales = 66,476,000 not -66,476,000). ``capex`` is stored as a positive
magnitude to match ``edgar_companyfacts`` (which applies ``abs()`` before
persisting), so the shared ``FCF = OCF - abs(capex)`` derivation holds
identically across sources.
"""
from __future__ import annotations

# ── Fields resolved by FIRST MATCH among ordered synonyms ─────────────────
CONCEPT_MAP: dict[str, tuple[str, ...]] = {
    # ── Income statement (duration facts) ──
    "revenue": (
        "ifrs-full:Revenue",
        "ifrs-full:RevenueFromContractsWithCustomers",
        "ifrs-full:RevenueFromSaleOfGoods",
        "ifrs-full:RevenueFromRenderingOfServices",
    ),
    "cost_of_revenue": (
        "ifrs-full:CostOfSales",
        "ifrs-full:CostOfMerchandiseSold",
    ),
    "gross_profit": ("ifrs-full:GrossProfit",),
    "operating_income": (
        "ifrs-full:ProfitLossFromOperatingActivities",
        "ifrs-full:OperatingIncomeLoss",
    ),
    "net_income": (
        "ifrs-full:ProfitLoss",
        "ifrs-full:ProfitLossAttributableToOwnersOfParent",
    ),
    "rd_expense": ("ifrs-full:ResearchAndDevelopmentExpense",),
    "sga_expense": (
        "ifrs-full:SellingGeneralAndAdministrativeExpense",
        "ifrs-full:AdministrativeExpense",
    ),
    "interest_expense": (
        "ifrs-full:InterestExpense",
        "ifrs-full:FinanceCosts",
    ),
    "income_tax_expense": (
        "ifrs-full:IncomeTaxExpenseContinuingOperations",
        "ifrs-full:IncomeTaxExpenseBenefit",
    ),
    "depreciation_amortization": (
        "ifrs-full:DepreciationAndAmortisationExpense",
        "ifrs-full:DepreciationAmortisationAndImpairmentLossReversalOfImpairmentLossRecognisedInProfitOrLoss",
    ),
    "eps_basic": ("ifrs-full:BasicEarningsLossPerShare",),
    "eps_diluted": ("ifrs-full:DilutedEarningsLossPerShare",),

    # ── Balance sheet (instant facts) ──
    "total_assets": ("ifrs-full:Assets",),
    "total_equity": (
        "ifrs-full:Equity",
        "ifrs-full:EquityAttributableToOwnersOfParent",
    ),
    "current_assets": ("ifrs-full:CurrentAssets",),
    "current_liabilities": ("ifrs-full:CurrentLiabilities",),
    "cash_and_equivalents": (
        "ifrs-full:CashAndCashEquivalents",
        "ifrs-full:Cash",
    ),
    "short_term_investments": (
        "ifrs-full:OtherCurrentFinancialAssets",
        "ifrs-full:CurrentInvestments",
    ),
    "accounts_receivable": (
        "ifrs-full:CurrentTradeReceivables",
        "ifrs-full:TradeAndOtherCurrentReceivables",
    ),
    "inventory": ("ifrs-full:Inventories",),
    "goodwill": ("ifrs-full:Goodwill",),
    "long_term_debt": (
        "ifrs-full:NoncurrentPortionOfNoncurrentBorrowings",
        "ifrs-full:LongtermBorrowings",
        "ifrs-full:NoncurrentBorrowings",
    ),

    # ── Cash flow (duration facts) ──
    "operating_cash_flow": (
        "ifrs-full:CashFlowsFromUsedInOperatingActivities",
        "ifrs-full:CashFlowsFromUsedInOperations",
    ),
    "dividends_paid": (
        "ifrs-full:DividendsPaidClassifiedAsFinancingActivities",
        "ifrs-full:DividendsPaid",
    ),
    "share_repurchases": (
        "ifrs-full:PaymentsToAcquireOrRedeemEntitysShares",
    ),
    "share_based_compensation": (
        "ifrs-full:AdjustmentsForSharebasedPayments",
        "ifrs-full:ShareBasedPaymentsAdjustmentToProfitLoss",
    ),
}

# ── Fields resolved by SUMMING every present component ────────────────────
# Capex is split across PP&E / intangibles / (sometimes) development-cost
# capitalisation. First-match-wins would undercount: BONESUPPORT FY2024 PP&E
# alone is 1.53m SEK while total capex is ~5.8m. These are additive line
# items, not synonyms, so they get summed.
SUM_CONCEPT_MAP: dict[str, tuple[str, ...]] = {
    "capex": (
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "ifrs-full:PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities",
        "ifrs-full:PurchaseOfOtherLongtermAssetsClassifiedAsInvestingActivities",
    ),
    "total_debt": (
        "ifrs-full:NoncurrentPortionOfNoncurrentBorrowings",
        "ifrs-full:CurrentPortionOfNoncurrentBorrowings",
        "ifrs-full:ShorttermBorrowings",
    ),
}

# Share counts carry unit 'shares', not iso4217 — handled separately.
SHARE_CONCEPTS: tuple[str, ...] = (
    "ifrs-full:NumberOfSharesOutstanding",
    "ifrs-full:NumberOfSharesIssued",
    "ifrs-full:WeightedAverageNumberOfOrdinarySharesOutstanding",
)

# Facts carrying any dimension beyond these are segment/member breakdowns
# (revenue by geography, equity by class, ...). Only consolidated totals are
# consumed — a segment fact silently treated as a total is a wrong-number bug.
ALLOWED_DIMENSION_KEYS = frozenset({"concept", "entity", "period", "unit", "language"})
