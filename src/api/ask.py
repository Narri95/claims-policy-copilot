"""Ask a question about the policy wording and get a cited answer.

WHY THIS FILE EXISTS
--------------------
This is the first working version of the assistant (the "PoC"). It does RAG:
  1. EMBED   the question into a vector.
  2. SEARCH  the stored clause vectors for the closest matches (cosine
             similarity), so only the relevant clauses are used.
  3. ANSWER  ask the chat model to answer using ONLY those clauses and to
             cite clause numbers.

The assistant never decides a claim. If the wording does not cover the
question, or the outcome depends on facts, it must say so and refer the
question to a claims handler.

HOW TO RUN (project root, virtual environment active)
-----------------------------------------------------
    python src/api/ask.py "Does the Essential level cover lost keys?"
    python src/api/ask.py          # no argument: interactive, type 'q' to quit

NEEDS  data/processed/chunks_embedded.json and embeddings.npy
       (made by src/ingestion/embed_chunks.py)

LOGS   Every question is recorded in two files in the logs/ folder:
         logs/app.log      readable event log (start, timing, errors)
         logs/audit.jsonl  one JSON record per question: when, question,
                           clauses retrieved with scores, answer, seconds.
       The logs/ folder is git-ignored. Once real customer data is used,
       logs would contain personal data and need access control and retention.

LATER  The search step (retrieve) is the only part Azure AI Search will
       replace. The rest of this file stays the same.
"""
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from foundry_client import chat_client, embed_client, CHAT_DEPLOYMENT, EMBED_DEPLOYMENT

DATA_DIR = Path("data/processed")
LOG_DIR = Path("logs")
TOP_K = 4   # how many clauses to give the model

logger = logging.getLogger("claims_copilot")


def setup_logging() -> None:
    """Send log messages to logs/app.log (created on first use)."""
    LOG_DIR.mkdir(exist_ok=True)
    logging.basicConfig(
        filename=LOG_DIR / "app.log",
        encoding="utf-8",
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def write_audit(record: dict) -> None:
    """Append one JSON line to logs/audit.jsonl (one record per question)."""
    LOG_DIR.mkdir(exist_ok=True)
    with open(LOG_DIR / "audit.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

SYSTEM_PROMPT = """You are a claims-handler assistant for Northgate Motor Cover.
Answer using ONLY the policy clauses provided in the user message.

Rules:
- Cite the clause number in square brackets after each fact, for example [7.6].
- If the clauses do not contain the answer, say: "I can't find this in the policy wording."
- If the outcome depends on facts you do not have, or a clause is ambiguous,
  explain what the clauses say and recommend referring the case to a claims handler.
- Never decide, approve or decline a claim. You provide decision support only.
- Do not use outside knowledge. Do not guess amounts or conditions.
- Keep the answer short and clear."""


def load_index() -> tuple[list[dict], np.ndarray]:
    """Load the clause chunks and their vectors; normalise vectors for cosine search."""
    with open(DATA_DIR / "chunks_embedded.json", encoding="utf-8") as f:
        chunks = json.load(f)
    vectors = np.load(DATA_DIR / "embeddings.npy")
    # Dividing each vector by its length makes a simple dot product equal
    # to cosine similarity (1.0 = same meaning, near 0 = unrelated).
    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    return chunks, vectors


def retrieve(question: str, chunks: list[dict], vectors: np.ndarray, k: int = TOP_K):
    """Return the k clauses most similar to the question, with their scores."""
    response = embed_client().embeddings.create(model=EMBED_DEPLOYMENT, input=question)
    q = np.array(response.data[0].embedding, dtype="float32")
    q = q / np.linalg.norm(q)

    scores = vectors @ q                   # one similarity score per clause
    best = np.argsort(scores)[::-1][:k]    # indexes of the k highest scores
    return [(chunks[i], float(scores[i])) for i in best]


def answer(question: str, hits: list[tuple[dict, float]]) -> str:
    """Ask the chat model to answer from the retrieved clauses only."""
    context = "\n\n".join(
        f"[{c['clause']}] ({c['section']})\n{c['text']}" for c, _ in hits
    )
    user_message = f"Policy clauses:\n{context}\n\nQuestion: {question}"

    response = chat_client().chat.completions.create(
        model=CHAT_DEPLOYMENT,
        temperature=0,    # same question, same answer: easier to test
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
    )
    return response.choices[0].message.content


def ask(question: str, chunks, vectors) -> str:
    """Run the full pipeline for one question, print the result and log it."""
    request_id = uuid.uuid4().hex[:8]   # ties app.log lines to the audit record
    logger.info("[%s] question received: %s", request_id, question)
    start = time.perf_counter()
    try:
        hits = retrieve(question, chunks, vectors)
        reply = answer(question, hits)
    except Exception:
        logger.exception("[%s] failed", request_id)   # full error into app.log
        raise
    seconds = round(time.perf_counter() - start, 2)

    logger.info("[%s] answered in %ss using clauses %s", request_id, seconds,
                [c["clause"] for c, _ in hits])
    write_audit({
        "request_id": request_id,
        "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "question": question,
        "retrieved": [{"clause": c["clause"], "score": round(s, 3)} for c, s in hits],
        "answer": reply,
        "seconds": seconds,
        "chat_model": CHAT_DEPLOYMENT,
        "embed_model": EMBED_DEPLOYMENT,
    })

    print("\nRetrieved clauses (score):")
    for c, score in hits:
        print(f"  [{c['clause']}] {score:.2f}  {c['text'][:70]}...")
    print("\nAnswer:\n" + reply + f"\n\n({seconds}s, request {request_id})\n")
    return reply


def main() -> None:
    setup_logging()
    chunks, vectors = load_index()
    if len(sys.argv) > 1:
        ask(" ".join(sys.argv[1:]), chunks, vectors)
        return
    while True:                            # interactive mode
        question = input("Question (q to quit): ").strip()
        if question.lower() in ("q", "quit", ""):
            break
        ask(question, chunks, vectors)


if __name__ == "__main__":
    main()