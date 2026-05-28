import requests
import os
import time
import json
import re
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import pdfplumber


# ---------------- CONFIG ----------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "data" / "metadata_extraction_evaluation" / "papers"
METADATA_FILE = PROJECT_ROOT / "data" / "metadata_extraction_evaluation" / "metadata" / "papers.json"

TARGET_PER_PUBLISHER = 25

# Conference paper constraints for OpenAlex filtering.
MAX_PDF_PAGES = 20

# Reject very short papers that are usually cover pages, front matter, or other non-paper items.
MIN_VALID_PDF_PAGES = 4

PUBLISHERS = {
    "springer": {
        "aliases": ["springer"],
        "doi_prefixes": ["10.1007"],
        "openalex_filters": [
            "doi_starts_with:10.1007",
            "best_oa_location.source.type:conference"
        ]
    },
    "elsevier": {
        "aliases": ["elsevier"],
        "doi_prefixes": ["10.1016"],
        "openalex_filters": [
            "doi_starts_with:10.1016",
            "best_oa_location.source.type:conference"
        ]
    },
    "acm": {
        "aliases": ["acm", "association for computing machinery"],
        "doi_prefixes": ["10.1145"],
        "openalex_filters": [
            "doi_starts_with:10.1145",
            "best_oa_location.source.type:conference"
        ]
    },
    "ieee": {
        "aliases": ["ieee", "electrical and electronics engineers", "institute of electrical and electronics engineers"],
        "doi_prefixes": ["10.1109"],
        "openalex_filters": [
            "doi_starts_with:10.1109",
            "best_oa_location.source.type:conference"
        ]
    }
}

BASE_URL = "https://api.openalex.org/works"
REQUEST_HEADERS = {
    "User-Agent": "nlp-research-trend-analysis/1.0"
}

# ----------------------------------------

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(METADATA_FILE.parent, exist_ok=True)

def clear_previous_outputs():
    """Remove previously downloaded paper PDFs before creating a fresh dataset."""
    for path in OUTPUT_DIR.glob("*.pdf"):
        try:
            path.unlink()
        except OSError:
            pass

def build_filter_query(rule):
    filters = [
        "is_oa:true",
    ] + rule.get("openalex_filters", [])
    return ",".join(filters)

def fetch_works_for_publisher(rule, key, per_page=200, max_pages=10):
    filter_query = build_filter_query(rule)
    encoded_filter = quote_plus(filter_query, safe=",:")
    url = f"{BASE_URL}?filter={encoded_filter}&per-page={per_page}&cursor=*"
    all_results = []

    for page in range(1, max_pages + 1):
        try:
            response = requests.get(url, timeout=30, headers=REQUEST_HEADERS)
        except requests.RequestException as exc:
            print(f"[{key}] Failed to reach OpenAlex: {exc}")
            break

        if response.status_code != 200:
            print(f"[{key}] OpenAlex returned HTTP {response.status_code} for page {page}")
            break

        try:
            payload = response.json()
        except ValueError:
            print(f"[{key}] OpenAlex returned a non-JSON response for page {page}")
            break

        results = payload.get("results", [])
        all_results.extend(results)

        next_cursor = payload.get("meta", {}).get("next_cursor")
        if not next_cursor or not results:
            break

        url = f"{BASE_URL}?filter={encoded_filter}&per-page={per_page}&cursor={quote_plus(next_cursor)}"
        time.sleep(0.4)

    return all_results

def download_pdf(url, filepath):
    try:
        r = requests.get(url, timeout=20, headers=REQUEST_HEADERS)
        content_type = r.headers.get("content-type", "").lower()
        body = r.content
        is_pdf = (
            "application/pdf" in content_type
            or body.startswith(b"%PDF")
            or ("application/octet-stream" in content_type and b"%PDF" in body[:2048])
        )

        if r.status_code == 200 and is_pdf:
            with open(filepath, "wb") as f:
                f.write(body)
            return True

        if r.status_code == 200 and "text/html" in content_type:
            pdf_url = resolve_pdf_url_from_html(r.url, r.text)
            if pdf_url and pdf_url != url:
                pdf_response = requests.get(pdf_url, timeout=20, headers=REQUEST_HEADERS)
                pdf_content_type = pdf_response.headers.get("content-type", "").lower()
                pdf_body = pdf_response.content
                pdf_is_pdf = (
                    "application/pdf" in pdf_content_type
                    or pdf_body.startswith(b"%PDF")
                    or ("application/octet-stream" in pdf_content_type and b"%PDF" in pdf_body[:2048])
                )

                if pdf_response.status_code == 200 and pdf_is_pdf:
                    with open(filepath, "wb") as f:
                        f.write(pdf_body)
                    return True
    except requests.RequestException:
        return False
    return False

