import json
import os
from collections import Counter

INPUT_DIR = "output_data/grobid_enhanced_output"

counter = Counter()

for file in os.listdir(INPUT_DIR):

    if not file.endswith(".json"):
        continue

    with open(
        os.path.join(INPUT_DIR, file),
        encoding="utf-8"
    ) as f:

        data = json.load(f)

    counter[data.get(
        "year_source",
        "unknown"
    )] += 1

print(counter)

# Output like:
# publicationStmt    35
# date_attribute     12
# tei_fallback       28
# not_found           8