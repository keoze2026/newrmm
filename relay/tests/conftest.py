import os

# The test suite runs against a dedicated database, set before app.core.config
# reads its settings.
# Respect a DATABASE_URL the environment already provides - CI supplies its own
# Postgres - and fall back to the local development container otherwise. Setting
# it unconditionally made the suite ignore whichever database it was given.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://rdp:rdp_dev_pass@127.0.0.1:55433/rdp_test"
)

import subprocess  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.core.security import hash_secret  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Operator  # noqa: E402

RELAY_ROOT = Path(__file__).resolve().parent.parent
TEST_EMAIL = "tester@example.com"
TEST_PASSWORD = "TestPassw0rd!"


@pytest.fixture(scope="session", autouse=True)
async def migrated_database():
    """Rebuild the test schema by running the real migrations, then seed an operator."""
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await engine.dispose()

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=RELAY_ROOT,
        env=os.environ.copy(),
        check=True,
        capture_output=True,
    )

    async with SessionLocal() as db:
        db.add(
            Operator(
                email=TEST_EMAIL,
                full_name="Test Operator",
                password_hash=hash_secret(TEST_PASSWORD),
                role="admin",
            )
        )
        await db.commit()

    yield
    await engine.dispose()


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def auth_headers(client):
    response = await client.post(
        "/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}
