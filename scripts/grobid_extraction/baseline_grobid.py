import os
import json
import time
from pathlib import Path
import requests
from lxml import etree

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# ================= CONFIG =================

GROBID_BASE_URL = os.environ.get("GROBID_BASE_URL", "http://localhost:8070")
GROBID_URL = f"{GROBID_BASE_URL}/api/processFulltextDocument"
GROBID_ALIVE_URL = f"{GROBID_BASE_URL}/api/isalive"
PDF_FOLDER = PROJECT_ROOT / "data" / "metadata_extraction_evaluation" / "papers"
GROBID_REQUEST_TIMEOUT_SECONDS = int(
    os.environ.get("GROBID_REQUEST_TIMEOUT_SECONDS", "180")
)

# Folder instead of single JSON file
# OUTPUT_FOLDER = PROJECT_ROOT / "output_data" / "grobid_baseline_output"       # baseline with 0.8.0
OUTPUT_FOLDER = PROJECT_ROOT / "output_data" / "grobid_baseline_output_latest"  # baseline with latest GROBID (0.9.1)
GROBID_READY_TIMEOUT_SECONDS = 300
GROBID_READY_POLL_SECONDS = 5


def is_grobid_available():
    try:
        response = requests.get(GROBID_ALIVE_URL, timeout=5)
        return response.ok
    except requests.RequestException:
        return False


def wait_for_grobid_ready():
    elapsed_seconds = 0

    while elapsed_seconds < GROBID_READY_TIMEOUT_SECONDS:
        if is_grobid_available():
            return True

        print(
            f"Waiting for GROBID at {GROBID_BASE_URL}... "
            f"retrying in {GROBID_READY_POLL_SECONDS}s"
        )
        time.sleep(GROBID_READY_POLL_SECONDS)
        elapsed_seconds += GROBID_READY_POLL_SECONDS

    return False

def extract_metadata(pdf_path):
    try:
        with open(pdf_path, "rb") as f:

            files = {
                "input": (os.path.basename(pdf_path), f, "application/pdf")
            }

            response = requests.post(
                GROBID_URL,
                files=files,
                timeout=GROBID_REQUEST_TIMEOUT_SECONDS,
            )

    except requests.RequestException as exc:
        print(f"GROBID request failed for {pdf_path}: {exc}")
        return None

    if response.status_code == 200:
        return response.text

    print(
        f"GROBID returned status {response.status_code} for {pdf_path}: "
        f"{response.text[:200]}"
    )
    return None

# ================= PARSE TEI XML =================

def parse_tei(xml_text):

    ns = {"tei": "http://www.tei-c.org/ns/1.0"}

    try:
        root = etree.fromstring(xml_text.encode())
    except Exception as e:
        print(f"XML Parsing Error: {e}")
        return None

    # -------- Title --------
    title = root.xpath("//tei:titleStmt/tei:title/text()", namespaces=ns)
    title = title[0].strip() if title else None

    # -------- DOI --------
    doi = root.xpath("//tei:idno[@type='DOI']/text()", namespaces=ns)
    doi = doi[0].strip() if doi else None

    # -------- Authors --------
    authors = []

    for author in root.xpath("//tei:teiHeader//tei:author", namespaces=ns):

        first_names = author.xpath(".//tei:forename/text()", namespaces=ns)
        surnames = author.xpath(".//tei:surname/text()", namespaces=ns)

        full_name = " ".join(first_names + surnames).strip()

        if full_name:
            authors.append(full_name)

    # -------- Abstract --------
    abstract = root.xpath("//tei:abstract//text()", namespaces=ns)

    abstract = " ".join(
        [text.strip() for text in abstract if text.strip()]
    ) if abstract else None

    # -------- Keywords --------
    keywords = root.xpath("//tei:keywords//tei:term/text()", namespaces=ns)

    keywords = [k.strip() for k in keywords if k.strip()]

    # -------- Year --------
    year = root.xpath("//tei:publicationStmt//tei:date/text()", namespaces=ns)

    year = year[0].strip() if year else None

    return {
        "title": title,
        "doi": doi,
        "authors": authors,
        "abstract": abstract,
        "keywords": keywords,
        "year": year
    }

# ================= PROCESS PDF FOLDER =================

def process_folder():

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)

    if not wait_for_grobid_ready():
        print(
            "GROBID is not reachable at "
            f"{GROBID_BASE_URL}. Start the Docker container first, "
            "or set GROBID_BASE_URL to a running server."
        )
        return

    pdf_files = [
        f for f in os.listdir(PDF_FOLDER)
        if f.endswith(".pdf")
    ]

    print(f"Processing {len(pdf_files)} PDFs...")

    for pdf_file in pdf_files:

        pdf_path = os.path.join(PDF_FOLDER, pdf_file)

        print(f"\nProcessing: {pdf_file}")

        xml = extract_metadata(pdf_path)

        if not xml:
            print(f"Failed extraction: {pdf_file}")
            continue

        parsed_data = parse_tei(xml)

        if not parsed_data:
            print(f"Failed parsing: {pdf_file}")
            continue

        # Add source filename
        parsed_data["file_name"] = pdf_file

        # Create output JSON filename
        json_name = os.path.splitext(pdf_file)[0] + ".json"

        output_path = os.path.join(OUTPUT_FOLDER, json_name)

        # Save individual JSON
        with open(output_path, "w", encoding="utf-8") as f:

            json.dump(
                parsed_data,
                f,
                indent=4,
                ensure_ascii=False
            )

        print(f"Saved: {output_path}")

# ================= MAIN =================

if __name__ == "__main__":

    process_folder()