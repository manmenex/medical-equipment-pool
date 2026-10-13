# ADR-0001: Canonical Audit Framework and Failed-Login Identifiers

## Status

Accepted by Governance PR #8. Roadmap PR3 implementation is not complete until
its behavior conforms to this decision.

## Context

Later Roadmap work needs one reusable audit contract for attribution,
redaction, request context, transaction behavior, and authorized reads. Login
failures add a privacy risk: employee codes and email addresses are low-entropy
identifiers, so a deterministic unkeyed hash remains enumerable by dictionary
matching even when the raw input is absent.

## Decision

1. Roadmap PR3 owns one canonical audit-event writer; later PRs reuse it rather
   than creating parallel audit systems.
2. Mandatory business-mutation audit writes use the same `AsyncSession` and
   transaction as the business write. The helper flushes but does not commit.
3. Audit actor and subject/entity are separate. An authentication target is
   never attributed as the actor.
4. For a failed login against a known account, actor remains null and the known
   account may be the subject if this does not create enumeration in the API.
5. For an unknown submitted identifier, actor and subject `entity_id` remain
   null. The identifier is not stored raw, as a deterministic unkeyed hash, or
   in any enumerable/correlatable representation.
6. A keyed HMAC may be considered only through a separately approved design
   covering secret creation/storage/rotation, access, retention, purpose, and
   deletion. Roadmap PR3 neither requires nor introduces keyed HMAC.
7. Secret redaction is centralized, recursive, and unconditional before audit
   persistence.

## Alternatives considered

- **Store the raw identifier:** rejected; directly exposes employee/email data.
- **Store SHA-256 or another deterministic unkeyed hash:** rejected; low-entropy
  identifiers are enumerable offline.
- **Store a keyed HMAC now:** deferred; it creates a new secret lifecycle and
  retention/correlation capability outside PR3 scope.
- **Store no submitted identifier for unknown accounts:** selected; a generic
  login-failure event can retain safe request metadata without identity data.
- **Per-endpoint audit/redaction logic:** rejected; it permits divergence and
  secret leakage as endpoints are added.

## Consequences

- Unknown failed-login attempts cannot be grouped by submitted identity from
  audit storage; rate limiting and security telemetry must use separately
  approved ephemeral controls rather than the permanent audit payload.
- Tests must prove identifier non-persistence/non-enumerability, null actor and
  subject for unknown accounts, recursive redaction, and normal failed-login
  audit persistence behavior.
- PR descriptions must not claim privacy compliance merely because an input is hashed.
- Any future correlation design requires a new or superseding ADR.

## Scope boundary

This ADR does not design rate limiting, a SIEM, broad observability, retention
periods, encryption infrastructure, missing auth endpoints, or new CRUD. It
does not change the business-audit atomicity exception explicitly documented
for authentication availability.

## Related PRs and documents

- Governance PR #8 and correction commit `69736e7`
- Draft implementation PR #7
- [`../ARCHITECTURE_DECISIONS.md`](../ARCHITECTURE_DECISIONS.md)
- [`../audits/04-consolidated-implementation-plan.md`](../audits/04-consolidated-implementation-plan.md), Roadmap PR3
- [`../ARCHITECTURE_GUARDRAILS.md`](../ARCHITECTURE_GUARDRAILS.md)

## Supersedes / superseded by

- **Supersedes:** Governance wording that allowed an unkeyed one-way
  correlation hash for unknown identifiers.
- **Superseded by:** None. Future changes require a stable new ADR identifier;
  ADR numbers are never reused or renumbered.
