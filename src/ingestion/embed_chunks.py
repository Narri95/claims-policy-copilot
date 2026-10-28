"""Turn the policy clause chunks into embedding vectors (local, no AI Search).

WHY THIS FILE EXISTS
--------------------
To search by meaning, every clause is converted into a list of numbers (an
"embedding") by the Foundry embedding model. Clauses with similar meaning get
similar vectors, so a question can later be matched to the right clause.
This version stores the vectors in a local file. Azure AI Search replaces the
local file later; the chunks and vectors themselves stay the same.

HOW TO RUN (project root, virtual environment active)
-----------------------------------------------------
    python src/ingestion/embed_chunks.py

INPUT   data/processed/chunks.json          (made by chunk_wording.py)
OUTPUT  data/processed/chunks_embedded.json the chunks that were embedded
        data/processed/embeddings.npy       one row of numbers per chunk,
                                            in the same order as the JSON

The table chunk is skipped on purpose: its tick/cross icons were lost during
PDF extraction, so it could produce confidently wrong answers.
"""
import json
import sys
from pathlib import Path

import numpy as np

# foundry_client.py lives in src/api, so add that folder to Python's search path.
sys.path.append(str(Path(__file__).resolve().parents[1] / "api"))
from foundry_client import embed_client, EMBED_DEPLOYMENT  # noqa: E402

DATA_DIR = Path("data/processed")
BATCH_SIZE = 16   # clauses sent to the model per request (fewer, bigger calls)


def load_clause_chunks() -> list[dict]:
    """Load chunks.json and keep only clause chunks (not the table)."""
    with open(DATA_DIR / "chunks.json", encoding="utf-8") as f:
        chunks = json.load(f)
    return [c for c in chunks if c["type"] == "clause"]


def embed_texts(texts: list[str]) -> np.ndarray:
    """Return one embedding vector per text, in the same order."""
    client = embed_client()
    vectors = []
    for start in range(0, len(texts), BATCH_SIZE):
        batch = texts[start:start + BATCH_SIZE]
        response = client.embeddings.create(model=EMBED_DEPLOYMENT, input=batch)
        # The API returns items with an index; sort to be sure of the order.
        for item in sorted(response.data, key=lambda d: d.index):
            vectors.append(item.embedding)
        print(f"  embedded {min(start + BATCH_SIZE, len(texts))}/{len(texts)}")
    return np.array(vectors, dtype="float32")


def main() -> None:
    chunks = load_clause_chunks()
    print(f"Embedding {len(chunks)} clause chunks with '{EMBED_DEPLOYMENT}'...")

    # Put the section and clause number in front of the text so the vector
    # also carries "which part of the policy is this".
    texts = [f"{c['section']} | clause {c['clause']}: {c['text']}" for c in chunks]
    vectors = embed_texts(texts)

    np.save(DATA_DIR / "embeddings.npy", vectors)
    with open(DATA_DIR / "chunks_embedded.json", "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)

    print(f"Saved {vectors.shape[0]} vectors of length {vectors.shape[1]}.")


if __name__ == "__main__":
    main()