import pytest

from tests.conftest import login

pytestmark = pytest.mark.asyncio


async def _auth_headers(client, role="admin"):
    identifier = f"{role.upper()}001"
    token = await login(client, identifier)
    return {"Authorization": f"Bearer {token}"}


def _assert_envelope_shape(body: dict, expected_status: int, *, expects_errors: bool = False):
    required_keys = {"detail", "code", "status", "errors"} if expects_errors else {"detail", "code", "status"}
    assert set(body.keys()) == required_keys
    assert body["status"] == expected_status
    assert isinstance(body["detail"], str)
    assert isinstance(body["code"], str)
    if expects_errors:
        assert isinstance(body["errors"], list)


# ---------------------------------------------------------------------------
# Malformed UUIDs: path, query, and body
# ---------------------------------------------------------------------------


async def test_malformed_uuid_path_parameter_returns_422_validation_error(client, seeded_users):
    headers = await _auth_headers(client, "admin")
    # equipment_id is a typed uuid.UUID path parameter, so FastAPI/Pydantic
    # rejects it before any route code runs -> RequestValidationError.
    resp = await client.get("/api/v1/equipment/not-a-uuid", headers=headers)
    assert resp.status_code == 422
    body = resp.json()
    _assert_envelope_shape(body, 422, expects_errors=True)
    assert body["code"] == "VALIDATION_ERROR"
    assert any("equipment_id" in err["field"] for err in body["errors"])
    # The malformed value itself must not be echoed back.
    assert "not-a-uuid" not in resp.text


async def test_malformed_uuid_query_parameter_returns_400_invalid_input(client, seeded_users):
    headers = await _auth_headers(client, "admin")
    # department_id is a plain-str query param validated by our own
    # parse_uuid(), not a Pydantic-typed one -> domain-layer 400, not 422.
    resp = await client.get("/api/v1/equipment", headers=headers, params={"department_id": "also-not-a-uuid"})
    assert resp.status_code == 400
    body = resp.json()
    _assert_envelope_shape(body, 400)
    assert body["code"] == "INVALID_INPUT"


async def test_malformed_uuid_request_body_field_returns_400_invalid_input(client, seeded_users):
    headers = await _auth_headers(client, "admin")
    # category_id is a plain-str body field validated by our own
    # parse_uuid() (see PR2 known limitations: kept as str, not a Pydantic
    # UUID type, to avoid a schema/contract change) -> 400, not 422.
    resp = await client.post(
        "/api/v1/equipment",
        headers=headers,
        json={"asset_number": "BODY-UUID-0001", "equipment_name": "Pump", "category_id": "still-not-a-uuid"},
    )
    assert resp.status_code == 400
    body = resp.json()
    _assert_envelope_shape(body, 400)
    assert body["code"] == "INVALID_INPUT"


# ---------------------------------------------------------------------------
# Sensitive input must never be reflected in a validation error response
# ---------------------------------------------------------------------------


async def test_password_like_value_is_never_reflected_in_a_422_response(client, seeded_users):
    headers = await _auth_headers(client, "admin")
    secret_marker = "S3cretMarkerThatMustNeverAppear!"
    # employee_code is required and omitted here, so this 422s — the
    # password value in the same payload must never appear in the response,
    # since Pydantic v2's per-error "input" field would otherwise echo it.
    resp = await client.post(
        "/api/v1/users",
        headers=headers,
        json={
            "full_name": "New User",
            "email": "new-user-422@mep-hospital-test.dev",
            "password": secret_marker,
            "role_name": "viewer",
        },
    )
    assert resp.status_code == 422
    body = resp.json()
    _assert_envelope_shape(body, 422, expects_errors=True)
    assert secret_marker not in resp.text


async def test_password_like_value_is_never_reflected_in_a_duplicate_conflict_response(client, seeded_users):
    headers = await _auth_headers(client, "admin")
    secret_marker = "AnotherS3cretMarker!"
    payload = {
        "employee_code": "DUPPW001",
        "full_name": "New User",
        "email": "dup-pw-001@mep-hospital-test.dev",
        "password": secret_marker,
        "role_name": "viewer",
    }
    first = await client.post("/api/v1/users", headers=headers, json=payload)
    assert first.status_code == 201, first.text

    second = await client.post("/api/v1/users", headers=headers, json=payload)
    assert second.status_code == 409
    assert secret_marker not in second.text


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


