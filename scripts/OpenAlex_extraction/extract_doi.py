# Extract DOI/arXiv/title from PDFs, then enrich metadata via OpenAlex.
# Output is JSON with the same top-level schema as papers.json groundtruth.
import json
import os
import re
from pathlib import Path

import pdfplumber
import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PAPERS_DIR = PROJECT_ROOT / "data" / "metadata_extraction_evaluation" / "papers"
OUTPUT_JSON = PROJECT_ROOT / "output_data" / "Evaluation_Output" / "openalex_metadata_output" / "metadata_1.json"
EXTRACTION_VERSION = 1

# Regular expression patterns for DOI and arXiv ID
doi_pattern = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
arxiv_pattern = re.compile(r"\d{4}\.\d{4,5}v\d+")

# Normalize arXiv ID by removing version suffix (e.g., v1, v2)
def normalize_arxiv_id(arxiv_id):
    return arxiv_id.split("v")[0]


# Function to query OpenAlex API
def query_openalex(identifier, id_type):
    base_url = "https://api.openalex.org/works"

    if id_type == "doi":
        params = {"filter": f"doi:{identifier}"}
    elif id_type == "arxiv":
        params = {"filter": f"ids.arxiv:arXiv:{identifier}"}
    elif id_type == "title":
        params = {
            "search": identifier,
            "per-page": 1,
        }
    else:
        return None

    print("OpenAlex params:", params)
    response = requests.get(base_url, params=params, timeout=30)

    if response.status_code != 200:
        print("OpenAlex request failed:", response.status_code)
        return None

    data = response.json()
    if data.get("meta", {}).get("count", 0) == 0:
        print("No OpenAlex record found")
        return None

    return data["results"][0]


def extract_title(first_page_text):
    if not first_page_text:
        return None

    lines = [line.strip() for line in first_page_text.split("\n") if line.strip()]

    title_lines = []
    for line in lines:
        lower = line.lower()

        if "abstract" in lower:
            break

        if ":vixra" in line.lower():
            line = re.sub(r"^.*?:vixra\s*", "", line, flags=re.I)

        if (
            re.fullmatch(r"\d{2,4}\s+\w{3}\s+\d{1,2}", line)
            or re.fullmatch(r"\d+", line)
            or len(line) < 10
        ):
            continue

        title_lines.append(line)
        if len(title_lines) >= 3:
            break

    title = " ".join(title_lines)
    return title.split(",")[0] if title else None


COMMON_TITLE_WORDS = {
    "Learning", "Reasoning", "System", "Agent", "Agents", "Model", "Models",
    "Analysis", "Survey", "Study", "Framework", "Approach", "Methods",
    "Scaling", "Efficient", "Long-Horizon", "Diagnosis", "Search", "Optimization",
    "Networks", "Network", "Deep", "Neural", "Graph", "Graphs", "Data",
    "Representation", "Representations", "Understanding", "Generation", "Generative",
    "Paradigm", "Prediction", "Inception", "Labs",
}


def looks_like_vocab_phrase(w1, w2):
    return w1 in COMMON_TITLE_WORDS or w2 in COMMON_TITLE_WORDS


def looks_like_author_token(word):
    return (
        len(word) >= 4
        and word[0].isupper()
        and any(c.isupper() for c in word[1:])
        and not word.isupper()
    )


def clean_title(raw_title):
    if not raw_title:
        return None

    title = raw_title.split("\n")[0].strip()
    title = re.sub(r"[\*\u2217\d]+", "", title)
    title = re.sub(r"\s+", " ", title)

    words = title.split()

    while words and looks_like_author_token(words[-1]):
        words.pop()

    while words and re.fullmatch(r"[A-Z][a-z]+[A-Z][a-z]+", words[-1]):
        words.pop()

    min_title_words = 4
    while len(words) >= 2:
        if len(words) <= min_title_words:
            break

        w1, w2 = words[-2], words[-1]
        if (
            re.fullmatch(r"[A-Z][a-z]+", w1)
            and re.fullmatch(r"[A-Z][a-z]+", w2)
            and not looks_like_vocab_phrase(w1, w2)
        ):
            words = words[:-2]
        else:
            break

    return " ".join(words).strip()


