"""Gemini-based metadata extraction from research paper PDFs.

All heavy lifting is in pure functions; callers configure model names,
rate-limits, paths, and API clients themselves.

Version history
---------------
1 – first-page image only; flat author list; no references.
2 – full PDF input; structured AuthorInfo (dept/institution/email);
    reference list; ML methods; per-paper JSON output with resume support.
3 – constraint-driven topic/keyword extraction window; references removed.
"""

import json
import os
from io import BytesIO
from pathlib import Path
from typing import Optional

from google import genai
from google.genai import types
from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter

# ---------------------------------------------------------------------------
# Extraction version — bump this to force re-extraction of already-processed
# papers (any saved JSON with a lower version will be overwritten).
# ---------------------------------------------------------------------------

EXTRACTION_VERSION = 3

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "metadata_extraction_evaluation" / "papers"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output_data" / "gemini_extracted_data" / "metadata_output"

load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

METADATA_PROMPT = """
You are an academic metadata extraction system.

From the full text of a research paper (provided as a PDF), extract the
following metadata.  If a field cannot be found, return null or an empty list
as appropriate.

For topic/keyword-focused fields (keywords, generated_keywords, ml_methods),
use this evidence policy:
1) Primary evidence: Title + Abstract + Introduction.
2) Scope window: first 4 pages as the safe default context window.
3) Fallback: if the Introduction is weak/missing/generic, use
    Title + Abstract + Conclusion, but only when the Conclusion clearly
    summarizes the paper's core contributions.
4) Prefer high-precision terms; avoid generic filler keywords.
5) Return exactly six items for generated_keywords when possible.
6) Do not infer information beyond what is explicitly stated in the provided
    content.
7) Only include ML/AI methods explicitly mentioned in the provided content.

Return structured JSON matching the schema exactly.
"""

# ---------------------------------------------------------------------------
# Pydantic schema (used for structured output)
# ---------------------------------------------------------------------------


class AuthorInfo(BaseModel):
    name: Optional[str] = Field(default=None, description="Full name of the author")
    department: Optional[str] = Field(
        default=None,
        description="Department or faculty the author belongs to",
    )
    institution: Optional[str] = Field(
        default=None,
        description="University, research institute, or company name",
    )
    email: Optional[str] = Field(
        default=None, description="Contact e-mail address of the author"
    )


class PaperMetadata(BaseModel):
    version: int = Field(
        default=EXTRACTION_VERSION,
        description="Schema/extraction version — do not modify",
    )
    doi: Optional[str] = Field(default=None, description="DOI of the paper")
    arxiv_id: Optional[str] = Field(default=None, description="arXiv identifier")
    title: Optional[str] = Field(default=None, description="Full paper title")
    authors: list[AuthorInfo] = Field(
        default_factory=list,
        description="Structured list of authors with affiliation and contact details",
    )
    year: Optional[str] = Field(default=None, description="Publication year")
    keywords: list[str] = Field(
        default_factory=list, description="Keywords listed in the paper"
    )
    generated_keywords: list[str] = Field(
        default_factory=list,
        description="Ten keywords inferred from the title, abstract, and introduction",
    )
    ml_methods: list[str] = Field(
        default_factory=list,
        description="Machine-learning or AI methods / models used in the paper",
    )


# ---------------------------------------------------------------------------
# Gemini extraction
# ---------------------------------------------------------------------------


def extract_first_n_pages(pdf_path: Path, n: int = 4) -> bytes:
    """Return a PDF byte stream containing only the first *n* pages."""
    reader = PdfReader(pdf_path)
    writer = PdfWriter()

    for i in range(min(n, len(reader.pages))):
        writer.add_page(reader.pages[i])

    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def extract_metadata_from_pdf(
    pdf_path: Path,
    client: genai.Client,
    model_name: str = "gemini-3-flash-preview",
) -> PaperMetadata:
    """Extract structured metadata from a full PDF.

    Sends the first four pages of the PDF (safe default context window) to
    Gemini and uses google-genai structured output (Pydantic
    ``response_schema``) to parse the response directly into a
    :class:`PaperMetadata` instance.
    """
    # Extracting metadata: send a 4-page PDF window instead of rasterized images.
    pdf_bytes = extract_first_n_pages(pdf_path, n=4)
    pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")

    # Gemini structured output: constrain the response to the PaperMetadata schema.
    response = client.models.generate_content(
        model=model_name,
        contents=[METADATA_PROMPT, pdf_part],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=PaperMetadata,
        ),
    )

    return response.parsed


# ---------------------------------------------------------------------------
# Per-paper JSON helpers
# ---------------------------------------------------------------------------


def paper_json_path(output_dir: Path, pdf_path: Path) -> Path:
    """Return the path where the per-paper JSON result should be stored."""
    # Saving metadata: each PDF gets its own JSON file named after pdf_path.stem.
    return output_dir / f"{pdf_path.stem}.json"


def already_extracted(output_dir: Path, pdf_path: Path) -> bool:
    """Return True if a valid, up-to-date extraction result already exists."""
    json_path = paper_json_path(output_dir, pdf_path)
    if not json_path.exists():
        return False
    try:
        with open(json_path, encoding="utf-8") as fh:
            record = json.load(fh)
        return record.get("version", 0) >= EXTRACTION_VERSION
    except Exception:
        return False


def save_paper_result(output_dir: Path, pdf_path: Path, record: dict) -> None:
    """Write *record* to the per-paper JSON file."""
    json_path = paper_json_path(output_dir, pdf_path)
    # Saving metadata: persist final record (success or error) for resume/debug.
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Single-paper processing
# ---------------------------------------------------------------------------


def process_paper(
    pdf_path: Path,
    client: genai.Client,
    output_dir: Path,
    model_name: str = "gemini-3-flash-preview",
) -> dict:
    """Extract metadata for a single PDF and save the result to *output_dir*.

    If an up-to-date JSON already exists for this PDF it is loaded and returned
    immediately without hitting the API.

    Returns a dict with either the parsed metadata fields plus ``source_file``,
    or ``error`` fields when extraction fails.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Resume support: skip API calls when an up-to-date JSON already exists.
    if already_extracted(output_dir, pdf_path):
        with open(paper_json_path(output_dir, pdf_path), encoding="utf-8") as fh:
            return json.load(fh)

    try:
        # Extracting metadata from the full PDF, then convert to plain dict for JSON.
        metadata = extract_metadata_from_pdf(pdf_path, client, model_name)
        record = metadata.model_dump()
        record["source_file"] = pdf_path.name
    except Exception as error:
        # Save errors as structured output so batch runs can continue.
        record = {
            "version": EXTRACTION_VERSION,
            "source_file": pdf_path.name,
            "error": str(error),
        }

    save_paper_result(output_dir, pdf_path, record)
    return record


def process_all_papers(
    client: genai.Client,
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    model_name: str = "gemini-3-flash-preview",
) -> list[dict]:
    """Process every PDF in *input_dir* and save per-paper JSON to *output_dir*."""
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for pdf_path in sorted(input_dir.iterdir()):
        if pdf_path.suffix.lower() != ".pdf":
            continue
        results.append(process_paper(pdf_path, client, output_dir, model_name))

    return results


if __name__ == "__main__":
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=api_key)
    process_all_papers(client)