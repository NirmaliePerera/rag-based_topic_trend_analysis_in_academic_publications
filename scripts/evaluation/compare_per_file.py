# This script compares predicted metadata against ground truth on a per-file basis.
#python scripts/evaluation/compare_per_file.py grobid
#python scripts/evaluation/compare_per_file.py gemini
#python scripts/evaluation/compare_per_file.py openalex


import json
import os
from difflib import SequenceMatcher
import sys

if len(sys.argv) < 2:
    print("Usage: python compare_per_file.py <method>")
    print("Available methods: grobid, gemini, openalex")
    sys.exit(1)

METHOD = sys.argv[1]
  # e.g., grobid, gemini, openalex

# Map method names to folder names
METHOD_TO_FOLDER = {
    "grobid": "grobid_metadata_output",
    "grobid_enhanced": "grobid_enhanced_output",
    "gemini": "gemini",
    "openalex": "openalex"
}

if METHOD not in METHOD_TO_FOLDER:
    print(f"Unknown method: {METHOD}")
    print(f"Available methods: {', '.join(METHOD_TO_FOLDER.keys())}")
    sys.exit(1)

FOLDER_NAME = METHOD_TO_FOLDER[METHOD]



# -------- PATHS --------
# Compute paths relative to project root
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

GT_PATH = os.path.join(PROJECT_ROOT, "data", "metadata_extraction_evaluation", "metadata", "papers.json")
PRED_DIR = os.path.join(PROJECT_ROOT, "output_data", "grobid_enhanced_output")
#PRED_DIR = os.path.join(PROJECT_ROOT, "output_data", "grobid_baseline_output")
#PRED_DIR = os.path.join(PROJECT_ROOT, "output_data", "Evaluation_Output", FOLDER_NAME)
OUT_DIR = os.path.join(PROJECT_ROOT, "output_data", "Evaluation_Output", "evaluations", METHOD)

os.makedirs(OUT_DIR, exist_ok=True)

if not os.path.exists(PRED_DIR):
    print(f"Prediction directory not found: {PRED_DIR}")
    sys.exit(1)


# -------- HELPERS --------

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def normalize(text):
    if not text:
        return ""
    return text.lower().strip()

def similarity(a, b):
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()

def exact_match(a, b):
    return normalize(a) == normalize(b)

def author_set(authors):

    normalized = set()

    for a in authors:

        # Case 1: dict format
        if isinstance(a, dict):
            name = a.get("name")

        # Case 2: plain string format
        else:
            name = a

        if name:
            normalized.add(normalize(name))

    return normalized

def jaccard(a, b):
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if len(a | b) != 0 else 0

# -------- LOAD GROUND TRUTH --------

ground_truth = load_json(GT_PATH)
gt_map = {item["source_file"]: item for item in ground_truth}

# -------- PROCESS EACH FILE --------

for filename in os.listdir(PRED_DIR):
    if not filename.endswith(".json"):
        continue

    pred_path = os.path.join(PRED_DIR, filename)
    pred_data = load_json(pred_path)
    
    # Handle both list and dict formats (openalex returns list, others return dict)
    if isinstance(pred_data, list):
        if len(pred_data) == 0:
            print(f"Skipping {filename} (empty list)")
            continue
        pred = pred_data[0]
    else:
        pred = pred_data

    source_file = pred.get("source_file") or pred.get("file_name")

    if not source_file or source_file not in gt_map:
        print(f"Skipping {filename} (no match in ground truth)")
        continue

    gt = gt_map[source_file]

    # -------- COMPARISON --------
    result = {
        "source_file": source_file,

        "doi_match": exact_match(gt.get("doi"), pred.get("doi")),

        "title_similarity": similarity(
            gt.get("title"), pred.get("title")
        ),

        "year_match": exact_match(
            str(gt.get("year")), str(pred.get("year"))
        ),

        "author_similarity": jaccard(
            author_set(gt.get("authors", [])),
            author_set(pred.get("authors", []))
        )
    }

    # References are not evaluated (ground truth has no reference lists).
    # Keep an explicit flag so downstream code knows we skipped reference evaluation.
    result["references_evaluated"] = False

    # -------- SAVE PER PAPER --------
    out_path = os.path.join(
        OUT_DIR,
        filename.replace(".json", "_eval.json")
    )

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    print(f"Saved: {out_path}")

print("\nDone. Per-paper evaluations created.")