def resolve_pdf_url_from_html(page_url, html):
    patterns = [
        r'<meta[^>]+name=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+property=["\']citation_pdf_url["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+name=["\']citation_pdf_url["\']',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']citation_pdf_url["\']',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, flags=re.I | re.S)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return urljoin(page_url, candidate)

    link_patterns = [
        r'(?:href|src)=["\']([^"\']+\.pdf[^"\']*)["\']',
    ]

    for pattern in link_patterns:
        match = re.search(pattern, html, flags=re.I | re.S)
        if match:
            candidate = match.group(1).strip()
            if candidate:
                return urljoin(page_url, candidate)

    return None

def extract_title_from_pdf(filepath):
    """Extract a likely paper title from the first page text."""
    try:
        first_page_text = ""
        with pdfplumber.open(filepath) as pdf:
            for i, page in enumerate(pdf.pages[:2]):
                page_text = page.extract_text()
                if page_text:
                    if i == 0:
                        first_page_text = page_text
                    else:
                        first_page_text += "\n" + page_text

        if not first_page_text:
            return None

        lines = [line.strip() for line in first_page_text.split("\n") if line.strip()]
        title_lines = []

        for line in lines:
            lower = line.lower()

            if "abstract" in lower:
                break

            if ":vixra" in lower:
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

        title = " ".join(title_lines).strip()
        if not title:
            return None

        title = title.split(",")[0].strip()
        title = re.sub(r"\s+", " ", title)
        return title or None
    except Exception:
        return None

def get_pdf_page_count(filepath):
    try:
        with pdfplumber.open(filepath) as pdf:
            return len(pdf.pages)
    except Exception:
        return None

def is_valid_pdf_page_count(page_count):
    # Treat unreadable PDFs (None) as invalid so we skip files where
    # the page count couldn't be determined (e.g., malformed or HTML wrappers).
    if page_count is None:
        return False
    return MIN_VALID_PDF_PAGES <= page_count <= MAX_PDF_PAGES

def get_biblio_page_count(work):
    biblio = work.get("biblio") or {}
    # Try explicit 'pages' field (like '1-10' or '123')
    pages_field = biblio.get("pages")
    if pages_field and isinstance(pages_field, str):
        # look for ranges
        m = re.search(r'(\d+)\s*[-–—]\s*(\d+)', pages_field)
        if m:
            try:
                return int(m.group(2)) - int(m.group(1)) + 1
            except Exception:
                pass
        m2 = re.search(r'(\d+)', pages_field)
        if m2:
            try:
                return int(m2.group(1))
            except Exception:
                pass
    # Fallback to first_page/last_page
    first = biblio.get("first_page")
    last = biblio.get("last_page")
    try:
        if first and last:
            return int(last) - int(first) + 1
    except Exception:
        pass
    return None

def choose_best_title(pdf_title, openalex_title):
    pdf_title = (pdf_title or "").strip()
    openalex_title = (openalex_title or "").strip()

    if pdf_title and not openalex_title:
        return pdf_title
    if openalex_title and not pdf_title:
        return openalex_title
    if not pdf_title and not openalex_title:
        return None

    pdf_words = len(pdf_title.split())
    openalex_words = len(openalex_title.split())

    # Prefer the PDF title when OpenAlex is suspiciously short.
    if pdf_words >= 3 and openalex_words <= 2:
        return pdf_title

    # Prefer the longer title when one is a clear prefix of the other.
    pdf_lower = pdf_title.lower()
    openalex_lower = openalex_title.lower()
    if pdf_lower.startswith(openalex_lower) or openalex_lower.startswith(pdf_lower):
        return pdf_title if len(pdf_title) >= len(openalex_title) else openalex_title

    # Default to the more informative title.
    return pdf_title if len(pdf_title) >= len(openalex_title) else openalex_title

def extract_arxiv_id(work):
    # Extract arXiv ID if present
    locations = work.get("locations", [])
    for loc in locations:
        source = (loc or {}).get("source") or {}
        if source.get("display_name", "").lower() == "arxiv":
            return loc.get("landing_page_url", "").split("/")[-1]
    return None

def process_authors(work):
    authors = []
    for a in work.get("authorships", []):
        authors.append({
            "name": a.get("author", {}).get("display_name"),
            "department": None,
            "institution": (
                a.get("institutions")[0]["display_name"]
                if a.get("institutions") else None
            ),
            "email": None
        })
    return authors

def build_metadata(work, filename, pdf_title=None):
    openalex_title = work.get("title")
    # Prefer OpenAlex title; fallback to PDF-extracted title when OpenAlex is missing
    title = openalex_title or pdf_title

    return {
        "version": 1,
        "doi": work.get("doi", "").replace("https://doi.org/", "") if work.get("doi") else None,
        "arxiv_id": extract_arxiv_id(work),
        "title": title,
        "authors": process_authors(work),
        "year": str(work.get("publication_year")) if work.get("publication_year") else None,

        # Not available from OpenAlex → leave empty
        "keywords": extract_keywords(work),
        "generated_keywords": [],
        "ml_methods": [],
        "references": [],

        "source_file": filename
    }

