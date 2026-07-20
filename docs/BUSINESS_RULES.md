# Business Rules

**Purpose:** Compact, current-state summary of approved Medical Equipment Pool business rules, for fast AI/human onboarding
**Authority:** Summary only. Each rule cites its authoritative source; the cited source controls in case of any apparent conflict with this file. This file does not add, relax, or reinterpret a rule.
**Update trigger:** A rule below is confirmed changed by an approved ADR, `docs/ARCHITECTURE_DECISIONS.md` entry, or Governance PR
**Maintainer:** Architecture Owner

Only approved, confirmed rules are listed here. Do not add a rule that has not been confirmed through the sources below.

## Four Equipment States

Equipment has exactly four states: `AVAILABLE_AT_POOL`, `ISSUED_TO_WARD`, `UNAVAILABLE_DEFECTIVE`, `DECOMMISSIONED`. No fifth state (in particular, no cleaning-related state) exists.

- Source: `docs/HOSPITAL_DOMAIN_MODEL.md` ("Confirmed workflow"); `docs/audits/04-consolidated-implementation-plan.md` Part A; implemented by migration `0006_equipment_state_model.py` and `backend/app/models/equipment.py`.

## Cleaning is performed during receipt and is not tracked

Equipment receipt is one atomic digital operation with a binary outcome (usable or defective). Cleaning is a physical process that may happen before or after the digital receipt entry; the system has no cleaning state, cleaning-complete action, or cleaning workflow, and never records cleaning status.

- Source: `docs/ARCHITECTURE_DECISIONS.md` ("No cleaning workflow"); `AGENTS.md` (Domain Guardrails); `docs/audits/04-consolidated-implementation-plan.md` Part B.1.

## UUID is relational identity

The internal UUID is the permanent relational primary key for an equipment record. It is never entered manually by an operator and is the only identifier borrow/return records reference. It does not change even if BCM Code, Item No, or Asset Number are later corrected or reassigned.

- Source: `knowledge/adr/ADR-002-identifier-model.md`; `knowledge/business-rules/equipment-pool.md`.

## BCM is the manual identifier

BCM Code is the primary operator-facing identifier and the only identifier accepted by manual equipment search. It is unique across all equipment; uniqueness and search matching are enforced on its canonical persisted form.

- Source: `knowledge/adr/ADR-002-identifier-model.md`; `knowledge/adr/ADR-003-bcm-manual-search.md`; `knowledge/architecture/identifiers.md`.

## Item No is internal QR lookup only

Item No is the identifier encoded in the hospital's existing QR labels. It is used only for exact QR lookup, is unavailable as a manual-search identifier, and is absent from normal operator-facing response contracts — it may appear only in explicitly restricted administrative/import contexts.

- Source: `knowledge/adr/ADR-002-identifier-model.md`; `knowledge/adr/ADR-004-hospital-item-no-qr.md`; `knowledge/architecture/api-information-boundaries.md`.

**"ME Code" is retired.** It does not name any current or planned identifier; any document or task still using it means BCM Code or Item No and should be corrected.

## Dispatch/Return owns transaction lifecycle

A dispatch/return transaction has exactly two states, `OPEN` and `CLOSED`. Dispatch opens a transaction and moves equipment `AVAILABLE_AT_POOL -> ISSUED_TO_WARD`; receipt closes it with a usable or defective outcome. Dispatch and receipt are the only paths that open or close a transaction — administrative/manual equipment-status maintenance is a separate, narrower transition set that never opens or closes a transaction and never originates or targets `ISSUED_TO_WARD`.

- Source: `docs/HOSPITAL_DOMAIN_MODEL.md` ("Confirmed workflow"); implemented by `backend/app/services/borrow_service.py` (dispatch/receipt) versus the administrative status-transition table in `backend/app/models/equipment.py`.

## Decommission requires AVAILABLE -> UNAVAILABLE_DEFECTIVE -> DECOMMISSIONED

`AVAILABLE_AT_POOL` has no direct transition to `DECOMMISSIONED`. Equipment must first be marked `UNAVAILABLE_DEFECTIVE`; only `UNAVAILABLE_DEFECTIVE` may transition to `DECOMMISSIONED`. `DECOMMISSIONED` is terminal with no outgoing transition.

- Source: `backend/app/models/equipment.py` (manual-maintenance transition table); confirmed as a review finding during Roadmap PR6 (see `docs/DECISION_LOG.md`).

## Related documents

| Concern | Document |
|---|---|
| Full domain workflow narrative and terminology | `docs/HOSPITAL_DOMAIN_MODEL.md` |
| Architecture invariants that protect these rules | `docs/ARCHITECTURE_GUARDRAILS.md` |
| Per-decision rationale and history | `docs/DECISION_LOG.md`, `docs/ARCHITECTURE_DECISIONS.md` |
| Identifier/QR architecture detail | `knowledge/adr/ADR-002` through `ADR-004`, `knowledge/architecture/` |
| Preferred terminology | `docs/GLOSSARY.md`, `knowledge/glossary.md` |
