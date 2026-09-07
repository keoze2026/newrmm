async def test_create_attended_session(client, auth_headers):
    response = await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)
    assert response.status_code == 201
    body = response.json()
    assert body["mode"] == "attended"
    assert body["state"] == "pending"
    assert len(body["code"]) == 8
    assert body["device_id"] is None


async def test_created_session_appears_in_the_list(client, auth_headers):
    created = (
        await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)
    ).json()

    listed = await client.get("/sessions", headers=auth_headers)
    assert listed.status_code == 200
    assert created["id"] in [s["id"] for s in listed.json()]


async def test_session_codes_are_unique(client, auth_headers):
    codes = set()
    for _ in range(10):
        body = (
            await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)
        ).json()
        codes.add(body["code"])
    assert len(codes) == 10


async def test_unattended_session_requires_a_device(client, auth_headers):
    response = await client.post("/sessions", json={"mode": "unattended"}, headers=auth_headers)
    assert response.status_code == 400


async def test_unattended_session_with_an_enrolled_device(client, auth_headers):
    device = (
        await client.post(
            "/devices", json={"name": "Reception PC", "os": "windows"}, headers=auth_headers
        )
    ).json()

    response = await client.post(
        "/sessions",
        json={"mode": "unattended", "device_id": device["id"]},
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert response.json()["device_id"] == device["id"]


async def test_session_state_transitions_and_timestamps(client, auth_headers):
    session = (
        await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)
    ).json()

    activated = await client.patch(
        f"/sessions/{session['id']}", json={"state": "active"}, headers=auth_headers
    )
    assert activated.status_code == 200
    assert activated.json()["state"] == "active"
    assert activated.json()["started_at"] is not None

    ended = await client.patch(
        f"/sessions/{session['id']}", json={"state": "ended"}, headers=auth_headers
    )
    assert ended.json()["state"] == "ended"
    assert ended.json()["ended_at"] is not None

    # An ended session cannot be reopened.
    again = await client.patch(
        f"/sessions/{session['id']}", json={"state": "active"}, headers=auth_headers
    )
    assert again.status_code == 409


async def test_missing_session_returns_404(client, auth_headers):
    response = await client.get(
        "/sessions/00000000-0000-0000-0000-000000000000", headers=auth_headers
    )
    assert response.status_code == 404
