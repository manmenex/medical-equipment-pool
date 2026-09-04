# Equipment API

**Purpose:** Request/response contract for every `/api/v1/equipment` endpoint.
**Authority:** Documents current behavior in `backend/app/api/v1/equipment.py` and `backend/app/schemas/equipment.py`. Not a design proposal.
**Update trigger:** An equipment endpoint's request/response shape, validation, or error behavior changes.
**Maintainer:** Repository Owner

All endpoints require a valid bearer token (`401 NOT_AUTHENTICATED` otherwise); role restrictions are called out per endpoint. Base path: `/api/v1/equipment`.

## Identifier boundary (read before using this API)

Equipment has **two distinct identifiers** with different visibility (`knowledge/architecture/api-information-boundaries.md`, ADR-002/ADR-003/ADR-004):

- **`bcm_code`** — the operator-facing identifier. Appears in every normal response (`EquipmentOut`, `BcmSuggestion`).
- **`item_no`** — the internal QR-resolution key. Write-only: accepted in `EquipmentCreate`/`EquipmentUpdate`, but **never** returned by `EquipmentOut`, `BcmSuggestion`, or any other operator-facing response. It appears only in the audit trail's internal `before`/`after` data (not exposed via this API) and in `POST /equipment/resolve-qr`'s internal lookup, whose *response* still omits it.

Do not assume the presence of `item_no` in any response body — its absence from `EquipmentOut` is intentional, not an oversight.

## `GET /equipment` — search/list

Cursor-paginated equipment search.

**Auth:** Any authenticated user.

### Query parameters

| Parameter | Type | Notes |
|---|---|---|
| `q` | string, optional | Free-text search term |
| `status` | `EquipmentStatus`, optional | One of `available_at_pool`, `issued_to_ward`, `unavailable_defective`, `decommissioned` |
| `department_id` | string (UUID), optional | Plain-string query param, validated by `parse_uuid` — malformed value is `400 INVALID_INPUT`, not `422` |
| `category_id` | string (UUID), optional | Same validation as `department_id` |
| `limit` | integer, default `25`, max `200` | |
| `cursor` | string, optional | Opaque pagination cursor from a prior response's `next_cursor` |

### Response — `200 OK` (`Page[EquipmentOut]`)

```json
{
  "items": [ { "...": "EquipmentOut, see below" } ],
  "next_cursor": "opaque-string-or-null",
  "total": 42
}
```

## `POST /equipment/resolve-qr` — resolve a scanned QR code

Resolves a scanned Item-No QR payload to one equipment record. Deliberately a `POST` with a body rather than a `GET` with the raw value in the path/query string, so an arbitrary scanned payload (which may contain URL-unsafe characters, or an unrelated external URL) never lands in an access log line.

**Auth:** Any authenticated user.

### Request body (`QrResolveRequest`)

```json
{ "raw_value": "the raw scanned QR payload" }
```

### Response — `200 OK` (`EquipmentOut`, see below — still excludes `item_no`)

### Errors

| Status | Code | Cause |
|---|---|---|
| `400` | `MALFORMED_QR_CODE` | Payload isn't readable as a valid Item No (empty, too long, URL-shaped, or a retired legacy format) |
| `404` | `EQUIPMENT_NOT_FOUND` | Payload parses to a well-formed Item No, but no equipment matches it |

## `GET /equipment/search/bcm` — BCM Code manual search

Manual-search suggestions for the operator-facing BCM Code identifier.

**Auth:** Any authenticated user.

### Query parameters

| Parameter | Type | Notes |
|---|---|---|
| `q` | string, default `""`, max length 64 | Search term |
| `limit` | integer, default `10`, range 1–20 | |

### Response — `200 OK` (`list[BcmSuggestion]`)

```json
[ { "id": "uuid", "bcm_code": "BCM-1234" } ]
```

Deliberately minimal — never includes `item_no`, device name, brand, model, serial number, or status.

## `GET /equipment/{equipment_id}` — get one

**Auth:** Any authenticated user.

### Response — `200 OK` (`EquipmentOut`) / Errors: `404 EQUIPMENT_NOT_FOUND`

## `GET /equipment/{equipment_id}/history` — status history

**Auth:** Any authenticated user.

### Response — `200 OK` (`list[EquipmentStatusHistoryOut]`)

```json
[
  {
    "id": "uuid",
    "from_status": "available_at_pool",
    "to_status": "issued_to_ward",
    "reason": "Dispatched",
    "changed_at": "2026-07-21T10:00:00Z"
  }
]
```

`from_status` is `null` for the equipment's very first recorded status entry.

## `POST /equipment` — create

