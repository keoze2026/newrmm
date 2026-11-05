"""Every operator can see and join any session - deliberate, for team
coverage. Only the session's own operator, or an admin, may end it.
"""
from app.core.security import hash_secret
from app.db.session import SessionLocal
from app.models import Operator

OTHER_EMAIL = "colleague@example.com"
OTHER_PASSWORD = "AlsoAPassw0rd!"


async def other_operator_headers(client, role: str = "operator") -> dict:
    """A second operator, distinct from the one `auth_headers` logs in as -
    needed to test that one operator cannot act on another's session."""
    async with SessionLocal() as db:
        db.add(
            Operator(
                email=OTHER_EMAIL,
                full_name="Colleague",
                password_hash=hash_secret(OTHER_PASSWORD),
                role=role,
            )
        )
        await db.commit()
    response = await client.post(
        "/auth/login", json={"email": OTHER_EMAIL, "password": OTHER_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_any_operator_can_see_a_session_they_did_not_create(client, auth_headers):
    """Visibility is deliberately shared - this is not what is being
    restricted, and must keep working."""
    created = (
        await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)
    ).json()
    colleague = await other_operator_headers(client)

    listed = await client.get("/sessions", headers=colleague)
    assert created["id"] in [s["id"] for s in listed.json()]
    assert (await client.get(f"/sessions/{created['id']}", headers=colleague)).status_code == 200


async def test_a_non_owner_non_admin_cannot_end_another_operators_session_with_patch(
    client, auth_headers
):
    created = (
        await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)
    ).json()
    colleague = await other_operator_headers(client)

    response = await client.patch(
        f"/sessions/{created['id']}", json={"state": "ended"}, headers=colleague
    )
    assert response.status_code == 403

    still_open = await client.get(f"/sessions/{created['id']}", headers=auth_headers)
    assert still_open.json()["state"] != "ended"


async def test_a_non_owner_non_admin_cannot_delete_another_operators_session(
    client, auth_headers
):
    created = (
        await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)
    ).json()
    colleague = await other_operator_headers(client)

    response = await client.delete(f"/sessions/{created['id']}", headers=colleague)
    assert response.status_code == 403

    still_open = await client.get(f"/sessions/{created['id']}", headers=auth_headers)
    assert still_open.json()["state"] != "ended"


async def test_the_sessions_own_operator_can_still_end_it(client, auth_headers):
    created = (
        await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)
    ).json()
    response = await client.patch(
        f"/sessions/{created['id']}", json={"state": "ended"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["state"] == "ended"


async def test_an_admin_can_end_someone_elses_session(client, auth_headers):
    """The seeded `auth_headers` operator is role=admin (conftest.py) - a
    colleague creates the session, the admin ends it."""
    colleague = await other_operator_headers(client)
    created = (
        await client.post("/sessions", json={"mode": "attended"}, headers=colleague)
    ).json()

    response = await client.patch(
        f"/sessions/{created['id']}", json={"state": "ended"}, headers=auth_headers
    )
    assert response.status_code == 200
    assert response.json()["state"] == "ended"
