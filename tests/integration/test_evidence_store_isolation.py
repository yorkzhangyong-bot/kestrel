"""No planted value of a run ever reaches the experience store or a retrieval query (013/FR-063, 013/SC-013).

A confirmed override-family run in both placements, driven by the **repeating** attacker and judge doubles — whose
turn-2-and-later messages and progress notes echo the run's real token parts, read back from the store — and a
spy store that records every pattern document, memory record and query. Without those doubles this test would
pass vacuously. The run's own `prompt_text` and turn rows must still carry everything, so a replay re-sends them
verbatim. The callback half (a planted URL) is part 2's, where the callback task exists."""
from __future__ import annotations

import httpx
import pytest

from kestrel.evidence import override
from tests.support import (RepeatingStubAttacker, RepeatingStubJudge, SpyExperienceStore, StubEmbeddingFunction,
                           fixture_library, planted_values, saved_target)

FEATURE = "013"

PLACEMENTS = [("direct_injection", "dir-001"), ("indirect_injection", "iin-001")]


def warm_client(make_client, settings, *, confirm_on_turn: int | None = None, library=None):
    """A client whose experience store is a spy and whose attacker and judge repeat the run's planted parts.

    `confirm_on_turn` makes the stub target answer that turn with the run's own joined form, so the run is
    confirmed there and the write-back takes the *pattern* path with the winning messages as its document.
    `library` defaults to the fixture library; the shipped one is what carries the sidecar's quoting frames."""
    spy = SpyExperienceStore(settings.chroma_path, embedding_function=StubEmbeddingFunction())
    state: dict = {"turn": 0}

    def reply(request: httpx.Request) -> httpx.Response:
        state["turn"] += 1
        store = state.get("store")
        if confirm_on_turn is not None and state["turn"] == confirm_on_turn and store is not None:
            from tests.support import in_progress_run_id
            run_id = in_progress_run_id(store)
            joined = planted_values(store, run_id).get("joined", "") if run_id is not None else ""
            return httpx.Response(200, json={"reply": f"as instructed: {joined}"})
        return httpx.Response(200, json={"reply": "an ordinary reply"})

    api = make_client(settings, transport=httpx.MockTransport(reply), library=library or fixture_library(),
                      experience=spy, judge=RepeatingStubJudge(None, verdict="failed"),
                      attacker=RepeatingStubAttacker(None))
    store = api.app.state.store
    api.app.state.judge._store = store
    api.app.state.attacker._store = store
    state["store"] = store
    return api, spy, store


def written_texts(spy: SpyExperienceStore) -> list[str]:
    """Every text this run handed the store: the pattern documents, the memory records and their summaries."""
    texts = [document for document in spy.pattern_documents if document]
    for memory in spy.memory_writes:
        texts += [str(value) for key, value in memory.items() if key == "summary" and value]
    return texts