def normalize_openalex_author(authorship):
    author_name = (authorship.get("author") or {}).get("display_name")
    institutions = authorship.get("institutions") or []
    institution_name = None
    for inst in institutions:
        if inst.get("display_name"):
            institution_name = inst["display_name"]
            break

    return {
        "name": author_name,
        "department": None,
        "institution": institution_name,
        "email": None,
    }


def get_openalex_keywords(data):
    return [
        c.get("display_name")
        for c in (data.get("concepts") or [])
        if c.get("display_name")
    ]


def build_schema_record(filename, openalex_data, extracted_title, normalized_arxiv, extracted_doi):
    if openalex_data:
        ids = openalex_data.get("ids") or {}
        openalex_doi = ids.get("doi")
        if openalex_doi and openalex_doi.startswith("https://doi.org/"):
            openalex_doi = openalex_doi.replace("https://doi.org/", "")

        return {
            "version": EXTRACTION_VERSION,
            "doi": openalex_doi or extracted_doi,
            "arxiv_id": normalized_arxiv,
            "title": openalex_data.get("title") or extracted_title,
            "authors": [
                normalize_openalex_author(a)
                for a in (openalex_data.get("authorships") or [])
            ],
            "year": str(openalex_data.get("publication_year")) if openalex_data.get("publication_year") else None,
            "keywords": get_openalex_keywords(openalex_data),
            "generated_keywords": [],
            "ml_methods": [],
            "references": [],
            "source_file": filename,
        }

    return {
        "version": EXTRACTION_VERSION,
        "doi": extracted_doi,
        "arxiv_id": normalized_arxiv,
        "title": extracted_title,
        "authors": [],
        "year": None,
        "keywords": [],
        "generated_keywords": [],
        "ml_methods": [],
        "references": [],
        "source_file": filename,
    }


def process_papers():
    records = []

    for filename in sorted(os.listdir(PAPERS_DIR)):
        if not filename.lower().endswith(".pdf"):
            continue
        if len(filename) > 1 and filename[1] == "_":
            continue
    
        filepath = PAPERS_DIR / filename
        print(f"\nProcessing file: {filename}")

        data = None
        title = None
        arxiv_id = None

        text = ""
        first_page_text = ""

        with pdfplumber.open(filepath) as pdf:
            for i, page in enumerate(pdf.pages[:2]):
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
                    if i == 0:
                        first_page_text = page_text

        match = doi_pattern.search(text)
        arxiv_match = arxiv_pattern.search(filename)

        
        if match:
            print("DOI found:", match.group())
            data = query_openalex(match.group(), "doi")
        elif arxiv_match:
            raw_arxiv = arxiv_match.group()
            arxiv_id = normalize_arxiv_id(raw_arxiv)
            print("arXiv ID found:", raw_arxiv)
            print("Normalized arXiv ID:", arxiv_id)
            data = query_openalex(arxiv_id, "arxiv")

        if data is None:
            print("arXiv/DOI lookup failed - trying title search")
            title = extract_title(first_page_text)

            if title:
                print("Title extracted:", title)
                cleaned_title = clean_title(title)
                print("Cleaned title:", cleaned_title)
                data = query_openalex(cleaned_title, "title")

        record = build_schema_record(
            filename=filename,
            openalex_data=data,
            extracted_title=title,
            normalized_arxiv=arxiv_id if arxiv_match else None,
            extracted_doi=match.group() if match else None,
        )
        records.append(record)

        if data:
            print("OpenAlex title:", data.get("title"))
            print("Authors count:", len(data.get("authorships", [])))

    os.makedirs(OUTPUT_JSON.parent, exist_ok=True)
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)

    print("Metadata extraction completed. JSON saved to:", OUTPUT_JSON)


if __name__ == "__main__":
    process_papers()
