import os
import json
import re
import requests
import time
import re
import fitz  # PyMuPDF
from lxml import etree
from collections import Counter

# ================= CONFIG =================

GROBID_URL = "http://localhost:8070/api/processFulltextDocument"

PDF_FOLDER = "data/metadata_extraction_evaluation/papers"

# Previous output folder (kept for reference)
# OUTPUT_FOLDER = "output_data/grobid_enhanced_output"
# OUTPUT_FOLDER = "output_data/grobid_year_enhanced_v2"

# New output folder for year-enhanced results
OUTPUT_FOLDER = "output_data/grobid_year_enhanced_v2_pdf_first"
# OUTPUT_FOLDER = "output_data/grobid_year_enhanced_v2_pdf_first_latest"


# ================= HELPERS =================

def normalize_text(text):

    if not text:
        return None

    text = str(text)

    # Remove extra whitespace
    text = re.sub(r"\s+", " ", text)

    return text.strip()


# def normalize_year(year_text):

#     if not year_text:
#         return None

#     match = re.search(r"(19|20)\d{2}", str(year_text))

#     if match:
#         return match.group()

#     return None


def clean_doi(doi):

    if not doi:
        return None

    doi = normalize_text(doi)

    doi = doi.replace("https://doi.org/", "")
    doi = doi.replace("http://doi.org/", "")
    doi = doi.replace("doi:", "")

    doi = doi.strip()

    # DOI regex
    match = re.search(
        r"10\.\d{4,9}/[-._;()/:A-Z0-9]+",
        doi,
        re.I
    )

    if match:
        return match.group()

    return doi


def clean_authors(authors):

    cleaned = []
    seen = set()

    for author in authors:

        name = normalize_text(author)

        if not name:
            continue

        # Remove very short names
        if len(name.split()) < 2:
            continue

        key = name.lower()

        if key in seen:
            continue

        seen.add(key)

        cleaned.append({
            "name": name
        })

    return cleaned


def clean_keywords(keywords):

    cleaned = []

    seen = set()

    for kw in keywords:

        kw = normalize_text(kw)

        if not kw:
            continue

        kw = kw.lower()

        if kw in seen:
            continue

        seen.add(kw)

        cleaned.append(kw)

    return cleaned


def compute_confidence(data):

    score = 0

    if data.get("title"):
        score += 0.25

    if data.get("doi"):
        score += 0.25

    if data.get("authors"):
        score += 0.25

    if data.get("year"):
        score += 0.25

    return round(score, 2)



def recover_year(root, xml_text, pdf_path):

    ns = {"tei": "http://www.tei-c.org/ns/1.0"}

    # -----------------------------
    # Priority 1:
    # publicationStmt date
    # -----------------------------

    date_text = root.xpath(
        "//tei:publicationStmt//tei:date/text()",
        namespaces=ns
    )

    if date_text:

        match = re.search(
            r"(19|20)\d{2}",
            date_text[0]
        )

        if match:
            return match.group(), "publicationStmt"

    # -----------------------------
    # Priority 2:
    # date/@when attributes
    # -----------------------------

    date_attrs = root.xpath(
        "//tei:date/@when",
        namespaces=ns
    )

    for d in date_attrs:

        match = re.search(
            r"(19|20)\d{2}",
            d
        )

        if match:
            return match.group(), "date_attribute"

    # -----------------------------
    # Priority 3:
    # PDF first-page recovery
    # -----------------------------

    pdf_year, pdf_source = recover_year_from_pdf(
        pdf_path
    )

    if pdf_year:
        return pdf_year, pdf_source

    # -----------------------------
    # Priority 4:
    # search entire TEI XML
    # -----------------------------

    years = re.findall(
        r"(?:19|20)\d{2}",
        xml_text
    )

    years = [
        int(y)
        for y in years
        if 1990 <= int(y) <= 2026
    ]

    if not years:
        return None, "not_found"

    # -----------------------------
    # most frequent year
    # -----------------------------

    year_counter = Counter(years)

    return (
        str(year_counter.most_common(1)[0][0]),
        "tei_fallback"
    )

# ================= FIRST PAGE EXTRACTION =================

def extract_first_page_text(pdf_path):

    try:

        doc = fitz.open(pdf_path)

        if len(doc) == 0:
            return ""

        page = doc[0]

        text = page.get_text("text")

        doc.close()

        return text

    except Exception as e:

        print(f"PDF text extraction error: {e}")

        return ""
# ================= YEAR RECOVERY =================

