"""Ask a question about the policy wording and get a cited answer.

WHY THIS FILE EXISTS
--------------------
This is the first working version of the assistant (the "PoC"). It does RAG:
  1. EMBED   the question into a vector.
  2. SEARCH  find the best clauses with HYBRID search: meaning (vector
             cosine similarity) plus exact words (BM25 keyword score), merged
             with Reciprocal Rank Fusion. Meaning alone missed the clause on
             "reasonable care"; keywords find it.
  3. ANSWER  ask the chat model to answer using ONLY those clauses (plus the
             definitions, which are always included) and to cite clause numbers.

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
       replace. The rest of this file stays the same. Azure AI Search does
       hybrid search (vector + keyword + rank fusion) natively.
"""
import json
import logging
import math
import re
import sys
import time
import uuid
from collections import Counter
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np

from foundry_client import chat_client, embed_client, CHAT_DEPLOYMENT, EMBED_DEPLOYMENT

DATA_DIR = Path("data/processed")
LOG_DIR = Path("logs")
TOP_K = 6      # how many searched clauses to give the model
RRF_K = 60     # standard Reciprocal Rank Fusion constant
# Common words ignored by the keyword search.
STOPWORDS = {"a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "is", "it",
             "was", "my", "i", "me", "am", "do", "did", "does", "for", "if", "we",
             "you", "your", "our", "that", "this", "be", "by", "with", "as", "are",
             "not", "from", "any", "while", "can", "will", "what", "how", "long", "have"}

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

General rules:
- Cite the clause number in square brackets after each fact, for example [7.6].
- Do not use outside knowledge. Do not guess amounts or conditions.
- If the clauses do not contain the answer, say: "I can't find this in the policy wording."
- Never decide, approve or decline a claim. You provide decision support only.
- Keep the answer short and clear.

Two kinds of question:
1. QUESTION ABOUT THE POLICY ("Does Essential cover lost keys?", "How long do I
   have to report an incident?"): answer directly from the clauses.
2. QUESTION ABOUT A SPECIFIC INCIDENT ("My car was stolen while I...", "I left
   the keys..., am I covered?"): do NOT say whether the incident is or is not
   covered. Instead:
   a) quote what the relevant clauses say, including any exception;
   b) use defined terms from the definitions clauses (for example "unattended");
   c) list the facts that would decide the outcome;
   d) recommend referring the case to a claims handler.

The definitions (clauses 1.1 to 1.7) are always provided in full. Only say a term
is undefined if it is missing from them (for example "reasonable care"); in that
case say the wording does not define it and recommend referring the case to a
claims handler. If a clause such as an exclusion mentions that term, quote it."""


def load_index() -> tuple[list[dict], np.ndarray]:
    """Load the clause chunks and their vectors; normalise vectors for cosine search."""
    with open(DATA_DIR / "chunks_embedded.json", encoding="utf-8") as f:
        chunks = json.load(f)
    vectors = np.load(DATA_DIR / "embeddings.npy")
    # Dividing each vector by its length makes a simple dot product equal
    # to cosine similarity (1.0 = same meaning, near 0 = unrelated).
    vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
    return chunks, vectors


def tokenize(text: str) -> list[str]:
    """Lower-case words and numbers, without the common stop words."""
    return [w for w in re.findall(r"[a-z0-9\u00a3]+", text.lower()) if w not in STOPWORDS]


def keyword_scores(question: str, chunks: list[dict], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
    """BM25 keyword score of every clause for the question.

    A clause scores higher when it contains the question's words, especially
    rare words ("unattended") rather than common ones ("car").
    """
    docs = [tokenize(c["text"]) for c in chunks]
    n = len(docs)
    avg_len = sum(len(d) for d in docs) / n
    doc_freq = Counter(t for d in docs for t in set(d))   # clauses containing each word
    scores = np.zeros(n)
    for i, doc in enumerate(docs):
        counts = Counter(doc)
        for term in set(tokenize(question)):
            if term in counts:
                idf = math.log(1 + (n - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
                tf = counts[term]
                scores[i] += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(doc) / avg_len))
    return scores


def ranks(scores: np.ndarray) -> np.ndarray:
    """Rank of each item (0 = best)."""
    order = np.argsort(scores)[::-1]
    r = np.empty(len(scores), dtype=int)
    r[order] = np.arange(len(scores))
    return r


def retrieve(question: str, chunks: list[dict], vectors: np.ndarray, k: int = TOP_K):
    """Hybrid search: return the k best clauses as (clause, cosine score) pairs.

    Vector search finds clauses with similar MEANING; keyword search finds
    clauses with the same WORDS. Reciprocal Rank Fusion merges the two
    rankings: a clause near the top of either list rises in the final list.
    """
    response = embed_client().embeddings.create(model=EMBED_DEPLOYMENT, input=question)
    q = np.array(response.data[0].embedding, dtype="float32")
    q = q / np.linalg.norm(q)
    cosine = vectors @ q                       # one similarity score per clause

    keyword = keyword_scores(question, chunks)
    fused = 1 / (RRF_K + ranks(cosine))
    # Only clauses that share at least one word get a keyword vote.
    fused = fused + np.where(keyword > 0, 1 / (RRF_K + ranks(keyword)), 0)

    best = np.argsort(fused)[::-1][:k]
    return [(chunks[i], float(cosine[i])) for i in best]


@lru_cache(maxsize=1)
def definitions() -> list[dict]:
    """The definition clauses (section 1). They are short and apply to every
    other clause, so they are added to every question."""
    with open(DATA_DIR / "chunks_embedded.json", encoding="utf-8") as f:
        return [c for c in json.load(f) if c["section"].startswith("1.")]


def answer(question: str, hits: list[tuple[dict, float]]) -> str:
    """Ask the chat model to answer from the retrieved clauses plus definitions."""
    shown = {c["clause"] for c, _ in hits}
    extra = [d for d in definitions() if d["clause"] not in shown]
    clauses = [c for c, _ in hits] + extra
    context = "\n\n".join(f"[{c['clause']}] ({c['section']})\n{c['text']}" for c in clauses)
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
        "definitions_included": True,
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