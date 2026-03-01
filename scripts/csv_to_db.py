import csv
import sqlite3
from pathlib import Path

CSV_PATH = "output_data/openAlex/metadata_1.csv"
DB_PATH = "output_data/openAlex/metadata.db"

if Path(DB_PATH).exists():
    print("WARNING: Existing database detected:", DB_PATH)

# Ensure directory exists
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

# Connect to SQLite database (creates file if not exists)
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

cursor.execute("DROP TABLE IF EXISTS papers;")
 
# Create table
cursor.execute("""
CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT UNIQUE,
    arxiv_id TEXT,
    doi TEXT,
    title_extracted TEXT,
    openalex_found BOOLEAN,
    openalex_title TEXT,
    publication_year INTEGER,
    authors_count INTEGER,
    authors TEXT,
    institutions TEXT,
    concepts TEXT
)
""")

# Insert CSV data
with open(CSV_PATH, newline="", encoding="utf-8") as csvfile:
    reader = csv.DictReader(csvfile)

    for row in reader:
        cursor.execute("""
        INSERT OR IGNORE INTO papers (
            filename,
            arxiv_id,
            doi,
            title_extracted,
            openalex_found,
            openalex_title,
            publication_year,
            authors_count,
            authors,
            institutions,
            concepts
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row.get("filename"),
            row.get("arxiv_id") or None,
            row.get("doi") or None,
            row.get("title_extracted") or None,
            1 if row.get("openalex_found") == "True" else 0,
            row.get("openalex_title") or None,
            int(row["publication_year"]) if row.get("publication_year") else None,
            int(row["authors_count"]) if row.get("authors_count") else None,
            row.get("authors") or None,
            row.get("institutions") or None,
            row.get("concepts") or None
        ))

conn.commit()
conn.close()

print("Database created and populated at:", DB_PATH)
