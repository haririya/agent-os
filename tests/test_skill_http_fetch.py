"""http-fetch skill — unit tests for direct HTTP request script."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUNDLED = ROOT / "src" / "agentos" / "skills" / "bundled"
SCRIPTS = BUNDLED / "http-fetch" / "scripts"


def _import_http_fetch():
    sys.path.insert(0, str(SCRIPTS))
    try:
        import http_fetch  # type: ignore[import-not-found]

        return http_fetch
    finally:
        sys.path.pop(0)


def test_http_fetch_truncates_to_exact_max_bytes(capsys: pytest.CaptureFixture[str]) -> None:
    """Truncated raw output must not exceed --max-bytes budget."""
    http_fetch = _import_http_fetch()
    response_body = b"abcdefghijklmnopqrstuvwxyz"  # 26 bytes

    with (
        patch.object(http_fetch, "_fetch", return_value=(200, response_body, "OK")),
        patch("sys.stdin.isatty", return_value=True),
    ):
        code = http_fetch.main(["--url", "https://example.com", "--max-bytes", "10"])
        assert code == 0

    captured = capsys.readouterr()
    encoded = captured.out.encode("utf-8")
    assert len(encoded) == 10
    assert captured.out.endswith("…")
    assert captured.out == "abcdefg…"


def test_http_fetch_small_max_bytes(capsys: pytest.CaptureFixture[str]) -> None:
    """Max bytes smaller than 3-byte marker truncates without negative slicing."""
    http_fetch = _import_http_fetch()
    response_body = b"abcdefghij"

    with (
        patch.object(http_fetch, "_fetch", return_value=(200, response_body, "OK")),
        patch("sys.stdin.isatty", return_value=True),
    ):
        code = http_fetch.main(["--url", "https://example.com", "--max-bytes", "2"])
        assert code == 0

    captured = capsys.readouterr()
    encoded = captured.out.encode("utf-8")
    assert len(encoded) == 2
    assert captured.out == "ab"


def test_http_fetch_untruncated_when_under_budget(capsys: pytest.CaptureFixture[str]) -> None:
    """Response under --max-bytes budget is preserved verbatim."""
    http_fetch = _import_http_fetch()
    response_body = b"hello"

    with (
        patch.object(http_fetch, "_fetch", return_value=(200, response_body, "OK")),
        patch("sys.stdin.isatty", return_value=True),
    ):
        code = http_fetch.main(["--url", "https://example.com", "--max-bytes", "100"])
        assert code == 0

    captured = capsys.readouterr()
    assert captured.out == "hello"


def test_http_fetch_validates_url_and_method(capsys: pytest.CaptureFixture[str]) -> None:
    """Invalid URL schemes or unsupported HTTP methods return exit code 2."""
    http_fetch = _import_http_fetch()

    # Invalid URL
    code_url = http_fetch.main(["--url", "ftp://example.com"])
    assert code_url == 2
    captured_url = capsys.readouterr()
    assert "invalid url" in captured_url.err

    # Invalid Method
    code_method = http_fetch.main(["--url", "https://example.com", "--method", "INVALID"])
    assert code_method == 2
    captured_method = capsys.readouterr()
    assert "unsupported method" in captured_method.err
