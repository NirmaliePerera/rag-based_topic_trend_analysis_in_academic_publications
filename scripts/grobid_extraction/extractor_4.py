# Uses papers from slaai conference
import os
import requests
import json
import time
from lxml import etree
from tqdm import tqdm
import re

EXTRACTION_VERSION = 1

# ================= CONFIG =================
GROBID_URL = "http://localhost:8070/api/processFulltextDocument"
# PDF_ROOT = "data/papers"
# OUTPUT_DIR = "output_data/grobid_extracted/slaai_output"
# OUTPUT_DIR = "output_data/grobid_extracted/metadata_output"

# New paths for evaluation
PDF_ROOT = "data/metadata_extraction_evaluation/papers"
OUTPUT_DIR = "output_data/Evaluation_Output/grobid_metadata_output"

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

    # -------- IDs --------
    doi = extract_idno(root, ns, ["DOI", "doi"])
    arxiv_id = extract_idno(root, ns, ["arXiv", "arxiv", "arXIV"])

    # -------- Authors (structured) --------
    authors = []
    for author in root.xpath("//tei:teiHeader//tei:author", namespaces=ns):
        first_names = author.xpath(".//tei:forename/text()", namespaces=ns)
        last_names = author.xpath(".//tei:surname/text()", namespaces=ns)
        full_name = " ".join([x.strip() for x in (first_names + last_names) if x.strip()]).strip()

        department = first_or_none(author.xpath(".//tei:orgName[@type='department']/text()", namespaces=ns))
        institution = first_or_none(author.xpath(".//tei:orgName[@type='institution']/text()", namespaces=ns))

        if not institution:
            institution = first_or_none(
                author.xpath(".//tei:affiliation//tei:orgName[not(@type) or @type='institution']/text()", namespaces=ns)
            )

        email = first_or_none(author.xpath(".//tei:email/text()", namespaces=ns))

        authors.append(
            {
                "name": full_name or None,
                "department": department,
                "institution": institution,
                "email": email,
            }
        )

    authors = clean_author_records(authors)

    # -------- Keywords --------
    keywords = root.xpath("//tei:keywords//tei:term/text()", namespaces=ns)
    keywords = [k.strip().lower() for k in keywords if k.strip()]

    keywords = clean_keywords(keywords)

    # -------- References --------
    references = extract_references(root, ns)

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
        "version": EXTRACTION_VERSION,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "title": title,
        "authors": authors,
        "year": str(year) if year is not None else None,
        "keywords": keywords,
        "generated_keywords": [],
        "ml_methods": [],
        "references": references,
        "source_file": file_name,
    }


# ================= CLEANING AUTHORS =================
def clean_author_records(authors):
    cleaned = []
    seen = set()

    org_keywords = [
        "university",
        "institute",
        "lab",
        "labs",
        "team",
        "group",
        "college",
        "department",
        "center",
        "centre",
    ]

    for author in authors:
        name = (author.get("name") or "").strip()
        if not name:
            continue

        name_lower = name.lower()

        # Skip records that look like organizations instead of people.
        if len(name.split()) < 2:
            continue
        if name.isupper() or sum(1 for c in name if c.isupper()) > len(name) / 2:
            continue
        if any(k in name_lower for k in org_keywords):
            continue

        key = (
            name_lower,
            (author.get("institution") or "").strip().lower(),
            (author.get("email") or "").strip().lower(),
        )
        if key in seen:
            continue

        seen.add(key)
        cleaned.append(
            {
                "name": name,
                "department": normalize_text(author.get("department")),
                "institution": normalize_text(author.get("institution")),
                "email": normalize_text(author.get("email")),
            }
        )

    return cleaned

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


def first_or_none(values):
    for value in values:
        v = value.strip()
        if v:
            return v
    return None


def normalize_text(value):
    if value is None:
        return None
    value = str(value).strip()
    return value if value else None


def extract_idno(root, ns, id_types):
    for id_type in id_types:
        values = root.xpath(f"//tei:idno[@type='{id_type}']/text()", namespaces=ns)
        value = first_or_none(values)
        if value:
            return value

    all_idnos = root.xpath("//tei:idno/text()", namespaces=ns)
    for value in all_idnos:
        cleaned = value.strip()
        if not cleaned:
            continue
        if any(token.lower() in cleaned.lower() for token in id_types):
            return cleaned

    return None


