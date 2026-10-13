# Master Data API: Wards and Departments

**Purpose:** Contract for the ward and department master-data endpoints, including the optional contact `phone`.
**Authority:** Documents current behavior in `backend/app/api/v1/master_data.py` and `backend/app/schemas/master_data.py`. Not a design proposal.
**Update trigger:** The ward/department endpoints' request/response shape, validation, or role gates change.
**Maintainer:** Repository Owner

## Endpoints

| Method and path | Roles | Notes |
|---|---|---|
| `GET /api/v1/wards` | any authenticated user | list, ordered by name |
| `POST /api/v1/wards` | administrator only | create (`201`) |
| `GET /api/v1/departments` | any authenticated user | list, ordered by name |
| `POST /api/v1/departments` | administrator only | create (`201`) |

There is **no update or delete endpoint** for wards or departments. The `phone` is therefore set at create time only; changing an existing ward's or department's phone needs a master-data update path that does not exist yet (flagged prerequisite, Roadmap PR25E slice B0).

## `phone` (Roadmap PR25E slice B0)

`WardCreate`, `DepartmentCreate`, `WardOut` and `DepartmentOut` carry an optional `phone` (string or `null`, default `null`). It is the ward/department contact number the dispatch form will use to prefill `phone_number` (ward first, department as fallback); it is not a personal or patient number.

Validation on create (`422 VALIDATION_ERROR` when violated):

- surrounding whitespace is trimmed; a blank value is stored as `null`
- at most 20 characters (same cap as `phone_number` on a dispatch)
- digits, spaces and dashes, an optional leading `+`, and an optional extension (`ext 12`, `ext. 12`, `x12`); at least 3 digits

Existing rows have `phone: null` until recreated; the migration (`0026_ward_department_phone`) does not backfill.
