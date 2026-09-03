from __future__ import annotations

from decimal import Decimal

from signals.config import load_catalogue
from signals.detectors.business import (
    auditor_change,
    capacity_expansion,
    credit_rating_downgrade,
    credit_rating_upgrade,
    key_person_exit,
    order_win,
    parse_order_value,
)
from tests.signals.helpers import event, make_ctx, public, qend, quarters

CFG = load_catalogue()


def test_parse_order_value() -> None:
    assert parse_order_value("received an order worth Rs. 1,250.50 crore from X") == (
        Decimal("1250.50"),
        "Rs. 1,250.50 crore",
    )
    assert parse_order_value("orders valued at Rs 45 crore") == (Decimal("45"), "Rs 45 crore")
    assert parse_order_value("no numbers here") is None


def test_order_win_requires_material_value_and_text() -> None:
    q = quarters([100.0] * 4)  # TTM revenue 400
    big = event("announcements", public(qend(3), 50), 901, category="order_win", subject="Order")
    small = event("announcements", public(qend(3), 51), 902, category="order_win", subject="Order")
    no_text = event(
        "announcements", public(qend(3), 52), 903, category="order_win", subject="Order"
    )
    texts = {
        901: "The Company has received an order worth Rs. 120.00 crore from a PSU.",
        902: "The Company has received an order worth Rs. 12.00 crore from a PSU.",
    }
    sigs = order_win(make_ctx(quarters=q, announcements=[big, small, no_text], texts=texts), CFG)
    assert [s.dedupe_key for s in sigs] == [f"announcement:{big.id}"]
    assert (
        sigs[0].parameters["pct_of_ttm_revenue"] == 0.3
        and sigs[0].evidence[0].quote == "Rs. 120.00 crore"
    )
    assert (
        order_win(make_ctx(quarters=q[:2], announcements=[big], texts=texts), CFG) == []
    )  # no TTM revenue


def test_capacity_expansion() -> None:
    a = event(
        "announcements", public(qend(3), 50), 911, category="capacity_expansion", subject="Capacity"
    )
    [sig] = capacity_expansion(
        make_ctx(
            announcements=[a],
            texts={911: "expansion of manufacturing capacity by 40% at the existing facility"},
        ),
        CFG,
    )
    assert (
        sig.parameters["capacity_increase_pct"] == 40 and sig.evidence[0].quote == "capacity by 40%"
    )
    assert (
        capacity_expansion(
            make_ctx(announcements=[a], texts={911: "we plan to expand capacity"}), CFG
        )
        == []
    )


def test_credit_rating_actions() -> None:
    up = event("credit_ratings", public(qend(3), 50), action="upgrade", rating="A-", agency="X")
    down = event(
        "credit_ratings", public(qend(3), 51), action="downgrade", rating="BB+", agency="X"
    )
    same = event(
        "credit_ratings", public(qend(3), 52), action="reaffirmed", rating="BBB", agency="X"
    )
    ctx = make_ctx(ratings=[up, down, same])
    assert [s.dedupe_key for s in credit_rating_upgrade(ctx, CFG)] == [f"rating:{up.id}"]
    assert [s.dedupe_key for s in credit_rating_downgrade(ctx, CFG)] == [f"rating:{down.id}"]


def test_key_person_exit_and_auditor_change() -> None:
    cfo = event(
        "announcements",
        public(qend(3), 50),
        921,
        category="resignation",
        subject="Resignation of Chief Financial Officer",
        summary="",
    )
    clerk = event(
        "announcements",
        public(qend(3), 51),
        922,
        category="resignation",
        subject="Resignation of Company Secretary",
        summary="",
    )
    sigs = key_person_exit(
        make_ctx(
            announcements=[cfo, clerk], texts={921: "Mr X has resigned as Chief Financial Officer."}
        ),
        CFG,
    )
    assert [s.dedupe_key for s in sigs] == [f"announcement:{cfo.id}"] and sigs[0].evidence[
        0
    ].quote == "Chief Financial Officer"

    early = event(
        "announcements",
        public(qend(3), 52),
        931,
        category="auditor_change",
        subject="Resignation of auditor",
        summary="routine=false",
    )
    routine = event(
        "announcements",
        public(qend(3), 53),
        932,
        category="auditor_change",
        subject="Change of auditor",
        summary="",
    )
    texts = {
        931: "The auditors have resigned before completion of their term citing pre-occupation.",
        932: "The auditors retire on completion of their term under mandatory rotation.",
    }
    sigs = auditor_change(make_ctx(announcements=[early, routine], texts=texts), CFG)
    assert [s.dedupe_key for s in sigs] == [f"announcement:{early.id}"]
