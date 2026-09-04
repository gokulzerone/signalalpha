"""The decision layer: turn research output into something a human can act on.

The research modules answer "what changed and is it true". This package answers the three
questions that stand between a reader and a decision:

* **Is this ready to decide on?** :mod:`decisions.readiness` runs a checklist and names what
  is missing, instead of hiding gaps behind a score.
* **What does this actually say, in words?** :mod:`decisions.narrate` renders every signal
  type in plain language from its stored parameters, deterministically.
* **How much of it could I even trade, and what did signals like this do historically?**
  :mod:`decisions.sizing` does the liquidity arithmetic; base rates come from the backtest.

Nothing here recommends a trade. The vocabulary is about research attention (shortlist,
track, pass, needs evidence), and the words buy, sell, target price and recommendation do
not appear in any output (PRD §16).
"""

from decisions.narrate import narrate_signal, narrate_summary
from decisions.readiness import Readiness, ReadinessCheck, assess_readiness
from decisions.sizing import LiquidityProfile, liquidity_profile

__all__ = [
    "LiquidityProfile",
    "Readiness",
    "ReadinessCheck",
    "assess_readiness",
    "liquidity_profile",
    "narrate_signal",
    "narrate_summary",
]
