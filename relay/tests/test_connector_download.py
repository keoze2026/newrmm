"""The Windows installer is downloaded with the session code in its name, so a
person downloads, installs and is connected with nothing to type."""
import pytest

from app.api import connector


@pytest.fixture
def builds(tmp_path, monkeypatch):
    (tmp_path / "rmm-agent-setup.exe").write_bytes(b"MZ installer bytes")
    (tmp_path / "rmm-agent-windows.exe").write_bytes(b"MZ bare agent")
    monkeypatch.setattr(connector, "BUILD_DIR", tmp_path)
    return tmp_path


def _filename(response) -> str:
    disposition = response.headers["content-disposition"]
    return disposition.split("filename=", 1)[1].strip('"')


async def test_the_installer_carries_a_valid_code_in_its_name(client, auth_headers, builds):
    created = (await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)).json()
    response = await client.get(f"/connector/windows?code={created['code']}")
    assert response.status_code == 200
    assert _filename(response) == f"rmm-agent-setup-{created['code']}.exe"


async def test_the_bytes_are_untouched_so_a_signature_stays_valid(client, auth_headers, builds):
    created = (await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)).json()
    response = await client.get(f"/connector/windows?code={created['code']}")
    assert response.content == b"MZ installer bytes"


async def test_an_unknown_code_never_becomes_a_file_name(client, builds):
    """Only a code the server just confirmed may appear in a name."""
    response = await client.get("/connector/windows?code=../../etc/passwd")
    assert response.status_code == 200
    assert _filename(response) == "rmm-agent-setup.exe"


async def test_an_expired_code_gets_the_plain_installer(client, auth_headers, builds):
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models import Session as SessionRow

    created = (await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)).json()
    async with SessionLocal() as db:
        row = await db.scalar(select(SessionRow).where(SessionRow.id == created["id"]))
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()

    response = await client.get(f"/connector/windows?code={created['code']}")
    assert _filename(response) == "rmm-agent-setup.exe"


async def test_other_platforms_keep_their_plain_names(client, auth_headers, tmp_path, monkeypatch):
    (tmp_path / "rmm-agent-linux").write_bytes(b"ELF")
    monkeypatch.setattr(connector, "BUILD_DIR", tmp_path)
    created = (await client.post("/sessions", json={"mode": "attended"}, headers=auth_headers)).json()
    response = await client.get(f"/connector/linux?code={created['code']}")
    assert _filename(response) == "rmm-agent-linux"
