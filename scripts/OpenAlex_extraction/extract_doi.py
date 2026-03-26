# Extracting DOIs, arXiv IDs, and metadata from SLAAI 2022 papers using pdfplumber and and searching metadata from OpenAlex API
import os
import re
import pdfplumber
import requests
import csv
import glob

PAPERS_DIR = "data/sample_papers"
OUTPUT_CSV = "output_data/openAlex/metadata_1.csv"

csv_file = open(OUTPUT_CSV, mode="w", newline="", encoding="utf-8")
csv_writer = csv.DictWriter(
    csv_file,
    fieldnames=[
        "filename",
        "arxiv_id",
        "doi",
        "title_extracted",
        "openalex_found",
        "openalex_title",
        "authors_count",
        "publication_year",
        "authors",
        "institutions",
        "concepts"
    ]
)

csv_writer.writeheader()

# Regular expression patterns for DOI and arXiv ID
doi_pattern = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
arxiv_pattern = re.compile(r"\d{4}\.\d{4,5}v\d+")

# Iterate through PDF files in the directory
for filename in os.listdir(PAPERS_DIR):
    if (not filename.lower().endswith(".pdf")) or filename[1] == '_':
        continue
    
    # Skip files that don't match the expected pattern (e.g., "1_1234.5678v1.pdf")
    filepath = os.path.join(PAPERS_DIR, filename)
    print(f"\nProcessing file: {filename}")                                      #output 1

    data = None
    title = None
    arxiv_id = None


    text = ""
    first_page_text = ""

    # Extract text from the first 2 pages of the PDF
    with pdfplumber.open(filepath) as pdf:
        for i, page in enumerate(pdf.pages[:2]):
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
                if i == 0:
                    first_page_text = page_text

    # Search for DOI and arXiv ID in the extracted text and filename
    match = doi_pattern.search(text)
    arxiv_match = arxiv_pattern.search(filename)

        
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
                "search": identifier,                                   #params for output 4,9
                "per-page": 1
            }
        else:
            return None

        # Debug: Print the API request parameters
        print("OpenAlex params:", params)                                 #Output 4, Output 9

        # Make the API request with a timeout
        response = requests.get(base_url, params=params, timeout=30)

        # Debug: Print the API response status code
        if response.status_code != 200:
            print("OpenAlex request failed:", response.status_code)       #Output 5
            return None

        data = response.json()

        # Debug: Print the number of results returned by OpenAlex
        if data.get("meta", {}).get("count", 0) == 0:
            print("No OpenAlex record found")                                #Output 10
            return None

        # Debug: Print the title of the first OpenAlex result
        return data["results"][0]

                # ------------- Title Extraction -----------------

    def extract_title(first_page_text):
        if not first_page_text:
            return None

        lines = [line.strip() for line in first_page_text.split("\n") if line.strip()]

        # Heuristic: The title is likely in the first few lines before the abstract, excluding lines that look like headers/footers or contain the viXra identifier.
        title_lines = []
        for line in lines:
            lower = line.lower()

            # Stop at abstract
            if "abstract" in lower:
                break
            
            # Remove viXra identifier prefix if present
            if ":vixra" in line.lower():
                line = re.sub(r'^.*?:vixra\s*', '', line, flags=re.I)


            # Skip junk headers / footers like "5202 nuJ 62"
            if (
                re.fullmatch(r'\d{2,4}\s+\w{3}\s+\d{1,2}', line)  # 5202 nuJ 62
                or re.fullmatch(r'\d+', line)                    # page numbers
                or len(line) < 10                              # too short lines
            ):
                continue

            # Heuristic: Skip lines that look like "Proceedings of the 1st Workshop on Systematic Learning for Artificial Intelligence (SLAAI 2022)" or "Inception Labs" which are likely not part of the title
            title_lines.append(line)

            # Stop after collecting 3 lines to avoid including too much non-title text
            if len(title_lines) >= 3:
                break

        # Join the collected lines and take the part before any comma, which often separates the title from author names or affiliations
        title = " ".join(title_lines)
        return title.split(",")[0] if title else None


            # ------------- Cleaning Titles -----------------

    # Common words in Titles that should not be mistaken for author names 
    COMMON_TITLE_WORDS = {          #Should begin with a capital letter
        "Learning", "Reasoning", "System", "Agent", "Agents", "Model", "Models",
        "Analysis", "Survey", "Study", "Framework", "Approach", "Methods",
        "Scaling", "Efficient", "Long-Horizon", "Diagnosis", "Search", "Optimization",
        "Networks", "Network", "Deep", "Neural", "Graph", "Graphs", "Data",
        "Representation", "Representations", "Understanding", "Generation", "Generative", 
        "Paradigm", "Prediction", "Inception", "Labs"
    }

    # Heuristic to check if two words look like a common title phrase (e.g., "Learning System") rather than an author name (e.g., "Xiao Zhan")
    def looks_like_vocab_phrase(w1, w2):
        return w1 in COMMON_TITLE_WORDS or w2 in COMMON_TITLE_WORDS
    
    # Heuristic to check if a single word looks like an author
    def looks_like_author_token(word):
        return (
            len(word) >= 4
            and word[0].isupper()                   # Start with capital letter (e.g., Xiao Zhan)       
            and any(c.isupper() for c in word[1:])  # Contains at least one more capital letter (e.g., XiaoZhan, XIAOZhan)
            and not word.isupper()                  # Exclude all-caps words (e.g., XIAOZhan)
        )

    # Function to clean and standardize titles
    def clean_title(raw_title):
        if not raw_title:
            return None

        # 1. Keep only the first line
        title = raw_title.split("\n")[0].strip()

        # 2. Remove affiliation markers
        title = re.sub(r'[\*\u2217\d]+', '', title)

        # 3. Normalize whitespace
        title = re.sub(r'\s+', ' ', title)
                
        words = title.split()

        # 4. Remove trailing single-token author names (Unicode CamelCase)
        while words and looks_like_author_token(words[-1]):
            words.pop()

        # 5. Remove trailing CamelCase author names (XiaoZhan XiaoLi ...)
        while words and re.fullmatch(r'[A-Z][a-z]+[A-Z][a-z]+', words[-1]):
            words.pop()

        # 6. Remove trailing two-word author name (Xiao Zhan)
        MIN_TITLE_WORDS = 4

        while len(words) >= 2:
            # Do not over-strip
            if len(words) <= MIN_TITLE_WORDS:
                break

            w1, w2 = words[-2], words[-1]

            if (
                re.fullmatch(r'[A-Z][a-z]+', w1)
                and re.fullmatch(r'[A-Z][a-z]+', w2)
                and not looks_like_vocab_phrase(w1, w2)
            ):
                words = words[:-2]
            else:
                break


        return " ".join(words).strip()

            # ------------- Main Logic -----------------

    if match:
        print("DOI found:", match.group())
        data = query_openalex(match.group(), "doi")
    elif arxiv_match:
        raw_arxiv = arxiv_match.group()
        arxiv_id = normalize_arxiv_id(raw_arxiv)

        print("arXiv ID found:", raw_arxiv)                     #output 2
        print("Normalized arXiv ID:", arxiv_id)                 #output 3      

        data = query_openalex(arxiv_id, "arxiv")

    if data is None:
        print("arXiv lookup failed — trying title search")             #output 6
        title = extract_title(first_page_text)

        if title:
            print("Title extracted:", title)                                #output 7  
            cleaned_title = clean_title(title)
            print("Cleaned title:", cleaned_title)                          #output 8

            data = query_openalex(cleaned_title, "title")
 

    authors = None
    institutions = None
    concepts = None

    if data:
        authors = "; ".join(
            a["author"]["display_name"]
            for a in data.get("authorships", [])
            if a.get("author")
        )

        # Extract unique institution names from all authors
        institutions = "; ".join(
            sorted({
                inst["display_name"]
                for a in data.get("authorships", [])
                for inst in a.get("institutions", [])
                if inst.get("display_name")
            })
        )

        # Extract concepts (topics) associated with the paper
        concepts = "; ".join(
            c["display_name"]
            for c in data.get("concepts", [])
            if c.get("display_name")
        )
  
    # Write the extracted metadata to the CSV file
    row = {
    "filename": filename,
    "arxiv_id": arxiv_id if arxiv_match else None,
    "doi": match.group() if match else None,
    "title_extracted": title if "title" in locals() else None,
    "openalex_found": data is not None,
    "openalex_title": data.get("title") if data else None,
    "publication_year": data.get("publication_year") if data else None,
    "authors_count": len(data.get("authorships", [])) if data else None,
    "authors": authors,
    "institutions": institutions,
    "concepts": concepts
    }

    csv_writer.writerow(row)

    #if data is None:
    #    print("No OpenAlex metadata found — skipping")
    #    continue

    # Debug: Print the title and authors count from OpenAlex if data was found
    if data:
        print("OpenAlex title:", data.get("title"))                                 #Output 10  
        print("Authors count:", len(data.get("authorships", [])))                   #Output 11

csv_file.close()
print("Metadata extraction completed. CSV saved to:", OUTPUT_CSV)
