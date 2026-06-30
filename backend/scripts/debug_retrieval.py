"""
One-off debug script. Run from inside backend/:

    python scripts/debug_retrieval.py "what's your return policy?"

Prints the raw retrieval + rerank results so we can see exactly what
score the top match is getting, instead of guessing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.vectorstore import retrieve_and_rerank  # noqa: E402


def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "what's your return policy?"
    print(f"Query: {query!r}\n")

    results = retrieve_and_rerank(query=query, top_k=3)

    if not results:
        print("No results returned at all — collection may be empty or query embedding failed.")
        return

    for i, r in enumerate(results, 1):
        print(f"--- Result {i} | relevance_score={r['relevance_score']:.4f} ---")
        print(r["text"][:300])
        print()


if __name__ == "__main__":
    main()
