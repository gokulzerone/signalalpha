"""The plain-language verdict must never dress an unmeasured factor as a good one."""

from __future__ import annotations

from decisions.verdict import FACTORS, UNMEASURED, build_verdict

BANNED = ("buy", "sell", "target price", "recommendation")


def _verdict(**kw: object):  # type: ignore[no-untyped-def]
    base = dict(
        scores={
            "inflection": 90.0,
            "quality": 70.0,
            "valuation": 80.0,
            "attention_gap": 65.0,
            "risk": 15.0,
        },
        change_sentence="Operating margin rose 587bp against its four-quarter average to 9.3%.",
        readiness_gaps=[],
        liquidity_days_to_exit=1.0,
        base_rate_known=True,
        negative_count=0,
        forensic_flags=[],
    )
    base.update(kw)
    return build_verdict(**base)  # type: ignore[arg-type]


def test_covers_every_factor_and_says_what_each_measures() -> None:
    v = _verdict()
    assert [f.key for f in v.factors] == list(FACTORS)
    assert all(f.measures and f.verdict for f in v.factors)
    assert v.headline == "Strong on all 4 measures that could be checked."
    assert v.strong == 4 and v.checkable == 4


def test_an_unmeasured_factor_is_named_not_scored() -> None:
    v = _verdict(
        scores={
            "inflection": 90.0,
            "quality": None,
            "valuation": 80.0,
            "attention_gap": 65.0,
            "risk": 15.0,
        }
    )
    quality = next(f for f in v.factors if f.key == "quality")
    assert quality.measured is False and quality.value is None and quality.verdict == UNMEASURED
    assert v.checkable == 3, "an unmeasured factor is not counted as checked"
    assert v.headline == "Strong on all 3 measures that could be checked."
    assert any("dash is an unmeasured factor" in c for c in v.caveats)


def test_weak_and_risky_cases_read_plainly() -> None:
    v = _verdict(
        scores={
            "inflection": 0.0,
            "quality": 20.0,
            "valuation": 10.0,
            "attention_gap": 12.0,
            "risk": 85.0,
        }
    )
    assert v.headline == "Weak on all 4 measures that could be checked."
    assert any("almost nothing is changing" in s.lower() for s in v.summary)
    assert any("already be in the price" in s for s in v.summary)
    assert any("risk reads high" in s.lower() for s in v.summary)


def test_caveats_name_every_real_gap() -> None:
    v = _verdict(
        base_rate_known=False,
        negative_count=2,
        forensic_flags=["audit_qualification"],
        liquidity_days_to_exit=16.0,
        readiness_gaps=["Load two more quarters."],
    )
    joined = " ".join(v.caveats)
    assert "one-off" in joined and "2 signal(s) point the other way" in joined
    assert "audit qualification" in joined and "16 trading days" in joined
    assert "Load two more quarters." in v.caveats


def test_verdict_never_uses_trading_language() -> None:
    for scores in (
        {
            "inflection": 95.0,
            "quality": 95.0,
            "valuation": 95.0,
            "attention_gap": 95.0,
            "risk": 2.0,
        },
        {"inflection": 0.0, "quality": None, "valuation": 0.0, "attention_gap": 0.0, "risk": 99.0},
    ):
        v = _verdict(
            scores=scores,
            base_rate_known=False,
            negative_count=3,
            forensic_flags=["related_party_revenue"],
        )
        text = " ".join(
            [v.headline, *v.summary, *v.caveats, *(f.verdict + f.measures for f in v.factors)]
        ).lower()
        for word in BANNED:
            assert word not in text, word


def test_nothing_measurable_says_so() -> None:
    v = _verdict(
        scores={
            "inflection": None,
            "quality": None,
            "valuation": None,
            "attention_gap": None,
            "risk": None,
        }
    )
    assert v.headline == "Nothing here could be measured from the filings on file."
    assert v.checkable == 0


def test_a_concern_is_stated_once_not_twice() -> None:
    """The reading and the readiness checklist overlap; two wordings of one gap read as two."""
    v = _verdict(
        base_rate_known=False,
        liquidity_days_to_exit=8.0,
        readiness_gaps=[
            "Treat this as a one-off: no reliable record of how signals like this played out.",
            "Size any position against daily traded value; exiting may take many days.",
            "Load two more quarters before trusting growth signals.",
        ],
    )
    joined = " ".join(v.caveats).lower()
    assert joined.count("one-off") == 1
    assert sum(1 for c in v.caveats if "traded value" in c or "trading days" in c) == 1
    assert any("two more quarters" in c for c in v.caveats), "a distinct gap is still kept"
