"""Read the cover-level table straight from the PDF, including coloured icons.

WHY THIS FILE EXISTS
--------------------
The cover-level table marks "included" and "not included" with small coloured
symbols (green = included, red = not included). Plain text extraction loses
them. Azure Document Intelligence read the table structure well but could not
tell the symbols apart reliably (see docs/ingestion.md). This PDF has a real
text layer, so we can read each symbol's COLOUR directly from the PDF, which
is exact. Document Intelligence stays the tool for scanned documents.

WHAT IT DOES
------------
  1. Finds the table on page 1 and reads every cell's text.
  2. For a cell holding a symbol, reads its colour: green -> "Included",
     red -> "Not included".
  3. Builds one searchable chunk per benefit row, for example:
     "Lost keys by cover level. Essential: Not included; ... Premier: £400; ..."

HOW TO RUN (project root, virtual environment active)
-----------------------------------------------------
    pip install pdfplumber
    python src/ingestion/extract_table.py

OUTPUT  data/processed/table_chunks.json (one chunk per benefit row)
        Re-run embed_chunks.py afterwards so the rows get embeddings.
"""
import json
import re
from pathlib import Path

import pdfplumber

PDF = Path("data/synthetic/northgate_motor_wording.pdf")
OUT = Path("data/processed/table_chunks.json")
SECTION = "3. Cover levels at a glance"
TABLE_PAGE = 0                                   # page 1
SYMBOL_FONTS = ("Zapf", "Dingbat", "Symbol")     # fonts that hold the icons


def tidy(text: str | None) -> str:
    """Join wrapped lines and collapse repeated spaces."""
    return re.sub(r"\s+", " ", text or "").strip()


def symbol_in_cell(page, bbox) -> str | None:
    """Return 'Included' or 'Not included' if the cell holds a coloured symbol."""
    x0, top, x1, bottom = bbox
    for ch in page.chars:
        if not any(font in ch["fontname"] for font in SYMBOL_FONTS):
            continue
        cx, cy = (ch["x0"] + ch["x1"]) / 2, (ch["top"] + ch["bottom"]) / 2
        if x0 <= cx <= x1 and top <= cy <= bottom:
            colour = ch.get("non_stroking_color") or (0, 0, 0)
            if len(colour) < 3:                  # grey-scale colour: cannot tell
                return None
            r, g, _ = colour[:3]
            return "Included" if g > r else "Not included"   # green vs red
    return None


def extract_rows(pdf_path: Path = PDF) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """Return (tier names, [(benefit, [value per tier]), ...])."""
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[TABLE_PAGE]
        table = page.find_tables()[0]
        text = table.extract()
        header = [tidy(c) for c in text[0]]
        tiers = header[1:]

        rows = []
        for r in range(1, len(text)):
            benefit = tidy(text[r][0])
            values = []
            for c in range(1, len(header)):
                bbox = table.rows[r].cells[c]
                symbol = symbol_in_cell(page, bbox) if bbox else None
                values.append(symbol or tidy(text[r][c]))
            rows.append((benefit, values))
    return tiers, rows


def to_chunks(tiers, rows) -> list[dict]:
    """One searchable chunk per benefit row."""
    chunks = []
    for n, (benefit, values) in enumerate(rows, start=1):
        by_level = "; ".join(f"{t}: {v}" for t, v in zip(tiers, values))
        chunks.append({
            "id": f"table-{n:03d}",
            "type": "table_row",
            "section": SECTION,
            "clause": f"Table 3: {benefit}",
            "text": f"{benefit} by cover level. {by_level}.",
        })
    return chunks


def main() -> None:
    tiers, rows = extract_rows()
    print("Cover levels:", ", ".join(tiers))
    for benefit, values in rows:
        print(f"  {benefit:30} | " + " | ".join(values))

    symbols = sum(v in ("Included", "Not included") for _, vals in rows for v in vals)
    print(f"\n{len(rows)} rows, {symbols} symbol cells read by colour.")
    if symbols == 0:
        print("WARNING: no symbols found; check the PDF has a text layer.")

    chunks = to_chunks(tiers, rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)
    print(f"Saved {len(chunks)} table chunks to {OUT}")


if __name__ == "__main__":
    main()