"""Kestrel's FastAPI app. Run it with: uvicorn --factory kestrel.api.main:create_app"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from kestrel.api.schemas import (AttackFamilyOut, AttackPromptOut, AttackerOut, ConfigOut, ConnectionSettingsIn,
                                 ConnectionTestRequest, ConnectionTestResult, ExperienceOut, FormDefaults, HeaderOut,
                                 JudgeOut, ProfileOut, RunDetail, RunRequest, RunSummary, SaveTargetRequest,
                                 TargetDetail, TargetSummary, TermsOut, TurnOut, AdaptiveCapsOut,
                                 ArmProgressOut, ArmResultOut, CategoryCountOut, ComparisonOut,
                                 CreateExperimentRequest, ExperimentResultOut, ExperimentStatusOut,
                                 ExperimentSummaryOut, RateOut, experiment_diff, validate_canaries,
                                 validate_experiment, validate_save, validate_settings)
from kestrel.attack.attacker import GOALS, AttackerClient
from kestrel.attacks.library import FAMILIES, AttackLibrary, LibraryError, load_library
from kestrel.experience.hints import format_hints
from kestrel.experience.store import ExperienceStore, ExperienceStoreError, describe_store_error
from kestrel.experience.writeback import write_back
from kestrel.experiments import pricing as exp_pricing
from kestrel.experiments import results as exp_results
from kestrel.experiments.engine import run_experiment
from kestrel.report.model import build_report
from kestrel.report.recommend import recommendations_for
from kestrel.report.render import render_html, render_markdown
from kestrel.connection.address_guard import default_resolver
from kestrel.connection.sessions import FormSessions
from kestrel.connection.tester import ResolvedSettings, refused, run_test
from kestrel.judge.client import JudgeClient
from kestrel.runs import execute_run, execute_adaptive_run
from kestrel.store import Turn
from kestrel.secrets import Vault, load_or_create_key
from kestrel.settings import Settings, load_settings
from kestrel.store import (ExperimentInProgress, NameTaken, Run, RunInProgress, Target, TargetNotFound,
                           TargetStore, utc_now)

LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
DEFAULTS = FormDefaults(method="POST", body_template='{"message": "{{prompt}}"}', response_path="$.reply")
TERMS_PATH = Path(__file__).with_name("terms.md")
NOT_TESTED = "Run a successful test with these settings before saving."
NAME_TAKEN = "Another saved target already has this name."


def create_app(settings: Settings | None = None, *, transport: httpx.AsyncBaseTransport | None = None,
               resolver: Any = None, library: AttackLibrary | None = None, judge: Any = None,
               attacker: Any = None, experience: Any = None) -> FastAPI:
    """Build the app. Tests pass settings, a transport for targets, a fake resolver, a library, a judge, an attacker
    and an experience store (a stub-backed one keeps tests offline)."""
    settings = settings or load_settings()
    logger = _configure_logging()
    key, _source = load_or_create_key(settings, logger)
    vault = Vault(key)
    terms = load_terms()
    store = TargetStore(settings.db_path, vault)
    if not store.key_matches():
        logger.error("The encryption key doesn't match the one used to save targets, so saved auth header values "
                     "can't be read. Restore the old key, or re-enter the values.")
    closed = store.close_interrupted_runs()  # release any run the last process left in progress (FR-031)
    if closed:
        logger.info("Closed %d run(s) that were interrupted by a previous shutdown.", closed)

    if library is None:
        try:
            library = load_library()
        except LibraryError as error:
            logger.warning("The attack library could not be loaded, so attacks are unavailable: %s", error)
    # Capture any injected test doubles before defaulting: experiments build a client per arm, so in tests the
    # injected stub is reused for every arm, while production builds a real per-arm client from settings.
    injected_judge, injected_attacker = judge, attacker
    judge = judge or JudgeClient(model=settings.judge_model, api_key=settings.judge_api_key,
                                 base_url=settings.judge_base_url)
    attacker = attacker or AttackerClient(model=settings.attacker_model, api_key=settings.attacker_api_key,
                                          base_url=settings.attacker_base_url)
    if experience is None:  # production: the local ChromaDB store with its default embeddings (feature 004)
        try:
            experience = ExperienceStore(settings.chroma_path)
            experience.self_check()  # surface a bad store (mismatched EF, failed model download) clearly, now
        except Exception as error:
            reason = error.args[0] if isinstance(error, ExperienceStoreError) else describe_store_error(error)
            logger.error("The experience store at %s is unavailable, so runs will record loudly as not written "
                         "back (Principle V): %s", settings.chroma_path, reason)
            experience = None
    if experience is not None and library is not None:
        try:
            seeded = experience.seed_patterns(library)  # idempotent (FR-004)
            logger.info("Seeded %d attack pattern(s) into the experience store.", seeded)
        except Exception as error:
            logger.error("The experience store could not be seeded, so runs will record loudly as not written "
                         "back: %s", describe_store_error(error))
            experience = None

    app = FastAPI(title="Kestrel API", version="0.1.0")
    app.state.settings = settings
    app.state.vault = vault
    app.state.store = store
    app.state.transport = transport
    app.state.resolver = resolver or default_resolver
    app.state.sessions = FormSessions()
    app.state.library = library
    app.state.judge = judge
    app.state.attacker = attacker
    app.state.experience = experience
    app.state.injected_judge = injected_judge        # feature 007: reused for every arm in tests
    app.state.injected_attacker = injected_attacker
    app.state.experiment_tasks = set()               # keep background experiment tasks referenced (no GC)
    app.add_exception_handler(RequestValidationError, _validation_error)

    @app.get("/api/config", response_model=ConfigOut)
    def get_config() -> ConfigOut:
        return ConfigOut(mode=settings.mode, defaults=DEFAULTS, terms=terms,
                         judge=JudgeOut(model=settings.judge_model, configured=app.state.judge.configured),
                         attacker=AttackerOut(model=settings.attacker_model,
                                              configured=app.state.attacker.configured),
                         adaptive=AdaptiveCapsOut(max_turns=settings.adaptive_max_turns,
                                                  token_budget=settings.adaptive_token_budget,
                                                  time_limit_s=settings.adaptive_time_limit_s),
                         experience=ExperienceOut(pattern_k=settings.experience_pattern_k,
                                                  memory_cap=settings.experience_memory_cap,
                                                  use_prior_experience_default=True))

    @app.post("/api/connection-tests", response_model=ConnectionTestResult)
    async def connection_test(body: ConnectionTestRequest, request: Request) -> Any:
        errors = validate_settings(body.settings, has_target=body.target_id is not None)
        if errors:
            return form_errors(errors)
        stored: dict[str, str | None] | None = None
        if body.target_id is not None:
            try:
                stored = stored_values(store, body.target_id)
            except TargetNotFound:
                return not_found(body.target_id)
            errors = kept_value_errors(body.settings, stored)
            if errors:
                return form_errors(errors)

        resolved = resolve(body.settings, stored)
        display_name = body.display_name.strip()
        form_id = str(body.form_id)
        sessions: FormSessions = request.app.state.sessions
        if not sessions.start(form_id):
            return api_error(409, "test_in_progress", "A test for this form is already running.")
        fingerprint = None
        try:
            if stored is not None and needs_unreadable_value(body.settings, stored):
                return refused("credentials_unreadable", resolved, display_name).as_dict()  # nothing is sent
            result = await run_test(resolved, mode=settings.mode, display_name=display_name,
                                    transport=request.app.state.transport, resolver=request.app.state.resolver)
            if result.ok:
                fingerprint = sessions.fingerprint(resolved)
        finally:
            sessions.finish(form_id, fingerprint)
        return result.as_dict()

    @app.get("/api/targets", response_model=list[TargetSummary])
    def list_targets() -> list[TargetSummary]:
        return [summary(target) for target in store.list_targets()]

    @app.post("/api/targets", status_code=201, response_model=TargetDetail)
    def save_target(body: SaveTargetRequest, request: Request) -> Any:
        errors = (validate_settings(body.settings, has_target=False) + validate_save(body, terms.version)
                  + validate_canaries(body.canaries))
        if errors:
            return form_errors(errors)
        resolved = resolve(body.settings)
        sessions: FormSessions = request.app.state.sessions
        if sessions.last_success(str(body.form_id)) != sessions.fingerprint(resolved):
            return api_error(409, "not_tested", NOT_TESTED)
        try:
            target = store.create_target(name=body.name.strip(), url=resolved.url, method=resolved.method,
                                         headers=list(resolved.headers), body_template=resolved.body_template,
                                         response_path=resolved.response_path, terms_version=terms.version,
                                         description=_clean_description(body.description))
            if body.canaries:
                store.set_canaries(target.id, body.canaries)
        except NameTaken:
            return api_error(409, "name_taken", NAME_TAKEN, field="name")
        return detail(store.get_target(target.id), store.list_canaries(target.id))

    @app.get("/api/targets/{target_id}", response_model=TargetDetail)
    def get_target(target_id: int) -> Any:
        try:
            return detail(store.get_target(target_id), store.list_canaries(target_id))
        except TargetNotFound:
            return not_found(target_id)

    @app.put("/api/targets/{target_id}", response_model=TargetDetail)
    def update_target(target_id: int, body: SaveTargetRequest, request: Request) -> Any:
        try:
            existing = store.get_target(target_id)
            stored = stored_values(store, target_id)
        except TargetNotFound:
            return not_found(target_id)
        errors = (validate_settings(body.settings, has_target=True) + kept_value_errors(body.settings, stored)
                  + validate_save(body, terms.version) + validate_canaries(body.canaries))
        if errors:
            return form_errors(errors)

        resolved = resolve(body.settings, stored)
        current = ResolvedSettings(url=existing.url, method=existing.method,
                                   headers=tuple((h.name, stored[h.name.lower()] or "") for h in existing.headers),
                                   body_template=existing.body_template, response_path=existing.response_path)
        sessions: FormSessions = request.app.state.sessions
        changed = sessions.fingerprint(resolved) != sessions.fingerprint(current)  # a name-only edit needs no test
        if changed and sessions.last_success(str(body.form_id)) != sessions.fingerprint(resolved):
            return api_error(409, "not_tested", NOT_TESTED)
        try:
            target = store.update_target(target_id, name=body.name.strip(), url=resolved.url, method=resolved.method,
                                         headers=[(h.name.strip(), h.value) for h in body.settings.headers],
                                         body_template=resolved.body_template, response_path=resolved.response_path,
                                         terms_version=terms.version, description=_clean_description(body.description))
        except NameTaken:
            return api_error(409, "name_taken", NAME_TAKEN, field="name")
        if body.canaries is not None:  # None keeps the stored canaries; [] clears them (contracts/kestrel-api.md)
            store.set_canaries(target_id, body.canaries)
        return detail(store.get_target(target_id), store.list_canaries(target_id))

    @app.delete("/api/targets/{target_id}", status_code=204)
    def delete_target(target_id: int) -> Response:
        try:
            store.delete_target(target_id)
        except TargetNotFound:
            return not_found(target_id)
        if app.state.experience is not None:  # forget this target's memory too; shared patterns stay (FR-024/25)
            try:
                app.state.experience.delete_target_memory(target_id)
            except Exception:
                logger.exception("could not delete experience memory for target %s", target_id)
        return Response(status_code=204)

    @app.post("/api/runs", status_code=201, response_model=RunDetail)
    async def start_run(body: RunRequest, request: Request) -> Any:
        library: AttackLibrary | None = request.app.state.library
        if library is None:
            return api_error(503, "library_unavailable", "The attack library is not available.")
        try:
            target = store.get_target(body.target_id)
        except TargetNotFound:
            return not_found(body.target_id)

        # Preconditions are checked before any run row is written (contracts/kestrel-api.md).
        if not target.permission_confirmed_at:
            return api_error(409, "permission_missing",
                             "Tick the permission box and save the target before attacking it.")
        if target.terms_version != terms.version:
            return api_error(409, "terms_outdated",
                             "The terms of service have changed; read them and tick the box again.")
        try:
            prompt = library.pick(body.family, body.prompt_id)
        except LookupError as error:
            field = "prompt_id" if body.prompt_id else "family"
            return form_errors([{"field": field, "message": str(error)}])

        resolved = ResolvedSettings(
            url=target.url, method=target.method,
            headers=tuple((h.name, stored_values(store, target.id).get(h.name.lower()) or "")
                          for h in target.headers),
            body_template=target.body_template, response_path=target.response_path)
        if body.mode == "adaptive" and not request.app.state.attacker.configured:
            return api_error(409, "attacker_unavailable",
                             "No attacker model is configured, so an adaptive attack can't run.")
        experience = request.app.state.experience

        def hint_provider(conversation: list[tuple[str, str]]) -> str | None:
            """The attacker's background each turn: purpose always; patterns + memory only on a warm run (FR-021)."""
            purpose = target.description
            if not body.use_prior_experience or experience is None:
                return format_hints(purpose=purpose, patterns=[], memory=[])  # cold: purpose only (FR-015)
            memory = experience.retrieve_memory(target_id=target.id, family=prompt.family,
                                                 cap=settings.experience_memory_cap)
            query = f"{GOALS.get(prompt.family, '')} {_recent_conversation(conversation)}".strip()
            patterns = experience.retrieve_patterns(family=prompt.family, query_text=query,
                                                    k=settings.experience_pattern_k)
            return format_hints(purpose=purpose, patterns=patterns, memory=memory)

        try:
            if body.mode == "adaptive":
                run = await execute_adaptive_run(
                    store, target_id=target.id, seed_prompt=prompt, attacker_source=library.attacker_source,
                    canaries=store.list_canaries(target.id), resolved=resolved, mode=settings.mode,
                    attacker=request.app.state.attacker, judge=request.app.state.judge,
                    max_turns=settings.adaptive_max_turns, token_budget=settings.adaptive_token_budget,
                    time_limit_s=settings.adaptive_time_limit_s, transport=request.app.state.transport,
                    resolver=request.app.state.resolver, use_prior_experience=body.use_prior_experience,
                    hint_provider=hint_provider)
            else:
                run = await execute_run(store, target_id=target.id, prompt=prompt,
                                        attacker_source=library.attacker_source,
                                        canaries=store.list_canaries(target.id), resolved=resolved,
                                        mode=settings.mode, judge=request.app.state.judge,
                                        transport=request.app.state.transport, resolver=request.app.state.resolver,
                                        use_prior_experience=body.use_prior_experience)
        except RunInProgress:
            return api_error(409, "run_in_progress", "A run against this target is already in progress.")
        # Write back to the experience store after every run; a failure is loud, never discards the run (FR-006/10).
        turns = store.list_turns(run.id)
        write_back(request.app.state.experience, store, run, turns)
        return run_detail(store.get_run(run.id), turns)

    @app.get("/api/targets/{target_id}/runs", response_model=list[RunSummary])
    def list_runs(target_id: int) -> Any:
        try:
            return [run_summary(run) for run in store.list_runs(target_id)]
        except TargetNotFound:
            return not_found(target_id)

    @app.get("/api/targets/{target_id}/profile", response_model=ProfileOut)
    def target_profile(target_id: int) -> Any:
        try:
            store.get_target(target_id)
        except TargetNotFound:
            return not_found(target_id)
        experience = app.state.experience
        if experience is None:  # store unavailable: an empty profile, not an error
            return ProfileOut(target_id=target_id, total_runs=0, by_family=[], by_verdict=[], recent=[])
        return ProfileOut(**experience.profile(target_id))

    @app.get("/api/targets/{target_id}/report")
    async def target_report(target_id: int, format: str = "md") -> Any:
        """Generate the OWASP-mapped report for a target (feature 005). Read-only: no run, no send, no store write."""
        if format not in ("md", "html"):
            return form_errors([{"field": "format", "message": "format must be 'md' or 'html'."}])
        try:
            target = store.get_target(target_id)
        except TargetNotFound:
            return not_found(target_id)
        runs = store.list_runs(target_id)
        turns_by_run = {run.id: store.list_turns(run.id) for run in runs if run.mode == "adaptive"}
        # One judge call per uncached success (FR-012); cached thereafter. No target send, no experience write.
        recommendations = await recommendations_for(store, app.state.judge, runs, turns_by_run)
        experience_summary = _experience_counts(app.state.experience, target_id)
        model = build_report(target=target, runs=runs, turns_by_run=turns_by_run, recommendations=recommendations,
                             experience_summary=experience_summary, now=utc_now())
        markdown = render_markdown(model)
        if format == "html":
            return Response(content=render_html(markdown), media_type="text/html; charset=utf-8")
        return Response(content=markdown, media_type="text/markdown; charset=utf-8")

    @app.get("/api/runs/{run_id}", response_model=RunDetail)
    def get_run(run_id: int) -> Any:
        try:
            return run_detail(store.get_run(run_id), store.list_turns(run_id))
        except LookupError:
            return api_error(404, "not_found", f"No run with id {run_id}.")

    @app.get("/api/attack-families")
    def attack_families(request: Request) -> Any:
        library: AttackLibrary | None = request.app.state.library
        if library is None:
            return api_error(503, "library_unavailable", "The attack library is not available.")
        return {"library_version": library.version,
                "families": [AttackFamilyOut(**f).model_dump() for f in library.families()]}

    @app.get("/api/attack-prompts")
    def attack_prompts(family: str, request: Request) -> Any:
        library: AttackLibrary | None = request.app.state.library
        if library is None:
            return api_error(503, "library_unavailable", "The attack library is not available.")
        try:
            prompts = library.prompts_in(family)
        except LookupError as error:
            return form_errors([{"field": "family", "message": str(error)}])
        return {"prompts": [AttackPromptOut(id=p.id, title=p.title, text=p.text, family=p.family,
                                            owasp_category=p.owasp_category, source=p.source).model_dump()
                            for p in prompts]}

    @app.post("/api/experiments", status_code=201)
    async def create_experiment(body: CreateExperimentRequest, request: Request) -> Any:
        library: AttackLibrary | None = request.app.state.library
        if library is None:
            return api_error(503, "library_unavailable", "The attack library is not available.")
        try:
            target = store.get_target(body.target_id)
        except TargetNotFound:
            return not_found(body.target_id)
        if not target.permission_confirmed_at:
            return api_error(409, "permission_missing",
                             "Tick the permission box and save the target before attacking it.")
        if target.terms_version != terms.version:
            return api_error(409, "terms_outdated",
                             "The terms of service have changed; read them and tick the box again.")
        errors = validate_experiment(body, list(FAMILIES))
        if errors:
            return form_errors(errors)
        attacker_ready = request.app.state.attacker.configured or request.app.state.injected_attacker is not None
        if body.mode == "adaptive" and not attacker_ready:
            return api_error(409, "attacker_unavailable",
                             "No attacker model is configured, so an adaptive experiment can't run.")
        families = body.families or list(FAMILIES)
        try:
            seed_prompt_ids = {family: library.pick(family).id for family in families}
        except LookupError as error:
            return form_errors([{"field": "families", "message": str(error)}])
        try:
            experiment = store.create_experiment(
                target_id=target.id, mode=body.mode, families=families, reps=body.reps,
                seed_prompt_ids=seed_prompt_ids,
                max_runs=body.caps.max_runs or settings.experiment_max_runs,
                token_budget_total=body.caps.token_budget_total or settings.experiment_token_budget,
                wall_clock_s=body.caps.wall_clock_s or settings.experiment_wall_clock_s,
                arm_a=body.arm_a.model_dump(), arm_b=body.arm_b.model_dump())
        except ExperimentInProgress:
            return api_error(409, "experiment_in_progress",
                             "An experiment against this target is already running.")
        _schedule_experiment(request.app, store, settings, experiment.id)
        return {"id": experiment.id, "status": experiment.status}

    @app.get("/api/experiments", response_model=list[ExperimentSummaryOut])
    def list_experiments() -> Any:
        return [_experiment_summary(experiment) for experiment in store.list_experiments()]

    @app.get("/api/experiments/{experiment_id}/status", response_model=ExperimentStatusOut)
    def experiment_status(experiment_id: int) -> Any:
        try:
            experiment = store.get_experiment(experiment_id)
        except LookupError:
            return api_error(404, "not_found", f"No experiment with id {experiment_id}.")
        return _experiment_status(store, settings, experiment)

    @app.get("/api/experiments/{experiment_id}/result", response_model=ExperimentResultOut)
    def experiment_result(experiment_id: int) -> Any:
        try:
            experiment = store.get_experiment(experiment_id)
        except LookupError:
            return api_error(404, "not_found", f"No experiment with id {experiment_id}.")
        return _experiment_result(store, settings, experiment)

    return app


