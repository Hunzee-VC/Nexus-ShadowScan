"""Suite-size tripwires: a broken or partial install must not report green (audit F12).

The suite silently shrank before anyone noticed: the HEAD commit claims
27,621 passed / 73 skipped (27,697 collected, pytest 9.2.0, CPython 3.13,
xdist), while the clean re-run at the same HEAD collected 27,672 with 174
skips -- a 101-skip swing with no test to see it. 54 ``importorskip`` sites,
61 ``skipif`` and 28 ``pytest.skip`` sites mean a partial install can skip
hundreds of tests and still pass.

Reference numbers (all at HEAD ``d8f4e585``):

- 2026-11-09 clean re-run (Python 3.12.3, serial, full clone + tags,
  benchmark-suite submodule at ``1ce0eee3``): **27,672 collected, 174
  skipped, 3 xfailed**, from ``~/workspace/test-tmp-shadowscan-clean/pytest2.log``.
- HEAD commit claim (Python 3.13, xdist, local run, no CI run cited):
  **27,697 collected, 73 skipped** -- 25 more collected than either
  November run, so collection varies by interpreter and platform
  (Darwin-only tests, git-version gates, SDK ``importorskip``).
- Measured while writing this file (Python 3.12.3, this venv, which has no
  cloud SDKs): **27,669 collected**, 193 items carrying ``skip``/``skipif``
  markers. The 3-test gap against the November figure is unexplained and
  immaterial at these bounds; if the lower bound ever trips by a few tests,
  re-measure on the full-install configuration before loosening it.

Bounds are deliberately generous. They are a tripwire for silent shrinkage
or accidental growth, not a ratchet: update them deliberately, with the new
reference run named in the commit message, never by widening them to make a
failing run pass.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# Full-install reference: 27,672 collected (2026-11-09), 27,697 claimed on
# 3.13. The floor allows ~670 fewer (missing cloud SDKs, git < 2.45,
# platform gates); the ceiling allows growth plus the 3.13 variance.
MIN_COLLECTED = 27_000
MAX_COLLECTED = 28_500
# 193 skip/skipif-marked items measured; headroom for new conditional tests.
MAX_SKIP_MARKED = 300

_COLLECTED = re.compile(r"(?m)^(\d+) tests? collected")


@pytest.mark.slow
def test_suite_collection_stays_within_bounds() -> None:
    """Re-collect the whole suite and check the total has not silently shrunk.

    A subprocess collection is used instead of the running session's items:
    it measures the full suite whatever the outer run selected, and it works
    the same under xdist as serially. It re-collects rather than re-running,
    so it costs about a minute, not an hour -- hence the ``slow`` marker, so
    ``make test-fast`` skips it.
    """
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-p",
            "no:cacheprovider",
            "tests",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    match = _COLLECTED.search(completed.stdout)
    assert match is not None, (
        "could not read a collected total from the collection run "
        f"(exit {completed.returncode}):\n{completed.stdout[-2000:]}\n{completed.stderr[-2000:]}"
    )
    collected = int(match.group(1))
    assert MIN_COLLECTED <= collected <= MAX_COLLECTED, (
        f"suite collected {collected} tests, outside [{MIN_COLLECTED}, {MAX_COLLECTED}]; "
        "a drop usually means an install lost a dependency or a module stopped "
        "importing, a jump means new tests landed without updating these bounds -- "
        "re-measure on the full-install configuration and update them deliberately"
    )


def test_skip_markers_stay_within_bounds(request: pytest.FixtureRequest) -> None:
    """Items carrying skip/skipif markers must stay within the recorded ceiling.

    This is an upper bound only, so a partial session (``-k``, a single file)
    can only lower the count and never trips it. Runtime skips
    (``pytest.skip()`` inside a test body) are not visible here; the
    collected-total tripwire above is the primary guard for those.
    """
    marked = sum(
        1
        for item in request.session.items
        if item.get_closest_marker("skip") is not None or item.get_closest_marker("skipif") is not None
    )
    assert marked <= MAX_SKIP_MARKED, (
        f"{marked} collected tests carry skip/skipif markers, over the {MAX_SKIP_MARKED} "
        "ceiling; a jump usually means a new conditional skip landed -- re-measure "
        "and update the bound deliberately"
    )
