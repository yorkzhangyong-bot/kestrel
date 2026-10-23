"""Pydantic models for every boundary: line store entities, tool I/O and model-output schemas.

Field names and constraints follow specs/001-packing-list-check/data-model.md.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, computed_field, model_validator

CODE_PATTERN = r"^\d{4}\.\d{2}$"
CODE_RE = re.compile(CODE_PATTERN)


def now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- enums
class FlagKind(str, Enum):
    ok = "ok"
    vague = "vague"
    stop_word = "stop_word"


class RuleSource(str, Enum):
    firm_stop_words = "firm_stop_words"
    ics2_unacceptable = "ics2_unacceptable"
    ics2_stop_words = "ics2_stop_words"
    judgement = "judgement"


class Route(str, Enum):
    auto_accept = "auto_accept"
    review = "review"
    ask_shipper = "ask_shipper"


class DecisionRoute(str, Enum):
    accepted = "accepted"
    review = "review"
    ask_shipper = "ask_shipper"


class ChosenHow(str, Enum):
    auto = "auto"
    top = "top"
    other_candidate = "other_candidate"
    typed = "typed"


class LineStatus(str, Enum):
    pending = "pending"
    checked = "checked"
    failed = "failed"


class CreatedBy(str, Enum):
    file = "file"
    paste = "paste"
    sample = "sample"
    shipper_reply = "shipper_reply"


class Actor(str, Enum):
    routing_rule = "routing_rule"
    threshold_change = "threshold_change"
    clerk = "clerk"
    shipper_reply = "shipper_reply"
    system = "system"


class ChangeKind(str, Enum):
    route_computed = "route_computed"
    threshold_recomputed = "threshold_recomputed"
    clerk_decision = "clerk_decision"
    code_decided = "code_decided"
    reply_applied = "reply_applied"
    version_added = "version_added"
    line_failed = "line_failed"


class SourceKind(str, Enum):
    nomenclature = "nomenclature"
    bti = "bti"
    ics2_rule = "ics2_rule"
    firm_rule = "firm_rule"
    shipper_history = "shipper_history"


class RetrievalMode(str, Enum):
    hybrid = "hybrid"
    vector_only = "vector_only"


# --------------------------------------------------------------------------- value objects
class Money(BaseModel):
    amount: Decimal
    currency: str = "USD"


class ShipperRef(BaseModel):
    name: str = "New shipper"
    known: bool = False
    past_shipment_count: int = 0


class SourceFile(BaseModel):
    name: str
    size_bytes: int
    kind: str


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    cost_eur: float = 0.0
    calls: int = 0

    def add(self, other: "Usage") -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens
        self.cost_usd += other.cost_usd
        self.cost_eur += other.cost_eur
        self.calls += other.calls


class Precedent(BaseModel):
    reference: str
    member_state: str = ""
    code: str = ""
    description: str = ""
    reasoning: str = ""
    valid_from: date | None = None
    valid_to: date | None = None
    url: str | None = None
    language: str = ""


class Source(BaseModel):
    id: str
    kind: SourceKind
    title: str
    excerpt: str = ""


class Candidate(BaseModel):
    code: str = Field(pattern=CODE_PATTERN)
    subheading_text: str = ""
    confidence: int = Field(ge=0, le=100, strict=True)
    rationale: str = ""
    history_only: bool = False
    source_ids: list[str] = Field(default_factory=list)
    precedent: Precedent | None = None

    @computed_field  # type: ignore[misc]
    @property
    def chapter(self) -> str:
        return self.code[:2]


class Flag(BaseModel):
    kind: FlagKind
    rule_source: RuleSource | None = None
    matched_term: str | None = None
    reason: str = ""
    ask_for: list[str] = Field(default_factory=list)
    pure_stop_word: bool = False
    source_doc: str | None = None


class Extracted(BaseModel):
    material: str = ""
    part_name: str = ""
    use: str = ""


class RetrievalTrace(BaseModel):
    original: str = ""
    queries: list[str] = Field(default_factory=list)
    chapter_filter: list[str] | None = None
    filter_reason: str = ""
    bm25_hits: int = 0
    vector_hits: int = 0
    fused: int = 0
    sent_to_model: int = 0
    history_chunks: int = 0
    precedent_chunks: int = 0                                  # chunks added because a BTI ruling pointed at their code
    precedent_codes: list[str] = Field(default_factory=list)   # codes proposed by matching rulings (≤ 3)
    mode: RetrievalMode = RetrievalMode.hybrid


class Decision(BaseModel):
    route: DecisionRoute
    decided_code: str | None = Field(default=None, pattern=CODE_PATTERN)
    chosen_how: ChosenHow | None = None
    by: Literal["clerk"] = "clerk"
    at: datetime = Field(default_factory=now)

    @model_validator(mode="after")
    def _accepted_needs_code(self) -> "Decision":
        if self.route == DecisionRoute.accepted and not self.decided_code:
            raise ValueError("an accepted decision needs a decided_code")
        return self


class LineVersion(BaseModel):
    version_no: int = 1
    created_at: datetime = Field(default_factory=now)
    created_by: CreatedBy = CreatedBy.file
    text_zh: str = ""
    text_en: str = ""
    truncated: bool = False
    unreadable: bool = False
    reply_text: str | None = None
    extracted: Extracted | None = None
    flag: Flag | None = None
    candidates: list[Candidate] = Field(default_factory=list)
    no_valid_candidate: bool = False
    precedents_checked: bool = False
    retrieval_trace: RetrievalTrace | None = None
    sources: list[Source] = Field(default_factory=list)
    status: LineStatus = LineStatus.pending
    error_reason: str | None = None
    computed_route: Route = Route.review
    route_reason: str = ""
    decision: Decision | None = None
    contradiction_note: str | None = None

    @property
    def top_confidence(self) -> int | None:
        return self.candidates[0].confidence if self.candidates else None

    @property
    def top_code(self) -> str | None:
        return self.candidates[0].code if self.candidates else None

    @property
    def display_text(self) -> str:
        parts = [t for t in (self.text_zh, self.text_en) if t]
        return " / ".join(parts)


class Line(BaseModel):
    line_no: int = Field(ge=1)
    source_ref: str = ""
    qty: str | None = None
    weight_kg: float | None = None
    volume_cbm: float | None = None
    value: Money | None = None
    versions: list[LineVersion] = Field(default_factory=list)

    @property
    def current(self) -> LineVersion:
        return self.versions[-1]

    @property
    def ever_flagged(self) -> bool:
        return any(v.flag is not None and v.flag.kind != FlagKind.ok for v in self.versions)


class CheckStep(BaseModel):
    tool: str
    summary: str = ""
    started_at: datetime = Field(default_factory=now)
    elapsed_s: float = 0.0
    ok: bool = True
    run_by: Literal["agent", "app"] = "agent"


class CheckRun(BaseModel):
    id: str
    started_at: datetime = Field(default_factory=now)
    elapsed_s: float = 0.0
    line_count: int = 0
    steps: list[CheckStep] = Field(default_factory=list)
    tool_calls: int = 0


class DecisionRecord(BaseModel):
    at: datetime = Field(default_factory=now)
    line_no: int
    version_no: int
    change: ChangeKind
    previous: str | None = None
    new: str | None = None
    actor: Actor
    note: str | None = None


class Shipment(BaseModel):
    id: str
    reference: str = ""
    shipper: ShipperRef = Field(default_factory=ShipperRef)
    filing_type: Literal["ics2_house_ens"] = "ics2_house_ens"
    threshold: int = Field(default=85, ge=60, le=99)
    ask_floor: int = Field(default=50, ge=0, le=100)
    hybrid_search: bool = True
    source: SourceFile | None = None
    origin: str | None = None
    destination: str | None = None
    mode: str | None = None
    created_at: datetime = Field(default_factory=now)
    usage: Usage = Field(default_factory=Usage)
    lines: list[Line] = Field(default_factory=list)
    audit: list[DecisionRecord] = Field(default_factory=list)
    check_runs: list[CheckRun] = Field(default_factory=list)


# --------------------------------------------------------------------------- knowledge base records
class NomenclatureChunk(BaseModel):
    id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    ranks: dict[str, int] = Field(default_factory=dict)

    @property
    def code(self) -> str:
        return self.metadata.get("subheading", self.id.split(":", 1)[-1])


class RuleEntry(BaseModel):
    term: str
    lang: str = "en"
    acceptable_example: str | None = None
    category: str | None = None
    implementation_date: str | None = None


class RuleList(BaseModel):
    list: str
    source_doc: str = ""
    source_date: str = ""
    note: str | None = None
    entries: list[RuleEntry] = Field(default_factory=list)


class Alias(BaseModel):
    alias: str
    lang: str
    term: str


class PastShipment(BaseModel):
    reference: str
    date: str
    codes: list[str] = Field(default_factory=list)


class ShipperProfile(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    past_shipments: list[PastShipment] = Field(default_factory=list)

    @property
    def history_codes(self) -> list[str]:
        seen: list[str] = []
        for s in self.past_shipments:
            for c in s.codes:
                if c not in seen:
                    seen.append(c)
        return seen


# --------------------------------------------------------------------------- tool I/O
class ParsedLine(BaseModel):
    line_no: int = 0
    text_zh: str = ""
    text_en: str = ""
    qty: str | None = None
    weight_kg: float | None = None
    volume_cbm: float | None = None
    value: Money | None = None
    source_ref: str = ""
    truncated: bool = False
    unreadable: bool = False


class ParsePackingListOutput(BaseModel):
    lines: list[ParsedLine] = Field(default_factory=list)
    sheet: str | None = None
    header_row: int | None = None
    skipped_rows: int = 0
    shipper_name_detected: str | None = None
    meta: dict[str, str | None] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class DescriptionCheck(BaseModel):
    line_no: int
    flag: Flag | None = None
    status: LineStatus = LineStatus.checked
    error_reason: str | None = None


class Classification(BaseModel):
    line_no: int
    candidates: list[Candidate] = Field(default_factory=list)
    no_valid_candidate: bool = False
    retrieval_trace: RetrievalTrace | None = None
    sources: list[Source] = Field(default_factory=list)
    status: LineStatus = LineStatus.checked
    error_reason: str | None = None


class LookupPrecedentOutput(BaseModel):
    by_code: dict[str, list[Precedent]] = Field(default_factory=dict)
    none_found: list[str] = Field(default_factory=list)


class ApplyReplyOutput(BaseModel):
    needs_line: bool = False
    target_line_no: int | None = None
    applied_to_selected: bool = False
    new_version_no: int | None = None
    extracted: Extracted | None = None
    contradiction_note: str | None = None


# --------------------------------------------------------------------------- model-output schemas
class JudgementOut(BaseModel):
    vague: bool
    missing: list[Literal["material", "product_name", "use"]] = Field(default_factory=list)
    reason: str = ""


class TranslateOut(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=5)
    hyde: str | None = None


class RankCandidate(BaseModel):
    code: str = Field(pattern=CODE_PATTERN)
    confidence: int = Field(ge=0, le=100, strict=True)
    rationale: str = Field(min_length=1)
    history_only: bool = False


class RankOut(BaseModel):
    candidates: list[RankCandidate] = Field(default_factory=list, max_length=3)


class ExtractOut(BaseModel):
    material: str = ""
    part_name: str = ""
    use: str = ""