async def test_missing_credentials_returns_401_with_www_authenticate(client, seeded_users):
    resp = await client.get("/api/v1/equipment")
    assert resp.status_code == 401
    body = resp.json()
    _assert_envelope_shape(body, 401)
    assert body["code"] == "NOT_AUTHENTICATED"
    assert resp.headers.get("www-authenticate") == "Bearer"


async def test_invalid_access_token_returns_401_with_www_authenticate(client, seeded_users):
    resp = await client.get("/api/v1/equipment", headers={"Authorization": "Bearer not-a-real-token"})
    assert resp.status_code == 401
    body = resp.json()
    _assert_envelope_shape(body, 401)
    assert body["code"] == "NOT_AUTHENTICATED"
    assert resp.headers.get("www-authenticate") == "Bearer"


async def test_insufficient_permissions_returns_403_forbidden(client, seeded_users):
    headers = await _auth_headers(client, "viewer")
    resp = await client.post(
        "/api/v1/equipment", headers=headers, json={"asset_number": "FORBID-0001", "equipment_name": "X"}
    )
    assert resp.status_code == 403
    body = resp.json()
    _assert_envelope_shape(body, 403)
    assert body["code"] == "FORBIDDEN"


# ---------------------------------------------------------------------------
# Exact envelope shape across status codes
# ---------------------------------------------------------------------------


async def test_400_envelope_shape(client, seeded_users):
    headers = await _auth_headers(client, "admin")
    resp = await client.get("/api/v1/equipment", headers=headers, params={"department_id": "bad"})
    assert resp.status_code == 400
    _assert_envelope_shape(resp.json(), 400)


async def test_401_envelope_shape(client):
    resp = await client.get("/api/v1/equipment")
    assert resp.status_code == 401
    _assert_envelope_shape(resp.json(), 401)


async def test_404_domain_not_found_envelope_shape(client, seeded_users):
    headers = await _auth_headers(client, "admin")
    resp = await client.get("/api/v1/equipment/00000000-0000-0000-0000-000000000000", headers=headers)
    assert resp.status_code == 404
    body = resp.json()
    _assert_envelope_shape(body, 404)
    assert body["code"] == "EQUIPMENT_NOT_FOUND"


async def test_404_unknown_route_envelope_shape(client, seeded_users):
    headers = await _auth_headers(client, "admin")
    resp = await client.get("/api/v1/this-route-does-not-exist", headers=headers)
    assert resp.status_code == 404
    body = resp.json()
    _assert_envelope_shape(body, 404)
    assert body["code"] == "NOT_FOUND"


async def test_405_method_not_allowed_envelope_shape(client, seeded_users):
    headers = await _auth_headers(client, "admin")
    # /api/v1/equipment supports GET/POST, not DELETE.
    resp = await client.delete("/api/v1/equipment", headers=headers)
    assert resp.status_code == 405
    body = resp.json()
    _assert_envelope_shape(body, 405)
    assert body["code"] == "METHOD_NOT_ALLOWED"


async def test_409_envelope_shape(client, seeded_users):
    headers = await _auth_headers(client, "admin")
    payload = {"code": "ENV409", "name": "Dept"}
    first = await client.post("/api/v1/departments", headers=headers, json=payload)
    assert first.status_code == 201
    second = await client.post("/api/v1/departments", headers=headers, json=payload)
    assert second.status_code == 409
    _assert_envelope_shape(second.json(), 409)


async def test_422_envelope_shape(client, seeded_users):
    headers = await _auth_headers(client, "admin")
    resp = await client.get("/api/v1/equipment/not-a-uuid", headers=headers)
    assert resp.status_code == 422
    _assert_envelope_shape(resp.json(), 422, expects_errors=True)


async def test_500_envelope_shape(client, seeded_users, monkeypatch):
    from httpx import ASGITransport, AsyncClient

    from app.api.v1 import equipment as equipment_module
    from app.main import app as fastapi_app

    async def boom(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(equipment_module.equipment_crud, "search", boom)
    headers = await _auth_headers(client, "admin")

    transport = ASGITransport(app=fastapi_app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as raw_client:
        resp = await raw_client.get("/api/v1/equipment", headers=headers)

    assert resp.status_code == 500
    _assert_envelope_shape(resp.json(), 500)
    assert resp.json()["code"] == "INTERNAL_ERROR"
