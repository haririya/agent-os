"""The ephemeral ``agentos_exec_*`` workdir must not survive an early return.

``execute_code`` makes a temporary workdir whenever no workspace is configured,
but the cleanup used to hang off the ``finally`` of the *non-sandbox* branch
only. Every early return inside the sandbox branch — denial, backend failure,
escalation denial, timeout, error — skipped it and left one directory behind per
call.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agentos.sandbox.types import (
    DenialReason,
    DenialResult,
    SandboxResult,
    SecurityLevel,
    SuggestedNextStep,
)
from agentos.tools.builtin import code_exec
from agentos.tools.types import ToolContext, current_tool_context


def _denial() -> DenialResult:
    return DenialResult(
        reason=DenialReason.POLICY_DENIED,
        suggested_next_step=SuggestedNextStep.REPLAN,
        level=SecurityLevel.STANDARD,
        action_fingerprint="fp",
        message="denied",
    )


def _sandbox_result(*, notes: tuple[str, ...] = ()) -> SandboxResult:
    return SandboxResult(
        returncode=0,
        stdout="ok",
        stderr="",
        wall_time_s=0.0,
        backend_used="none",
        backend_notes=notes,
    )


@pytest.fixture
def temp_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``tempfile.mkdtemp`` at an empty directory we can count."""
    root = tmp_path / "tmp"
    root.mkdir()
    monkeypatch.setattr(code_exec.tempfile, "tempdir", str(root))
    monkeypatch.setattr(code_exec, "get_runtime", lambda: None)
    token = current_tool_context.set(None)
    try:
        yield root
    finally:
        current_tool_context.reset(token)


def _leaked(root: Path) -> list[Path]:
    return sorted(root.glob("agentos_exec_*"))


def _gate(monkeypatch: pytest.MonkeyPatch, result: object) -> None:
    async def _fake_gate(**_kwargs: object) -> tuple[object, object, object]:
        request = code_exec.SandboxRequest(
            argv=("python", "-c", "pass"),
            cwd=Path("."),
            action_kind="code.exec",
            policy=None,
        )
        return result, None, request

    monkeypatch.setattr(code_exec, "gate_action", _fake_gate)


def test_denied_calls_leave_no_tempdir(temp_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _gate(monkeypatch, _denial())

    for index in range(5):
        out = asyncio.run(code_exec.execute_code(f"print({index})"))
        assert '"status": "denied"' in out

    assert _leaked(temp_root) == []


def test_backend_failure_leaves_no_tempdir(
    temp_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _gate(monkeypatch, code_exec.SandboxRequest)  # any non-DenialResult

    async def _boom(*_args: object, **_kwargs: object) -> SandboxResult:
        raise RuntimeError("backend exploded")

    monkeypatch.setattr(code_exec, "run_under_backend", _boom)

    out = asyncio.run(code_exec.execute_code("print(1)"))
    assert "backend exploded" in out
    assert _leaked(temp_root) == []


def test_escalation_denial_leaves_no_tempdir(
    temp_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _gate(monkeypatch, code_exec.SandboxRequest)

    async def _noted(*_args: object, **_kwargs: object) -> SandboxResult:
        return _sandbox_result(notes=("backend denied",))

    async def _escalate(*_args: object, **_kwargs: object) -> DenialResult:
        return _denial()

    monkeypatch.setattr(code_exec, "run_under_backend", _noted)
    monkeypatch.setattr(code_exec, "escalate_backend_denial", _escalate)

    out = asyncio.run(code_exec.execute_code("print(1)"))
    assert '"status": "denied"' in out
    assert _leaked(temp_root) == []


def test_sandbox_success_leaves_no_tempdir(
    temp_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _gate(monkeypatch, code_exec.SandboxRequest)

    async def _ok(*_args: object, **_kwargs: object) -> SandboxResult:
        return _sandbox_result()

    monkeypatch.setattr(code_exec, "run_under_backend", _ok)

    out = asyncio.run(code_exec.execute_code("print(1)"))
    assert '"exit_code": 0' in out
    assert _leaked(temp_root) == []


def test_escalated_subprocess_timeout_leaves_no_tempdir(
    temp_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _gate(monkeypatch, code_exec.SandboxRequest)

    async def _noted(*_args: object, **_kwargs: object) -> SandboxResult:
        return _sandbox_result(notes=("backend denied",))

    async def _escalate(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(code_exec, "run_under_backend", _noted)
    monkeypatch.setattr(code_exec, "escalate_backend_denial", _escalate)

    out = asyncio.run(code_exec.execute_code("import time\ntime.sleep(30)", timeout=1))
    assert '"timed_out": true' in out
    assert _leaked(temp_root) == []


def test_escalated_subprocess_error_leaves_no_tempdir(
    temp_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _gate(monkeypatch, code_exec.SandboxRequest)

    async def _noted(*_args: object, **_kwargs: object) -> SandboxResult:
        return _sandbox_result(notes=("backend denied",))

    async def _escalate(*_args: object, **_kwargs: object) -> None:
        return None

    async def _spawn_fails(*_args: object, **_kwargs: object) -> object:
        raise OSError("no fork for you")

    monkeypatch.setattr(code_exec, "run_under_backend", _noted)
    monkeypatch.setattr(code_exec, "escalate_backend_denial", _escalate)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", _spawn_fails)

    out = asyncio.run(code_exec.execute_code("print(1)"))
    assert "no fork for you" in out
    assert _leaked(temp_root) == []


def test_configured_workspace_is_never_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    keeper = workspace / "keep.txt"
    keeper.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(code_exec, "get_runtime", lambda: None)
    _gate(monkeypatch, _denial())

    token = current_tool_context.set(ToolContext(workspace_dir=str(workspace)))
    try:
        asyncio.run(code_exec.execute_code("print(1)"))
    finally:
        current_tool_context.reset(token)

    assert keeper.read_text(encoding="utf-8") == "keep"


def test_tempdir_cleanup_on_setup_exception(
    temp_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ephemeral workdir must be cleaned up even if an exception occurs during setup."""

    def _boom_env() -> dict[str, str]:
        raise RuntimeError("setup env failure")

    monkeypatch.setattr(code_exec, "_build_safe_env", _boom_env)

    with pytest.raises(RuntimeError, match="setup env failure"):
        asyncio.run(code_exec.execute_code("print(1)"))

    assert _leaked(temp_root) == []
