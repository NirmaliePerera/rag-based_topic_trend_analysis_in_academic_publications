"""Gemini-based metadata extraction from research paper PDFs.

All heavy lifting is in pure functions; callers configure model names,
rate-limits, paths, and API clients themselves.

Version history
---------------
1 - first-page image only; flat author list; no references.
2 - full PDF input; structured AuthorInfo (dept/institution/email);
    reference list; ML methods; per-paper JSON output with resume support.
3 - constraint-driven topic/keyword extraction window; references removed.
4 - full PDF context with strict attention window (Abstract/Intro/Discussion); 
    simplified schema (names only, specific fields removed).
5 - improved prompt and schema; more robust error handling; retry logic for
    rate-limited API calls; per-paper JSON output with resume support.
"""

import time
import json
import os
from pathlib import Path
from typing import Optional
from io import BytesIO
from pypdf import PdfReader, PdfWriter
from google import genai
from google.genai import types
from google.genai import errors
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Extraction version — bump this to force re-extraction of already-processed
# papers (any saved JSON with a lower version will be overwritten).
# ---------------------------------------------------------------------------

EXTRACTION_VERSION = 5

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "papers"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output_data" / "gemini_extracted_data" / "gemini_extracted_slaai"

load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

METADATA_PROMPT = """
You are an academic metadata extraction system.

You are provided with the initial pages of a research paper PDF. From this text, 
extract the requested metadata fields. If a field cannot be found, return null 
or an empty list as appropriate.

FIELD-SPECIFIC GUIDANCE:
1) `title`: The full title of the paper. Ignore journal names, running headers, or conference banners.
2) `authors`: Extract author names as a list of strings (e.g., ["Jane Doe", "John Smith"]). Exclude affiliations, emails, or degrees.
3) `doi`: Extract the digital object identifier if present (e.g., "10.1016/..."). Check headers, footers, and margins.
4) `year`: The 4-digit publication or copyright year. Check headers, footers, or publication metadata notices.
5) `keywords`: Author-defined keywords explicitly listed under headings such as "Keywords", "Index Terms", "Key Words", or "Subject Categories".
6) `abstract`: Extract the verbatim text of the Abstract. Preserve exact wording without summarizing. If formatted across multiple columns, join the text into a single clean paragraph without stray line breaks.

Return structured JSON matching the schema exactly.
"""

# ---------------------------------------------------------------------------
# Pydantic schema (used for structured output)
# ---------------------------------------------------------------------------

class PaperMetadata(BaseModel):
    version: int = Field(
        default=EXTRACTION_VERSION,
        description="Schema/extraction version — do not modify",
    )
    doi: Optional[str] = Field(default=None, description="DOI of the paper")
    title: Optional[str] = Field(default=None, description="Full paper title")
    authors: list[str] = Field(
        default_factory=list,
        description="List of author names (e.g., ['Jane Doe', 'John Smith'])",
    )
    year: Optional[str] = Field(default=None, description="Publication year")
    keywords: list[str] = Field(
        default_factory=list, description="Author-defined keywords explicitly listed in the paper"
    )
    abstract: Optional[str] = Field(
        default=None, description="The verbatim text of the paper's abstract"
    )

# ---------------------------------------------------------------------------
# Gemini extraction
# ---------------------------------------------------------------------------

def extract_first_n_pages(pdf_path: Path, n: int = 2) -> bytes:
    """Return a PDF byte stream containing only the first *n* pages."""
    reader = PdfReader(pdf_path)
    writer = PdfWriter()

    for i in range(min(n, len(reader.pages))):
        writer.add_page(reader.pages[i])

    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()

def extract_metadata_from_pdf_with_retry(
    pdf_path: Path, 
    client: genai.Client, 
    model_name: str = "gemini-3.5-flash", 
    max_retries: int = 5
) -> PaperMetadata:
    """Extracts metadata with automatic retries for 429 (Resource Exhausted) errors."""
    pdf_bytes = extract_first_n_pages(pdf_path, n=2)
    pdf_part = types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")
    
    for attempt in range(1, max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=[METADATA_PROMPT, pdf_part],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=PaperMetadata,
                    temperature=0.1,
                ),
            )
            return response.parsed
            
        except errors.APIError as e:
            if e.code == 429 or "RESOURCE_EXHAUSTED" in str(e):
                if attempt == max_retries:
                    print(f"   ❌ Max retries reached for {pdf_path.name}.")
                    raise e
                
                wait_time = 15 * (2 ** (attempt - 1))
                print(f"   ⚠️ Rate limit hit. Waiting {wait_time}s before attempt {attempt + 1}/{max_retries}...")
                time.sleep(wait_time)
            else:
                raise e
        except Exception as e:
            print(f"   ❌ Unexpected error on {pdf_path.name}: {e}")
            raise e
            
    return None

# ---------------------------------------------------------------------------
# Per-paper JSON helpers
# ---------------------------------------------------------------------------

def paper_json_path(output_dir: Path, pdf_path: Path) -> Path:
    """Return the path where the per-paper JSON result should be stored."""
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
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)

# ---------------------------------------------------------------------------
# Single-paper processing
# ---------------------------------------------------------------------------

def process_paper(
    pdf_path: Path,
    client: genai.Client,
    output_dir: Path,
    model_name: str = "gemini-3.5-flash",
) -> dict:
    """Extract metadata for a single PDF and save the result to *output_dir*."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Resume support: skip API calls when an up-to-date JSON already exists.
    if already_extracted(output_dir, pdf_path):
        print(f"   ⏩ Skipping {pdf_path.name} (already extracted)")
        with open(paper_json_path(output_dir, pdf_path), encoding="utf-8") as fh:
            return json.load(fh)

    try:
        metadata = extract_metadata_from_pdf_with_retry(pdf_path, client, model_name)
        if metadata is None:
            raise RuntimeError("Extraction returned empty result")
        record = metadata.model_dump()
        record["source_file"] = pdf_path.name
        print(f"   ✅ Success!")
    except Exception as error:
        record = {
            "version": EXTRACTION_VERSION,
            "source_file": pdf_path.name,
            "error": str(error),
        }
        print(f"   ❌ Error: {error}")

    save_paper_result(output_dir, pdf_path, record)
    return record

# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def process_all_papers(
    client: genai.Client,
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    model_name: str = "gemini-3.5-flash",
) -> list[dict]:
    """Process every PDF in *input_dir* (including subfolders) and save per-paper JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_dir.exists():
        print(f"Error: Input directory does not exist: {input_dir}")
        return []

    # Recursively find all PDF files in subfolders
    pdf_files = [
        p for p in sorted(input_dir.rglob("*")) 
        if p.is_file() and p.suffix.lower() == ".pdf"
    ]
    print(f"Found {len(pdf_files)} PDF file(s) in {input_dir}")

    BASE_DELAY_SECONDS = 16
    results = []

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"[{i}/{len(pdf_files)}] Processing {pdf_path.name}...")
        
        is_cached = already_extracted(output_dir, pdf_path)
        record = process_paper(pdf_path, client, output_dir, model_name)
        results.append(record)

        # Only delay if an actual API call was made and there are remaining files
        if not is_cached and i < len(pdf_files):
            print(f"   ⏱️ Sleeping {BASE_DELAY_SECONDS}s to stay under RPM limit...")
            time.sleep(BASE_DELAY_SECONDS)

    print("\n🎉 Batch processing complete!")
    return results

if __name__ == "__main__":
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set")

    print("Starting metadata extraction...")
    client = genai.Client(api_key=api_key)
    process_all_papers(client)