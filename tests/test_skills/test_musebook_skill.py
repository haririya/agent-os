"""Tests for the bundled musebook skill script (muse.py).

Verifies that JSON output survives non-UTF-8 console code pages (Windows cp437 /
cp1252), API paths normalize correctly without duplicate /api/ prefixes, and
canonical message generation adheres to the musebook-v1 protocol.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "src" / "agentos" / "skills" / "bundled" / "musebook" / "scripts" / "muse.py"


def _run_muse(*args: str, **env_overrides: str) -> subprocess.CompletedProcess[bytes]:
    env = {**os.environ, **env_overrides}
    env.pop("PYTHONIOENCODING", None)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        env=env,
    )


def test_keygen_survives_cp437_stdout_encoding() -> None:
    """muse.py keygen output contains em-dash in 'note' which raises UnicodeEncodeError on cp437."""
    proc = _run_muse("keygen", PYTHONIOENCODING="cp437")
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    data = json.loads(proc.stdout.decode("utf-8"))
    assert data["ok"] is True
    assert "public_key" in data
    assert "secret" in data
    assert "\u2014" in data["note"]


def test_sign_emoji_survives_cp1252_stdout_encoding() -> None:
    """muse.py sign output with emoji reactions raises UnicodeEncodeError on cp1252."""
    proc = _run_muse(
        "sign",
        "--endpoint",
        "react",
        "--muse-id",
        "muse_test",
        "--secret",
        "wVE5adj76q7PAM7kNB2NsFmK2QWSkssfU6m1_r2vJfM",
        "--field",
        "emoji=💛",
        PYTHONIOENCODING="cp1252",
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    data = json.loads(proc.stdout.decode("utf-8"))
    assert data["ok"] is True
    assert data["body"]["emoji"] == "💛"


def test_api_path_normalization() -> None:
    """Path resolution normalizes leading slashes and redundant 'api/' prefixes."""
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import muse
    finally:
        sys.path.pop(0)

    assert muse.normalize_api_path("latest.json") == "latest.json"
    assert muse.normalize_api_path("/latest.json") == "latest.json"
    assert muse.normalize_api_path("api/latest.json") == "latest.json"
    assert muse.normalize_api_path("/api/latest.json") == "latest.json"
    assert muse.normalize_api_path("api/thread.json") == "thread.json"


def test_canonical_message_spec_agreement() -> None:
    """Canonical message format matches the spec: protocol, endpoint, timestamp, nonce, muse_id."""
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import muse
    finally:
        sys.path.pop(0)

    msg = muse.canonical_message(
        endpoint="post",
        timestamp="1700000000000",
        nonce="testnonce1234567890",
        muse_id="muse_sample",
        fields={"channel": "lobby", "text": "hello 🪶"},
    )
    expected = (
        "musebook-v1\n"
        "post\n"
        "1700000000000\n"
        "testnonce1234567890\n"
        "muse_sample\n"
        "channel:5:lobby\n"
        "text:10:hello 🪶"
    )
    assert msg == expected
