# This script has a more robust extraction for year, compared to extractor_1.py, including multiple fallback methods. It also includes better error handling and logging for debugging purposes.
import os
import requests
import json
import time
from lxml import etree
from tqdm import tqdm
import re

# ================= CONFIG =================
GROBID_URL = "http://localhost:8070/api/processFulltextDocument"
PDF_FOLDER = "data/sample_papers"
OUTPUT_FILE = "output_data/grobid_extracted/metadata_output.json"

# ================= EXTRACTION =================

def extract_metadata(pdf_path):
    try:
        with open(pdf_path, "rb") as f:
            files = {
                "input": (os.path.basename(pdf_path), f, "application/pdf")
            }

            response = requests.post(GROBID_URL, files=files)

        if response.status_code == 200 and response.text.strip():
            return response.text
        else:
            print(f"[ERROR] Empty or bad response: {pdf_path}")
            print(f"Status Code: {response.status_code}")
            print(f"Response: {response.text[:200]}")
            return None

    except Exception as e:
        print(f"[EXCEPTION] {pdf_path}: {e}")
        return None

# ================= PARSING =================

def parse_tei(xml_text, file_name=None):
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    
    # === Basic validation ===
    if not xml_text or not xml_text.strip().startswith("<"):
        print("[WARNING] Invalid XML received")
        return None

    try:
        root = etree.fromstring(xml_text.encode())
    except Exception as e:
        print(f"[XML ERROR] {e}")
        return None

    # -------- Title --------
    title = root.xpath("//tei:titleStmt/tei:title/text()", namespaces=ns)
    title = title[0].strip() if title else None

    # -------- Abstract --------
    abstract = root.xpath("//tei:abstract//text()", namespaces=ns)
    abstract = " ".join([t.strip() for t in abstract if t.strip()]) if abstract else None

    # -------- Authors --------
    authors = []
    for author in root.xpath("//tei:teiHeader//tei:author", namespaces=ns):
        first_names = author.xpath(".//tei:forename/text()", namespaces=ns)
        last_names = author.xpath(".//tei:surname/text()", namespaces=ns)
        full_name = " ".join(first_names + last_names).strip()
        if full_name:
            authors.append(full_name)

        # ----- Apply cleaning ------
    authors = clean_authors(authors)

    # -------- Keywords --------
    keywords = root.xpath("//tei:keywords//tei:term/text()", namespaces=ns)
    keywords = [k.strip().lower() for k in keywords if k.strip()]
    
        # ----- Apply cleaning ------
    keywords = clean_keywords(keywords)

    # -------- Year --------
    year = None

    # Try extracting from filename (arXiv style)
    if file_name and file_name[:2].isdigit():
        year = int("20" + file_name[:2])

    # Try TEI <publicationStmt>
    if year is None:
        year = extract_year_from_publication_stmt(root)

    # Fallback: extract from XML text (footer/header)
    if year is None:
        year = extract_year_from_text(xml_text)

    return {
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "keywords": keywords,
        "year": year,
        "file_name": file_name
    }


# ================= CLEANING AUTHORS =================
def clean_authors(authors):
    cleaned = []

    org_keywords = ["university", "institute", "lab", "labs", "ai", "team", "group", "college", "department", "center", "centre"]

    for name in authors:
        name_lower = name.lower().strip()

        # Rule 1: Remove very short names
        if len(name.split()) < 2:
            continue

        # Rule 2: Remove all-uppercase / org-like
        if name.isupper() or sum(1 for c in name if c.isupper()) > len(name)/2:
            continue

        # Rule 3: Remove organization-like names
        if any(k in name_lower for k in org_keywords):
            continue

        # Rule 4: Remove names ending with common org abbreviations
        org_abbr = ["uc", "mit", "csail", "stanford", "cmu", "eth", "ibm", "google", "deepmind"]
        if any(abbr in name_lower.split() for abbr in org_abbr):
            continue

        cleaned.append(name)

    # Remove duplicates
    return list(set(cleaned))

# ================= CLEANING KEYWORDS =================

def clean_keywords(keywords):
    stopwords = {"and", "or", "the", "full", "form", "abbreviations"}
    cleaned = []
    
    for kw in keywords:
        # split multi-word concatenations if needed
        parts = kw.replace(",", " ").split()
        parts = [p for p in parts if p.lower() not in stopwords]

        if 0 < len(parts) <= 6:  # keep phrases with 1–6 words
            cleaned.append(" ".join(parts))

    # remove duplicates
    return list(set(cleaned))

# ================= YEAR EXTRACTION =================

def extract_year_from_text(xml_text):
    """Fallback: search for a 4-digit year in the whole XML text"""
    years = re.findall(r"(?:19|20)\d{2}", xml_text)
    if years:
        return int(years[0])
    return None

def extract_year_from_publication_stmt(root):
    """Try to extract the year from TEI <publicationStmt>/<date> if present"""
    ns = {"tei": "http://www.tei-c.org/ns/1.0"}
    date_text = root.xpath("//tei:publicationStmt//tei:date/text()", namespaces=ns)
    if date_text:
        match = re.search(r"(?:19|20)\d{2}", date_text[0])
        if match:
            return int(match.group())
    return None

# ================= MAIN PIPELINE =================

def process_folder():
    results = []
    failed_files = []

    pdf_files = [f for f in os.listdir(PDF_FOLDER) if f.endswith(".pdf")]

    print(f"\nProcessing {len(pdf_files)} PDFs...\n")

    for pdf_file in tqdm(pdf_files):
        path = os.path.join(PDF_FOLDER, pdf_file)

        file_name = os.path.basename(pdf_file)

        xml = extract_metadata(path)
        if xml:
            data = parse_tei(xml, file_name)

            if data and data.get("title"):
                data["file_name"] = pdf_file
                results.append(data)
            else:
                print(f"[SKIPPED] Parsing failed: {pdf_file}")
                failed_files.append(pdf_file)
        else:
            print(f"[SKIPPED] Extraction failed: {pdf_file}")
            failed_files.append(pdf_file)

        # Prevent overloading GROBID
        time.sleep(1)

    print("\nFailed files:")
    for f in failed_files:
        print(f)

    return results


# ================= SAVE =================

def save_results(data):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print(f"\nSaved results to {OUTPUT_FILE}")


# ================= RUN =================

if __name__ == "__main__":
    metadata = process_folder()
    save_results(metadata)

    # For quick testing of the extraction function on a single file:
#if __name__ == "__main__":
#    test_file = "data/sample_papers/2506.08388v3.pdf"  # use one of your PDFs

#    xml = extract_metadata(test_file)

#    if xml:
#        print("\n--- FIRST 500 CHARACTERS OF RESPONSE ---\n")
#        print(xml[:500])
#    else:
#        print("No response received.")