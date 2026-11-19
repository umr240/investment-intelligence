# Roadmap

Ordered list of open outcomes, one line each. `/agentic-kit:next` specifies the first unchecked outcome without a spec, then stops for sign-off; merging the spec's PR approves it, and the spec adds its link here.

- [ ] Every stored deep-dive narrative passes `deepdive/narrative_guard.py` (8 of 13 failed the contract, ADR-023-A1; ADR-045 to ADR-047 carry the fix)
- [ ] SEC-first provenance covers the deferred fields B.1, B.4 and B.5 (ADR-033, `docs/architecture/API_FIELD_AUDIT.md`)
- [ ] One monthly LLM spend ceiling, checked before every provider request (ADR-031-A2, proposed: its spec opens by accepting or rejecting it)
- [ ] AWS account guardrails as code, near-$0 budget with a Bedrock deny (ADR-058, proposed: its spec opens by accepting or rejecting it; needs ADR-031-A2)
- [ ] Amazon Bedrock as an off-by-default narrative provider (ADR-031-A3, proposed: its spec opens by accepting or rejecting it; needs ADR-031-A2 and ADR-058)
