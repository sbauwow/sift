from __future__ import annotations

from sift.state import (
    HttpRequest,
    JsonStateStore,
    SupabaseStateStore,
    build_state_store,
)


def test_json_store_round_trip(tmp_path):
    store = JsonStateStore(tmp_path / "s.json")
    assert store.load() is None
    store.save({"tick": 3, "stats": [{"region": "easy", "tier": "local"}]})
    assert store.load()["tick"] == 3


def test_supabase_store_save_upserts_row():
    captured: list[HttpRequest] = []

    def transport(req):
        captured.append(req)
        return None

    store = SupabaseStateStore(
        base_url="https://proj.supabase.co", api_key="k", agent_id="sift-1",
        transport=transport,
    )
    store.save({"tick": 2})

    req = captured[0]
    assert req.method == "POST"
    assert req.url == "https://proj.supabase.co/rest/v1/sift_agent_state"
    assert req.headers["apikey"] == "k"
    assert "merge-duplicates" in req.headers["Prefer"]
    assert b'"agent_id": "sift-1"' in req.body


def test_supabase_store_load_reads_state_column():
    def transport(req):
        assert req.method == "GET"
        assert "agent_id=eq.sift-1" in req.url
        return [{"state": {"tick": 7}}]

    store = SupabaseStateStore(
        base_url="https://proj.supabase.co", api_key="k", agent_id="sift-1",
        transport=transport,
    )
    assert store.load() == {"tick": 7}


def test_supabase_store_load_empty_returns_none():
    store = SupabaseStateStore(
        base_url="https://proj.supabase.co", api_key="k", agent_id="x",
        transport=lambda req: [],
    )
    assert store.load() is None


def test_build_state_store_selects_backend():
    assert isinstance(build_state_store("a", env={}), JsonStateStore)
    supa = build_state_store("a", env={"SUPABASE_URL": "https://p.supabase.co", "SUPABASE_KEY": "k"})
    assert isinstance(supa, SupabaseStateStore)


def test_agent_persists_through_supabase_store():
    """Agent state round-trips through an in-memory Supabase double."""
    import random

    from sift.agent import HeartbeatAgent
    from sift.harness import EvaluationResult, HarnessRun, TaskSpec
    from sift.router import Ladder, Policy, Router, Rung

    rows: dict[str, dict] = {}

    def transport(req):
        if req.method == "POST":
            import json

            rows["r"] = json.loads(req.body)[0]["state"]
            return None
        return [{"state": rows["r"]}] if "r" in rows else []

    class StubProvider:
        def __init__(self, name):
            self.name, self.model = name, "stub"

    class StubRunner:
        def run_task(self, task, provider):
            passed = provider.name == "cloud" or "easy" in task.tags
            return HarnessRun(task.id, provider.name, provider.model, "ok",
                              EvaluationResult(task.id, passed, 0, "", ""),
                              cost_usd=0.0 if provider.name == "local" else 0.02)

    def make_router():
        ladder = Ladder([Rung("local", StubProvider("local"), is_local=True),
                         Rung("cloud", StubProvider("cloud"))])
        return Router(ladder, StubRunner(), policy=Policy(), rng=random.Random(0))

    tasks = [TaskSpec(id=f"e{i}", prompt="p", check_command="true", tags=("easy",)) for i in range(6)]
    store = SupabaseStateStore(base_url="https://p.supabase.co", api_key="k",
                               agent_id="sift-1", transport=transport)
    agent = HeartbeatAgent(make_router(), tasks, state_store=store,
                           probe_size=6, sleep_fn=lambda _: None)
    agent.run(max_ticks=3)

    resumed = HeartbeatAgent(make_router(), tasks, state_store=store,
                             probe_size=6, sleep_fn=lambda _: None)
    assert resumed.tick_count == 3