def extract_keywords(work, top_n=8, min_score=0.3):
    concepts = work.get("concepts", [])

    filtered = [c for c in concepts if c.get("score", 0) >= min_score]
    sorted_concepts = sorted(filtered, key=lambda x: x.get("score", 0), reverse=True)
    
    return [c["display_name"] for c in sorted_concepts[:top_n]]

def get_publisher(work):
    locations = work.get("locations", [])
    for loc in locations:
        source = loc.get("source")
        if source and source.get("publisher"):
            return source.get("publisher")
    return None

def collect_publisher_signals(work):
    signals = []

    for loc in work.get("locations", []) or []:
        source = (loc or {}).get("source") or {}

        for value in [
            source.get("publisher"),
            source.get("display_name"),
            source.get("host_organization_name"),
        ]:
            if value:
                signals.append(value.lower())

        for lineage_name in source.get("host_organization_lineage_names") or []:
            if lineage_name:
                signals.append(lineage_name.lower())

    for key in ["primary_location", "best_oa_location"]:
        source = ((work.get(key) or {}).get("source") or {})
        for value in [
            source.get("display_name"),
            source.get("host_organization_name"),
        ]:
            if value:
                signals.append(value.lower())

    oa_url = (work.get("open_access") or {}).get("oa_url")
    if oa_url:
        signals.append(oa_url.lower())

    return signals

def matches_publisher(work, rule, key):
    doi = (work.get("doi") or "").replace("https://doi.org/", "").lower()
    signals = collect_publisher_signals(work)

    # arXiv is often represented as preprint source rather than publisher.
    if key == "arxiv":
        if extract_arxiv_id(work):
            return True

    for prefix in rule.get("doi_prefixes", []):
        if doi.startswith(prefix.lower()):
            return True

    aliases = [alias.lower() for alias in rule.get("aliases", [])]
    if any(alias in signal for alias in aliases for signal in signals):
        return True

    return False

def build_pdf_candidates(work, key):
    candidates = []

    open_access = work.get("open_access") or {}
    content_urls = work.get("content_urls") or {}
    best_oa_location = work.get("best_oa_location") or {}

    for value in [
        open_access.get("oa_url"),
        content_urls.get("pdf"),
        content_urls.get("pdf_url"),
        best_oa_location.get("pdf_url"),
        best_oa_location.get("landing_page_url"),
    ]:
        if value:
            candidates.append(value)

    for location in work.get("locations", []) or []:
        if not isinstance(location, dict):
            continue

        for value in [
            location.get("pdf_url"),
            location.get("landing_page_url"),
        ]:
            if value:
                candidates.append(value)

    doi = (work.get("doi") or "").replace("https://doi.org/", "")
    if key == "acm" and doi.startswith("10.1145/"):
        candidates.append(f"https://dl.acm.org/doi/pdf/{doi}")

    # Keep order but drop duplicates.
    return list(dict.fromkeys(candidates))

def process_publisher(rule, all_works, key):
    collected = []
    count = 0

    for work in all_works:
        if count >= TARGET_PER_PUBLISHER:
            break

        if not matches_publisher(work, rule, key):
            continue

        # Prefilter by OpenAlex biblio page counts when available to avoid downloading long books/reports
        biblio_pages = get_biblio_page_count(work)
        if biblio_pages is not None and biblio_pages > MAX_PDF_PAGES:
            continue

        pdf_urls = build_pdf_candidates(work, key)
        if not pdf_urls:
            continue

        filename = f"{key}_{count}.pdf"
        filepath = OUTPUT_DIR / filename

        for pdf_url in pdf_urls:
            if download_pdf(pdf_url, filepath):
                page_count = get_pdf_page_count(filepath)
                if not is_valid_pdf_page_count(page_count):
                    try:
                        filepath.unlink()
                    except OSError:
                        pass
                    continue

                pdf_title = extract_title_from_pdf(filepath)
                metadata = build_metadata(work, filename, pdf_title=pdf_title)
                collected.append(metadata)
                count += 1
                print(f"Fetched {filename}")
                break

        time.sleep(0.2)

    print(f"Valid {key.upper()} research papers: {count}")

    return collected

def save_metadata(metadata):
    with open(METADATA_FILE, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

def main():
    clear_previous_outputs()

    all_metadata = []
    save_metadata(all_metadata)

    for key, publisher_rule in PUBLISHERS.items():
        all_works = []
        seen_ids = set()

        results = fetch_works_for_publisher(
            publisher_rule,
            key,
            per_page=200,
            max_pages=10,
        )

        for work in results:
            work_id = work.get("id") or work.get("doi")
            if not work_id or work_id in seen_ids:
                continue
            seen_ids.add(work_id)
            all_works.append(work)

        data = process_publisher(publisher_rule, all_works, key)
        all_metadata.extend(data)
        save_metadata(all_metadata)

if __name__ == "__main__":
    main()
