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
    python evals/run_eval.py                          # the main 17 questions
    python evals/run_eval.py evals/heldout_key.json   # a different question set
    python evals/run_eval.py --rescore evals/run5_prompt_v4.csv
        # re-score a saved results file with the current scoring rules,
        # WITHOUT calling the model again (writes <name>_rescored.csv)

INPUT   evals/answer_key.json (or the file you name)
OUTPUT  evals/results.csv for the main set; evals/results_<name>.csv for
        any other set (open in Excel; one row per question)
"""
import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

# ask.py and foundry_client.py live in src/api.
sys.path.append(str(Path(__file__).resolve().parents[1] / "src" / "api"))
from ask import load_index, retrieve, answer  # noqa: E402

DEFAULT_KEY = Path("evals/answer_key.json")


def clause_numbers(refs: str) -> list[str]:
    """Pull clause numbers like '5.2' out of text like '3 table, 5.2'."""
    return re.findall(r"\d+\.\d+", refs)


def expects_table(refs: str) -> bool:
    """True if the key says the answer also comes from the cover-level table."""
    return "table" in refs.lower()


def cited_in(reply: str) -> tuple[set[str], bool]:
    """Find what the answer cites inside square brackets.

    Returns (clause numbers cited, whether a table row was cited). Handles
    '[7.6]', '[6.4, 6.6]', '[Table 3: Lost keys]' and '[Table 3, 5.1, 5.2]'.
    """
    groups = re.findall(r"\[([^\]]*)\]", reply)
    numbers = {n for g in groups for n in re.findall(r"\d+\.\d+", g)}
    table = any(g.strip().lower().startswith("table") for g in groups)
    return numbers, table


def norm(text: str) -> str:
    """Lower-case and straighten curly apostrophes so phrase checks match."""
    return text.lower().replace("\u2019", "'")


def score_fields(expected_refs: str, retrieved: list[str], reply: str) -> dict:
    """Automatic checks for one answer (approximate; read the answers too)."""
    expected = clause_numbers(expected_refs)
    table = expects_table(expected_refs)
    wanted = bool(expected) or table
    cited_numbers, cited_table = cited_in(reply)
    text = norm(reply)
    return {
        # Was a correct clause (or table row, when expected) retrieved?
        "retrieval_hit": ((any(c in retrieved for c in expected)
                           or (table and any(c.startswith("Table") for c in retrieved)))
                          if wanted else ""),
        # Did the answer cite a correct clause (or a table row, when expected)?
        "cited_expected": ((any(c in cited_numbers for c in expected)
                            or (table and cited_table)) if wanted else ""),
        "refused": "can't find" in text or "cannot find" in text,
        "mentions_handler": "handler" in text,
    }


def score(item: dict, retrieved: list[str], reply: str) -> dict:
    return score_fields(item["clause_refs"], retrieved, reply)


def rate(rows: list[dict], kind: str, field: str) -> str:
    """Share of rows of one question type where a check is True."""
    subset = [r for r in rows if r["type"] == kind and r[field] != ""]
    if not subset:
        return "n/a"
    good = sum(bool(r[field]) for r in subset)
    return f"{good}/{len(subset)}"


def print_summary(rows: list[dict]) -> None:
    print("\nSUMMARY")
    print("  answerable  retrieval hit :", rate(rows, "answerable", "retrieval_hit"))
    print("  answerable  cited clause  :", rate(rows, "answerable", "cited_expected"))
    print("  ambiguous   retrieval hit :", rate(rows, "ambiguous", "retrieval_hit"))
    print("  ambiguous   handler named :", rate(rows, "ambiguous", "mentions_handler"))
    print("  out_of_scope refused      :", rate(rows, "out_of_scope", "refused"))
    secs = [float(r["seconds"]) for r in rows]
    print("  average seconds           :", round(sum(secs) / len(secs), 2))


def write_csv(rows: list[dict], path: Path) -> None:
    # utf-8-sig lets Excel show symbols such as the pound sign correctly.
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def rescore(csv_path: Path) -> None:
    """Re-score a saved results file with the current rules. No model calls."""
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        retrieved = [c.strip() for c in row["retrieved_clauses"].split(", ")]
        row.update(score_fields(row["expected_clauses"], retrieved, row["answer"]))
    out = csv_path.with_name(csv_path.stem + "_rescored.csv")
    write_csv(rows, out)
    print(f"Re-scored {len(rows)} rows from {csv_path}")
    print_summary(rows)
    print(f"\nSaved to {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the assistant on a question set.")
    parser.add_argument("key", nargs="?", type=Path, default=DEFAULT_KEY,
                        help="question set (JSON); default evals/answer_key.json")
    parser.add_argument("--rescore", type=Path, metavar="CSV",
                        help="re-score a saved results CSV without calling the model")
    args = parser.parse_args()
    if args.rescore:
        rescore(args.rescore)
        return

    key_file = args.key
    # The main set keeps writing results.csv; other sets get their own file.
    results_file = (Path("evals/results.csv") if key_file == DEFAULT_KEY
                    else Path(f"evals/results_{key_file.stem}.csv"))

    with open(key_file, encoding="utf-8") as f:
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

    write_csv(rows, results_file)
    print_summary(rows)
    print(f"\nFull results: {results_file}")


if __name__ == "__main__":
    main()