def stored_values(store: TargetStore, target_id: int) -> dict[str, str | None]:
    """Stored header values by lower-cased name; None for a value the current key can't decrypt."""
    return {h.name.lower(): h.value for h in store.resolve_headers(target_id)}


def kept_value_errors(settings: ConnectionSettingsIn, stored: dict[str, str | None]) -> list[dict[str, str]]:
    """`value: null` only works for a header the target has stored."""
    return [{"field": f"settings.headers.{i}.value", "message": "Enter a value for this header."}
            for i, header in enumerate(settings.headers)
            if header.value is None and header.name.strip().lower() not in stored]


def needs_unreadable_value(settings: ConnectionSettingsIn, stored: dict[str, str | None]) -> bool:
    return any(h.value is None and stored.get(h.name.strip().lower()) is None for h in settings.headers)


def not_found(target_id: int) -> JSONResponse:
    return api_error(404, "not_found", f"No target with id {target_id}.")


def resolve(settings: ConnectionSettingsIn, stored: dict[str, str | None] | None = None) -> ResolvedSettings:
    """Connection settings with every header value known; `value: null` takes the stored value (FR-017)."""
    stored = stored or {}
    headers = []
    for header in settings.headers:
        name = header.name.strip()
        value = header.value if header.value is not None else stored.get(name.lower())
        headers.append((name, value or ""))
    return ResolvedSettings(url=settings.url.strip(), method=settings.method, headers=tuple(headers),
                            body_template=settings.body_template, response_path=settings.response_path.strip())


