from __future__ import annotations

from decimal import Decimal

from signals.config import load_catalogue
from signals.detectors.ownership import (
    institutional_entry,
    pledge_increase,
    pledge_invocation,
    pledge_reduction,
    promoter_stake_decrease,
    promoter_stake_increase,
    shareholder_count_spike,
)
from tests.signals.helpers import event, holding, make_ctx, public, qend

CFG = load_catalogue()
CR = Decimal(10_000_000)


def test_promoter_stake_increase_and_decrease() -> None:
    up = make_ctx(holdings=[holding(qend(0), 55), holding(qend(1), 56)])
    [sig] = promoter_stake_increase(up, CFG)
    assert sig.parameters["change_pp"] == 1.0 and sig.dedupe_key == qend(1).isoformat()
    assert promoter_stake_decrease(up, CFG) == []
    flat = make_ctx(holdings=[holding(qend(0), 55), holding(qend(1), 55.2)])
    assert promoter_stake_increase(flat, CFG) == [] and promoter_stake_decrease(flat, CFG) == []
    down = make_ctx(holdings=[holding(qend(0), 55), holding(qend(1), 53)])
    [sig] = promoter_stake_decrease(down, CFG)
    assert sig.direction == -1


def test_insider_trades_trigger_stake_signals() -> None:
    buy = event(
        "insider_trades",
        public(qend(1), 5),
        side="buy",
        mode="market",
        category="promoter",
        value_inr=3 * CR,
    )
    small = event(
        "insider_trades",
        public(qend(1), 6),
        side="buy",
        mode="market",
        category="promoter",
        value_inr=Decimal("0.2") * CR,
    )
    off_market = event(
        "insider_trades",
        public(qend(1), 7),
        side="sell",
        mode="off_market",
        category="promoter",
        value_inr=30 * CR,
    )
    sell = event(
        "insider_trades",
        public(qend(1), 8),
        side="sell",
        mode="market",
        category="promoter_group",
        value_inr=5 * CR,
    )
    ctx = make_ctx(insider_trades=[buy, small, off_market, sell])
    ups = promoter_stake_increase(ctx, CFG)
    assert [s.dedupe_key for s in ups] == [f"insider:{buy.id}"]
    downs = promoter_stake_decrease(ctx, CFG)
    assert [s.dedupe_key for s in downs] == [f"insider:{sell.id}"]


def test_pledge_signals() -> None:
    reduce = make_ctx(holdings=[holding(qend(0), pledged=60), holding(qend(1), pledged=30)])
    [sig] = pledge_reduction(reduce, CFG)
    assert sig.direction == 1 and sig.parameters["change_pp"] == -30
    assert pledge_increase(reduce, CFG) == []
    increase = make_ctx(holdings=[holding(qend(0), pledged=10), holding(qend(1), pledged=25)])
    [sig] = pledge_increase(increase, CFG)
    assert sig.direction == -1
    tiny = make_ctx(holdings=[holding(qend(0), pledged=10), holding(qend(1), pledged=12)])
    assert pledge_increase(tiny, CFG) == [] and pledge_reduction(tiny, CFG) == []

    release = event(
        "pledge_events",
        public(qend(1), 3),
        event_type="release",
        pct_of_promoter_holding=Decimal(20),
        pct_of_total_shares=Decimal(11),
    )
    invoke = event(
        "pledge_events",
        public(qend(1), 4),
        event_type="invocation",
        pct_of_promoter_holding=Decimal(5),
        pct_of_total_shares=Decimal("2.5"),
    )
    ctx = make_ctx(pledge_events=[release, invoke])
    assert [s.dedupe_key for s in pledge_reduction(ctx, CFG)] == [f"pledge:{release.id}"]
    [inv] = pledge_invocation(ctx, CFG)
    assert inv.direction == -1 and inv.dedupe_key == f"pledge:{invoke.id}"
    assert pledge_invocation(make_ctx(pledge_events=[release]), CFG) == []


def test_institutional_entry() -> None:
    before = holding(qend(0), holders=[("Old Fund", "fii", 2.0)])
    after = holding(
        qend(1),
        holders=[("Old Fund", "fii", 2.1), ("New Fund", "mutual_fund", 1.5), ("Tiny", "fii", 0.5)],
    )
    sigs = institutional_entry(make_ctx(holdings=[before, after]), CFG)
    assert [s.parameters["holder"] for s in sigs] == ["New Fund"]
    assert (
        institutional_entry(
            make_ctx(holdings=[before, holding(qend(1), holders=[("Old Fund", "fii", 2.2)])]), CFG
        )
        == []
    )
    inst = event(
        "bulk_deals",
        public(qend(1), 2),
        client_name="Kalinga Mutual Fund",
        side="buy",
        value_inr=5 * CR,
    )
    retail = event(
        "bulk_deals", public(qend(1), 2), client_name="Some Person", side="buy", value_inr=5 * CR
    )
    seller = event(
        "bulk_deals", public(qend(1), 2), client_name="Other Fund", side="sell", value_inr=5 * CR
    )
    assert [
        s.dedupe_key for s in institutional_entry(make_ctx(bulk_deals=[inst, retail, seller]), CFG)
    ] == [f"bulk:{inst.id}"]


def test_shareholder_count_spike() -> None:
    [sig] = shareholder_count_spike(
        make_ctx(holdings=[holding(qend(0), retail=10000), holding(qend(1), retail=14000)]), CFG
    )
    assert sig.direction == -1 and abs(sig.parameters["growth"] - 0.4) < 1e-9
    assert (
        shareholder_count_spike(
            make_ctx(holdings=[holding(qend(0), retail=10000), holding(qend(1), retail=11000)]), CFG
        )
        == []
    )
