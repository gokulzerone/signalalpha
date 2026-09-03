"""Point-in-time backtester (PRD §11).

Signals are already timestamped at their filing's ``public_at``; scores are recomputed at
each rebalance date from data public at that date. Entry is the next trading day's open,
costs come from the execution model, delisted companies get their terminal return, and the
benchmark is the equal-weight return of the index's historical constituents.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from backtesting.config import BacktestConfig, load_backtest_config
from backtesting.execution import estimate
from backtesting.prices import Benchmark, PriceSeries, forward_leg, load_series
from backtesting.stats import EventStats, PortfolioStats, event_stats, portfolio_stats
from database.models import BacktestRun, Company, ScorePerformance, Signal, SignalPerformance
from database.pit import PointInTimeSession, end_of_day
from scoring.config import ScoreConfig, load_score_config
from scoring.inputs import compute_universe_inputs
from scoring.pipeline import score_universe
from signals.config import load_catalogue


@dataclass
class Event:
    kind: str  # "signal" | "score"
    subject: str  # signal_type or score_type
    bucket: int  # signal: 0 ; score: decile 1..10
    company_id: int
    public_date: date
    magnitude: float
    ref_id: int | None = None


@dataclass
class EventResult:
    event: Event
    horizon_days: int
    entry_date: date
    exit_date: date
    gross_return: float
    net_return: float
    benchmark_return: float
    excess: float
    round_trip_cost: float
    position_cap_inr: float | None
    terminal: bool


@dataclass
class GroupReport:
    kind: str
    subject: str
    bucket: int
    horizon_days: int
    events: EventStats
    portfolio: PortfolioStats
    low_sample: bool
    decay: dict[str, float | None] = field(default_factory=dict)

    def stats_json(self) -> dict[str, Any]:
        return {**self.events.to_json(), **self.portfolio.to_json(), "decay": self.decay}


@dataclass
class BacktestReport:
    run_id: int | None
    as_of: date
    groups: list[GroupReport]
    n_events: int

    def group(self, kind: str, subject: str, horizon: int, bucket: int = 0) -> GroupReport | None:
        return next(
            (
                g
                for g in self.groups
                if g.kind == kind
                and g.subject == subject
                and g.horizon_days == horizon
                and g.bucket == bucket
            ),
            None,
        )


class Backtester:
    def __init__(
        self,
        session: Session,
        *,
        as_of: datetime | date,
        is_mock: bool,
        config: BacktestConfig | None = None,
        score_config: ScoreConfig | None = None,
    ) -> None:
        self.session = session
        self.config = config or load_backtest_config()
        self.score_config = score_config or load_score_config()
        self.pit = PointInTimeSession(session, as_of, is_mock=is_mock)
        self.is_mock = is_mock
        self.companies: dict[int, Company] = {c.id: c for c in self.pit.companies()}
        self.series: dict[int, PriceSeries] = {}
        self.benchmark: Benchmark | None = None
        self._universe_cache: dict[date, dict[int, tuple[bool, bool]]] = {}

    # -------------------------------------------------------------- data
    def _load(self, start: date) -> None:
        for cid, company in self.companies.items():
            self.series[cid] = load_series(self.pit, company, start)
        names = self.config.benchmarks["mock" if self.is_mock else "live"]
        self.benchmark = Benchmark(self.pit, names[0], self.series, self.config)

    def _eligible(self, company_id: int, on: date) -> bool:
        """In the versioned universe on ``on`` (listed, in the cap band) and liquid unless
        the configuration includes illiquid names."""
        if on not in self._universe_cache:
            snaps = self.pit.universe(on)
            self._universe_cache[on] = {s.company_id: (s.in_universe, s.is_illiquid) for s in snaps}
        info = self._universe_cache[on].get(company_id)
        if info is None:
            return False
        in_universe, illiquid = info
        return in_universe and (self.config.include_illiquid or not illiquid)

    # ------------------------------------------------------------ events
    def signal_events(self, since: date | None = None) -> list[Event]:
        stmt = select(Signal).where(
            Signal.is_mock == self.is_mock, Signal.public_at <= self.pit.as_of
        )
        if since is not None:
            stmt = stmt.where(Signal.public_at > end_of_day(since))
        events: list[Event] = []
        for s in self.session.scalars(stmt.order_by(Signal.public_at)).all():
            if s.company_id not in self.companies:
                continue
            events.append(
                Event(
                    "signal",
                    s.signal_type,
                    0,
                    s.company_id,
                    s.public_at.astimezone(self.pit.as_of.tzinfo).date(),
                    float(s.magnitude),
                    s.id,
                )
            )
        return events

    def score_events(self, rebalance_dates: list[date]) -> list[Event]:
        events: list[Event] = []
        deciles = self.config.score_deciles
        for on in rebalance_dates:
            universe = compute_universe_inputs(
                self.session, as_of=on, is_mock=self.is_mock, config=self.score_config
            )
            results = score_universe(universe, self.score_config)
            for score_type in (
                "inflection",
                "quality",
                "valuation",
                "risk",
                "attention_gap",
                "opportunity",
            ):
                ranked = sorted(
                    (
                        (r[score_type].value, cid)
                        for cid, r in results.items()
                        if r[score_type].value is not None
                    ),
                    key=lambda x: (x[0], x[1]),
                )
                n = len(ranked)
                for i, (value, cid) in enumerate(ranked):
                    assert value is not None
                    decile = min(deciles, int(i * deciles / n) + 1) if n else 1
                    events.append(Event("score", score_type, decile, cid, on, value))
        return events

    # ----------------------------------------------------------- evaluate
    def evaluate(self, events: list[Event]) -> list[EventResult]:
        assert self.benchmark is not None
        out: list[EventResult] = []
        for ev in events:
            series = self.series.get(ev.company_id)
            if series is None or not self._eligible(ev.company_id, ev.public_date):
                continue
            for h in self.config.horizons_days:
                leg = forward_leg(series, ev.public_date, h, self.pit.as_of_date, self.config)
                if leg is None:
                    continue
                bench = self.benchmark.forward_return(ev.public_date, h)
                if bench is None:
                    continue
                exe = estimate(series, leg.entry_date, self.config.execution)
                net = (1 + leg.gross_return) * (1 - exe.round_trip_cost) - 1
                out.append(
                    EventResult(
                        ev,
                        h,
                        leg.entry_date,
                        leg.exit_date,
                        leg.gross_return,
                        net,
                        bench,
                        net - bench,
                        exe.round_trip_cost,
                        exe.position_cap_inr,
                        leg.terminal,
                    )
                )
        return out

    # ------------------------------------------------------------ reports
    def report(self, results: list[EventResult]) -> list[GroupReport]:
        groups: dict[tuple[str, str, int, int], list[EventResult]] = defaultdict(list)
        for r in results:
            groups[(r.event.kind, r.event.subject, r.event.bucket, r.horizon_days)].append(r)
        reports: list[GroupReport] = []
        means: dict[tuple[str, str, int], dict[str, float | None]] = defaultdict(dict)
        for (kind, subject, bucket, h), rs in groups.items():
            es = event_stats(
                [r.net_return for r in rs],
                [r.excess for r in rs],
                [r.event.magnitude for r in rs] if kind == "signal" else None,
            )
            means[(kind, subject, bucket)][str(h)] = es.mean_excess
            reports.append(
                GroupReport(
                    kind, subject, bucket, h, es, self._portfolio(rs), es.n < self.config.min_sample
                )
            )
        for rep in reports:
            rep.decay = dict(
                sorted(
                    means[(rep.kind, rep.subject, rep.bucket)].items(), key=lambda kv: int(kv[0])
                )
            )
        reports.sort(key=lambda g: (g.kind, g.subject, g.bucket, g.horizon_days))
        return reports

    def _portfolio(self, rs: list[EventResult]) -> PortfolioStats:
        """Equal-weight portfolio of the group's positions, rebalanced across open positions
        daily, with per-position weight capped by the liquidity cap."""
        if not rs:
            return portfolio_stats([], [], [])
        capital = self.config.execution.portfolio_capital_cr * 1e7
        day_set: set[date] = set()
        adjusted: dict[int, list[float]] = {}
        for r in rs:
            s = self.series[r.event.company_id]
            if r.event.company_id not in adjusted:
                adjusted[r.event.company_id] = s.adjusted_closes()
            i0 = s.index_on_or_after(r.entry_date)
            i1 = s.index_on_or_before(r.exit_date)
            if i0 is None or i1 is None:
                continue
            day_set.update(s.dates[i0 : i1 + 1])
        days = sorted(day_set)
        if not days:
            return portfolio_stats([], [], [])
        daily_ret: list[float] = []
        daily_cost: list[float] = []
        daily_turn: list[float] = []
        open_positions: list[EventResult] = []
        for d in days:
            open_positions = [r for r in rs if r.entry_date <= d <= r.exit_date]
            n_open = len(open_positions)
            ret = 0.0
            cost = 0.0
            turn = 0.0
            for r in open_positions:
                w = 1.0 / n_open
                if r.position_cap_inr is not None:
                    w = min(w, r.position_cap_inr / capital)
                s = self.series[r.event.company_id]
                adj = adjusted[r.event.company_id]
                i = s.index_on_or_before(d)
                if i is None or s.dates[i] != d:
                    continue
                if d == r.entry_date:
                    day_r = (
                        adj[i] / (s.opens[i] / (s.closes[i] / adj[i])) - 1 if s.closes[i] else 0.0
                    )
                    cost += w * r.round_trip_cost / 2
                    turn += w
                elif i > 0:
                    day_r = adj[i] / adj[i - 1] - 1
                else:
                    day_r = 0.0
                if d == r.exit_date:
                    cost += w * r.round_trip_cost / 2
                    turn += w
                    if r.terminal:
                        day_r = r.gross_return if r.gross_return <= -1 else day_r
                ret += w * day_r
            daily_ret.append(ret)
            daily_cost.append(cost)
            daily_turn.append(turn)
        return portfolio_stats(daily_ret, daily_cost, daily_turn)

    # ---------------------------------------------------------------- run
    def run(
        self,
        *,
        since: date | None = None,
        score_dates: list[date] | None = None,
        persist: bool = True,
    ) -> BacktestReport:
        earliest = min([since or date(1990, 1, 1), *(score_dates or [])])
        self._load(earliest - timedelta(days=30))
        events = self.signal_events(since)
        if score_dates:
            events += self.score_events(score_dates)
        results = self.evaluate(events)
        groups = self.report(results)
        run_id: int | None = None
        if persist:
            run_id = self._persist(groups, since, score_dates)
        return BacktestReport(run_id, self.pit.as_of_date, groups, len(results))

    def _persist(
        self, groups: list[GroupReport], since: date | None, score_dates: list[date] | None
    ) -> int:
        run = BacktestRun(
            as_of=self.pit.as_of_date,
            config_version=self.config.version,
            signal_config_version=load_catalogue().version,
            score_config_version=self.score_config.version,
            parameters={
                "since": since.isoformat() if since else None,
                "score_dates": [d.isoformat() for d in score_dates or []],
                "horizons": self.config.horizons_days,
                "include_illiquid": self.config.include_illiquid,
            },
            is_mock=self.is_mock,
        )
        self.session.add(run)
        self.session.flush()
        for g in groups:
            if g.kind == "signal":
                self.session.add(
                    SignalPerformance(
                        backtest_run_id=run.id,
                        signal_type=g.subject,
                        decile=g.bucket,
                        horizon_days=g.horizon_days,
                        config_version=self.config.version,
                        n=g.events.n,
                        low_sample=g.low_sample,
                        stats=g.stats_json(),
                        is_mock=self.is_mock,
                    )
                )
            else:
                self.session.add(
                    ScorePerformance(
                        backtest_run_id=run.id,
                        score_type=g.subject,
                        decile=g.bucket,
                        horizon_days=g.horizon_days,
                        config_version=self.config.version,
                        n=g.events.n,
                        low_sample=g.low_sample,
                        stats=g.stats_json(),
                        is_mock=self.is_mock,
                    )
                )
        run.finished_at = datetime.now(tz=self.pit.as_of.tzinfo)
        self.session.flush()
        return run.id


def month_ends(start: date, end: date, step_months: int = 1) -> list[date]:
    out: list[date] = []
    d = start
    while d <= end:
        nxt = (d.replace(day=1) + timedelta(days=32)).replace(day=1)
        month_end = nxt - timedelta(days=1)
        if month_end <= end and month_end >= start:
            out.append(month_end)
        d = nxt
    return out[::step_months]


def run_backtest(
    session: Session,
    *,
    as_of: datetime | date,
    is_mock: bool,
    since: date | None = None,
    score_dates: list[date] | None = None,
    config: BacktestConfig | None = None,
) -> BacktestReport:
    return Backtester(session, as_of=as_of, is_mock=is_mock, config=config).run(
        since=since, score_dates=score_dates
    )
