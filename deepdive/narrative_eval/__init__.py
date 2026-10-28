"""Narrative eval harness (ADR-047): golden set, deterministic graders, replay.

Nothing in this package calls a model; a live run goes through
`deepdive/narrative.py`, the allow-listed call site.
"""
