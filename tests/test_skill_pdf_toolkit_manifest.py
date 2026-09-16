"""pdf-toolkit ``merge.py`` — an unusable manifest is an error, not a traceback.

``main`` read the manifest with a bare ``json.loads`` and handed the result
straight to ``merge``, which indexes ``item["file"]``. Every malformed shape
therefore surfaced as a Python traceback with a non-zero exit but no usable
message:

* ``not json`` — ``json.JSONDecodeError``
* ``["a.pdf", "b.pdf"]``, a bare list of paths and the obvious thing to try —
  ``TypeError: string indices must be integers``
* ``[{"pages": "1-2"}]`` — ``KeyError: 'file'``
* ``[{"file": "a.pdf", "pages": 3}]`` — reaches ``spec.split(",")`` on an int

``load_manifest`` validates the shape up front and reports ``error: ...`` with
exit 2, the convention ``split.py`` and ``form_fill.py`` already follow. The
guard inside ``merge`` covers the other entry point: ``merge`` is public and a
caller that builds items itself should see an unusable entry skipped like a
missing file, not an exception from inside the loop.

The zero-page behaviour these tests sit next to — no file written, exit 2 —
landed separately in #2380 and is covered in
``tests/test_skill_pdf_toolkit_merge.py``; only the destructive consequence is
re-asserted here, because it is the reason the bug was worth fixing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "agentos" / "skills" / "bundled" / "pdf-toolkit" / "scripts"


def _merge_module():
    sys.path.insert(0, str(SCRIPTS))
    try:
        import merge  # type: ignore[import-not-found]
    finally:
        sys.path.pop(0)
    return merge


def _make_pdf(path: Path, pages: int, tag: str) -> None:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=LETTER)
    for number in range(1, pages + 1):
        c.setFont("Helvetica", 14)
        c.drawString(72, 720, f"{tag} PAGE {number}")
        c.showPage()
    c.save()


def _run(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    merge = _merge_module()
    monkeypatch.setattr(sys, "argv", ["merge.py", *argv])
    return int(merge.main())


# ── the manifest shapes that used to be tracebacks ──────────────────────────


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        ("not json", "is not valid JSON"),
        ('{"file": "a.pdf"}', "must be a JSON array"),
        ('["a.pdf", "b.pdf"]', 'entry 0 must be an object with a "file" key, got str'),
        ("[123]", 'entry 0 must be an object with a "file" key, got int'),
        ("[null]", 'entry 0 must be an object with a "file" key, got NoneType'),
        ('[{"pages": "1-2"}]', 'entry 0 is missing the "file" key'),
        ('[{"file": 7}]', 'entry 0 has a non-string "file": 7'),
        ('[{"file": "a.pdf", "pages": 3}]', 'entry 0 has a non-string "pages": 3'),
        ('[{"file": "a.pdf"}, {"file": null}]', 'entry 1 has a non-string "file": None'),
    ],
    ids=[
        "invalid-json",
        "object-not-array",
        "bare-path-list",
        "int-entry",
        "null-entry",
        "missing-file-key",
        "non-string-file",
        "non-string-pages",
        "second-entry-reported-by-index",
    ],
)
def test_an_unusable_manifest_exits_2_with_a_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, payload: str, expected: str
) -> None:
    """Each of these escaped as a traceback before.

    ``[{"file": "a.pdf", "pages": 3}]`` is the one a ``file``-only check still
    misses: nothing rejects it, and ``parse_ranges`` then calls ``.split(",")``
    on an int.
    """
    manifest = tmp_path / "m.json"
    manifest.write_text(payload, encoding="utf-8")
    out = tmp_path / "o.pdf"

    code = _run([str(manifest), "--out", str(out)], monkeypatch)

    assert code == 2
    captured = capsys.readouterr()
    assert captured.err.startswith("error: ")
    assert expected in captured.err
    assert "Traceback" not in captured.err
    assert not out.exists()


def test_the_offending_entry_is_named_by_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """A twenty-entry manifest is unfixable if the message does not say which
    entry is wrong."""
    entries = [{"file": f"f{i}.pdf"} for i in range(5)]
    entries[3] = {"file": "f3.pdf", "pages": 12}  # type: ignore[dict-item]
    manifest = tmp_path / "m.json"
    manifest.write_text(json.dumps(entries), encoding="utf-8")

    code = _run([str(manifest), "--out", str(tmp_path / "o.pdf")], monkeypatch)

    assert code == 2
    assert "entry 3" in capsys.readouterr().err


def test_a_valid_manifest_still_merges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Validation must not reject the shapes the schema documents — ``pages``
    present, and ``pages`` omitted to mean the whole file."""
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    _make_pdf(a, 3, "ALPHA")
    _make_pdf(b, 2, "BRAVO")
    manifest = tmp_path / "m.json"
    manifest.write_text(
        json.dumps([{"file": str(a), "pages": "1-2"}, {"file": str(b)}]), encoding="utf-8"
    )
    out = tmp_path / "o.pdf"

    code = _run([str(manifest), "--out", str(out)], monkeypatch)

    assert code == 0
    assert json.loads(capsys.readouterr().out)["pages_written"] == 4
    assert out.is_file()


