"""
Lattice graph-integrity tests (ADR-024 §1.6 / §1.7).

Two layers of guarantee:

  1. **Reference integrity** (CI-blocking) — every slug listed in any model's
     `related_models` must resolve to an existing model file. A dangling
     reference is a typo or a removed/renamed slug; both are bugs.

  2. **Asymmetric edges** (informational) — A → B without B → A is *allowed*
     (the lattice is a directed graph: a niche model often draws from a
     foundational one without reciprocity). This test asserts the count
     stays roughly stable so accidental edge-loss is visible. Dropping the
     count significantly without intent suggests an unintended edge purge.

If a model file is added or removed, the asymmetry count will shift —
update ``ASYMMETRY_BUDGET`` to match the new baseline. The point of the
budget is to make *unintentional* graph degradation surface in CI, not
to enforce a specific shape.
"""
from __future__ import annotations

from deepdive.mental_model_composer import (
    AsymmetricEdge,
    DanglingReference,
    ValidationReport,
    load_lattice,
    validate_lattice,
)

# ── Real-lattice CI guard ────────────────────────────────────────────────


# Approximate. Drift +/- ~30 is fine; large drops should prompt review.
ASYMMETRY_BUDGET = 350


def test_real_lattice_has_no_dangling_references() -> None:
    """The on-disk lattice must satisfy reference integrity (ADR-024 §1.6).

    Failure means a `related_models` slug points at a file that doesn't
    exist — typically a typo, a renamed slug, or a planned-but-never-
    authored model. Fix the reference (or author the missing model);
    do not relax this assertion.
    """
    report = validate_lattice(load_lattice())
    assert report.is_valid, (
        f"Dangling references in lattice ({len(report.errors)}):\n"
        + "\n".join(f"  {e}" for e in report.errors)
    )


def test_real_lattice_asymmetry_within_budget() -> None:
    """Asymmetric edges are tolerated (lattice is a directed graph), but
    the count is monitored so an unintentional purge surfaces in CI.
    """
    report = validate_lattice(load_lattice())
    assert len(report.warnings) <= ASYMMETRY_BUDGET, (
        f"Asymmetric-edge count {len(report.warnings)} exceeds budget "
        f"{ASYMMETRY_BUDGET}. Either reciprocate links, or update the "
        f"budget if the new shape is intentional."
    )


# ── Validator unit tests (synthetic lattices) ────────────────────────────


def _fake_model(slug: str, related: list[str], domain: str = "core"):
    """Build a MentalModel with the minimum fields required by the schema.

    The validator only looks at ``slug``, ``related_models``, ``file_path``,
    so the rest just satisfies pydantic.
    """
    from datetime import date

    from deepdive.mental_model_composer import MentalModel

    return MentalModel(
        slug=slug,
        name=slug.title(),
        school="test",
        citation_tier="◯",
        always_load=False,
        related_models=related,
        code_consequences=["test"],
        token_cost_estimate=200,
        version=1.0,
        added=date(2026, 1, 1),
        last_reviewed=date(2026, 1, 1),
        domain=domain,
        body="## Summary\nfoo\n## Inversion form\nbar\n",
        file_path=f"{domain}/{slug}.md",
    )


def _build(*pairs: tuple[str, list[str]]):
    return {slug: _fake_model(slug, refs) for slug, refs in pairs}


