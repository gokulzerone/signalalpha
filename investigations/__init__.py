"""Top-down investigation: world conditions, then India, then one listed company.

The chain runs in the direction a macro-led investor works: what is happening in the world,
what that changes, where supply and demand move, which listed Indian company sits in the path
of it, and then what that company's own filings say about value, fundamentals and threats.

Two rules keep it honest. The macro stages read the open web and every claim they make carries
the page it came from; the company stages read only filings already ingested here, and their
numbers are computed in Python. A company is never invented: it is chosen from the companies
this system actually covers, so everything said about it can be checked.
"""

from investigations.runner import STAGES, run_investigation, start_investigation

__all__ = ["STAGES", "run_investigation", "start_investigation"]