def summary(target: Target) -> TargetSummary:
    return TargetSummary(id=target.id, name=target.name, url=target.url, method=target.method,
                         permission_confirmed_at=target.permission_confirmed_at, terms_version=target.terms_version,
                         description=target.description)


def detail(target: Target, canaries: list[str] | None = None) -> TargetDetail:
    return TargetDetail(**summary(target).model_dump(), body_template=target.body_template,
                        response_path=target.response_path,
                        headers=[HeaderOut(name=h.name, has_value=True, readable=h.readable) for h in target.headers],
                        canaries=canaries if canaries is not None else [])


def _clean_description(description: str | None) -> str | None:
    """Trim the optional purpose description; an empty one is stored as nothing (FR-020)."""
    cleaned = (description or "").strip()
    return cleaned or None


def _recent_conversation(conversation: list[tuple[str, str]], turns: int = 2) -> str:
    """The text of the last `turns` turns (up to 2*turns messages), for the pattern-retrieval query (U1)."""
    return " ".join(text for _, text in conversation[-2 * turns:])


def _experience_counts(experience: Any, target_id: int) -> dict | None:
    """Read-only memory and pattern counts for the report's limitations note; None if the store is unavailable."""
    if experience is None:
        return None
    try:
        return {"memory_count": experience.count("memory", target_id=target_id),
                "pattern_count": experience.count("pattern")}
    except Exception:
        return None


