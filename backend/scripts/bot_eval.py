"""Score the chatbot on scripted shopper conversations, judged by what really changed.

    cd backend
    python -m scripts.bot_eval                      # every scenario with your real LLM keys
    python -m scripts.bot_eval --pause 25           # slower, for providers with a small per-minute allowance (free Groq tier)
    python -m scripts.bot_eval --only cancel_flow reorder
    python -m scripts.bot_eval --list
    python -m scripts.bot_eval --cleanup            # remove test data left behind by an interrupted run

Writes bot_eval_report.json. Scenarios the model provider throttled are reported as "RATE-LIMITED" (could not be judged),
never as failures of the bot.
"""
import argparse
import asyncio
import json
import logging

from app.services.bot_eval import SCENARIOS, GraphBot, cleanup_leftovers, report, run_all

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="run just these scenarios")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--cleanup", action="store_true")
    ap.add_argument("--pause", type=float, default=20.0, help="seconds to wait between turns (default 20)")
    ap.add_argument("--cooldown", type=float, default=65.0, help="seconds to wait before retrying a throttled scenario (default 65)")
    ap.add_argument("--verbose", action="store_true", help="show the application's own log lines")
    a = ap.parse_args()
    if a.list:
        for name, (_, signed_in, what) in SCENARIOS.items():
            print(f"{name:<26} {'signed in' if signed_in else 'guest':<10} {what}")
        raise SystemExit
    if a.cleanup:
        print(cleanup_leftovers())
        raise SystemExit
    if not a.verbose:
        logging.getLogger("wrennon").setLevel(logging.ERROR)   # keep the report readable; throttling is detected separately
    n = len(a.only) if a.only else len(SCENARIOS)
    print(f"Running {n} scenarios (about {max(1, round(n * 2 * (a.pause + 6) / 60))} minutes at --pause {a.pause:g}). Press Ctrl+C to stop; test data is cleaned up.")
    try:
        results = asyncio.run(run_all(GraphBot(), a.only, pause=a.pause, cooldown=a.cooldown))
    except KeyboardInterrupt:
        print("\nInterrupted. " + cleanup_leftovers())
        raise SystemExit(1)
    print(report(results))
    with open("bot_eval_report.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print("\nSaved bot_eval_report.json")
