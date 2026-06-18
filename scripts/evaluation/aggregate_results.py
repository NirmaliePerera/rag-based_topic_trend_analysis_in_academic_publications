# python scripts/evaluation/aggregate_results.py <method>
# Example: python scripts/evaluation/aggregate_results.py grobid_year_enhance (Method is folder name in evaluations)

import json
import os
import sys

if len(sys.argv) < 2:
    print("Usage: python aggregate_results.py <method>")
    print("Available methods: grobid, gemini, openalex")
    sys.exit(1)

METHOD = sys.argv[1]

# -------- PATHS --------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

# EVAL_DIR = os.path.join(
#    PROJECT_ROOT,
#    "output_data",
#    "Evaluation_Output",
#    "evaluations",
#    "grobid_baseline"
# )

#EVAL_DIR = os.path.join(
#    PROJECT_ROOT,
#    "output_data",
#    "Evaluation_Output",
#    "evaluations",
#    "grobid_enhanced_after_evaluation_modify"
#)

# EVAL_DIR = os.path.join(
#     PROJECT_ROOT,
#     "output_data",
#     "Evaluation_Output",
#     "evaluations",
#     "grobid_baseline_latest"
# )

# EVAL_DIR = os.path.join(
#     PROJECT_ROOT,
#     "output_data",
#     "Evaluation_Output",
#     "evaluations",
#     "grobid_year_enhance"
# )

# EVAL_DIR = os.path.join(
#     PROJECT_ROOT,
#     "output_data",
#     "Evaluation_Output",
#     "evaluations",
#     "grobid_year_enhance_latest"
# )

# EVAL_DIR = os.path.join(
#     PROJECT_ROOT,
#     "output_data",
#     "Evaluation_Output",
#     "evaluations",
#     "grobid_year_enhanced_v2"
# )


# EVAL_DIR = os.path.join(
#     PROJECT_ROOT,
#     "output_data",
#     "Evaluation_Output",
#     "evaluations",
#     "grobid_year_enhanced_v2_latest"
# )

EVAL_DIR = os.path.join(
    PROJECT_ROOT,
    "output_data",
    "Evaluation_Output",
    "evaluations",
    "grobid_year_enhanced_v2_pdf_first"
)

# EVAL_DIR = os.path.join(
#     PROJECT_ROOT,
#     "output_data",
#     "Evaluation_Output",
#     "evaluations",
#     "grobid_year_enhanced_v2_pdf_first_latest"
# )

#OUTPUT_PATH = os.path.join(
#    EVAL_DIR,
#    "summary.json"
#)

OUTPUT_PATH = os.path.join(EVAL_DIR, "summary.json")

if not os.path.exists(EVAL_DIR):
    print(f"Evaluation directory not found: {EVAL_DIR}")
    sys.exit(1)

# -------- HELPERS --------

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

# -------- AGGREGATION --------

total_files = 0

doi_matches = 0
year_matches = 0

title_similarity_sum = 0
author_similarity_sum = 0

for filename in os.listdir(EVAL_DIR):

    if not filename.endswith("_eval.json"):
        continue

    path = os.path.join(EVAL_DIR, filename)

    data = load_json(path)

    total_files += 1

    # DOI
    if data.get("doi_match"):
        doi_matches += 1

    # Year
    if data.get("year_match"):
        year_matches += 1

    # Title similarity
    title_similarity_sum += data.get(
        "title_similarity", 0
    )

    # Author similarity
    author_similarity_sum += data.get(
        "author_similarity", 0
    )

# -------- FINAL METRICS --------

if total_files == 0:
    print("No evaluation files found.")
    sys.exit(1)

summary = {

    "method": METHOD,

    "total_files": total_files,

    "doi_accuracy":
        doi_matches / total_files,

    "year_accuracy":
        year_matches / total_files,

    "average_title_similarity":
        title_similarity_sum / total_files,

    "average_author_similarity":
        author_similarity_sum / total_files
}

# -------- SAVE --------

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(summary, f, indent=4)

# -------- PRINT --------

print("\n===== SUMMARY =====\n")

print(f"Method: {METHOD}")
print(f"Files Evaluated: {total_files}")

print(f"\nDOI Accuracy: "
      f"{summary['doi_accuracy']:.4f}")

print(f"Year Accuracy: "
      f"{summary['year_accuracy']:.4f}")

print(f"Average Title Similarity: "
      f"{summary['average_title_similarity']:.4f}")

print(f"Average Author Similarity: "
      f"{summary['average_author_similarity']:.4f}")

print(f"\nSaved summary to:")
print(OUTPUT_PATH)