def run_summary(run: Run) -> RunSummary:
    return RunSummary(id=run.id, target_id=run.target_id, mode=run.mode, prompt_id=run.prompt_id,
                      prompt_title=run.prompt_title, family=run.family, owasp_category=run.owasp_category,
                      verdict=run.verdict, hard_evidence=run.hard_evidence, judge_used=run.judge_used,
                      judge_model=run.judge_model, failure_step=run.failure_step, started_at=run.started_at,
                      finished_at=run.finished_at, memory_written=run.memory_written,
                      use_prior_experience=run.use_prior_experience)


def run_detail(run: Run, turns: list[Turn] | None = None) -> RunDetail:
    return RunDetail(**run_summary(run).model_dump(), status=run.status, prompt_text=run.prompt_text,
                     reply_text=run.reply_text, reply_truncated=run.reply_truncated, reason=run.reason,
                     attacker_source=run.attacker_source, attacker_model=run.attacker_model,
                     turn_budget=run.turn_budget, turns_used=run.turns_used, token_budget=run.token_budget,
                     tokens_used=run.tokens_used, time_limit_s=run.time_limit_s,
                     stopping_condition=run.stopping_condition, succeeded_turn=run.succeeded_turn,
                     turns=[TurnOut(position=t.position, attacker_message=t.attacker_message, reply_text=t.reply_text,
                                    reply_truncated=t.reply_truncated, judge_verdict=t.judge_verdict,
                                    judge_reason=t.judge_reason, judge_progress=t.judge_progress)
                            for t in (turns or [])])