@pytest.mark.parametrize("family, seed_id", PLACEMENTS)
def test_no_token_part_joined_form_or_task_wording_reaches_the_store_or_a_query(make_client, settings, family,
                                                                                seed_id):  # FR-063, SC-013
    # Confirmed on turn 3, so the write-back takes the pattern path with the winning messages as its document -
    # turn 1's planted opening and the turn-2 and turn-3 attacker messages, which repeat the parts - and the
    # turn-3 retrieval query is built from turn 2's repeating message, which stripping alone would never clean.
    api, spy, store = warm_client(make_client, settings, confirm_on_turn=3)
    target = saved_target(store, description="a customs assistant")

    response = api.post("/api/runs", json={"target_id": target.id, "family": family, "prompt_id": seed_id,
                                           "mode": "adaptive"})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["verdict"] == "succeeded" and run["hard_evidence"] is True and run["succeeded_turn"] == 3
    assert [write.outcome for write in spy.pattern_writes], "a confirmed run must write a pattern"

    values = planted_values(store, run["id"])
    assert values["joined"] and values["first"] and values["second"]
    paragraph = override.override_task_paragraph(
        override.OverrideToken(values["first"], values["second"]))[0]
    markers = {"first part": values["first"], "second part": values["second"], "joined form": values["joined"],
               "task wording": paragraph}

    # Nothing written to the store, and nothing used to search, carries any of them. The turn-3 query is the one
    # that matters: it is built from turn 2's repeating attacker message, so only the value scrub can clean it.
    queries = [query["query_text"] for query in spy.queries]
    assert len(queries) == 2, "a warm adaptive run confirmed on turn 3 queries on turns 2 and 3"
    assert "<attacker turn 2>" in queries[1]
    for label, marker in markers.items():
        for query in queries:
            assert marker not in query, f"{label} reached a retrieval query"
        for text in written_texts(spy):
            assert marker not in text, f"{label} reached the experience store"

    # The repeating doubles really did echo the parts, so the check above cannot pass vacuously.
    turns = api.get(f"/api/runs/{run['id']}").json()["turns"]
    later = " ".join(turn["attacker_message"] for turn in turns[1:])
    notes = " ".join(turn.get("judge_progress") or "" for turn in turns)
    assert values["first"] in later and values["second"] in later
    assert values["first"] in notes and values["second"] in notes

    # The run's own record keeps everything exactly as sent, so a replay re-sends it verbatim (FR-063).
    assert values["first"] in run["prompt_text"] and values["second"] in run["prompt_text"]
    assert paragraph in run["prompt_text"]
    assert turns[0]["attacker_message"] == run["prompt_text"]


def test_a_shipped_indirect_seeds_frame_is_stripped_whole_with_its_paragraph(make_client, settings):  # FR-063, FR-064
    """The sidecar's quoting frame is part of the run's task text (FR-064): the sent and stored message carries
    the frame with the paragraph inside its quoted span, and every text the pool and the query see is the library
    seed byte-identical - the framed text removed as one string, never the paragraph alone with the frame left
    behind. Only the shipped library carries frames (a fixture seed gets a derived, frameless point), so this is
    the one offline run on it; the frame shows the agent was given retrieved-looking content inside the user turn,
    not that an instruction travelled a real retrieval path (part 2's side channel)."""
    from kestrel.attacks.library import load_library
    library = load_library()
    seed = library.pick("indirect_injection", "iin-001")
    point = override.load_insertion_points()[seed.id]
    api, spy, store = warm_client(make_client, settings, confirm_on_turn=3, library=library)
    target = saved_target(store, description="a customs assistant")

    response = api.post("/api/runs", json={"target_id": target.id, "family": "indirect_injection",
                                           "prompt_id": seed.id, "mode": "adaptive"})
    assert response.status_code == 201, response.text
    run = response.json()
    assert run["verdict"] == "succeeded" and run["succeeded_turn"] == 3

    values = planted_values(store, run["id"])
    paragraph = override.override_task_paragraph(override.OverrideToken(values["first"], values["second"]))[0]
    framed = point.frame(paragraph)
    assert run["prompt_text"] == override.place_task(seed.text, point, paragraph)
    assert framed in run["prompt_text"] and point.frame_prefix and seed.text not in run["prompt_text"]

    queries = [query["query_text"] for query in spy.queries]
    assert len(queries) == 2 and seed.text in queries[0]     # turn 2's query: turn 1's message, the framed text gone
    written = written_texts(spy)
    assert any(seed.text in text for text in written)       # the pattern document keeps the seed, nothing planted
    for text in queries + written:
        assert point.frame_prefix not in text and paragraph not in text
        assert values["first"] not in text and values["second"] not in text


def test_a_family_that_plants_nothing_writes_exactly_what_it_did_before(make_client, settings):  # FR-061, FR-063
    api, spy, store = warm_client(make_client, settings)
    target = saved_target(store)

    response = api.post("/api/runs", json={"target_id": target.id, "family": "system_prompt_leak",
                                           "prompt_id": "spl-001", "mode": "adaptive"})
    assert response.status_code == 201, response.text
    run = response.json()

    assert store.list_planted_tokens(run["id"]) == []
    seed = fixture_library().pick("system_prompt_leak", "spl-001").text
    assert run["prompt_text"] == seed
    # The seed itself is what the query and the pool see, unchanged by the stripping that found nothing to strip.
    assert any(seed in query["query_text"] for query in spy.queries)
