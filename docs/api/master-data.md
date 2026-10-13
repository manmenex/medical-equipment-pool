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
| `PATCH /api/v1/wards/{id}` | administrator only | edit `phone` only |
| `PATCH /api/v1/departments/{id}` | administrator only | edit `phone` only |
| `POST /api/v1/wards/phones/import` | administrator only | one-time bulk ward phone import |

There is **no general update or delete endpoint** for wards or departments (Owner decision 2026-10-13: phone only). `PATCH` accepts the body `{"phone": ...}` and nothing else: any other field is `422`. `null` or a blank string clears the phone. The same validation as create applies. `404` for an unknown id, `400` for a malformed id. Each change writes one canonical `update` audit entry with `before` and `after` (`{"phone": ...}`).

## `phone` (Roadmap PR25E slice B0)

`WardCreate`, `DepartmentCreate`, `WardOut` and `DepartmentOut` carry an optional `phone` (string or `null`, default `null`). It is the ward/department contact number the dispatch form will use to prefill `phone_number` (ward first, department as fallback); it is not a personal or patient number.

Validation on create (`422 VALIDATION_ERROR` when violated):

- surrounding whitespace is trimmed; a blank value is stored as `null`
- at most 20 characters (same cap as `phone_number` on a dispatch)
- digits, spaces and dashes, an optional leading `+`, and an optional extension (`ext 12`, `ext. 12`, `x12`); at least 3 digits

Existing rows have `phone: null` until recreated; the migration (`0026_ward_department_phone`) does not backfill.

## One-time ward phone import

`POST /api/v1/wards/phones/import?dry_run=true&overwrite=false` (administrator only). Body: `{"rows": [{"ward_name": "...", "phone": "..."}]}`, 1 to 500 rows (otherwise `422`). No hospital data is stored in the repository; the mapping is supplied at run time.

Matching is by exact ward name after trimming (case-sensitive; the repository has no ward-name normalizer). Per-row `outcome`:

| Outcome | Meaning |
|---|---|
| `will_set` | ward has no phone; it will be set |
| `will_overwrite` | ward has a different phone and `overwrite=true` |
| `skipped_existing` | ward has a different phone and `overwrite=false`; nothing is changed |
| `unchanged` | ward already has this phone |
| `unknown_ward` | no ward has this exact name |
| `ambiguous_ward` | more than one ward has this exact name |
| `invalid_phone` | blank or fails the phone validation |
| `duplicate_ward_name` | the name appears more than once in the input; all of its rows are rejected |

`dry_run` defaults to `true` and writes nothing. With `dry_run=false`, all `will_set`/`will_overwrite` rows are applied in one transaction, and exactly one batch `import` audit entry (entity type `ward`, PR12 convention) lists every changed ward with its before and after phone. The response carries `applied`, `counts` and `results`.

Operator procedure:

1. Build the JSON mapping from the Owner-supplied list (do not commit it).
2. Call with the default `dry_run=true`; review every row, fixing `unknown_ward`, `invalid_phone`, `duplicate_ward_name` and `ambiguous_ward` rows.
3. Decide on `overwrite` (leave it off unless existing phones are known to be wrong).
4. Repeat the same request with `dry_run=false` and check `applied` and `counts`.