def _schedule_experiment(app: FastAPI, store: TargetStore, settings: Settings, experiment_id: int) -> None:
    """Run the experiment in the background; keep the task referenced so it is not garbage-collected (R4)."""
    make_judge = (lambda model: app.state.injected_judge) if app.state.injected_judge is not None else None
    make_attacker = (lambda model: app.state.injected_attacker) if app.state.injected_attacker is not None else None
    task = asyncio.create_task(run_experiment(
        store, experiment_id=experiment_id, settings=settings, library=app.state.library,
        experience=app.state.experience, transport=app.state.transport, resolver=app.state.resolver,
        make_judge=make_judge, make_attacker=make_attacker))
    app.state.experiment_tasks.add(task)
    task.add_done_callback(app.state.experiment_tasks.discard)


def _experiment_summary(experiment) -> ExperimentSummaryOut:
    return ExperimentSummaryOut(id=experiment.id, target_id=experiment.target_id, status=experiment.status,
                                mode=experiment.mode, created_at=experiment.created_at,
                                finished_at=experiment.finished_at)


def _experiment_status(store: TargetStore, settings: Settings, experiment) -> ExperimentStatusOut:
    progress = store.experiment_progress(experiment.id)
    planned_per_arm = len(experiment.families) * experiment.reps
    arms = [ArmProgressOut(label=arm.label, run_order=arm.run_order,
                           completed=progress["per_arm"].get(arm.id, 0), planned=planned_per_arm)
            for arm in experiment.arms]
    return ExperimentStatusOut(id=experiment.id, status=experiment.status, stopped_reason=experiment.stopped_reason,
                               planned_runs=planned_per_arm * len(experiment.arms),
                               completed_runs=progress["completed"], tokens_used=progress["tokens"],
                               cost=_experiment_cost(store, settings, experiment), arms=arms)


