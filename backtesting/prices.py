"""Price series for backtests: point-in-time loading, corporate-action adjustment,
delisting terminal returns and the equal-weight benchmark."""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from datetime import date, timedelta

from backtesting.config import BacktestConfig
from database.models import Company, CorporateActionType, DelistingKind
from database.pit import PointInTimeSession


@dataclass
class PriceSeries:
    company_id: int
    dates: list[date]
    opens: list[float]
    closes: list[float]
    traded_values: list[float]
    adjustments: list[tuple[date, float]]  # (ex_date, factor): pre-ex prices are divided by factor
    delisted_on: date | None
    delisting_kind: DelistingKind | None

    def index_on_or_after(self, d: date) -> int | None:
        i = bisect.bisect_left(self.dates, d)
        return i if i < len(self.dates) else None

    def index_on_or_before(self, d: date) -> int | None:
        i = bisect.bisect_right(self.dates, d) - 1
        return i if i >= 0 else None

    def factor_between(self, start: date, end: date) -> float:
        """Product of adjustment factors for actions with ``start < ex_date <= end``."""
        f = 1.0
        for ex, factor in self.adjustments:
            if start < ex <= end:
                f *= factor
        return f

    def adv(self, before: date, window: int) -> float | None:
        i = self.index_on_or_before(before)
        if i is None:
            return None
        window_values = self.traded_values[max(0, i - window + 1) : i + 1]
        return sum(window_values) / len(window_values) if window_values else None

    def adjusted_closes(self) -> list[float]:
        """Backward-adjusted close series (all known actions applied)."""
        out = list(self.closes)
        for ex, factor in self.adjustments:
            cut = bisect.bisect_left(self.dates, ex)
            for i in range(cut):
                out[i] /= factor
        return out


def action_factor(
    action_type: CorporateActionType, num: int | None, den: int | None
) -> float | None:
    if num is None or den is None or den <= 0:
        return None
    if action_type is CorporateActionType.BONUS:
        return (num + den) / den  # 1:1 bonus doubles the share count
    if action_type is CorporateActionType.SPLIT:
        return num / den  # old face value / new face value
    return None


def load_series(pit: PointInTimeSession, company: Company, start: date) -> PriceSeries:
    rows = pit.prices(company.id, start)
    adjustments: list[tuple[date, float]] = []
    for ca in pit.corporate_actions(company.id):
        f = action_factor(ca.action_type, ca.ratio_numerator, ca.ratio_denominator)
        if f is not None and f != 1.0:
            adjustments.append((ca.ex_date, f))
    adjustments.sort()
    return PriceSeries(
        company_id=company.id,
        dates=[r.trade_date for r in rows],
        opens=[float(r.open) for r in rows],
        closes=[float(r.close) for r in rows],
        traded_values=[float(r.traded_value) for r in rows],
        adjustments=adjustments,
        delisted_on=company.delisted_on,
        delisting_kind=company.delisting_kind,
    )


@dataclass(frozen=True)
class Leg:
    entry_date: date
    entry_price: float
    exit_date: date
    exit_price: float
    gross_return: float
    terminal: bool


def forward_leg(
    series: PriceSeries, public_date: date, horizon_days: int, as_of: date, config: BacktestConfig
) -> Leg | None:
    """Entry at the next trading day's open after ``public_date``; exit at the close on or
    after ``entry + horizon``. Delisting inside the window applies the terminal return.
    Returns ``None`` when the window is not yet complete at ``as_of``."""
    i = series.index_on_or_after(public_date + timedelta(days=1))
    if i is None:
        return None
    entry_date, entry_price = series.dates[i], series.opens[i]
    target = entry_date + timedelta(days=horizon_days)
    if target > as_of:
        return None
    j = series.index_on_or_after(target)
    if j is None:
        if series.delisted_on is not None and series.delisted_on <= target:
            if series.delisting_kind is DelistingKind.COMPULSORY:
                terminal = config.terminal_returns.compulsory
                last = series.dates[-1]
                return Leg(
                    entry_date, entry_price, last, entry_price * (1 + terminal), terminal, True
                )
            last_close = series.closes[-1] * series.factor_between(entry_date, series.dates[-1])
            return Leg(
                entry_date,
                entry_price,
                series.dates[-1],
                last_close,
                last_close / entry_price - 1,
                True,
            )
        return None
    exit_date = series.dates[j]
    exit_price = series.closes[j] * series.factor_between(entry_date, exit_date)
    return Leg(entry_date, entry_price, exit_date, exit_price, exit_price / entry_price - 1, False)


class Benchmark:
    """Equal-weight return of the index's historical constituents over a window."""

    def __init__(
        self,
        pit: PointInTimeSession,
        index_name: str,
        series: dict[int, PriceSeries],
        config: BacktestConfig,
    ) -> None:
        self.pit = pit
        self.index_name = index_name
        self.series = series
        self.config = config
        self._members: dict[date, list[int]] = {}
        self._cache: dict[tuple[date, int], float | None] = {}

    def members(self, on: date) -> list[int]:
        if on not in self._members:
            self._members[on] = self.pit.index_constituents(self.index_name, on)
        return self._members[on]

    def forward_return(self, public_date: date, horizon_days: int) -> float | None:
        key = (public_date, horizon_days)
        if key not in self._cache:
            rets: list[float] = []
            for cid in self.members(public_date):
                s = self.series.get(cid)
                if s is None:
                    continue
                leg = forward_leg(s, public_date, horizon_days, self.pit.as_of_date, self.config)
                if leg is not None:
                    rets.append(leg.gross_return)
            self._cache[key] = sum(rets) / len(rets) if rets else None
        return self._cache[key]
