"""FastAPI service for the Claims & Policy Copilot.

WHY THIS FILE EXISTS
--------------------
Turns the command-line assistant (ask.py) into a web service that other
programs, a web page, or a cloud deployment can call.

ENDPOINTS
---------
  GET  /health   is the service up, and how many clauses are loaded
  POST /ask      {"question": "..."} -> answer, question type, citations
  GET  /docs     interactive API page (Swagger UI), generated automatically

RUN LOCALLY (project root, virtual environment active)
------------------------------------------------------
    pip install -r requirements.txt
    uvicorn --app-dir src/api main:app --reload
    then open http://127.0.0.1:8000/docs

SETTINGS (environment variables or .env)
----------------------------------------
    FOUNDRY_PROJECT_ENDPOINT, CHAT_DEPLOYMENT, EMBED_DEPLOYMENT  (as before)
    API_KEY   optional. If set, every /ask call must send the same value in
              an "X-API-Key" header. Set it on any public deployment so
              strangers cannot spend your model budget.

DESIGN NOTES
------------
  * The clause index is loaded once at start-up, not on every request.
  * Failures return a generic message plus a reference number; the details
    go to the log only, so internal addresses are never shown to callers.
  * Each answered question writes one "AUDIT" log line (to the console, which
    Azure collects). With real customer data these lines would contain
    personal data and need redaction, access control and a retention period.
"""
import json
import logging
import os
import secrets
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

# ask.py and foundry_client.py sit in this same folder.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ask import load_index, run_pipeline  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("claims_copilot.api")

DISCLAIMER = "Decision support only. A claims handler makes every decision."


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Runs once when the service starts: load the clauses and their vectors."""
    app.state.chunks, app.state.vectors = load_index()
    logger.info("Loaded %d clauses", len(app.state.chunks))
    yield


app = FastAPI(
    title="Claims & Policy Copilot",
    version="0.1.0",
    description="Cited answers about a (fictional) motor policy wording. "
                "Decision support only: it never decides a claim.",
    lifespan=lifespan,
)


def require_key(x_api_key: str | None = Header(default=None)) -> None:
    """If API_KEY is set, the caller must send it in the X-API-Key header."""
    expected = os.environ.get("API_KEY")
    if expected and not secrets.compare_digest(x_api_key or "", expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


class Citation(BaseModel):
    clause: str
    section: str
    score: float


class AskResponse(BaseModel):
    request_id: str
    kind: str                 # "policy", "incident" or "other"
    answer: str
    citations: list[Citation]
    seconds: float
    disclaimer: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "clauses_loaded": len(app.state.chunks)}


@app.post("/ask", response_model=AskResponse, dependencies=[Depends(require_key)])
def ask(request: AskRequest) -> AskResponse:
    request_id = uuid.uuid4().hex[:8]
    start = time.perf_counter()
    try:
        result = run_pipeline(request.question, app.state.chunks, app.state.vectors)
    except Exception:
        logger.exception("[%s] pipeline failed", request_id)   # details: log only
        raise HTTPException(
            status_code=502,
            detail=f"The assistant could not complete the request (reference {request_id}).",
        )
    seconds = round(time.perf_counter() - start, 2)

    citations = [Citation(clause=c["clause"], section=c["section"], score=round(s, 3))
                 for c, s in result["hits"]]
    logger.info("AUDIT %s", json.dumps({
        "request_id": request_id,
        "question": request.question,
        "kind": result["kind"],
        "clauses": [c.clause for c in citations],
        "answer": result["reply"],
        "seconds": seconds,
    }, ensure_ascii=False)) 

    return AskResponse(request_id=request_id, kind=result["kind"], answer=result["reply"],
                       citations=citations, seconds=seconds, disclaimer=DISCLAIMER)