def _experiment_cost(store: TargetStore, settings: Settings, experiment) -> float | None:
    """Total estimated cost across arms; None (unavailable) if any arm's primary-model price is unconfigured."""
    total = 0.0
    for arm in experiment.arms:
        tokens = sum(run.tokens_used or 0 for run in store.arm_runs(experiment.id, arm.id))
        price_model = arm.attacker_model if experiment.mode == "adaptive" else arm.judge_model
        cost = exp_pricing.arm_cost(tokens, price_model, settings.model_prices)
        if cost is None:
            return None
        total += cost
    return total


def _experiment_result(store: TargetStore, settings: Settings, experiment) -> ExperimentResultOut:
    links = store.experiment_run_links(experiment.id)
    arm_results = []
    for arm in sorted(experiment.arms, key=lambda a: a.label):
        runs = store.arm_runs(experiment.id, arm.id)
        send_failures = sum(1 for link in links if link.arm_id == arm.id and not link.send_ok)
        arm_results.append(exp_results.arm_result(arm, runs, mode=experiment.mode,
                                                  model_prices=settings.model_prices, send_failures=send_failures))
    comparison = exp_results.build_comparison(arm_results[0], arm_results[1])
    by_label = {arm.label: arm for arm in experiment.arms}
    return ExperimentResultOut(
        id=experiment.id, status=experiment.status, stopped_reason=experiment.stopped_reason,
        mode=experiment.mode, families=list(experiment.families), reps=experiment.reps,
        diff=experiment_diff(by_label["A"], by_label["B"]),
        order=_order_text(experiment), warming=_warming_text(experiment),
        arms=[_arm_result_out(result) for result in arm_results],
        comparison=ComparisonOut(confirmed=comparison.confirmed, suspected_diff=comparison.suspected_diff))