def extract_references(root, ns):
    references = []

    for bibl in root.xpath("//tei:listBibl//tei:biblStruct", namespaces=ns):
        ref_authors = []
        for author in bibl.xpath(".//tei:analytic//tei:author", namespaces=ns):
            first_names = author.xpath(".//tei:forename/text()", namespaces=ns)
            last_names = author.xpath(".//tei:surname/text()", namespaces=ns)
            full_name = " ".join([x.strip() for x in (first_names + last_names) if x.strip()]).strip()
            if full_name:
                ref_authors.append(full_name)

        title = first_or_none(bibl.xpath(".//tei:analytic/tei:title/text()", namespaces=ns))
        if not title:
            title = first_or_none(bibl.xpath(".//tei:monogr/tei:title/text()", namespaces=ns))

        journal = first_or_none(
            bibl.xpath(
                ".//tei:monogr/tei:title[@level='j' or @level='m' or @type='journal']/text()",
                namespaces=ns,
            )
        )
        if not journal:
            journal = first_or_none(bibl.xpath(".//tei:monogr/tei:title/text()", namespaces=ns))

        ref_year = first_or_none(bibl.xpath(".//tei:date/@when", namespaces=ns))
        if not ref_year:
            ref_year = first_or_none(bibl.xpath(".//tei:date/text()", namespaces=ns))
        if ref_year:
            match = re.search(r"(?:19|20)\d{2}", ref_year)
            ref_year = match.group() if match else None

        if ref_authors or title or journal or ref_year:
            references.append(
                {
                    "authors": ref_authors,
                    "title": title,
                    "journal": journal,
                    "year": ref_year,
                }
            )

    return references

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

def paper_json_path(pdf_file):
    rel_path = os.path.relpath(pdf_file, PDF_ROOT)
    rel_json = os.path.splitext(rel_path)[0] + ".json"
    return os.path.join(OUTPUT_DIR, rel_json)


def save_paper_result(data, pdf_file):
    output_path = paper_json_path(pdf_file)

    if os.path.exists(output_path):
        print(f"[SKIPPED] Already exists: {output_path}")
        return False

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

    print(f"[SAVED] {output_path}")
    return True

def process_folder():
    failed_files = []
    skipped_existing = 0
    saved_count = 0

    pdf_files = []
    for root, _, files in os.walk(PDF_ROOT):
        for file_name in files:
            if file_name.lower().endswith(".pdf"):
                pdf_files.append(os.path.join(root, file_name))

    pdf_files.sort()

    print(f"\nProcessing {len(pdf_files)} PDFs from {PDF_ROOT}...\n")

    for pdf_file in tqdm(pdf_files):
        rel_pdf = os.path.relpath(pdf_file, PDF_ROOT)

        if os.path.exists(paper_json_path(pdf_file)):
            skipped_existing += 1
            print(f"[SKIPPED] Already extracted: {rel_pdf}")
            continue

        file_name = os.path.basename(pdf_file)

        xml = extract_metadata(pdf_file)
        if xml:
            data = parse_tei(xml, file_name)

            if data and data.get("title"):
                data["source_file"] = rel_pdf
                if save_paper_result(data, pdf_file):
                    saved_count += 1
            else:
                print(f"[SKIPPED] Parsing failed: {rel_pdf}")
                failed_files.append(rel_pdf)
        else:
            print(f"[SKIPPED] Extraction failed: {rel_pdf}")
            failed_files.append(rel_pdf)

        # Prevent overloading GROBID
        time.sleep(1)

    print("\nFailed files:")
    for f in failed_files:
        print(f)

    print(f"\nSummary: saved={saved_count}, skipped_existing={skipped_existing}, failed={len(failed_files)}")

    return {
        "saved": saved_count,
        "skipped_existing": skipped_existing,
        "failed": failed_files,
    }


# ================= RUN =================

if __name__ == "__main__":
    process_folder()

    # For quick testing of the extraction function on a single file:
#if __name__ == "__main__":
#    test_file = "data/sample_papers/2506.08388v3.pdf"  # use one of your PDFs

#    xml = extract_metadata(test_file)

#    if xml:
#        print("\n--- FIRST 500 CHARACTERS OF RESPONSE ---\n")
#        print(xml[:500])
#    else:
#        print("No response received.")