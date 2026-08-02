"""GROBID-based metadata extraction from research paper PDFs.

Requires a running GROBID server (default: http://localhost:8070).
Extracts title, authors, doi, year, keywords, and abstract by parsing 
the TEI-XML response from GROBID's processHeaderDocument endpoint.
"""

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
import requests
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

EXTRACTION_VERSION = 5

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "papers"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output_data" / "grobid_extracted_slaai"

GROBID_URL = "http://localhost:8070/api/processHeaderDocument"

# TEI XML namespace used by GROBID
NS = {'tei': 'http://www.tei-c.org/ns/1.0'}

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class PaperMetadata(BaseModel):
    version: int = Field(default=EXTRACTION_VERSION)
    doi: Optional[str] = Field(default=None)
    title: Optional[str] = Field(default=None)
    authors: list[str] = Field(default_factory=list)
    year: Optional[str] = Field(default=None)
    keywords: list[str] = Field(default_factory=list)
    abstract: Optional[str] = Field(default=None)

# ---------------------------------------------------------------------------
# GROBID Extraction & Parsing
# ---------------------------------------------------------------------------

def parse_tei_xml(xml_content: bytes) -> PaperMetadata:
    """Parse the TEI-XML returned by GROBID into our Pydantic schema."""
    root = ET.fromstring(xml_content)
    
    # Extract Title
    title_node = root.find('.//tei:titleStmt/tei:title[@level="a"]', NS)
    title = title_node.text.strip() if title_node is not None and title_node.text else None

    # Extract DOI
    doi_node = root.find('.//tei:idno[@type="DOI"]', NS)
    doi = doi_node.text.strip() if doi_node is not None and doi_node.text else None

    # Extract Year
    date_node = root.find('.//tei:publicationStmt/tei:date[@type="published"]', NS)
    year = None
    if date_node is not None and 'when' in date_node.attrib:
        year = date_node.attrib['when'][:4]  # Extract YYYY

    # Extract Abstract
    abstract_node = root.find('.//tei:profileDesc/tei:abstract', NS)
    abstract = None
    if abstract_node is not None:
        # Join all text nodes inside the abstract to handle nested <p> or formatting tags
        abstract = " ".join(abstract_node.itertext()).strip()
        # Clean up excessive whitespaces
        abstract = " ".join(abstract.split())

    # Extract Keywords
    keywords = []
    for term in root.findall('.//tei:profileDesc/tei:textClass/tei:keywords/tei:term', NS):
        if term.text:
            keywords.append(term.text.strip())

    # Extract Authors
    authors = []
    author_nodes = root.findall('.//tei:sourceDesc/tei:biblStruct/tei:analytic/tei:author/tei:persName', NS)
    for author_node in author_nodes:
        first = author_node.find('tei:forename', NS)
        last = author_node.find('tei:surname', NS)
        
        first_name = first.text.strip() if first is not None and first.text else ""
        last_name = last.text.strip() if last is not None and last.text else ""
        
        full_name = f"{first_name} {last_name}".strip()
        if full_name:
            authors.append(full_name)

    return PaperMetadata(
        doi=doi,
        title=title,
        authors=authors,
        year=year,
        keywords=keywords,
        abstract=abstract
    )

def extract_metadata_with_grobid(pdf_path: Path) -> PaperMetadata:
    """Send a PDF to the local GROBID server and parse the result."""
    with open(pdf_path, 'rb') as f:
        files = {'input': (pdf_path.name, f, 'application/pdf')}
        # processHeaderDocument is extremely fast as it only processes the first few pages
        response = requests.post(GROBID_URL, files=files, timeout=30)
        
    response.raise_for_status()
    return parse_tei_xml(response.content)

# ---------------------------------------------------------------------------
# I/O Helpers
# ---------------------------------------------------------------------------

def paper_json_path(output_dir: Path, pdf_path: Path) -> Path:
    return output_dir / f"{pdf_path.stem}.json"

def already_extracted(output_dir: Path, pdf_path: Path) -> bool:
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
    json_path = paper_json_path(output_dir, pdf_path)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(record, fh, indent=2, ensure_ascii=False)

# ---------------------------------------------------------------------------
# Single-paper processing
# ---------------------------------------------------------------------------

def process_paper(pdf_path: Path, output_dir: Path) -> dict:
    if already_extracted(output_dir, pdf_path):
        print(f"   ⏩ Skipping {pdf_path.name} (already extracted)")
        with open(paper_json_path(output_dir, pdf_path), encoding="utf-8") as fh:
            return json.load(fh)

    try:
        metadata = extract_metadata_with_grobid(pdf_path)
        record = metadata.model_dump()
        record["source_file"] = pdf_path.name
        print(f"   ✅ Success!")
    except requests.exceptions.ConnectionError:
        print(f"   ❌ Connection Error: Is GROBID running at {GROBID_URL}?")
        raise
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
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)

    if not input_dir.exists():
        print(f"Error: Input directory does not exist: {input_dir}")
        return []

    pdf_files = [p for p in sorted(input_dir.rglob("*")) if p.is_file() and p.suffix.lower() == ".pdf"]
    print(f"Found {len(pdf_files)} PDF file(s) in {input_dir}")

    results = []
    # No sleep required for GROBID — it will run as fast as your CPU allows.
    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"[{i}/{len(pdf_files)}] Processing {pdf_path.name}...")
        record = process_paper(pdf_path, output_dir)
        results.append(record)

    print("\n🎉 Batch processing complete!")
    return results

if __name__ == "__main__":
    print("Starting GROBID metadata extraction...")
    process_all_papers()