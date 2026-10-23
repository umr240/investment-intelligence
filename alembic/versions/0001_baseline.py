"""Baseline: the whole schema in one revision.

Generated from the ORM and reviewed by hand. It replaces the 33 incremental
migrations, which stay in the private archive's history. An existing database
whose schema matches is stamped here (`alembic stamp --purge 0001_baseline`)
instead of being upgraded.

Revision ID: 0001_baseline
Revises:
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("cik", sa.Text(), nullable=True),
        sa.Column("exchange", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sector", sa.Text(), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("market_cap_usd", sa.Float(), nullable=True),
        sa.Column("market_cap_native", sa.Float(), nullable=True),
        sa.Column("market_cap_currency", sa.Text(), nullable=True),
        sa.Column("currency", sa.Text(), nullable=True),
        sa.Column(
            "data_source_tier", sa.Text(), server_default=sa.text("'sec_edgar'"), nullable=True
        ),
        sa.Column("lei", sa.Text(), nullable=True),
        sa.Column("ipo_date", sa.Date(), nullable=True),
        sa.Column("parent_ticker", sa.Text(), nullable=True),
        sa.Column("listing_type", sa.Text(), nullable=True),
        sa.Column(
            "fiscal_year_end_month", sa.Integer(), server_default=sa.text("12"), nullable=True
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False),
        sa.Column("ceo_name", sa.Text(), nullable=True),
        sa.Column("ceo_equity_pct", sa.Float(), nullable=True),
        sa.Column("ceo_total_pay", sa.Float(), nullable=True),
        sa.Column("is_founder_ceo", sa.Boolean(), nullable=True),
        sa.Column("ceo_tenure_years", sa.Float(), nullable=True),
        sa.Column("ceo_name_state", sa.Text(), nullable=True),
        sa.Column("ceo_name_fetched_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("ceo_equity_pct_state", sa.Text(), nullable=True),
        sa.Column("ceo_equity_pct_fetched_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("is_founder_ceo_state", sa.Text(), nullable=True),
        sa.Column("is_founder_ceo_fetched_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("ipo_date_state", sa.Text(), nullable=True),
        sa.Column("ipo_date_fetched_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("shares_float", sa.Float(), nullable=True),
        sa.Column("insider_pct_latest", sa.Float(), nullable=True),
        sa.Column("institution_pct_latest", sa.Float(), nullable=True),
        sa.Column("short_pct_float_latest", sa.Float(), nullable=True),
        sa.Column("pe_trailing", sa.Float(), nullable=True),
        sa.Column("pb_ratio", sa.Float(), nullable=True),
        sa.Column("ev_ebitda", sa.Float(), nullable=True),
        sa.Column("beta", sa.Float(), nullable=True),
        sa.Column("last_screened", sa.DateTime(), nullable=True),
        sa.Column("market_cap_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("sector_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("industry_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("sector_source", sa.Text(), nullable=True),
        sa.Column("sic_code", sa.Integer(), nullable=True),
        sa.Column("filer_category", sa.Text(), nullable=True),
        sa.Column("is_smaller_reporting_company", sa.Boolean(), nullable=True),
        sa.Column("is_financial_institution", sa.Boolean(), nullable=True),
        sa.Column("is_fund", sa.Boolean(), nullable=True),
        sa.Column("market_cap_usd_source", sa.Text(), nullable=True),
        sa.Column("ipo_date_source", sa.Text(), nullable=True),
        sa.Column("roic_source", sa.Text(), nullable=True),
        sa.Column("fcf_margin_source", sa.Text(), nullable=True),
        sa.Column("debt_to_equity_source", sa.Text(), nullable=True),
        sa.Column("revenue_growth_source", sa.Text(), nullable=True),
        sa.Column("pe_trailing_source", sa.Text(), nullable=True),
        sa.Column("pb_ratio_source", sa.Text(), nullable=True),
        sa.Column("ev_ebitda_source", sa.Text(), nullable=True),
        sa.Column("beta_source", sa.Text(), nullable=True),
        sa.Column("shares_float_source", sa.Text(), nullable=True),
        sa.Column("ceo_total_pay_source", sa.Text(), nullable=True),
        sa.Column("insider_pct_latest_source", sa.Text(), nullable=True),
        sa.Column("institution_pct_latest_source", sa.Text(), nullable=True),
        sa.Column("short_pct_float_latest_source", sa.Text(), nullable=True),
        sa.Column("exchange_source", sa.Text(), nullable=True),
        sa.Column("currency_source", sa.Text(), nullable=True),
        sa.Column("pretax_roic_source", sa.Text(), nullable=True),
        sa.Column("pt_adjusted_roic_source", sa.Text(), nullable=True),
        sa.Column("roic", sa.Float(), nullable=True),
        sa.Column("roic_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("pretax_roic", sa.Float(), nullable=True),
        sa.Column("pretax_roic_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("debt_to_equity", sa.Float(), nullable=True),
        sa.Column("debt_to_equity_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("fcf_margin", sa.Float(), nullable=True),
        sa.Column("fcf_margin_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("revenue_growth", sa.Float(), nullable=True),
        sa.Column("revenue_growth_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("pt_adjusted_roic", sa.Float(), nullable=True),
        sa.Column("pt_adjusted_roic_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("composite_score", sa.Float(), nullable=True),
        sa.Column("composite_score_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("data_completeness", sa.Float(), nullable=True),
        sa.Column("intrinsic_value_per_share", sa.Float(), nullable=True),
        sa.Column("margin_of_safety_pct", sa.Float(), nullable=True),
        sa.Column("intrinsic_value_tier", sa.Text(), nullable=True),
        sa.Column("intrinsic_value_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("framework_composite_score", sa.Float(), nullable=True),
        sa.Column("framework_verdict", sa.Text(), nullable=True),
        sa.Column("framework_scored_at", sa.DateTime(), nullable=True),
        sa.Column("framework_mode_used", sa.Text(), nullable=True),
        sa.Column("framework_unfeasible_count", sa.Integer(), nullable=True),
        sa.Column("latest_close", sa.Float(), nullable=True),
        sa.Column("latest_close_at", sa.DateTime(), nullable=True),
        sa.Column("latest_rsi_14", sa.Float(), nullable=True),
        sa.Column("latest_rsi_14_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("latest_sma_50", sa.Float(), nullable=True),
        sa.Column("latest_sma_50_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("latest_sma_200", sa.Float(), nullable=True),
        sa.Column("latest_sma_200_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("latest_macd_line", sa.Float(), nullable=True),
        sa.Column("latest_macd_signal", sa.Float(), nullable=True),
        sa.Column("latest_macd_histogram", sa.Float(), nullable=True),
        sa.Column("latest_macd_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("bew_verdict", sa.Text(), nullable=True),
        sa.Column("bew_score", sa.Integer(), nullable=True),
        sa.Column("bew_n_checks", sa.Integer(), nullable=True),
        sa.Column("bew_scored_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker"),
    )
    with op.batch_alter_table("companies", schema=None) as batch_op:
        batch_op.create_index(
            "idx_companies_ceo_equity_state",
            ["ceo_equity_pct_state"],
            unique=False,
            sqlite_where=sa.text("ceo_equity_pct_state IS NOT NULL"),
            postgresql_where=sa.text("ceo_equity_pct_state IS NOT NULL"),
        )
        batch_op.create_index(
            "idx_companies_ceo_name_state",
            ["ceo_name_state"],
            unique=False,
            sqlite_where=sa.text("ceo_name_state IS NOT NULL"),
            postgresql_where=sa.text("ceo_name_state IS NOT NULL"),
        )
        batch_op.create_index(
            "idx_companies_founder_state",
            ["is_founder_ceo_state"],
            unique=False,
            sqlite_where=sa.text("is_founder_ceo_state IS NOT NULL"),
            postgresql_where=sa.text("is_founder_ceo_state IS NOT NULL"),
        )
        batch_op.create_index(
            "idx_companies_framework_score", ["status", "framework_composite_score"], unique=False
        )
        batch_op.create_index(
            "idx_companies_ipo_state",
            ["ipo_date_state"],
            unique=False,
            sqlite_where=sa.text("ipo_date_state IS NOT NULL"),
            postgresql_where=sa.text("ipo_date_state IS NOT NULL"),
        )
        batch_op.create_index(
            "idx_companies_pt_adjusted_roic", ["status", "pt_adjusted_roic"], unique=False
        )
        batch_op.create_index(
            "idx_companies_status_score", ["status", "composite_score"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_companies_cik"), ["cik"], unique=False)

    op.create_table(
        "financial_source_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("accession_number", sa.Text(), nullable=False),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=True),
        sa.Column("period", sa.Text(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column("parser_version", sa.Integer(), nullable=True),
        sa.Column("parsing_status", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        # Named first, as in the author DB: SQLite reflection keeps one per column set.
        sa.UniqueConstraint("accession_number", name="uq_source_log_accession"),
        sa.UniqueConstraint("accession_number"),
    )
    op.create_table(
        "screener_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "run_date", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True
        ),
        sa.Column("region", sa.Text(), nullable=True),
        sa.Column("market_cap_min", sa.Float(), nullable=True),
        sa.Column("market_cap_max", sa.Float(), nullable=True),
        sa.Column("sector_filter", sa.Text(), nullable=True),
        sa.Column("ethics_filter", sa.Text(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=True),
        sa.Column("universe_count", sa.Integer(), nullable=True),
        sa.Column("passed_gates", sa.Integer(), nullable=True),
        sa.Column("results_json", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "skill_invocations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("skill_name", sa.Text(), nullable=False),
        sa.Column("skill_version", sa.Text(), nullable=False),
        sa.Column(
            "invoked_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column("args_json", sa.Text(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("tool_calls_count", sa.Integer(), nullable=True),
        sa.Column("tokens_prompt", sa.Integer(), nullable=True),
        sa.Column("tokens_completion", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column("postconditions_json", sa.Text(), nullable=True),
        sa.Column("shadow_mode_active", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("anomalies_json", sa.Text(), nullable=True),
        sa.Column("false_positive_annotation", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("skill_invocations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_skill_invocations_invoked_at"), ["invoked_at"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_skill_invocations_skill_name"), ["skill_name"], unique=False
        )

    op.create_table(
        "task_failures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_name", sa.Text(), nullable=False),
        sa.Column("cik", sa.Text(), nullable=False),
        sa.Column(
            "failed_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_name", "cik", name="uq_task_failures_task_cik"),
    )
    op.create_table(
        "task_runs",
        sa.Column("id", sa.Integer(), nullable=True),
        sa.Column("task_name", sa.Text(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=True),
        sa.Column(
            "started_at",
            sa.TIMESTAMP(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("rows_written", sa.Integer(), server_default=sa.text("0"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("task_runs", schema=None) as batch_op:
        batch_op.create_index("idx_task_runs_task", ["task_name", "started_at"], unique=False)
    # Descending keys: batch_op.create_index accepts column names only.
    op.create_index(
        "idx_task_runs_name_time", "task_runs", ["task_name", sa.text("started_at DESC")]
    )
    op.create_index("idx_task_runs_ticker", "task_runs", ["ticker", sa.text("started_at DESC")])

    op.create_table(
        "analyst_coverage",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("analyst_count", sa.Integer(), nullable=True),
        sa.Column("consensus_rating", sa.Text(), nullable=True),
        sa.Column("price_target_mean", sa.Float(), nullable=True),
        sa.Column("price_target_high", sa.Float(), nullable=True),
        sa.Column("price_target_low", sa.Float(), nullable=True),
        sa.Column("eps_estimate_next_q", sa.Float(), nullable=True),
        sa.Column("rev_estimate_next_q", sa.Float(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "earnings_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("fiscal_quarter", sa.Text(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=True),
        sa.Column("eps_actual", sa.Float(), nullable=True),
        sa.Column("eps_estimate", sa.Float(), nullable=True),
        sa.Column("eps_surprise_pct", sa.Float(), nullable=True),
        sa.Column("revenue_actual", sa.Float(), nullable=True),
        sa.Column("revenue_estimate", sa.Float(), nullable=True),
        sa.Column("rev_surprise_pct", sa.Float(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "fiscal_quarter", name="uq_earnings_quarter"),
    )
    op.create_table(
        "exclusion_verdicts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("policy", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column(
            "classified_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "policy", name="uq_exclusion_verdict_company_policy"),
    )
    with op.batch_alter_table("exclusion_verdicts", schema=None) as batch_op:
        batch_op.create_index(
            "ix_exclusion_verdicts_policy_status", ["policy", "status"], unique=False
        )

    op.create_table(
        "external_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("signal_name", sa.Text(), nullable=False),
        sa.Column("signal_value_numeric", sa.Float(), nullable=True),
        sa.Column("signal_value_text", sa.Text(), nullable=True),
        sa.Column("signal_unit", sa.Text(), nullable=True),
        sa.Column("as_of_date", sa.Date(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("source_quote", sa.Text(), nullable=True),
        sa.Column("source_document", sa.Text(), nullable=True),
        sa.Column("source_accession", sa.Text(), nullable=True),
        sa.Column("extraction_method", sa.Text(), nullable=False),
        sa.Column("extraction_confidence", sa.Text(), nullable=False),
        sa.Column(
            "extracted_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column("extracted_model", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "signal_name", "as_of_date", name="uq_external_signal"),
    )
    with op.batch_alter_table("external_signals", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_external_signals_company_id"), ["company_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_external_signals_signal_name"), ["signal_name"], unique=False
        )

    op.create_table(
        "financials",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("period", sa.Text(), nullable=False),
        sa.Column("period_end_date", sa.Date(), nullable=True),
        sa.Column("period_start_date", sa.Date(), nullable=True),
        sa.Column("filed_date", sa.Date(), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("event_time", sa.Text(), nullable=True),
        sa.Column(
            "fiscal_year_label_basis", sa.Text(), server_default=sa.text("'end'"), nullable=True
        ),
        sa.Column(
            "source_timezone", sa.Text(), server_default=sa.text("'US/Eastern'"), nullable=True
        ),
        sa.Column("revenue", sa.Float(), nullable=True),
        sa.Column("cost_of_revenue", sa.Float(), nullable=True),
        sa.Column("gross_profit", sa.Float(), nullable=True),
        sa.Column("gross_margin", sa.Float(), nullable=True),
        sa.Column("operating_income", sa.Float(), nullable=True),
        sa.Column("operating_expenses", sa.Float(), nullable=True),
        sa.Column("net_income", sa.Float(), nullable=True),
        sa.Column("ebitda", sa.Float(), nullable=True),
        sa.Column("rd_expense", sa.Float(), nullable=True),
        sa.Column("rd_disclosure_state", sa.Text(), nullable=True),
        sa.Column("sga_expense", sa.Float(), nullable=True),
        sa.Column("operating_cash_flow", sa.Float(), nullable=True),
        sa.Column("free_cash_flow", sa.Float(), nullable=True),
        sa.Column("capex", sa.Float(), nullable=True),
        sa.Column("total_assets", sa.Float(), nullable=True),
        sa.Column("total_equity", sa.Float(), nullable=True),
        sa.Column("total_debt", sa.Float(), nullable=True),
        sa.Column("long_term_debt", sa.Float(), nullable=True),
        sa.Column("cash_and_equivalents", sa.Float(), nullable=True),
        sa.Column("short_term_investments", sa.Float(), nullable=True),
        sa.Column("accounts_receivable", sa.Float(), nullable=True),
        sa.Column("current_assets", sa.Float(), nullable=True),
        sa.Column("current_liabilities", sa.Float(), nullable=True),
        sa.Column("inventory", sa.Float(), nullable=True),
        sa.Column("shares_outstanding", sa.Float(), nullable=True),
        sa.Column("shares_outstanding_pit", sa.Float(), nullable=True),
        sa.Column("share_split_factor", sa.Float(), nullable=True),
        sa.Column("eps_diluted", sa.Float(), nullable=True),
        sa.Column("eps_basic", sa.Float(), nullable=True),
        sa.Column("revenue_per_share", sa.Float(), nullable=True),
        sa.Column("interest_expense", sa.Float(), nullable=True),
        sa.Column("income_tax_expense", sa.Float(), nullable=True),
        sa.Column("funds_held_for_clients", sa.Float(), nullable=True),
        sa.Column("investment_income_interest", sa.Float(), nullable=True),
        sa.Column("share_based_compensation", sa.Float(), nullable=True),
        sa.Column("sbc_pct_of_revenue", sa.Float(), nullable=True),
        sa.Column("goodwill", sa.Float(), nullable=True),
        sa.Column("goodwill_pct_of_assets", sa.Float(), nullable=True),
        sa.Column("nrr_pct", sa.Float(), nullable=True),
        sa.Column("grr_pct", sa.Float(), nullable=True),
        sa.Column("retention_state", sa.Text(), nullable=True),
        sa.Column("retention_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("cloud_arr_usd", sa.Float(), nullable=True),
        sa.Column("cloud_arr_growth_yoy_pct", sa.Float(), nullable=True),
        sa.Column("total_arr_usd", sa.Float(), nullable=True),
        sa.Column("total_arr_growth_yoy_pct", sa.Float(), nullable=True),
        sa.Column("arr_state", sa.Text(), nullable=True),
        sa.Column("arr_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("patent_count_disclosed", sa.Float(), nullable=True),
        sa.Column("patent_disclosure_state", sa.Text(), nullable=True),
        sa.Column("patent_disclosure_fetched_at", sa.DateTime(), nullable=True),
        sa.Column("depreciation_amortization", sa.Float(), nullable=True),
        sa.Column("dividends_paid", sa.Float(), nullable=True),
        sa.Column("share_repurchases", sa.Float(), nullable=True),
        sa.Column("roic", sa.Float(), nullable=True),
        sa.Column("pretax_roic", sa.Float(), nullable=True),
        sa.Column("roe", sa.Float(), nullable=True),
        sa.Column("roa", sa.Float(), nullable=True),
        sa.Column("gp_a", sa.Float(), nullable=True),
        sa.Column("net_margin", sa.Float(), nullable=True),
        sa.Column("operating_margin", sa.Float(), nullable=True),
        sa.Column("fcf_margin", sa.Float(), nullable=True),
        sa.Column("rd_intensity", sa.Float(), nullable=True),
        sa.Column("asset_turnover", sa.Float(), nullable=True),
        sa.Column("debt_to_equity", sa.Float(), nullable=True),
        sa.Column("net_debt", sa.Float(), nullable=True),
        sa.Column("debt_to_ebitda", sa.Float(), nullable=True),
        sa.Column("current_ratio", sa.Float(), nullable=True),
        sa.Column("interest_coverage", sa.Float(), nullable=True),
        sa.Column("accruals_ratio", sa.Float(), nullable=True),
        sa.Column("buyback_yield", sa.Float(), nullable=True),
        sa.Column("customer_concentration_pct", sa.Float(), nullable=True),
        sa.Column("customer_relationship_years", sa.Float(), nullable=True),
        sa.Column("extraction_confidence", sa.Float(), nullable=True),
        sa.Column(
            "receivables_concentration_pct",
            sa.Float().with_variant(sa.REAL(), "sqlite"),
            nullable=True,
        ),
        sa.Column("customer_concentration_state", sa.Text(), nullable=True),
        sa.Column("customer_concentration_fetched_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("receivables_concentration_state", sa.Text(), nullable=True),
        sa.Column("receivables_concentration_fetched_at", sa.TIMESTAMP(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("fx_rate_to_usd", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "fiscal_year", "period", name="uq_financial_period"),
    )
    with op.batch_alter_table("financials", schema=None) as batch_op:
        batch_op.create_index(
            "idx_financials_cust_conc_state",
            ["customer_concentration_state"],
            unique=False,
            sqlite_where=sa.text("customer_concentration_state IS NOT NULL"),
            postgresql_where=sa.text("customer_concentration_state IS NOT NULL"),
        )
        batch_op.create_index(
            "idx_financials_recv_conc_state",
            ["receivables_concentration_state"],
            unique=False,
            sqlite_where=sa.text("receivables_concentration_state IS NOT NULL"),
            postgresql_where=sa.text("receivables_concentration_state IS NOT NULL"),
        )

    op.create_table(
        "framework_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("company_stage", sa.Text(), nullable=True),
        sa.Column("f1_score", sa.Float(), nullable=True),
        sa.Column("f2_score", sa.Float(), nullable=True),
        sa.Column("f3_score", sa.Float(), nullable=True),
        sa.Column("f4_score", sa.Float(), nullable=True),
        sa.Column("f5_score", sa.Float(), nullable=True),
        sa.Column("f6_score", sa.Float(), nullable=True),
        sa.Column("f7_score", sa.Float(), nullable=True),
        sa.Column("composite_score", sa.Float(), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=True),
        sa.Column("piotroski_score", sa.Integer(), nullable=True),
        sa.Column("overlay_ica_run", sa.Boolean(), nullable=True),
        sa.Column("overlay_psa_run", sa.Boolean(), nullable=True),
        sa.Column("overlay_bew_run", sa.Boolean(), nullable=True),
        sa.Column("overlay_notes", sa.Text(), nullable=True),
        sa.Column("disqualified", sa.Boolean(), nullable=True),
        sa.Column("disqualification_reasons", sa.Text(), nullable=True),
        sa.Column("scorecard_json", sa.Text(), nullable=True),
        sa.Column("narrative_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "insider_transactions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("filing_date", sa.Date(), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=True),
        sa.Column("insider_name", sa.Text(), nullable=True),
        sa.Column("insider_title", sa.Text(), nullable=True),
        sa.Column("transaction_type", sa.Text(), nullable=True),
        sa.Column("shares", sa.Float(), nullable=True),
        sa.Column("price_per_share", sa.Float(), nullable=True),
        sa.Column("value_usd", sa.Float(), nullable=True),
        sa.Column("is_open_market", sa.Boolean(), nullable=True),
        sa.Column("form_type", sa.Text(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "institutional_holders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("report_date", sa.Date(), nullable=False),
        sa.Column("holder_name", sa.Text(), nullable=True),
        sa.Column("shares_held", sa.Integer(), nullable=True),
        sa.Column("value_usd", sa.Float(), nullable=True),
        sa.Column("pct_of_shares_out", sa.Float(), nullable=True),
        sa.Column("change_in_shares", sa.Integer(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "portfolio_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("shares", sa.Float(), nullable=True),
        sa.Column("cost_basis_usd", sa.Float(), nullable=True),
        sa.Column("cost_basis_per_share", sa.Float(), nullable=True),
        sa.Column("thesis", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column(
            "added_to_portfolio_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column("exited_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "entry_date", name="uq_portfolio_position_entry"),
    )
    with op.batch_alter_table("portfolio_positions", schema=None) as batch_op:
        batch_op.create_index("idx_portfolio_active", ["is_active"], unique=False)
        batch_op.create_index("idx_portfolio_ticker", ["ticker"], unique=False)

    op.create_table(
        "price_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("adj_close", sa.Float(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "date", name="uq_price_date"),
    )
    op.create_table(
        "screener_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("screener_run_id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=True),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("hard_gate_passed", sa.Boolean(), nullable=True),
        sa.Column("gate_failures", sa.Text(), nullable=True),
        sa.Column("f1_proxy", sa.Float(), nullable=True),
        sa.Column("f2_proxy", sa.Float(), nullable=True),
        sa.Column("f3_proxy", sa.Float(), nullable=True),
        sa.Column("f4_proxy", sa.Float(), nullable=True),
        sa.Column("f5_proxy", sa.Float(), nullable=True),
        sa.Column("f6_proxy", sa.Float(), nullable=True),
        sa.Column("f7_proxy", sa.Float(), nullable=True),
        sa.Column("composite_score", sa.Float(), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["screener_run_id"],
            ["screener_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("screener_run_id", "ticker", name="uq_screener_result_run_ticker"),
    )
    op.create_table(
        "screener_stages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("screener_run_id", sa.Integer(), nullable=False),
        sa.Column("stage", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("input_count", sa.Integer(), nullable=True),
        sa.Column("output_count", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("state_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["screener_run_id"],
            ["screener_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("screener_run_id", "stage", name="uq_screener_stage"),
    )
    op.create_table(
        "short_interest",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("settlement_date", sa.Date(), nullable=False),
        sa.Column("short_interest", sa.Integer(), nullable=True),
        sa.Column("short_pct_float", sa.Float(), nullable=True),
        sa.Column("days_to_cover", sa.Float(), nullable=True),
        sa.Column("float_shares", sa.Integer(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "settlement_date", name="uq_short_date"),
    )
    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("added_date", sa.Date(), server_default=sa.text("(CURRENT_DATE)"), nullable=True),
        sa.Column("entry_triggers", sa.Text(), nullable=True),
        sa.Column("stop_loss_note", sa.Text(), nullable=True),
        sa.Column("role", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "deepdive_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("screener_result_id", sa.Integer(), nullable=True),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column(
            "run_date", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=True
        ),
        sa.Column("composite_score", sa.Float(), nullable=True),
        sa.Column("verdict", sa.Text(), nullable=True),
        sa.Column("f1_score", sa.Float(), nullable=True),
        sa.Column("f2_score", sa.Float(), nullable=True),
        sa.Column("f3_score", sa.Float(), nullable=True),
        sa.Column("f4_score", sa.Float(), nullable=True),
        sa.Column("f5_score", sa.Float(), nullable=True),
        sa.Column("f6_score", sa.Float(), nullable=True),
        sa.Column("f7_score", sa.Float(), nullable=True),
        sa.Column("framework_results_json", sa.Text(), nullable=True),
        sa.Column("overlays_triggered_json", sa.Text(), nullable=True),
        sa.Column("overlays_results_json", sa.Text(), nullable=True),
        sa.Column("bull_narrative", sa.Text(), nullable=True),
        sa.Column("bear_narrative", sa.Text(), nullable=True),
        sa.Column("risk_factors", sa.Text(), nullable=True),
        sa.Column("data_gaps_json", sa.Text(), nullable=True),
        sa.Column("edgar_10k_accession", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
        ),
        sa.ForeignKeyConstraint(
            ["screener_result_id"],
            ["screener_results.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "deep_dive_conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("deep_dive_run_id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.Text(), nullable=False),
        sa.Column("turn_index", sa.Integer(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("numeric_claims_json", sa.Text(), nullable=True),
        sa.Column("guard_warnings_json", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(
            ["deep_dive_run_id"],
            ["deepdive_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("deep_dive_run_id", "turn_index", name="uq_dive_conversation_turn"),
    )
    with op.batch_alter_table("deep_dive_conversations", schema=None) as batch_op:
        batch_op.create_index("idx_dive_conversation_run", ["deep_dive_run_id"], unique=False)
        batch_op.create_index("idx_dive_conversation_ticker", ["ticker"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("deep_dive_conversations", schema=None) as batch_op:
        batch_op.drop_index("idx_dive_conversation_ticker")
        batch_op.drop_index("idx_dive_conversation_run")

    op.drop_table("deep_dive_conversations")
    op.drop_table("deepdive_runs")
    op.drop_table("watchlist")
    op.drop_table("short_interest")
    op.drop_table("screener_stages")
    op.drop_table("screener_results")
    op.drop_table("price_history")
    with op.batch_alter_table("portfolio_positions", schema=None) as batch_op:
        batch_op.drop_index("idx_portfolio_ticker")
        batch_op.drop_index("idx_portfolio_active")

    op.drop_table("portfolio_positions")
    op.drop_table("institutional_holders")
    op.drop_table("insider_transactions")
    op.drop_table("framework_scores")
    with op.batch_alter_table("financials", schema=None) as batch_op:
        batch_op.drop_index(
            "idx_financials_recv_conc_state",
            sqlite_where=sa.text("receivables_concentration_state IS NOT NULL"),
            postgresql_where=sa.text("receivables_concentration_state IS NOT NULL"),
        )
        batch_op.drop_index(
            "idx_financials_cust_conc_state",
            sqlite_where=sa.text("customer_concentration_state IS NOT NULL"),
            postgresql_where=sa.text("customer_concentration_state IS NOT NULL"),
        )

    op.drop_table("financials")
    with op.batch_alter_table("external_signals", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_external_signals_signal_name"))
        batch_op.drop_index(batch_op.f("ix_external_signals_company_id"))

    op.drop_table("external_signals")
    with op.batch_alter_table("exclusion_verdicts", schema=None) as batch_op:
        batch_op.drop_index("ix_exclusion_verdicts_policy_status")

    op.drop_table("exclusion_verdicts")
    op.drop_table("earnings_history")
    op.drop_table("analyst_coverage")
    with op.batch_alter_table("task_runs", schema=None) as batch_op:
        batch_op.drop_index("idx_task_runs_ticker")
        batch_op.drop_index("idx_task_runs_task")
        batch_op.drop_index("idx_task_runs_name_time")

    op.drop_table("task_runs")
    op.drop_table("task_failures")
    with op.batch_alter_table("skill_invocations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_skill_invocations_skill_name"))
        batch_op.drop_index(batch_op.f("ix_skill_invocations_invoked_at"))

    op.drop_table("skill_invocations")
    op.drop_table("screener_runs")
    op.drop_table("financial_source_log")
    with op.batch_alter_table("companies", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_companies_cik"))
        batch_op.drop_index("idx_companies_status_score")
        batch_op.drop_index("idx_companies_pt_adjusted_roic")
        batch_op.drop_index(
            "idx_companies_ipo_state",
            sqlite_where=sa.text("ipo_date_state IS NOT NULL"),
            postgresql_where=sa.text("ipo_date_state IS NOT NULL"),
        )
        batch_op.drop_index("idx_companies_framework_score")
        batch_op.drop_index(
            "idx_companies_founder_state",
            sqlite_where=sa.text("is_founder_ceo_state IS NOT NULL"),
            postgresql_where=sa.text("is_founder_ceo_state IS NOT NULL"),
        )
        batch_op.drop_index(
            "idx_companies_ceo_name_state",
            sqlite_where=sa.text("ceo_name_state IS NOT NULL"),
            postgresql_where=sa.text("ceo_name_state IS NOT NULL"),
        )
        batch_op.drop_index(
            "idx_companies_ceo_equity_state",
            sqlite_where=sa.text("ceo_equity_pct_state IS NOT NULL"),
            postgresql_where=sa.text("ceo_equity_pct_state IS NOT NULL"),
        )

    op.drop_table("companies")
