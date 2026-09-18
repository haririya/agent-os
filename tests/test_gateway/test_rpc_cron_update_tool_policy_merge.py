"""``cron.update`` merges toolPolicy patches into existing policy (#2806).

When updating a job's toolPolicy (e.g. adding a denial or updating a profile),
unmentioned fields such as profile, allow, alsoAllow, and elevated must be preserved
rather than dropped and resetting to default access.
"""

from __future__ import annotations

from typing import Any

import pytest

from agentos.gateway.rpc import RpcContext
from agentos.gateway.rpc_cron import _handle_cron_update
from agentos.scheduler.payloads import AGENT_TURN_KIND
from agentos.scheduler.types import CronJob, ScheduleKind


class _FakeScheduler:
    def __init__(self, job: CronJob) -> None:
        self.job = job
        self.updated: dict[str, Any] | None = None

    async def update_job(self, job_id: str, **patch: Any) -> CronJob:
        self.updated = patch
        for key, value in patch.items():
            setattr(self.job, key, value)
        return self.job

    async def get_job(self, job_id: str) -> CronJob | None:
        return self.job


def _make_job(tool_policy: dict[str, Any]) -> CronJob:
    return CronJob(
        id="job-drink",
        name="drink",
        cron_expr="0 9 * * *",
        schedule_raw="0 9 * * *",
        schedule_kind=ScheduleKind.CRON,
        handler_key="agent_run",
        payload={"kind": AGENT_TURN_KIND, "task": "drink water", "agent_id": "main"},
        tool_policy=tool_policy,
    )


async def _update(scheduler: _FakeScheduler, params: dict[str, Any]) -> dict[str, Any]:
    return await _handle_cron_update(
        {"id": "job-drink", **params},
        RpcContext(conn_id="test", cron_scheduler=scheduler),
    )


@pytest.mark.asyncio
async def test_update_deny_only_preserves_existing_profile_allow_and_also_allow() -> None:
    job = _make_job(
        {
            "profile": "minimal",
            "allow": ["memory_search"],
            "also_allow": ["web_fetch"],
            "deny": ["exec_command"],
        }
    )
    scheduler = _FakeScheduler(job)

    await _update(scheduler, {"toolPolicy": {"deny": ["exec_command", "write_file"]}})

    assert scheduler.updated is not None
    assert scheduler.updated["tool_policy"] == {
        "profile": "minimal",
        "allow": ["memory_search"],
        "also_allow": ["web_fetch"],
        "deny": ["exec_command", "write_file"],
    }


@pytest.mark.asyncio
async def test_update_profile_only_preserves_existing_deny_and_also_allow() -> None:
    job = _make_job(
        {
            "deny": ["exec_command"],
            "also_allow": ["web_fetch"],
        }
    )
    scheduler = _FakeScheduler(job)

    await _update(scheduler, {"toolPolicy": {"profile": "minimal"}})

    assert scheduler.updated is not None
    assert scheduler.updated["tool_policy"] == {
        "profile": "minimal",
        "deny": ["exec_command"],
        "also_allow": ["web_fetch"],
    }


@pytest.mark.asyncio
async def test_update_tool_policy_snake_case_alias_and_elevated_merge() -> None:
    job = _make_job(
        {
            "profile": "minimal",
            "allow": ["memory_search"],
            "elevated": "bypass",
        }
    )
    scheduler = _FakeScheduler(job)

    await _update(scheduler, {"tool_policy": {"deny": ["exec_command"]}})

    assert scheduler.updated is not None
    assert scheduler.updated["tool_policy"] == {
        "profile": "minimal",
        "allow": ["memory_search"],
        "elevated": "bypass",
        "deny": ["exec_command"],
    }
