from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Device


async def test_enrollment_returns_the_secret_once_and_stores_only_a_hash(client, auth_headers):
    response = await client.post(
        "/devices", json={"name": "Workshop Mac", "os": "macos"}, headers=auth_headers
    )
    assert response.status_code == 201
    body = response.json()
    secret = body["enrollment_secret"]
    assert secret

    async with SessionLocal() as db:
        device = await db.scalar(select(Device).where(Device.id == body["id"]))
        assert device is not None
        assert device.secret_hash != secret
        assert device.secret_hash.startswith("$argon2")

    listed = await client.get("/devices", headers=auth_headers)
    assert body["id"] in [d["id"] for d in listed.json()]
    assert all("enrollment_secret" not in d for d in listed.json())


async def test_rejects_an_unsupported_operating_system(client, auth_headers):
    response = await client.post(
        "/devices", json={"name": "Toaster", "os": "freebsd"}, headers=auth_headers
    )
    assert response.status_code == 422
