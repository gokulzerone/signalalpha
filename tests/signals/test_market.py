from __future__ import annotations

from datetime import date, timedelta

from signals.config import load_catalogue
from signals.detectors.market import (
    delivery_volume_shift,
    price_lagging_fundamentals,
    surveillance_entry,
    surveillance_exit,
)
from tests.signals.helpers import IST, bars, event, make_ctx, public, qend

CFG = load_catalogue()


def test_delivery_volume_shift_fires_once_when_condition_appears() -> None:
    quiet = bars(120)
    assert delivery_volume_shift(make_ctx(prices=quiet), CFG) == []
    shifted = bars(120, tail=10, tail_value_mult=8, tail_delivery_add=40)  # last two weeks jump
    [sig] = delivery_volume_shift(make_ctx(prices=shifted), CFG)
    assert sig.direction == 1 and sig.parameters["value_uplift"] > 0.2
    ongoing = bars(120, tail=40, tail_value_mult=8, tail_delivery_add=30)  # already true a week ago
    assert delivery_volume_shift(make_ctx(prices=ongoing), CFG) == []


def test_surveillance_events() -> None:
    entry = event(
        "surveillance_events", public(qend(3), 5), framework="asm", event="entry", stage=1
    )
    exit_ = event(
        "surveillance_events", public(qend(3), 60), framework="asm", event="exit", stage=None
    )
    ctx = make_ctx(surveillance=[entry, exit_])
    assert [s.direction for s in surveillance_entry(ctx, CFG)] == [-1]
    assert [s.direction for s in surveillance_exit(ctx, CFG)] == [1]


def test_price_lagging_fundamentals() -> None:
    flat = bars(120, start=date(2024, 1, 1))
    as_of = flat[-1].public_at
    trigger = ("revenue_acceleration", as_of - timedelta(days=10))
    lagging = make_ctx(prices=flat, sector_change=0.25, prior_signals=[trigger], as_of=as_of)
    [sig] = price_lagging_fundamentals(lagging, CFG)
    assert (
        sig.parameters["gap"] == 0.25 and sig.parameters["trigger_signal"] == "revenue_acceleration"
    )
    assert (
        price_lagging_fundamentals(
            make_ctx(prices=flat, sector_change=-0.1, prior_signals=[trigger], as_of=as_of), CFG
        )
        == []
    )
    assert (
        price_lagging_fundamentals(make_ctx(prices=flat, sector_change=0.25, as_of=as_of), CFG)
        == []
    )
    stale = ("margin_inflection", as_of - timedelta(days=200))
    assert (
        price_lagging_fundamentals(
            make_ctx(prices=flat, sector_change=0.25, prior_signals=[stale], as_of=as_of), CFG
        )
        == []
    )
    assert as_of.tzinfo == IST
