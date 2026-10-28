"""Run every question in evals/answer_key.json through the assistant and score it.

WHY THIS FILE EXISTS
--------------------
Trying a few questions by hand is not evidence. This script runs the whole
answer key and produces numbers you can track as the system changes:
  - retrieval hit rate : was a correct clause among the clauses retrieved?
  - citation rate      : did the answer cite a correct clause?
  - refusal rate       : did out-of-scope questions get a refusal?
  - handler referral   : did ambiguous questions get referred to a handler?
  - average seconds    : speed per question

These checks are automatic and approximate. The CSV also has the answer and
the expected answer side by side so you can mark correctness by hand.

HOW TO RUN (project root, virtual environment active)
-----------------------------------------------------
    python evals/run_eval.py

INPUT   evals/answer_key.json
OUTPUT  evals/results.csv   (open in Excel; one row per question)
"""
import csv
import json
import re
import sys
import time
from pathlib import Path

# ask.py and foundry_client.py live in src/api.
sys.path.append(str(Path(__file__).resolve().parents[1] / "src" / "api"))
from ask import load_index, retrieve, answer  # noqa: E402

KEY_FILE = Path("evals/answer_key.json")
RESULTS_FILE = Path("evals/results.csv")


def clause_numbers(refs: str) -> list[str]:
    """Pull clause numbers like '5.2' out of text like '3 table, 5.2'."""
    return re.findall(r"\d+\.\d+", refs)


def norm(text: str) -> str:
    """Lower-case and straighten curly apostrophes so phrase checks match."""
    return text.lower().replace("\u2019", "'")


def score(item: dict, retrieved: list[str], reply: str) -> dict:
    expected = clause_numbers(item["clause_refs"])
    text = norm(reply)
    return {
        # Was any correct clause in the retrieved set? (blank if none expected)
        "retrieval_hit": (any(c in retrieved for c in expected) if expected else ""),
        # Did the answer cite at least one correct clause, e.g. "[6.3]"?
        "cited_expected": (any(f"[{c}]" in reply for c in expected) if expected else ""),
        # Did it say it cannot find the answer?
        "refused": "can't find" in text or "cannot find" in text,
        # Did it recommend a claims handler?
        "mentions_handler": "handler" in text,
    }


def rate(rows: list[dict], kind: str, field: str) -> str:
    """Share of rows of one question type where a check is True."""
    subset = [r for r in rows if r["type"] == kind and r[field] != ""]
    if not subset:
        return "n/a"
    good = sum(bool(r[field]) for r in subset)
    return f"{good}/{len(subset)}"


def main() -> None:
    with open(KEY_FILE, encoding="utf-8") as f:
        items = json.load(f)
    chunks, vectors = load_index()

    rows = []
    for item in items:
        start = time.perf_counter()
        hits = retrieve(item["question"], chunks, vectors)
        reply = answer(item["question"], hits)
        seconds = round(time.perf_counter() - start, 2)

        retrieved = [c["clause"] for c, _ in hits]
        row = {
            "id": item["id"], "type": item["type"], "question": item["question"],
            "expected_answer": item["expected_answer"],
            "expected_clauses": item["clause_refs"],
            "retrieved_clauses": ", ".join(retrieved),
            "answer": reply.replace("\n", " "), "seconds": seconds,
            **score(item, retrieved, reply),
            "correct_by_hand": "",      # you fill this in: yes / no / partly
        }
        rows.append(row)
        print(f"{item['id']} ({item['type']}) done in {seconds}s")

    # utf-8-sig lets Excel show symbols such as the pound sign correctly.
    with open(RESULTS_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print("\nSUMMARY")
    print("  answerable  retrieval hit :", rate(rows, "answerable", "retrieval_hit"))
    print("  answerable  cited clause  :", rate(rows, "answerable", "cited_expected"))
    print("  ambiguous   handler named :", rate(rows, "ambiguous", "mentions_handler"))
    print("  out_of_scope refused      :", rate(rows, "out_of_scope", "refused"))
    print("  average seconds           :", round(sum(r["seconds"] for r in rows) / len(rows), 2))
    print(f"\nFull results: {RESULTS_FILE}")


if __name__ == "__main__":
    main()