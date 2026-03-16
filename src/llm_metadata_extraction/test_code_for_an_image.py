# test code for extracting metadata from one image using Gemini API
# Could not find a free version that extract metadata from the image
# Found a free version but has limits (requests per a minute (RPM) - 5, tokens per a minute (TPM) - 250k, and requests per a day(RPD) - 20)

from google import genai
# from google.genai import types
import PIL.Image # use to open and read the image
import os
from dotenv import load_dotenv
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

image = PIL.Image.open("output_data/gemini_extracted_data/first_page_images/2506.08388v3_page1.png")

client = genai.Client(api_key=GEMINI_API_KEY)
response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[
        "Extract the DOI or arXiv ID, title, authors, institution, published year, author defined keywords, and most significant 5-6 keywords from title and abstract from this research paper page. Leave if not found.", image])


print(response.text)