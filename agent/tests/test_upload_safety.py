"""An interrupted upload must never destroy the file it was replacing.

Scan finding: Upload opened the target with "wb" (emptying it on the first
chunk) and abort() deleted it, so a failed re-upload lost the original.
"""
import base64

from rmm_agent import files


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def test_an_interrupted_reupload_leaves_the_original_intact(tmp_path):
    target = tmp_path / "report.docx"
    target.write_bytes(b"the original")
    upload = files.Upload(str(target))
    upload.write(_b64(b"half of the new"))
    assert target.read_bytes() == b"the original"
    upload.abort()
    assert target.read_bytes() == b"the original"
    assert list(tmp_path.iterdir()) == [target]


def test_a_finished_upload_replaces_the_file(tmp_path):
    target = tmp_path / "report.docx"
    target.write_bytes(b"old")
    target.chmod(0o640)
    upload = files.Upload(str(target))
    upload.write(_b64(b"new "))
    upload.write(_b64(b"contents"))
    assert upload.finish() == {"path": str(target), "size": 12}
    assert target.read_bytes() == b"new contents"
    assert (target.stat().st_mode & 0o777) == 0o640
    assert list(tmp_path.iterdir()) == [target]


def test_a_new_file_gets_normal_permissions_not_owner_only(tmp_path):
    target = tmp_path / "sub" / "new.txt"
    upload = files.Upload(str(target))
    upload.write(_b64(b"x"))
    upload.finish()
    assert (target.stat().st_mode & 0o777) == (0o666 & ~files._UMASK)
