# ADR 0001: Use retrieval-augmented generation, not fine-tuning

- **Status:** Accepted
- **Date:** 27 November 2026

## Context

The assistant must answer questions about a policy wording and show where each statement comes from. Policy wordings change (new editions, endorsements), and a wrong answer about cover is costly, so every answer needs to be checkable against the document.

## Decision

Retrieve the relevant clauses at question time and give them to the model with strict prompts: answer only from the retrieved text, cite a clause or table row for each statement, and refuse when the policy does not cover the question.

## Alternatives considered

| Option | Why not |
|---|---|
| Fine-tune a model on the wording | Knowledge is baked into the weights, so it cannot cite a clause reliably. Every new wording edition means retraining. A fine-tuned model can still state wrong cover confidently. |
| Put the whole wording in every prompt | Works for a short document, but costs more per question and gives the model no signal about which clauses matter. It does not scale to several products or editions. |
| Rules or keyword search only | Cannot handle paraphrased questions ("lost keys" versus "key replacement"). |

## Consequences

- Updating the policy means re-running ingestion and re-embedding, with no model training.
- Every answer carries citations, so a reviewer can check it against the source.
- Answer quality depends on retrieval, so retrieval is evaluated separately (see ADR 0002 and `evals/`).
- The assistant never gives a verdict on a claim. Incident questions get the relevant cover and exclusions and a referral to a claims handler. This is a design rule, not only a prompt wish: it follows from the risk of automated claim decisions.