def test_a_missing_manifest_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    manifest = tmp_path / "nope.json"

    code = _run([str(manifest), "--out", str(tmp_path / "o.pdf")], monkeypatch)

    assert code == 2
    assert "not found" in capsys.readouterr().err


def test_an_empty_manifest_array_is_accepted_and_merges_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """``[]`` is a well-formed manifest, so it is not a validation error — it
    falls through to the ordinary "nothing was merged" path."""
    manifest = tmp_path / "m.json"
    manifest.write_text("[]", encoding="utf-8")
    out = tmp_path / "o.pdf"

    code = _run([str(manifest), "--out", str(out)], monkeypatch)

    assert code == 2
    assert "no requested page exists" in capsys.readouterr().err
    assert not out.exists()


# ── merge() is public: an unusable entry skips, it does not raise ───────────


def test_merge_called_directly_skips_an_unusable_entry(tmp_path: Path) -> None:
    """``merge`` is reachable without going through ``load_manifest``.

    A caller that builds items itself should get the missing-file treatment for
    a bad entry, not a ``TypeError`` from ``item["file"]`` part way through a
    half-built document.
    """
    merge = _merge_module()
    good = tmp_path / "good.pdf"
    _make_pdf(good, 2, "GOOD")
    out = tmp_path / "o.pdf"

    result = merge.merge(["not-a-dict", {"file": 7}, {"file": str(good)}], out)

    assert result.pages_written == 2
    assert out.is_file()


def test_merge_called_directly_with_only_unusable_entries_writes_nothing(
    tmp_path: Path,
) -> None:
    merge = _merge_module()
    out = tmp_path / "o.pdf"

    result = merge.merge(["not-a-dict", {"no_file": 1}], out)

    assert result.pages_written == 0
    assert not out.exists()


def test_an_unusable_entry_is_named_on_stderr(tmp_path: Path, capsys) -> None:
    """Skipping silently would turn a typo into a quietly short merge."""
    merge = _merge_module()

    merge.merge([{"file": 7}], tmp_path / "o.pdf")

    assert "unusable manifest entry" in capsys.readouterr().err


# ── the destructive consequence, re-asserted ────────────────────────────────


def test_a_failed_merge_does_not_touch_an_existing_output(tmp_path: Path) -> None:
    """The reason this was worth fixing rather than a cosmetic exit code.

    ``--out`` pointing at a real PDF used to have it replaced by a valid 0-page
    file, so a merge that matched nothing destroyed real content and reported
    success. #2380 made ``merge`` skip the write; this pins the consequence
    byte for byte.
    """
    merge = _merge_module()
    out = tmp_path / "existing.pdf"
    _make_pdf(out, 4, "PRECIOUS")
    before = out.read_bytes()

    result = merge.merge([{"file": str(tmp_path / "absent.pdf")}], out)

    assert result.pages_written == 0
    assert out.read_bytes() == before


def test_a_failed_merge_does_not_create_the_output_directory(tmp_path: Path) -> None:
    """Nothing is left behind — not even an empty directory."""
    merge = _merge_module()
    out = tmp_path / "fresh" / "nested" / "o.pdf"

    result = merge.merge([{"file": str(tmp_path / "absent.pdf")}], out)

    assert result.pages_written == 0
    assert not out.parent.exists()


# ── relative paths in manifest resolved against manifest directory ─────────


def test_manifest_relative_paths_resolve_against_manifest_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Relative paths in manifest.json must resolve against the manifest file's
    parent directory, not the current working directory."""
    doc_dir = tmp_path / "documents"
    doc_dir.mkdir()
    a = doc_dir / "a.pdf"
    b = doc_dir / "b.pdf"
    _make_pdf(a, 2, "ALPHA")
    _make_pdf(b, 3, "BRAVO")

    manifest = doc_dir / "manifest.json"
    manifest.write_text(
        json.dumps([{"file": "a.pdf", "pages": "1"}, {"file": "b.pdf", "pages": "2-3"}]),
        encoding="utf-8",
    )

    work_dir = tmp_path / "other_work_dir"
    work_dir.mkdir()
    monkeypatch.chdir(work_dir)

    out = tmp_path / "out.pdf"
    code = _run([str(manifest), "--out", str(out)], monkeypatch)

    assert code == 0
    captured = capsys.readouterr()
    summary = json.loads(captured.out)
    assert summary["pages_written"] == 3
    assert summary["missing_files"] == []
    assert out.is_file()
