from __future__ import annotations

import pytest

from agentos.gateway import rpc_skills
from agentos.skills.hub.router import SourceRouter
from agentos.skills.hub.source import SkillMeta, SkillSource


class _StubRouter:
    def __init__(self, results: list[SkillMeta] | None = None) -> None:
        self._results = results or []
        self.calls: list[dict] = []

    async def search(self, query: str, limit: int = 20, source_id: str | None = None):
        self.calls.append({"query": query, "limit": limit, "source_id": source_id})
        return self._results[:limit]


class _Ctx:
    def __init__(self, router: _StubRouter) -> None:
        self._skill_router = router


class _StubSource(SkillSource):
    def __init__(self, source_id: str, results: list[SkillMeta]) -> None:
        self._source_id = source_id
        self._results = results
        self.calls: list[dict] = []

    @property
    def source_id(self) -> str:
        return self._source_id

    @property
    def trust_level(self) -> str:
        return "community"

    async def search(self, query: str, limit: int = 20) -> list[SkillMeta]:
        self.calls.append({"query": query, "limit": limit})
        return self._results[:limit]

    async def fetch(self, identifier: str):
        return None

    async def inspect(self, identifier: str):
        return None


def _no_lockfile(monkeypatch) -> None:
    monkeypatch.setattr(rpc_skills, "_installed_names", lambda: set())
    monkeypatch.setattr(rpc_skills, "installed_skill_identifiers", lambda: set())
    monkeypatch.setattr(rpc_skills, "_installed_lock_entries", dict)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_limit", [-5, -1, 0])
async def test_skills_search_clamps_non_positive_limit_to_one(monkeypatch, bad_limit: int) -> None:
    _no_lockfile(monkeypatch)
    router = _StubRouter()
    await rpc_skills._handle_skills_search({"query": "test", "limit": bad_limit}, _Ctx(router))

    assert len(router.calls) == 1
    assert router.calls[0]["limit"] == 1


@pytest.mark.asyncio
async def test_skills_search_clamps_oversized_limit_to_five_hundred(monkeypatch) -> None:
    _no_lockfile(monkeypatch)
    router = _StubRouter()
    await rpc_skills._handle_skills_search({"query": "test", "limit": 1000}, _Ctx(router))

    assert len(router.calls) == 1
    assert router.calls[0]["limit"] == 500


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid_limit", ["invalid", None, [], {}])
async def test_skills_search_falls_back_to_default_on_non_integer_limit(
    monkeypatch, invalid_limit: object
) -> None:
    _no_lockfile(monkeypatch)
    router = _StubRouter()
    await rpc_skills._handle_skills_search({"query": "test", "limit": invalid_limit}, _Ctx(router))

    assert len(router.calls) == 1
    assert router.calls[0]["limit"] == 20


@pytest.mark.asyncio
async def test_skills_search_passes_valid_limit_unchanged(monkeypatch) -> None:
    _no_lockfile(monkeypatch)
    router = _StubRouter()
    await rpc_skills._handle_skills_search({"query": "test", "limit": 42}, _Ctx(router))

    assert len(router.calls) == 1
    assert router.calls[0]["limit"] == 42


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [-10, -1, 0])
async def test_source_router_search_clamps_limit_to_one(limit: int) -> None:
    m1 = SkillMeta(name="s1", source_id="src1", identifier="id1")
    m2 = SkillMeta(name="s2", source_id="src1", identifier="id2")
    source = _StubSource("src1", [m1, m2])
    router = SourceRouter([source])

    results = await router.search("test", limit=limit)

    assert len(source.calls) == 1
    assert source.calls[0]["limit"] == 1
    assert len(results) == 1
    assert results[0].name == "s1"
