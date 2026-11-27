import pytest

from app.models.user import ROLE_EQUIPMENT_POOL_STAFF, ROLE_READ_ONLY
from tests.conftest import auth_headers

URL = "/api/v1/me/preferences"
GOOD = {"mode": "custom", "bg": "#F5EFE0", "surface": "#FBF7EE", "text": "#2B2B2B", "accent": "#1d4ed8",
        "font_size": 18, "font_family": "serif"}
EMPTY = {k: None for k in GOOD}


async def test_requires_auth(client, seeded_users):
    assert (await client.get(URL)).status_code == 401
    assert (await client.put(URL, json=GOOD)).status_code == 401


async def test_default_empty_then_round_trip_and_reset(client, seeded_users):
    h = await auth_headers(client, ROLE_READ_ONLY)
    assert (await client.get(URL, headers=h)).json() == EMPTY
    r = await client.put(URL, headers=h, json=GOOD)
    assert r.status_code == 200, r.text
    assert (await client.get(URL, headers=h)).json() == GOOD
    assert (await client.put(URL, headers=h, json={})).status_code == 200
    assert (await client.get(URL, headers=h)).json() == EMPTY


async def test_preferences_are_per_user(client, seeded_users):
    a = await auth_headers(client, ROLE_READ_ONLY)
    b = await auth_headers(client, ROLE_EQUIPMENT_POOL_STAFF)
    await client.put(URL, headers=a, json={"mode": "dark"})
    assert (await client.get(URL, headers=b)).json()["mode"] is None
    assert (await client.get(URL, headers=a)).json()["mode"] == "dark"


@pytest.mark.parametrize(
    "bad",
    [
        {"mode": "neon"},
        {"bg": "red"},
        {"bg": "#12345"},
        {"text": "#GGGGGG"},
        {"accent": "#1234567"},
        {"font_size": 13},
        {"font_size": 23},
        {"font_family": "comic"},
        {"unknown": "x"},
    ],
)
async def test_invalid_payloads_rejected(client, seeded_users, bad):
    h = await auth_headers(client, ROLE_READ_ONLY)
    assert (await client.put(URL, headers=h, json=bad)).status_code == 422
