# Project Glossary

**Purpose:** Preferred domain and audit terminology
**Authority:** Terminology only; workflow detail remains in `HOSPITAL_DOMAIN_MODEL.md`. Equipment-identifier terms (BCM Code, Item No, Asset Number, and the retired "ME Code") are owned by [`../knowledge/glossary.md`](../knowledge/glossary.md) — see `PROJECT_PLAYBOOK.md`'s topic-ownership table. This file remains authoritative for every other term below.
**Update trigger:** Approved term or ambiguity change
**Maintainer:** Documentation/Governance Engineer

| Preferred term | Concise definition | Avoid / clarify | Status |
|---|---|---|---|
| Equipment Pool | Central unit that dispatches and receives pool equipment | Not hospital-wide asset management | Current |
| Biomedical Engineering (BME) | Organizational/professional context for Equipment Pool staff | Do not assume all BME functions are in scope | Current context |
| Operator | Authenticated Equipment Pool staff member recording an action | Not ward requestor, patient, or generic “user” when attribution matters | Current |
| Administrator | Application role authorized for assigned administrative capabilities | Does not imply infrastructure/server administrator | Current |
| Department | Organizational grouping that may contain wards | Not interchangeable with ward | Current |
| Ward | First receiving destination recorded for a dispatch | Not current patient/equipment location | Current |
| First receiving ward | Ward selected when equipment first leaves the pool | Do not update for later real-world transfers | Current |
| Equipment | One physical device with internal UUID identity | Not a quantity/batch | Current |
| BCM Code, Item No, Asset Number, ~~ME Code~~ | See [`../knowledge/glossary.md`](../knowledge/glossary.md) | "ME Code" is retired — do not use | See `knowledge/adr/ADR-002` |
| Dispatch | Operator records equipment leaving pool for first receiving ward | Prefer over “borrow” in user-facing domain language | Roadmap target |
| Receipt | One atomic operation closing an open dispatch with usable/defective outcome | Not cleaning completion | Roadmap target |
| Issue | Physical/operational act of sending equipment to a ward | Prefer “dispatch” for system records | Contextual synonym |
| Return | Physical movement back toward the pool | Prefer “receipt” for the digital system action | Contextual synonym |
| Transaction | Dispatch record from opening through receipt/closure | Not a database transaction unless explicitly qualified | Current/target |
| Transaction Number | Human-readable unique transaction reference | Not database UUID; generation belongs to Roadmap PR4 | Roadmap PR4 target |
| Equipment State | System state controlling dispatch eligibility | Not cleaning or patient location | Roadmap PR6 target |
| `AVAILABLE_AT_POOL` | At pool and eligible for dispatch | Not merely “cleaned” | Roadmap PR6 target |
| `ISSUED_TO_WARD` | Dispatched with an open transaction | “Borrowed” is legacy implementation terminology | Roadmap PR6 target |
| `UNAVAILABLE_DEFECTIVE` | Blocked because unusable/defective or safely classified pending review | Not a cleaning state | Roadmap PR6 target |
| `DECOMMISSIONED` | Permanently retired; terminal normal state | Do not reactivate through ordinary workflow | Roadmap PR6 target |
| Shift Session | Future flexible operating session containing multiple operators' transactions | Not a transaction or fixed clock-time round | Confirmed future |
| `DAY` / `NIGHT` | Future Shift Session/Standby period labels | Do not invent fixed boundaries | Confirmed future |
| Standby Snapshot | Manually entered department-level counts for a Day/Night period | Not derived from transactions or Shift Sessions | Confirmed future |
| Ready-to-use unit | Manually counted equipment available for standby reporting | Exact schema deferred | Confirmed future snapshot concept |
| Charging cable | Separately counted standby accessory where required | Not inferred from equipment quantity | Confirmed future snapshot item |
| Clamp | Separately counted standby accessory where required | Exact type/schema deferred | Confirmed future snapshot item |
| Pneumatic pump | Separately counted standby item where required | Do not infer from dispatch records | Confirmed future snapshot item |
| Audit actor | Authenticated user/system context performing the action | Failed authentication target is never the actor | Current PR3 policy |
| Audit subject/entity | Resource affected by the action | Separate from actor | Current PR3 policy |
| Request ID | Validated bounded identifier for one HTTP request | Not a cross-request business identifier | Current PR3 policy |
| Correlation ID | Validated bounded identifier used to relate approved request activity | Not permission to persist submitted login identifiers | Current PR3 policy |

## Required distinctions

- **Receipt vs cleaning:** receipt records a usable/defective outcome; cleaning is
  a physical activity outside system state.
- **Ward vs department:** a ward is the first receiving destination; a department
  is an organizational grouping and future reporting dimension.
- **Actor vs subject:** actor performs; subject is affected. Unknown login
  attempts have neither actor nor subject identity persisted.
- **Pool location vs patient location:** the system may describe pool/first ward
  context but never tracks a patient or claims live patient/equipment location.
- **Current vs future:** Shift Sessions and Standby Snapshots are confirmed but
  unscheduled future work; target equipment/transaction terms land in their
  assigned Roadmap PRs.
