"""Shared test setup: make the source folders importable and provide dummy
settings, so the tests never need Azure access or a .env file."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for folder in ("src/api", "src/ingestion", "evals"):
    sys.path.insert(0, str(ROOT / folder))

os.environ.setdefault("FOUNDRY_PROJECT_ENDPOINT",
                      "https://example.services.ai.azure.com/api/projects/test")
os.environ.setdefault("CHAT_DEPLOYMENT", "test-chat")
os.environ.setdefault("EMBED_DEPLOYMENT", "test-embed")
