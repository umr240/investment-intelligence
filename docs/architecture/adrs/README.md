# Architecture decision records

Each ADR records one decision: the context, the options weighed, what was
chosen and why, and how it is verified. Smaller decisions live in
`../DECISIONS.md` as `DEC-nn` entries.

- **Numbering starts at ADR-016.** Earlier numbers were used before this
  repository existed and are not included here.
- **Amendments** keep the parent's number with a suffix: `ADR-023-A1` amends
  ADR-023. The parent ADR's status line names its amendments.
- **Status** is one of *Proposed* (written, awaiting sign-off), *Accepted*,
  *Superseded* (the status line names the successor) or *Draft*. A proposed
  ADR describes intent; the code may not do it yet.
- **Archived references.** Some ADRs cite probe scripts, plans or status
  snapshots that were retired when the repository was published. Those are
  marked *archived*; they survive in a private archive and are not needed to
  read the decision.

To add one, take the next free number, follow the shape of a recent ADR
(context, decision, alternatives, verification), and link it from any
`DEC-nn` entry or code comment that depends on it.
