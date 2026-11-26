"""The execution lease (014/FR-038, FR-014, SC-013, research D12): acquiring a run id already leased raises
immediately; releasing (even via an exception) makes it acquirable again; two apps' own lease sets never see each
other's run ids."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from kestrel.checkpointing import RunLeased, lease, mark_active

FEATURE = "014"


class _Store:
    def __init__(self):
        self.touched: list[int] = []

    def touch_last_activity(self, run_id, *, now=None):
        self.touched.append(run_id)


def _app_state():
    return SimpleNamespace(leases=set(), accepted_exits=set(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))


def test_acquiring_an_already_leased_run_raises_immediately():  # FR-038
    app_state = _app_state()
    store = _Store()
    with lease(app_state, store, 1):
        with pytest.raises(RunLeased):
            with lease(app_state, store, 1):
                pass


def test_releasing_makes_it_acquirable_again_even_after_an_exception():  # FR-038
    app_state = _app_state()
    store = _Store()
    with pytest.raises(ValueError):
        with lease(app_state, store, 1):
            raise ValueError("boom")
    with lease(app_state, store, 1):
        pass   # acquirable again


def test_two_concurrent_coroutines_racing_for_one_lease_exactly_one_succeeds():  # FR-038, SC-013
    app_state = _app_state()
    store = _Store()
    results = {"succeeded": 0, "refused": 0}

    async def racer():
        try:
            with lease(app_state, store, 1):
                await asyncio.sleep(0.01)
                results["succeeded"] += 1
        except RunLeased:
            results["refused"] += 1

    async def go():
        await asyncio.gather(racer(), racer())

    asyncio.run(go())
    assert results == {"succeeded": 1, "refused": 1}


def test_two_independent_apps_never_share_lease_sets_even_for_the_same_run_id():  # FR-038
    app_a, app_b = _app_state(), _app_state()
    store = _Store()
    with lease(app_a, store, 1):
        with lease(app_b, store, 1):   # a different app's own lease set: never refused
            pass


def test_mark_active_releases_touch_last_activity_only_when_called(): # FR-059, research D26
    app_state = _app_state()
    store = _Store()
    with lease(app_state, store, 1):
        mark_active(app_state, 1)
    assert store.touched == [1]

    store2 = _Store()
    with lease(app_state, store2, 2):
        pass   # no mark_active: a refused/no-op exit never touches the idle clock
    assert store2.touched == []