def recover_year_from_pdf(pdf_path):

    text = extract_first_page_text(pdf_path)

    if not text:
        return None, "not_found"

    years = re.findall(
        r"(?:19|20)\d{2}",
        text
    )

    if not years:
        return None, "not_found"

    years = [
        int(y)
        for y in years
        if 1990 <= int(y) <= 2026
    ]

    if not years:
        return None, "not_found"

    # Prefer most frequent year
    counter = Counter(years)

    best_year = counter.most_common(1)[0][0]

    return str(best_year), "pdf_first_page"

# ================= GROBID EXTRACTION =================

def extract_metadata(pdf_path):

    try:

        with open(pdf_path, "rb") as f:

            files = {
                "input": (
                    os.path.basename(pdf_path),
                    f,
                    "application/pdf"
                )
            }

            response = requests.post(
                GROBID_URL,
                files=files,
                timeout=120
            )

        if response.status_code == 200:
            return response.text

        print(f"HTTP Error: {response.status_code}")

        return None

    except Exception as e:

        print(f"Extraction Error: {e}")

        return None

# ================= PARSE + ENHANCE =================

def parse_tei(xml_text, pdf_path):

    ns = {"tei": "http://www.tei-c.org/ns/1.0"}

    try:
        root = etree.fromstring(xml_text.encode())

    except Exception as e:

        print(f"XML Parsing Error: {e}")

        return None

    # -------- TITLE --------

    title = root.xpath(
        "//tei:titleStmt/tei:title/text()",
        namespaces=ns
    )

    title = normalize_text(
        title[0]
    ) if title else None

    # -------- DOI --------

    doi = root.xpath(
        "//tei:idno[@type='DOI']/text()",
        namespaces=ns
    )

    doi = clean_doi(
        doi[0]
    ) if doi else None

    # -------- AUTHORS --------

    authors = []

    for author in root.xpath(
        "//tei:teiHeader//tei:author",
        namespaces=ns
    ):

        first_names = author.xpath(
            ".//tei:forename/text()",
            namespaces=ns
        )

        surnames = author.xpath(
            ".//tei:surname/text()",
            namespaces=ns
        )

        full_name = " ".join(
            first_names + surnames
        )

        authors.append(full_name)

    authors = clean_authors(authors)

    # -------- ABSTRACT --------

    abstract = root.xpath(
        "//tei:abstract//text()",
        namespaces=ns
    )

    abstract = (
        normalize_text(" ".join(abstract))
        if abstract else None
    )

    # -------- KEYWORDS --------

    keywords = root.xpath(
        "//tei:keywords//tei:term/text()",
        namespaces=ns
    )

    keywords = clean_keywords(keywords)

    # -------- YEAR --------

    #year = root.xpath(
     #   "//tei:publicationStmt//tei:date/text()",
      #  namespaces=ns
    #)

    #year = normalize_year(
    #    year[0]
    #) if year else None

    year, year_source = recover_year(
        root,
        xml_text,
        pdf_path
    )

    # -------- FINAL OUTPUT --------

    result = {
        "title": title,
        "doi": doi,
        "authors": authors,
        "abstract": abstract,
        "keywords": keywords,
        "year": year,
        "year_source": year_source
    }

    result["confidence_score"] = (
        compute_confidence(result)
    )

    return result

# ================= PROCESS FOLDER =================

def process_folder():

    os.makedirs(
        OUTPUT_FOLDER,
        exist_ok=True
    )

    pdf_files = [

        f for f in os.listdir(PDF_FOLDER)

        if f.endswith(".pdf")
    ]

    print(f"Processing {len(pdf_files)} PDFs...")

    for pdf_file in pdf_files:

        pdf_path = os.path.join(
            PDF_FOLDER,
            pdf_file
        )

        print(f"\nProcessing: {pdf_file}")

        xml = extract_metadata(pdf_path)

        if not xml:

            print(f"Failed extraction: {pdf_file}")

            continue

        parsed_data = parse_tei(
            xml,
            pdf_path
        )

        if not parsed_data:

            print(f"Failed parsing: {pdf_file}")

            continue

        parsed_data["source_file"] = pdf_file

        json_name = (
            os.path.splitext(pdf_file)[0]
            + ".json"
        )

        output_path = os.path.join(
            OUTPUT_FOLDER,
            json_name
        )

        with open(
            output_path,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                parsed_data,
                f,
                indent=4,
                ensure_ascii=False
            )

        print(f"Saved: {output_path}")

        # Prevent overload
        time.sleep(2)

# ================= MAIN =================

if __name__ == "__main__":

    process_folder()