def _order_text(experiment) -> str:
    ordered = sorted((arm for arm in experiment.arms if arm.run_order is not None), key=lambda a: a.run_order)
    if ordered and len(ordered) == len(experiment.arms):
        return " then ".join(arm.label for arm in ordered)
    return "A then B"


def _warming_text(experiment) -> str:
    return "; ".join(f"{arm.label} {'warm' if arm.write_back else 'cold (no write-back)'}"
                     for arm in sorted(experiment.arms, key=lambda a: a.label))


def _arm_result_out(result) -> ArmResultOut:
    return ArmResultOut(label=result.label, attacker_model=result.attacker_model, judge_model=result.judge_model,
                        run_order=result.run_order, completed=result.completed, send_failures=result.send_failures,
                        confirmed=_rate_out(result.confirmed), suspected=_rate_out(result.suspected),
                        mean_turns_to_success=result.mean_turns_to_success, mean_tokens=result.mean_tokens,
                        cost=result.cost, cost_note=result.cost_note,
                        by_family=[_cat_out(c) for c in result.by_family],
                        by_owasp=[_cat_out(c) for c in result.by_owasp])


def _rate_out(rate) -> RateOut:
    return RateOut(successes=rate.successes, n=rate.n, rate=rate.rate, ci=rate.ci)


