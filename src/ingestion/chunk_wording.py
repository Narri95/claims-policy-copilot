"""Split the Northgate policy wording PDF into one chunk per clause.

WHY THIS FILE EXISTS
--------------------
A RAG assistant answers best when each search result is one complete clause
(for example clause 7.6 about theft), not an arbitrary slice of text that
could cut an exclusion in half. This script turns the PDF into a list of
clause chunks. Each chunk carries its section name and clause number, so the
assistant can cite "clause 7.6" exactly.

HOW TO RUN (from the project root, with the virtual environment active)
-----------------------------------------------------------------------
    python src/ingestion/chunk_wording.py
    python src/ingestion/chunk_wording.py path/to/other_wording.pdf

INPUT
-----
A PDF where every clause starts a line with a number like "4.3", under
headings like "4. Section A: Damage to your car".

OUTPUT
------
data/processed/chunks.json, a list of objects shaped like this:

    {
      "id":      "chunk-013",              # unique id, in document order
      "type":    "clause" or "table",      # "table" = the cover-level matrix
      "section": "4. Section A: ...",      # the heading this chunk sits under
      "clause":  "4.3",                    # clause number ("3" for the table)
      "text":    "We do not pay for ..."   # the clause text on a single line
    }

KNOWN LIMITATION
----------------
The cover-level table (section 3) is extracted as flat text. Tick and cross
icons both come out as the same square character, so "included" cannot be
told apart from "not included". Reading that table properly needs Azure
Document Intelligence (a later step). Clause chunks are not affected.
"""

# --- Imports: standard library first, then third-party ----------------------
import argparse            # reads options typed after the script name
import json                # saves the chunks as a JSON file
import re                  # regular expressions, used to spot headings/clauses
from pathlib import Path   # safe file paths that work on Windows and Linux

from pypdf import PdfReader  # reads the text out of the PDF (pip install pypdf)

# --- Settings you may want to change ----------------------------------------
# Where to read the PDF from if no path is given on the command line.
DEFAULT_PDF = Path("data/synthetic/northgate_motor_wording.pdf")
# Folder where the result is saved. It is created if it does not exist.
OUTPUT_DIR = Path("data/processed")

# A section heading looks like: "4. Section A: Damage to your car"
#   ^(\d+)   one or more digits at the start of the line (the section number)
#   \.\s+    a dot, then at least one space
#   (\S.*)$  the heading words
HEADING_RE = re.compile(r"^(\d+)\.\s+(\S.*)$")

# A clause start looks like: "4.3 We do not pay ..."
#   ^(\d+\.\d+)   digits, a dot, digits (the clause number, e.g. 4.3)
#   \s+(.*)$      a space, then the clause text
CLAUSE_RE = re.compile(r"^(\d+\.\d+)\s+(.*)$")

# Headings are numbered 1 to 9 in this document.
MAX_SECTION_NUMBER = 9
# A long line that starts with a number is body text, not a heading.
MAX_HEADING_LENGTH = 60


def extract_lines(pdf_path: Path) -> list[str]:
    """Read every page of the PDF and return its non-empty lines, trimmed."""
    reader = PdfReader(pdf_path)

    # extract_text() returns the text of one page; join all pages together,
    # separated by newlines, so we can treat the document as one long text.
    text = "\n".join(page.extract_text() for page in reader.pages)

    # Split into lines, strip spaces from both ends, and drop blank lines.
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_chunks(lines: list[str]) -> list[dict]:
    """Group the document's lines into clause chunks.

    Rules, applied to each line in order:
      1. A line starting "N.N " (for example "4.3 ...") begins a new clause.
      2. A short line starting "N. " is a section heading. It is remembered
         and attached to every chunk that follows it.
      3. The "Cover levels" heading also begins one special table chunk.
      4. Any other line continues the chunk currently being built. This
         handles clauses that wrap across several lines in the PDF.
    """
    chunks: list[dict] = []   # finished chunks, in document order
    section = ""              # the heading we are currently under
    current: dict | None = None   # the chunk being built, or None

    def finish_current() -> None:
        """Close the chunk being built and add it to the finished list."""
        nonlocal current      # we are changing the variable defined above
        if current:
            # The text was collected as a list of lines; join into one string.
            current["text"] = " ".join(current["text"]).strip()
            chunks.append(current)
            current = None

    for line in lines:
        clause = CLAUSE_RE.match(line)    # e.g. "4.3 We do not ..."
        heading = HEADING_RE.match(line)  # e.g. "4. Section A: ..."

        if clause:
            # Rule 1: a new clause starts. Save the previous chunk first.
            finish_current()
            current = {
                "type": "clause",
                "section": section,
                "clause": clause.group(1),    # the number, e.g. "4.3"
                "text": [clause.group(2)],    # first line of the clause text
            }

        elif (heading
              and int(heading.group(1)) <= MAX_SECTION_NUMBER
              and len(line) < MAX_HEADING_LENGTH):
            # Rule 2: a section heading. Save the previous chunk, then
            # remember this heading for the chunks that follow.
            finish_current()
            section = line

            if "Cover levels" in line:
                # Rule 3: start the special chunk for the cover-level table.
                current = {
                    "type": "table",
                    "section": section,
                    "clause": "3",
                    "text": [],
                }

        elif current:
            # Rule 4: a continuation line. Add it to the current chunk.
            current["text"].append(line)

    finish_current()   # do not forget the last chunk in the document

    # Give every chunk a unique, ordered id: chunk-001, chunk-002, ...
    for number, chunk in enumerate(chunks, start=1):
        chunk["id"] = f"chunk-{number:03d}"

    return chunks


def write_chunks(chunks: list[dict], output_dir: Path = OUTPUT_DIR) -> Path:
    """Save the chunks as a UTF-8 JSON file and return its path."""
    output_dir.mkdir(parents=True, exist_ok=True)   # create folder if missing
    path = output_dir / "chunks.json"

    # encoding="utf-8" matters on Windows: the default encoding cannot write
    # the square symbol the PDF's tick and cross icons turn into.
    with open(path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, indent=2, ensure_ascii=False)
    return path


def main() -> None:
    """Command-line entry point: read the PDF, chunk it, save, print a summary."""
    parser = argparse.ArgumentParser(description="Split a policy wording PDF into clause chunks.")
    parser.add_argument("pdf", nargs="?", type=Path, default=DEFAULT_PDF,
                        help="path to the policy wording PDF (optional)")
    args = parser.parse_args()

    chunks = parse_chunks(extract_lines(args.pdf))
    path = write_chunks(chunks)

    tables = sum(c["type"] == "table" for c in chunks)
    print(f"{len(chunks)} chunks ({tables} table) written to {path}")

    # Print one sample clause so you can check the result by eye.
    for c in chunks:
        if c["clause"] == "4.3":
            print(f"\n{c['id']} | {c['section']} | clause {c['clause']}\n{c['text']}")


# This block runs only when the file is executed directly
# (not when another file imports it, for example in tests).
if __name__ == "__main__":
    main()
