import os
import pymupdf as fitz  # PyMuPDF

PDF_DIR = "data/sample_papers"
IMAGE_DIR = "output_data/gemini_extracted_data/first_page_images"

os.makedirs(IMAGE_DIR, exist_ok=True)

def convert_first_page(pdf_path, output_image_path):
    doc = fitz.open(pdf_path)
    page = doc[0]  # first page
    pix = page.get_pixmap(dpi=300)
    pix.save(output_image_path)
    doc.close()

def process_all_pdfs():
    for filename in os.listdir(PDF_DIR):
        if not filename.lower().endswith(".pdf"):
            continue

        pdf_path = os.path.join(PDF_DIR, filename)
        base_name = os.path.splitext(filename)[0]
        image_path = os.path.join(IMAGE_DIR, f"{base_name}_page1.png")

        convert_first_page(pdf_path, image_path)
        print(f"Saved: {image_path}")

if __name__ == "__main__":
    process_all_pdfs()