def _cat_out(count) -> CategoryCountOut:
    return CategoryCountOut(key=count.key, confirmed=count.confirmed, suspected=count.suspected, n=count.n)


def load_terms(path: Path = TERMS_PATH) -> TermsOut:
    """terms.md starts with a `version: N` line; the rest is the text shown next to the permission checkbox."""
    first, _, rest = path.read_text(encoding="utf-8").partition("\n")
    if not first.startswith("version:"):
        raise RuntimeError(f"{path} must start with a 'version: N' line.")
    return TermsOut(version=first.split(":", 1)[1].strip(), text=rest.strip())


def form_errors(errors: list[dict[str, str]]) -> JSONResponse:
    """A 422 in the contract's format; messages never contain submitted values."""
    return JSONResponse(status_code=422, content={"errors": errors})


def api_error(status: int, code: str, message: str, field: str | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "field": field, "message": message}})


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's default handler echoes the submitted input; this one keeps only field and message (research R9).
    return form_errors([_field_error(error) for error in exc.errors()])


def _field_error(error: dict[str, Any]) -> dict[str, str]:
    if error.get("type") == "json_invalid":
        return {"field": "body", "message": "The request body isn't valid JSON."}
    field = ".".join(str(part) for part in error.get("loc", ()) if part != "body") or "body"
    message = str(error.get("msg") or "Invalid value.").removeprefix("Value error, ")
    return {"field": field, "message": message}


def _configure_logging() -> logging.Logger:
    logger = logging.getLogger("kestrel")
    logger.setLevel(logging.INFO)
    if not any(getattr(handler, "_kestrel", False) for handler in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        handler._kestrel = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
    return logger
