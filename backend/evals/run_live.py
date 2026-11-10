"""Run the eval cases against the REAL model.   python -m evals.run_live [--dry-run] [--only ID]

Needs GROQ_API_KEY (and friends) in the environment; makes real, billable LLM
calls. Only the `live:` expectations are checked - things that must hold
however the model phrases its answer. Exit code 1 if any case fails.
--dry-run swaps in the scripted stub model to prove the runner itself works.
"""
import argparse
import sys

from evals.harness import check, load_cases, run_case


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only")
    args = ap.parse_args()

    cases = [c for c in load_cases()["agent_cases"] if c.get("live") and (not args.only or c["id"] == args.only)]
    failed = 0
    for case in cases:
        if args.dry_run and case.get("live_only"):
            print(f"SKIP  {case['id']} (needs a real model)")
            continue
        res = run_case(case, mode="stub" if args.dry_run else "live")
        fails = check(case["live"], res)
        print(f"{'FAIL' if fails else 'PASS'}  {case['id']}")
        for f in fails:
            print(f"        - {f}")
        if not args.dry_run:
            print(f"        reply: {res.reply[:140]!r}")
        failed += bool(fails)
    print(f"\n{len(cases) - failed}/{len(cases)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
