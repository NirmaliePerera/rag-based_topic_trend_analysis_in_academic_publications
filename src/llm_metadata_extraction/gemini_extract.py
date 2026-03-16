# Enhanced the test code for extracting metadata from one image, to extract from a image folder
# Previously could not find a free version that extract metadata from the image
# Found a free version (gemini-2.5-flash) but has limits (requests per a minute (RPM) - 5, tokens per a minute (TPM) - 250k, and requests per a day(RPD) - 20)

import json
import os
import time
from pathlib import Path
from PIL import Image
from google import genai
from dotenv import load_dotenv
from prompt import METADATA_PROMPT

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
PROJECT_ROOT = Path(__file__).resolve().parents[2]
IMAGE_DIR = PROJECT_ROOT / "output_data" / "gemini_extracted_data" / "first_page_images"
OUTPUT_JSON = PROJECT_ROOT / "output_data" / "gemini_extracted_data" / "metadata_output" / "metadata.json"
MODEL_NAME = "gemini-2.5-flash"  # change if needed
REQUESTS_PER_MINUTE = 5
REQUEST_INTERVAL_SECONDS = 60 / REQUESTS_PER_MINUTE

OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)

client = genai.Client(api_key=GEMINI_API_KEY)


def strip_code_fences(text):
    stripped_text = text.strip()
    if stripped_text.startswith("```"):
        lines = stripped_text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped_text = "\n".join(lines).strip()
    return stripped_text


def wait_for_rate_limit(last_request_time):
    if last_request_time is None:
        return

    elapsed_seconds = time.monotonic() - last_request_time
    remaining_seconds = REQUEST_INTERVAL_SECONDS - elapsed_seconds
    if remaining_seconds > 0:
        print(f"Waiting {remaining_seconds:.1f}s to stay within rate limits...")
        time.sleep(remaining_seconds)


def extract_metadata_from_image(image_path):
    with Image.open(image_path) as image:
        response = client.models.generate_content(
            model=MODEL_NAME,
            contents=[METADATA_PROMPT, image],
        )
    return response.text


def process_all_images():
    if not IMAGE_DIR.exists():
        raise FileNotFoundError(f"Image directory not found: {IMAGE_DIR}")

    image_paths = sorted(
        path for path in IMAGE_DIR.iterdir()
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )

    all_metadata = []
    last_request_time = None

    for index, image_path in enumerate(image_paths, start=1):
        print(f"Processing {index}/{len(image_paths)}: {image_path.name}")
        wait_for_rate_limit(last_request_time)

        try:
            metadata_text = extract_metadata_from_image(image_path)
            parsed_metadata = json.loads(strip_code_fences(metadata_text))
            if not isinstance(parsed_metadata, dict):
                parsed_metadata = {"data": parsed_metadata}
            parsed_metadata["source_image"] = image_path.name
            all_metadata.append(parsed_metadata)
        except json.JSONDecodeError:
            all_metadata.append({
                "source_image": image_path.name,
                "error": "Invalid JSON",
                "raw": metadata_text,
            })
        except Exception as error:
            all_metadata.append({
                "source_image": image_path.name,
                "error": str(error),
            })
            print(f"Error processing {image_path.name}: {error}")
        finally:
            last_request_time = time.monotonic()

    with open(OUTPUT_JSON, "w", encoding="utf-8") as file_handle:
        json.dump(all_metadata, file_handle, indent=2, ensure_ascii=False)

    print(f"Saved metadata for {len(all_metadata)} image(s) to {OUTPUT_JSON}")


if __name__ == "__main__":
    process_all_images()