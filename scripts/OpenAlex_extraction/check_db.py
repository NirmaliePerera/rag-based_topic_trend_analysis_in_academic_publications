#Check contents of the database (testing purpose)
import sqlite3

conn = sqlite3.connect("output_data/openAlex/metadata.db")
cursor = conn.cursor()

cursor.execute("SELECT filename, openalex_found FROM papers LIMIT 5")
print(cursor.fetchall())

conn.close()
