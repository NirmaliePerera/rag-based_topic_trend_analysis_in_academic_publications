import json
import os
import re
import unicodedata

# =====================================================
# CONFIG
# =====================================================

GROUND_TRUTH_FILE = "data/metadata_extraction_evaluation/metadata/papers.json"

BASELINE_FOLDER = "output_data/grobid_baseline_output"

ENHANCED_FOLDER = "output_data/grobid_year_enhanced_v2"

# =====================================================
# HELPERS
# =====================================================

def remove_accents(text):
    if not text:
        return ""

    return "".join(
        c for c in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(c)
    )


def canonical_author(name):

    if not name:
        return ""

    name = name.lower()

    name = remove_accents(name)

    name = name.replace(".", "")

    name = re.sub(r"\s+", " ", name).strip()

    parts = name.split()

    if len(parts) == 0:
        return ""

    surname = parts[-1]

    initials = "".join(
        p[0]
        for p in parts[:-1]
        if len(p) > 0
    )

    return f"{surname}_{initials}"


def author_set(authors):

    result = set()

    for author in authors:

        if isinstance(author, dict):

            name = author.get("name")

        elif isinstance(author, str):

            name = author

        else:
            continue

        if not name:
            continue

        result.add(
            canonical_author(name)
        )

    return result


def jaccard(a, b):

    if not a and not b:
        return 1.0

    union = a | b

    if len(union) == 0:
        return 0.0

    return len(a & b) / len(union)


def resolve_output_file(folder, filename, suffix=".json"):
    base_name = os.path.splitext(filename)[0]

    candidates = [
        os.path.join(folder, base_name + suffix),
        os.path.join(folder, base_name + "_eval" + suffix),
    ]

    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate

    return None


# =====================================================
# LOAD DATA
# =====================================================

with open(GROUND_TRUTH_FILE, "r", encoding="utf-8") as f:
    ground_truth = json.load(f)

gt_lookup = {}

for item in ground_truth:
    filename = item.get("filename") or item.get("source_file")

    if not filename:
        continue

    gt_lookup[filename] = item


# =====================================================
# ANALYSIS
# =====================================================

papers_worse = 0
papers_better = 0
papers_same = 0

total_removed_authors = 0
total_added_authors = 0

print("\n" + "=" * 80)
print("AUTHOR EXTRACTION COMPARISON")
print("=" * 80)

for filename, gt in gt_lookup.items():

    baseline_file = resolve_output_file(BASELINE_FOLDER, filename)

    enhanced_file = resolve_output_file(ENHANCED_FOLDER, filename)

    if not os.path.exists(baseline_file):
        continue

    if not os.path.exists(enhanced_file):
        continue

    with open(baseline_file, "r", encoding="utf-8") as f:
        baseline = json.load(f)

    with open(enhanced_file, "r", encoding="utf-8") as f:
        enhanced = json.load(f)

    # =====================================================
    # DEBUG ONE PAPER
    # =====================================================

    # if filename == "ieee_16.pdf":

    #     print("\n" + "=" * 80)
    #     print("DEBUG IEEE_16")
    #     print("=" * 80)

    #     print("\nBASELINE FILE:")
    #     print(baseline_file)

    #     print("\nENHANCED FILE:")
    #     print(enhanced_file)

    #     print("\nRAW GT AUTHORS:")
    #     print(gt.get("authors", []))

    #     print("\nRAW BASELINE AUTHORS:")
    #     print(baseline.get("authors", []))

    #     print("\nRAW ENHANCED AUTHORS:")
    #     print(enhanced.get("authors", []))

    #     print("\nCANONICAL GT:")
    #     print(author_set(gt.get("authors", [])))

    #     print("\nCANONICAL BASELINE:")
    #     print(author_set(baseline.get("authors", [])))

    #     print("\nCANONICAL ENHANCED:")
    #     print(author_set(enhanced.get("authors", [])))

    #     print("\nTOP-LEVEL KEYS IN ENHANCED JSON:")
    #     print(list(enhanced.keys()))

    #     print("=" * 80)

    gt_authors = author_set(
        gt.get("authors", [])
    )

    baseline_authors = author_set(
        baseline.get("authors", [])
    )

    enhanced_authors = author_set(
        enhanced.get("authors", [])
    )

    baseline_score = jaccard(
        gt_authors,
        baseline_authors
    )

    enhanced_score = jaccard(
        gt_authors,
        enhanced_authors
    )

    removed = baseline_authors - enhanced_authors

    added = enhanced_authors - baseline_authors

    total_removed_authors += len(removed)
    total_added_authors += len(added)

    if enhanced_score < baseline_score:

        papers_worse += 1

        print("\n" + "-" * 80)
        print(f"PAPER: {filename}")
        print("-" * 80)

        print(
            f"Baseline Score : {baseline_score:.4f}"
        )

        print(
            f"Enhanced Score : {enhanced_score:.4f}"
        )

        print(
            f"Score Change   : "
            f"{enhanced_score - baseline_score:.4f}"
        )

        print("\nRemoved Authors:")

        if removed:
            for author in sorted(removed):
                print(f"  - {author}")
        else:
            print("  None")

        print("\nGround Truth:")
        print(sorted(gt_authors))

        print("\nBaseline:")
        print(sorted(baseline_authors))

        print("\nEnhanced:")
        print(sorted(enhanced_authors))

    elif enhanced_score > baseline_score:

        papers_better += 1

    else:

        papers_same += 1


# =====================================================
# SUMMARY
# =====================================================

print("\n")
print("=" * 80)
print("SUMMARY")
print("=" * 80)

print(
    f"Papers Worse      : {papers_worse}"
)

print(
    f"Papers Better     : {papers_better}"
)

print(
    f"Papers Unchanged  : {papers_same}"
)

print(
    f"Authors Removed   : {total_removed_authors}"
)

print(
    f"Authors Added     : {total_added_authors}"
)