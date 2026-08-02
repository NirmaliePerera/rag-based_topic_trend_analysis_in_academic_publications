from pathlib import Path

import pymupdf as fitz  # PyMuPDF

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PDF_DIR = PROJECT_ROOT / "data" / "metadata_extraction_evaluation" / "papers"
IMAGE_DIR = PROJECT_ROOT / "output_data" / "gemini_extracted_data" / "first_page_images"

IMAGE_DIR.mkdir(parents=True, exist_ok=True)

def convert_first_page(pdf_path, output_image_path):
    doc = fitz.open(pdf_path)
    page = doc[0]  # first page
    pix = page.get_pixmap(dpi=300)
    pix.save(output_image_path)
    doc.close()

def process_all_pdfs():
    for pdf_path in sorted(PDF_DIR.iterdir()):
        filename = pdf_path.name
        if not filename.lower().endswith(".pdf"):
            continue

        base_name = pdf_path.stem
        image_path = IMAGE_DIR / f"{base_name}_page1.png"

        convert_first_page(pdf_path, image_path)
        print(f"Saved: {image_path}")

if __name__ == "__main__":
    process_all_pdfs()
