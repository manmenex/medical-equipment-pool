# Knowledge Layer

**Status:** v2 — governance/documentation only. No runtime system, code,
or test change is introduced by this directory.

## What this is

This directory holds durable, implementation-independent architecture
decisions (`adr/`) and the business rules and architecture concepts that
follow from them (`architecture/`, `business-rules/`), plus a shared
glossary (`glossary.md`).

**This directory's authority is defined by, and limited to, its place in
the repository's single source-of-truth hierarchy in
[`docs/PROJECT_PLAYBOOK.md`](../docs/PROJECT_PLAYBOOK.md).** This
document does not restate or compete with that hierarchy — see the
Playbook for the authoritative statement of which document governs which
topic, and `docs/PROJECT_PLAYBOOK.md`'s topic-ownership table for the
specific mapping of each topic covered here.

In short: for the topics this layer currently covers (equipment scope,
identifier model, BCM manual search, hospital QR identification), `adr/`
and the `architecture/`/`business-rules/` documents that elaborate it are
the authoritative source — not because "Knowledge" as a category
outranks other documents in general, but because the Playbook's topic
ownership table assigns those specific topics here. Other documents
(`AGENTS.md`, `docs/GLOSSARY.md`, `docs/HOSPITAL_DOMAIN_MODEL.md`,
`docs/audits/04-consolidated-implementation-plan.md`) either point to
this layer for those topics or remain authoritative for topics not yet
covered here — the Playbook's table says which, for every topic, so
there is exactly one answer per topic, never two.

## Structure

- **`adr/`** — Architecture Decision Records. One accepted decision per
  file, never renumbered; a later decision that changes one supersedes
  it explicitly rather than editing history.
- **`architecture/`** — durable technical concepts that implement an
  ADR's decision (for example, how an identifier is canonicalized).
- **`business-rules/`** — durable operational rules that follow from an
  ADR (for example, what a search result may and may not contain).
- **`glossary.md`** — shared term definitions for this layer.
- **`traceability/`** — **not authoritative.** Implementation-to-decision
  mappings and current implementation status live here, separately from
  the decisions themselves. See `traceability/README.md`.

## What does not belong in `adr/`, `architecture/`, or `business-rules/`

Those three locations describe durable decisions and constraints, not
the code that implements them. They do not name source files, functions,
UI components, migration identifiers, concrete endpoint routes, or
current implementation/PR status — that content, when useful, belongs in
`traceability/` instead, clearly marked non-authoritative. A document in
`adr/`, `architecture/`, or `business-rules/` should still be accurate
even after the code that currently implements it is rewritten.

## Numbering note

This layer's ADRs use `ADR-00N` in `knowledge/adr/`. A separate,
pre-existing ADR set at `docs/adr/ADR-0001-*.md` (indexed from
`docs/ARCHITECTURE_DECISIONS.md`) uses four-digit numbers for a different
set of topics (audit-write atomicity, failed-login identifiers). Both
sets are real; neither supersedes the other. `docs/PROJECT_PLAYBOOK.md`
is the place that states which ADR set governs which topic.