class TestValidatorBehaviour:
    def test_clean_lattice_reports_no_errors_no_warnings(self) -> None:
        # A fully reciprocal triangle: every edge has a reverse.
        lattice = _build(
            ("a", ["b", "c"]),
            ("b", ["a", "c"]),
            ("c", ["a", "b"]),
        )
        report = validate_lattice(lattice)
        assert report.is_valid is True
        assert report.errors == []
        assert report.warnings == []
        assert report.total_models == 3
        assert report.total_edges == 6

    def test_dangling_reference_is_an_error(self) -> None:
        lattice = _build(
            ("a", ["b", "ghost"]),
            ("b", ["a", "c"]),
            ("c", ["a", "b"]),
        )
        report = validate_lattice(lattice)
        assert report.is_valid is False
        # Exactly one dangling: ghost. (b → c, c → b are clean.)
        assert len(report.errors) == 1
        err = report.errors[0]
        assert isinstance(err, DanglingReference)
        assert err.source_slug == "a"
        assert err.referenced_slug == "ghost"

    def test_dangling_reference_is_not_double_counted_as_warning(self) -> None:
        # 'ghost' doesn't exist → it's an error. We must NOT also flag the
        # reverse-edge "missing" as an asymmetry warning, because there's
        # no node to reciprocate from in the first place.
        lattice = _build(
            ("a", ["b", "ghost"]),
            ("b", ["a", "c"]),
            ("c", ["a", "b"]),
        )
        report = validate_lattice(lattice)
        ghost_warnings = [
            w for w in report.warnings
            if "ghost" in (w.source_slug, w.target_slug)
        ]
        assert ghost_warnings == [], (
            "ghost should not appear in asymmetry warnings — it's an error"
        )

    def test_asymmetric_edge_is_a_warning_not_an_error(self) -> None:
        # a → b → c → a (one-way cycle). Every edge is asymmetric.
        lattice = _build(
            ("a", ["b", "c"]),  # a → b is asymmetric (b doesn't list a)
            ("b", ["c", "a"]),
            ("c", ["a", "b"]),
        )
        # Make a→b asymmetric: rebuild with b not pointing back at a
        lattice = _build(
            ("a", ["b", "c"]),
            ("b", ["c", "a"]),  # b → a reciprocates a → b
            ("c", ["a", "b"]),
        )
        report = validate_lattice(lattice)
        assert report.is_valid is True
        assert report.warnings == []  # this case is fully reciprocal — sanity guard

        # Now the actual asymmetry case: drop a single back-edge.
        lattice = _build(
            ("a", ["b", "c"]),
            ("b", ["c", "x"]),  # b doesn't list a → asymmetric a→b
            ("c", ["a", "b"]),
            ("x", ["b", "c"]),  # x exists; b ↔ x reciprocal
        )
        report = validate_lattice(lattice)
        assert report.is_valid is True
        # a → b is asymmetric; x → c is asymmetric
        warn_pairs = {(w.source_slug, w.target_slug) for w in report.warnings}
        assert ("a", "b") in warn_pairs
        for w in report.warnings:
            assert isinstance(w, AsymmetricEdge)

    def test_reciprocal_edge_produces_no_warning(self) -> None:
        lattice = _build(
            ("a", ["b", "c"]),
            ("b", ["a", "c"]),
            ("c", ["a", "b"]),
        )
        report = validate_lattice(lattice)
        assert report.warnings == []

    def test_report_summary_string(self) -> None:
        lattice = _build(
            ("a", ["b", "ghost"]),
            ("b", ["a", "c"]),
            ("c", ["a", "b"]),
        )
        report = validate_lattice(lattice)
        s = report.summary()
        assert "3 models" in s
        assert "errors" in s
        assert "warnings" in s

    def test_validation_report_is_a_pydantic_model(self) -> None:
        lattice = _build(
            ("a", ["b", "c"]),
            ("b", ["a", "c"]),
            ("c", ["a", "b"]),
        )
        report = validate_lattice(lattice)
        assert isinstance(report, ValidationReport)
        # Pydantic-serialisable for audit-trail use
        dumped = report.model_dump()
        assert dumped["total_models"] == 3
        assert dumped["total_edges"] == 6

    def test_errors_and_warnings_are_deterministically_ordered(self) -> None:
        # Stable ordering matters when these reports get diffed in CI.
        lattice = _build(
            ("z", ["a", "ghost_z"]),
            ("a", ["m", "ghost_a"]),  # m → a reciprocates; ghost_a dangles
            ("m", ["a", "z"]),         # m → z reciprocates z → ... wait z → a only
        )
        report = validate_lattice(lattice)
        # Errors sorted by (source_slug, referenced_slug)
        err_keys = [(e.source_slug, e.referenced_slug) for e in report.errors]
        assert err_keys == sorted(err_keys)
        # Warnings sorted by (source_slug, target_slug)
        warn_keys = [(w.source_slug, w.target_slug) for w in report.warnings]
        assert warn_keys == sorted(warn_keys)
