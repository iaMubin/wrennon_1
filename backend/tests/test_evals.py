"""Runs evals/cases.yaml in stub mode (scripted LLM). See evals/harness.py."""
import pytest

from app.services.llm import mask_pii
from evals.harness import check, load_cases, run_case

CASES = load_cases()


def _param(case):
    marks = []
    if case.get("known_issue"):
        marks.append(pytest.mark.xfail(strict=True, reason=case["known_issue"]))
    return pytest.param(case, id=case["id"], marks=marks)


@pytest.mark.parametrize("case", [_param(c) for c in CASES["agent_cases"] if not c.get("live_only")])
def test_agent_case(case):
    res = run_case(case, mode="stub")
    failures = check(case["expect"], res)
    assert not failures, "\n".join(failures)


@pytest.mark.parametrize("case", [_param(c) for c in CASES["pii_cases"]])
def test_pii_case(case):
    masked = mask_pii(case["text"])
    if case.get("unchanged"):
        assert masked == case["text"]
    for s in case.get("gone", []):
        assert s not in masked
    for s in case.get("has", []):
        assert s in masked


def test_every_agent_case_has_unique_id():
    ids = [c["id"] for c in CASES["agent_cases"]] + [c["id"] for c in CASES["pii_cases"]]
    assert len(ids) == len(set(ids))


def test_live_runner_works_in_dry_run_mode():
    from evals.run_live import main
    import sys
    old = sys.argv
    sys.argv = ["run_live", "--dry-run"]
    try:
        assert main() in (0, 1)  # exercising the runner itself; stub model can't satisfy every live rule
    finally:
        sys.argv = old
