# ADR 0002: Hybrid retrieval over clause-level chunks, with a local index

- **Status:** Accepted (with a known limitation)
- **Date:** 27 November 2026

## Context

Policy wording has a clear structure (numbered clauses) and a cover-level table whose meaning is carried by coloured symbols. Early evaluation runs with plain vector search missed clauses that mattered: a definition that changes the meaning of an exclusion, and an exclusion clause relevant to an incident question.

## Decision

1. **Chunk by clause**, so each citation points to one numbered clause, and turn each table row into its own chunk (the symbol colours are read from the PDF, because text extraction loses them).
2. **Hybrid ranking:** combine embedding similarity (`text-embedding-3-small`) with a BM25-style keyword score using Reciprocal Rank Fusion (`RRF_K=60`, `TOP_K=6`).
3. **Always include the definitions** (section 1), and **add the exclusions** (section 7) when the question is classified as an incident.
4. Keep the index (`embeddings.npy`, `chunks_embedded.json`) in the container image and search it in memory.

## Alternatives considered

| Option | Why not |
|---|---|
| Fixed-size text chunks | Citations would not map to clause numbers, and a clause could be split across chunks. |
| Vector search only | Missed exact terms and clause references that keyword matching finds easily. |
| Azure AI Search | The right production choice. Creating the service failed with a free-tier quota error ("1 out of 1 free tier"), and no search service existed in the subscription. Paying for a basic tier was not justified for 51 chunks. |
| Document Intelligence for the table | Read the table structure well but reported the coloured symbols unreliably (`:selected:` or a plain square), so colour was read directly with `pdfplumber` and verified cell by cell against the source (55 of 55). |

## Consequences

- The index is small enough (51 clauses and table rows) that in-memory search is fast and has no extra cost or network hop.
- Re-ingesting means rebuilding the image. That is acceptable for one document, and it keeps the deployed version and its data in step.
- **Limitation:** this does not scale to many documents. The production path is Azure AI Search with the same chunks, with the same hybrid and fusion logic replaced by the service's hybrid query. The retrieval step is isolated in `retrieve()` to make that swap small.
- Including definitions and exclusions by rule fixed the missed-clause failures seen in early runs, at the cost of slightly longer prompts.
- Evaluation sets were used while tuning, so reported scores are development results, not an unbiased test (see README, Known limitations).