**Auth:** Role `administrator` only (Roadmap PR10's confirmed 3-role model — narrowed from the pre-PR10 `admin`/`biomedical_engineer` gate, since `biomedical_engineer` has no confirmed equivalent; `app.api.v1.deps.ADMINISTRATOR_ONLY_ROLES`).

### Request body (`EquipmentCreate`)

```json
{
  "asset_number": "AST-1001",
  "serial_number": null,
  "equipment_name": "Infusion Pump",
  "category_id": null,
  "brand": null,
  "model": null,
  "department_owner_id": null,
  "current_location_id": null,
  "pm_due_date": null,
  "cal_due_date": null,
  "bcm_code": "BCM-1234",
  "item_no": null
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `asset_number` | string, 1–50 chars | Yes | |
| `serial_number` | string, ≤100 chars, or `null` | No | |
| `equipment_name` | string, 1–255 chars | Yes | |
| `category_id`, `department_owner_id`, `current_location_id` | string (UUID) or `null` | No | Validated to reference an existing row (`400 INVALID_INPUT` otherwise) |
| `pm_due_date`, `cal_due_date` | date (`YYYY-MM-DD`) or `null` | No | |
| `bcm_code` | string, ≤64 chars, or `null` | No | Normalized (canonicalized) before storage — see `app.services.identifiers.normalize_bcm_code` |
| `item_no` | string, ≤64 chars, or `null` | No | Write-only; normalized via `normalize_item_no`; never echoed back in the response |

### Response — `201 Created` (`EquipmentOut`)

```json
{
  "id": "uuid",
  "asset_number": "AST-1001",
  "serial_number": null,
  "equipment_name": "Infusion Pump",
  "category_id": null,
  "brand": null,
  "model": null,
  "department_owner_id": null,
  "current_location_id": null,
  "pm_due_date": null,
  "cal_due_date": null,
  "bcm_code": "BCM-1234",
  "status": "available_at_pool",
  "created_at": "2026-07-21T10:00:00Z",
  "updated_at": "2026-07-21T10:00:00Z"
}
```

Note: `id`, `status`, `created_at`, `updated_at` are response-only fields — `item_no` is deliberately absent.

### Errors

| Status | Code | Cause |
|---|---|---|
| `400` | `INVALID_INPUT` | A `*_id` reference field doesn't exist, or an `IntegrityError` was classified as foreign-key/not-null/check |
| `409` | `DUPLICATE` | A unique-constraint violation (e.g. duplicate `bcm_code` or canonical identifier collision) |
| `422` | `VALIDATION_ERROR` | Missing required field, wrong type, or a field exceeds its length bound |
| `403` | `FORBIDDEN` | Caller's role isn't `administrator` |

## `PATCH /equipment/{equipment_id}` — partial update

**Auth:** Role `administrator` only (same rule as create above).

### Request body (`EquipmentUpdate`)

All fields optional; only fields present in the request are applied (`exclude_unset=True` — sending `null` explicitly for a field is different from omitting it). Same fields as `EquipmentCreate` except `asset_number` cannot be changed here (it's absent from `EquipmentUpdate`). `bcm_code`/`item_no` use the identical normalization and length bound as create (PR5-H3R: create and update apply identical validation, not just identical normalization).

### Response — `200 OK` (`EquipmentOut`)

### Errors

Same as `POST /equipment`, plus `404 EQUIPMENT_NOT_FOUND` if `equipment_id` doesn't resolve.

## `POST /equipment/{equipment_id}/status` — manual lifecycle status change

Authorized maintenance-lifecycle transitions only. **This endpoint can never perform a dispatch or receipt transition** — those are exclusively `POST /borrow` and `POST /return/{transaction_id}` (`docs/api/dispatch.md`, `docs/api/receipt.md`), since only those endpoints keep the corresponding `BorrowTransaction` atomically in sync.

**Auth:** Roles `administrator` or `equipment_pool_staff` may call this endpoint at all (`app.api.v1.deps.EQUIPMENT_POOL_OPERATION_ROLES`), but this single endpoint covers three distinct capabilities distinguished by the requested `status` target — Roadmap PR10's confirmed matrix grants marking equipment defective (target `unavailable_defective`) to both roles, but reactivating (target `available_at_pool`) and decommissioning (target `decommissioned`) to `administrator` only. A non-administrator request targeting either administrator-only status is rejected with `403 FORBIDDEN` in the request body, before any database read or side effect (`EQUIPMENT_STATUS_ADMINISTRATOR_ONLY_TARGETS`, `backend/app/api/v1/equipment.py`).

### Request body (`EquipmentStatusChange`)

```json
{ "status": "unavailable_defective", "reason": "Failed inspection" }
```

| Field | Type | Required |
|---|---|---|
| `status` | `EquipmentStatus` | Yes |
| `reason` | string or `null` | No |

### Allowed transitions (`MANUAL_LIFECYCLE_TRANSITIONS`, `backend/app/models/equipment.py`)

| From | Allowed to |
|---|---|
| `available_at_pool` | `unavailable_defective` |
| `unavailable_defective` | `available_at_pool`, `decommissioned` |

`issued_to_ward` is never a valid source or target here — dispatch/receipt own that status exclusively (`DISPATCH_RECEIPT_TRANSITIONS`, used only by `borrow_service`):

| From | Allowed to (dispatch/receipt only) |
|---|---|
| `available_at_pool` | `issued_to_ward` |
| `issued_to_ward` | `available_at_pool`, `unavailable_defective` |

`available_at_pool` has no direct route to `decommissioned` — equipment must first be marked `unavailable_defective`.

### Response — `200 OK` (`EquipmentOut`)

### Errors

| Status | Code | Cause |
|---|---|---|
| `404` | `EQUIPMENT_NOT_FOUND` | `equipment_id` doesn't resolve |
| `409` | `INVALID_STATUS_TRANSITION` | Requested `status` isn't in the current status's allowed-transitions set above |
| `403` | `FORBIDDEN` | Caller's role isn't `administrator`/`equipment_pool_staff`, or the request targets an administrator-only status (`available_at_pool`/`decommissioned`) as a non-administrator |

## `DELETE /equipment/{equipment_id}` — soft delete

**Auth:** Role `administrator` only.

### Response — `204 No Content` (empty body)

### Errors

| Status | Code | Cause |
|---|---|---|
| `404` | `EQUIPMENT_NOT_FOUND` | `equipment_id` doesn't resolve |
| `403` | `FORBIDDEN` | Caller's role isn't `administrator` |

## See also

- `docs/api/dispatch.md`, `docs/api/receipt.md` — the only endpoints allowed to move equipment into/out of `issued_to_ward`
- `docs/api/ERROR_CODES.md` — full status/code reference
