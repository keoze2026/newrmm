async def test_health_reports_database_and_redis(client):
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok", body
    assert body["checks"]["database"] == "ok"
    assert body["checks"]["redis"] == "ok"
