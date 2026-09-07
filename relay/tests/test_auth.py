from tests.conftest import TEST_EMAIL, TEST_PASSWORD


async def test_login_succeeds_with_valid_credentials(client):
    response = await client.post(
        "/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["expires_in"] > 0


async def test_login_fails_with_wrong_password(client):
    response = await client.post(
        "/auth/login", json={"email": TEST_EMAIL, "password": "not-the-password"}
    )
    assert response.status_code == 401


async def test_login_fails_for_unknown_operator(client):
    response = await client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
    )
    assert response.status_code == 401


async def test_me_returns_the_authenticated_operator(client, auth_headers):
    response = await client.get("/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == TEST_EMAIL


async def test_protected_routes_reject_anonymous_callers(client):
    for path in ("/auth/me", "/sessions", "/devices", "/audit"):
        assert (await client.get(path)).status_code == 401


async def test_protected_routes_reject_a_forged_token(client):
    headers = {"Authorization": "Bearer not.a.real.token"}
    assert (await client.get("/sessions", headers=headers)).status_code == 401
