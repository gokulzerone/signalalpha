"""Agent runtime (PRD §7, §7.1, §8).

Every agent: builds a point-in-time input snapshot, calls the LLM with a strict output
schema, then runs a deterministic post-validator. Claims carry *quotes* of documents the
agent was given; Python locates each quote and creates the evidence record, so the model
can only select spans, never invent them. Outputs are cached by
``(company, agent, as_of, prompt_version, input_hash, model_id)`` and cost is metered
against a per-company daily budget.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.config import PROMPT_DIR, AgentConfig, load_agent_config
from agents.llm import LLMClient, get_client, input_hash
from database.models import AgentRun, Company, DocumentText, ResearchRun, RunStatus
from database.pit import PointInTimeSession
from evidence import (
    Claim,
    ClaimValidationError,
    SpanError,
    create_evidence_from_quote,
    validate_claims,
)
from signals.context import DetectionContext, HistoryLoader

UTC = ZoneInfo("UTC")


class AgentError(Exception):
    pass


class ValidationFailure(AgentError):  # noqa: N818 - domain name used throughout
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


class BudgetExceededError(AgentError):
    pass


class PrerequisiteMissingError(AgentError):
    pass


# ------------------------------------------------------------------ schemas
class Quote(BaseModel):
    """A verbatim passage from one of the documents given to the agent."""

    document_id: int
    quote: str = Field(min_length=8, max_length=800)


class AgentClaim(BaseModel):
    text: str = Field(min_length=1, max_length=1000)
    quotes: list[Quote] = Field(min_length=1)


@dataclass
class DocumentRef:
    id: int
    text: DocumentText
    title: str


@dataclass
class AgentInputs:
    snapshot: dict[str, Any]
    documents: dict[int, DocumentRef] = field(default_factory=dict)
    allowed_numbers: list[float] = field(default_factory=list)


@dataclass
class AgentContext:
    session: Session
    company: Company
    as_of: date
    is_mock: bool
    pit: PointInTimeSession
    ctx: DetectionContext
    client: LLMClient
    config: AgentConfig
    run: ResearchRun | None = None
    outputs: dict[str, AgentRun] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        session: Session,
        company: Company,
        as_of: date,
        *,
        is_mock: bool,
        client: LLMClient | None = None,
        run: ResearchRun | None = None,
        config: AgentConfig | None = None,
    ) -> AgentContext:
        config = config or load_agent_config()
        pit = PointInTimeSession(session, as_of, is_mock=is_mock)
        ctx = HistoryLoader(pit, company).at(pit.as_of)
        return cls(
            session, company, as_of, is_mock, pit, ctx, client or get_client(config), config, run
        )


# ------------------------------------------------------------------ helpers
def _json_default(o: Any) -> Any:
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, datetime | date):
        return o.isoformat()
    raise TypeError(f"not serialisable: {type(o)}")


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=_json_default, sort_keys=True, indent=1)


def collect_numbers(obj: Any, out: list[float] | None = None) -> list[float]:
    out = [] if out is None else out
    if isinstance(obj, bool):
        return out
    if isinstance(obj, int | float | Decimal):
        out.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_numbers(v, out)
    elif isinstance(obj, list | tuple):
        for v in obj:
            collect_numbers(v, out)
    return out


_NUMBER_RE = re.compile(
    r"(?<![\w.])(-?\d[\d,]*(?:\.\d+)?)\s*(%|percent|pp|bp|x|crore|cr\b)?", re.IGNORECASE
)


def numbers_in(text: str) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    for m in _NUMBER_RE.finditer(text):
        raw = m.group(1).replace(",", "")
        try:
            value = float(raw)
        except ValueError:
            continue
        unit = (m.group(2) or "").lower()
        # skip years, small ordinals and period counts
        if unit == "" and (1990 <= value <= 2100 or (value == int(value) and abs(value) < 100)):
            continue
        out.append((value, unit))
    return out


def collect_text_numbers(obj: Any, out: list[float] | None = None) -> list[float]:
    """Numbers mentioned inside validated upstream text (already checked at their source)."""
    out = [] if out is None else out
    if isinstance(obj, str):
        for value, unit in numbers_in(obj):
            out.append(value)
            if unit in ("%", "percent", "pp"):
                out.append(value / 100)
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_text_numbers(v, out)
    elif isinstance(obj, list | tuple):
        for v in obj:
            collect_text_numbers(v, out)
    return out


def check_numbers(text: str, allowed: list[float], tolerance: float) -> list[str]:
    """Every figure in ``text`` must match some structured value within tolerance.
    Percent-style figures may match a fraction x100; basis points a fraction x10000."""
    problems: list[str] = []
    for value, unit in numbers_in(text):
        candidates = {value}
        if unit in ("%", "percent", "pp"):
            candidates.add(value / 100)
        if unit == "bp":
            candidates.add(value / 10_000)
        ok = False
        for cand in candidates:
            for a in allowed:
                if abs(a - cand) <= max(tolerance * abs(a), 0.006):
                    ok = True
                    break
            if ok:
                break
        if not ok:
            problems.append(f"figure {value}{unit} does not match any structured input")
    return problems


class Agent(ABC):
    name: ClassVar[str]
    prompt_version: ClassVar[str] = "v1"
    output_model: ClassVar[type[BaseModel]]
    requires: ClassVar[tuple[str, ...]] = ()

    # -------------------------------------------------------- abstract API
    @abstractmethod
    def build_inputs(self, actx: AgentContext) -> AgentInputs: ...

    @abstractmethod
    def validate(
        self, actx: AgentContext, inputs: AgentInputs, output: BaseModel
    ) -> dict[str, Any]:
        """Return the validated output to store; raise :class:`ValidationFailure` otherwise."""

    # ------------------------------------------------------------ prompt
    def system_prompt(self) -> str:
        return (PROMPT_DIR / f"{self.name}_{self.prompt_version}.md").read_text()

    def user_message(self, inputs: AgentInputs) -> str:
        return dumps({"agent": self.name, **inputs.snapshot})

    # ---------------------------------------------------------- evidence
    def resolve_claims(
        self, actx: AgentContext, inputs: AgentInputs, claims: list[AgentClaim]
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Create evidence for each quote (verified verbatim span) and validate the claims."""
        errors: list[str] = []
        stored: list[dict[str, Any]] = []
        for i, claim in enumerate(claims):
            ids: list[int] = []
            for qt in claim.quotes:
                doc = inputs.documents.get(qt.document_id)
                if doc is None:
                    errors.append(
                        f"claim {i}: document {qt.document_id} was not given to the agent"
                    )
                    continue
                try:
                    ev = create_evidence_from_quote(
                        actx.session,
                        document_text=doc.text,
                        company_id=actx.company.id,
                        quote=qt.quote,
                        created_by=f"agent:{self.name}",
                    )
                except SpanError:
                    errors.append(
                        f"claim {i}: quote not found verbatim in document {qt.document_id}: {qt.quote[:60]!r}"
                    )
                    continue
                ids.append(ev.id)
            if not ids:
                errors.append(f"claim {i}: no verifiable evidence")
                stored.append(
                    {
                        "text": claim.text,
                        "quotes": [q.model_dump() for q in claim.quotes],
                        "evidence_ids": [],
                    }
                )
                continue
            try:
                validate_claims(
                    actx.session,
                    [Claim(text=claim.text, evidence_ids=ids)],
                    company_id=actx.company.id,
                    as_of=actx.pit.as_of,
                    is_mock=actx.is_mock,
                )
            except ClaimValidationError as exc:
                errors.append(f"claim {i}: {exc}")
            stored.append(
                {
                    "text": claim.text,
                    "quotes": [q.model_dump() for q in claim.quotes],
                    "evidence_ids": ids,
                }
            )
        return stored, errors

    # ---------------------------------------------------------------- run
    def spent_today(self, actx: AgentContext) -> Decimal:
        since = datetime.now(tz=UTC) - timedelta(days=1)
        total = actx.session.scalar(
            select(func.coalesce(func.sum(AgentRun.cost_usd), 0)).where(
                AgentRun.company_id == actx.company.id, AgentRun.created_at >= since
            )
        )
        return Decimal(total or 0)

    def cached(self, actx: AgentContext, key: str) -> AgentRun | None:
        return actx.session.scalars(
            select(AgentRun)
            .where(
                AgentRun.company_id == actx.company.id,
                AgentRun.agent_name == self.name,
                AgentRun.as_of == actx.as_of,
                AgentRun.prompt_version == self.prompt_version,
                AgentRun.input_snapshot_hash == key,
                AgentRun.model_id == actx.client.model_id,
                AgentRun.status == RunStatus.COMPLETED,
                AgentRun.validated.is_(True),
                AgentRun.is_mock == actx.is_mock,
            )
            .order_by(AgentRun.id.desc())
        ).first()

    def run(self, actx: AgentContext) -> AgentRun:
        for dep in self.requires:
            if dep not in actx.outputs or not actx.outputs[dep].validated:
                raise PrerequisiteMissingError(f"{self.name} requires a validated {dep} run first")
        inputs = self.build_inputs(actx)
        system = self.system_prompt()
        user = self.user_message(inputs)
        key = input_hash(system, user)
        hit = self.cached(actx, key)
        if hit is not None:
            actx.outputs[self.name] = hit
            return hit
        if self.spent_today(actx) >= Decimal(str(actx.config.daily_budget_usd_per_company)):
            raise BudgetExceededError(f"daily budget exhausted for company {actx.company.id}")
        record = AgentRun(
            research_run_id=actx.run.id if actx.run else None,
            company_id=actx.company.id,
            agent_name=self.name,
            as_of=actx.as_of,
            model_id=actx.client.model_id,
            prompt_version=self.prompt_version,
            input_snapshot_hash=key,
            status=RunStatus.RUNNING,
            validated=False,
            validation_errors=[],
            is_mock=actx.is_mock,
        )
        actx.session.add(record)
        actx.session.flush()
        try:
            response = actx.client.complete(
                system=system,
                user=user,
                output_model=self.output_model,
                max_tokens=actx.config.max_tokens,
            )
            record.tokens_in, record.tokens_out, record.cost_usd = (
                response.tokens_in,
                response.tokens_out,
                response.cost_usd,
            )
            record.model_id = response.model_id
            try:
                parsed = self.output_model.model_validate(response.output)
            except ValidationError as exc:
                raise ValidationFailure(
                    [
                        f"schema: {e['msg']} at {'.'.join(str(x) for x in e['loc'])}"
                        for e in exc.errors()
                    ]
                ) from exc
            record.output = self.validate(actx, inputs, parsed)
            record.validated = True
            record.status = RunStatus.COMPLETED
        except ValidationFailure as exc:
            record.status = RunStatus.FAILED
            record.validation_errors = exc.errors
            record.output = record.output or {"raw": None}
        except AgentError:
            record.status = RunStatus.FAILED
            actx.session.flush()
            raise
        except Exception as exc:  # one agent must not stop the pipeline
            record.status = RunStatus.FAILED
            record.validation_errors = [f"{type(exc).__name__}: {exc}"]
            record.output = record.output or {"raw": None}
        actx.session.flush()
        actx.outputs[self.name] = record
        return record


def signal_summaries(
    actx: AgentContext, families: tuple[str, ...] | None = None, since_days: int = 730
) -> list[dict[str, Any]]:
    cutoff = actx.pit.as_of - timedelta(days=since_days)
    out: list[dict[str, Any]] = []
    for s in actx.pit.signals(actx.company.id):
        if s.public_at <= cutoff or (families and s.family not in families):
            continue
        out.append(
            {
                "signal_id": s.id,
                "signal_type": s.signal_type,
                "family": s.family,
                "direction": s.direction,
                "magnitude": float(s.magnitude),
                "public_at": s.public_at.date().isoformat(),
                "dedupe_key": s.dedupe_key,
                "parameters": s.parameters,
            }
        )
    return out


def document_ref(
    actx: AgentContext, raw_document_id: int, title: str, limit: int | None = None
) -> DocumentRef | None:
    text = actx.pit.document_text(raw_document_id)
    if text is None:
        return None
    return DocumentRef(raw_document_id, text, title)


def snapshot_document(ref: DocumentRef, limit: int) -> dict[str, Any]:
    body = ref.text.text
    return {
        "document_id": ref.id,
        "title": ref.title,
        "text": body[:limit],
        "truncated": len(body) > limit,
    }
