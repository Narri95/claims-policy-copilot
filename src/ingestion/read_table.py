"""Read the cover-level table with Azure Document Intelligence (exploration).

WHY THIS FILE EXISTS
--------------------
A plain PDF text reader turned every tick and cross icon in the cover-level
table into the same square character, so "included" and "not included" were
indistinguishable. Document Intelligence's "prebuilt-layout" model reads
tables as rows and columns. This script sends the PDF page that holds the
table and PRINTS how each cell comes back, so we can see what the service
does with the icons BEFORE we decide how to turn the table into data.

HOW TO RUN (project root, virtual environment active)
-----------------------------------------------------
    python src/ingestion/read_table.py

NEEDS   DOCINTEL_ENDPOINT and DOCINTEL_KEY in .env
        data/synthetic/northgate_motor_wording.pdf
OUTPUT  Tables printed to the screen, and the full raw result saved to
        data/processed/layout_result.json for inspection.

COST    Only page 1 is sent (where the table is), which also keeps the
        Free tier (which reads at most 2 pages) happy.
"""
import json
import os
from pathlib import Path

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

load_dotenv(override=True)

PDF = Path("data/synthetic/northgate_motor_wording.pdf")
OUT = Path("data/processed/layout_result.json")
TABLE_PAGES = "1"     # the cover-level table is on page 1


def analyse(pdf: Path):
    """Send the PDF to the prebuilt-layout model and wait for the result."""
    client = DocumentIntelligenceClient(
        endpoint=os.environ["DOCINTEL_ENDPOINT"],
        credential=AzureKeyCredential(os.environ["DOCINTEL_KEY"]),
    )
    with open(pdf, "rb") as f:
        poller = client.begin_analyze_document("prebuilt-layout", body=f, pages=TABLE_PAGES)
    return poller.result()


def print_table(number: int, table) -> None:
    """Print one table as a grid. repr() shows hidden or unusual characters."""
    print(f"\nTABLE {number}: {table.row_count} rows x {table.column_count} columns")
    grid = [[""] * table.column_count for _ in range(table.row_count)]
    for cell in table.cells:
        grid[cell.row_index][cell.column_index] = cell.content
    for r, row in enumerate(grid):
        print(f"  row {r}: " + " | ".join(repr(c) for c in row))


def main() -> None:
    result = analyse(PDF)

    tables = result.tables or []
    print(f"Found {len(tables)} table(s).")
    for i, table in enumerate(tables, start=1):
        print_table(i, table)

    # Selection marks are the service's name for checkbox-style symbols.
    marks = sum(len(p.selection_marks or []) for p in result.pages)
    print(f"\nSelection marks detected on the page: {marks}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(result.as_dict(), f, indent=2, ensure_ascii=False)
    print(f"Raw result saved to {OUT}")


if __name__ == "__main__":
    main()