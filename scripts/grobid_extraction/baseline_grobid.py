import os
import requests
import json
import time
from lxml import etree
# ================= CONFIG =================

GROBID_URL = "http://localhost:8070/api/processFulltextDocument"
PDF_FOLDER = "data/metadata_extraction_evaluation/papers"
OUTPUT_FOLDER = "output_data/grobid_baseline_output"


# ================= EXTRACT XML FROM GROBID =================

def extract_metadata(pdf_path):

    for attempt in range(3):
        try:
            with open(pdf_path, "rb") as f:
                files = {
                    "input": (os.path.basename(pdf_path), f, "application/pdf")
                }

                response = requests.post(
                    GROBID_URL,
                    files=files,
                    timeout=300
                )

            if response.status_code == 200:
                return response.text

            print(f"HTTP Error: {response.status_code}")

        except requests.exceptions.Timeout:
            print(f"Timeout on attempt: {attempt+1}")

        except Exception as e:
            print(f"Attempt {attempt+1} failed: {e}")
            
        time.sleep(5)  # Wait before retrying
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

        time.sleep(10)  # Sleep to avoid overwhelming GROBID

# ================= MAIN =================

if __name__ == "__main__":

    process_folder()

