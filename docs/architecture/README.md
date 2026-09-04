# Architecture Diagrams

These diagrams are navigation aids, not independent requirements. Text in
[`../ARCHITECTURE_DECISIONS.md`](../ARCHITECTURE_DECISIONS.md),
[`../HOSPITAL_DOMAIN_MODEL.md`](../HOSPITAL_DOMAIN_MODEL.md), and the assigned
Roadmap section remains authoritative.

## System context

```mermaid
flowchart LR
    Requestors["Hospital wards/departments\nexternal requestors\nnot application users"]
    Staff["Equipment Pool / BME operators"]
    Browser["Browser / PWA client"]

    subgraph Managed["Approved managed deployment boundary"]
        API["FastAPI backend"]
        PG[("PostgreSQL\nsystem of record")]
        Redis[("Redis\ncache / refresh-token support")]
    end

    Requestors -->|"phone / operational request"| Staff
    Staff --> Browser
    Browser -->|"HTTPS API"| API
    API --> PG
    API --> Redis
```

The application does not assume direct access to hospital-managed servers.
Deployment-provider detail remains unselected. See “Managed deployment
preferred” in `ARCHITECTURE_DECISIONS.md`.

## Audit and transaction flow

```mermaid
flowchart TD
    Req["HTTP request"] --> Context["Validated request ID / correlation ID\nand bounded request metadata"]
    Context --> Auth["Authenticated actor resolution"]
    Auth --> Service["Authorized business mutation"]
    Service --> Business["Business write"]
    Service --> Audit["Canonical audit helper\nexplicit safe snapshots"]

    subgraph Tx["Shared AsyncSession / database transaction"]
        Business --> FlushBusiness["flush"]
        Audit --> Redact["recursive central redaction"]
        Redact --> FlushAudit["flush; no independent commit"]
    end

    FlushBusiness --> Outcome{"all required writes succeed?"}
    FlushAudit --> Outcome
    Outcome -->|"yes"| Commit["single commit"]
    Outcome -->|"no"| Rollback["rollback business + audit"]
    Commit --> AdminRead["Administrator-only audit read\nbounded deterministic pagination"]
```

Authentication-event persistence has its separately documented availability
strategy; unknown failed-login identifiers have null actor/subject and no
persisted identity representation. See
[`../adr/ADR-0001-canonical-audit-and-failed-login-identifiers.md`](../adr/ADR-0001-canonical-audit-and-failed-login-identifiers.md).

## Equipment Pool domain flow

```mermaid
stateDiagram-v2
    [*] --> AVAILABLE_AT_POOL
    AVAILABLE_AT_POOL --> ISSUED_TO_WARD: dispatch to first receiving ward
    ISSUED_TO_WARD --> AVAILABLE_AT_POOL: receipt outcome = usable
    ISSUED_TO_WARD --> UNAVAILABLE_DEFECTIVE: receipt outcome = defective
    UNAVAILABLE_DEFECTIVE --> AVAILABLE_AT_POOL: approved return to service
    UNAVAILABLE_DEFECTIVE --> DECOMMISSIONED: decommission

    note right of ISSUED_TO_WARD
      No patient tracking
      No inter-ward transfer tracking
      No cleaning state
    end note
```

Shift Sessions and Standby Snapshots are confirmed future concepts outside this
state machine. They are not inferred from transactions and are not introduced by
these diagrams.
