"""
manifest.py
-----------
Manages the "memory/state" between daily job runs:
  - manifest.json maps article_id -> {slug, content_hash, source_url,
    updated_at, gemini_file_name}
  - Compares the new scrape with the old manifest to classify added / updated / skipped
  - Uploads/deletes files INDIVIDUALLY to/from Gemini File Search Store via API to
    accurately track gemini_file_name for each article_id, enabling
    the deletion of the old version when an article is updated.

Persistence note: manifest.json must be persisted across container runs
(containers inherently lack long-term state). Instructions for Part 3 of this project:
  -> Run the container on AWS EC2 using Linux Cron and mount the
     `data/` volume to persist manifest.json. See README.md for details.
"""

import json
import os
import time

from google.genai import types

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "manifest.json")


def load_manifest() -> dict:
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_manifest(manifest: dict) -> None:
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    with open(MANIFEST_PATH, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)


def classify(article_id: str, content_hash: str, manifest: dict) -> str:
    """Returns 'added' | 'updated' | 'skipped'."""
    prev = manifest.get(article_id)
    if prev is None:
        return "added"
    if prev.get("content_hash") != content_hash:
        return "updated"
    return "skipped"


def upload_single_file(client, store_name: str, filepath: str, display_name: str = ""):
    """Uploads a single .md file to Gemini File Search Store.
    Returns the file name (resource identifier) to be saved in the manifest.
    """
    slug = display_name or os.path.splitext(os.path.basename(filepath))[0]

    op = client.file_search_stores.upload_to_file_search_store(
        file_search_store_name=store_name,
        file=filepath,
        config=types.UploadToFileSearchStoreConfig(
            display_name=slug,
            mime_type="text/plain",
        ),
    )

    # Wait for the upload operation to complete
    _wait_for_operation(op, slug)

    # Return the file name from the operation result if available
    if hasattr(op, "result") and op.result:
        return getattr(op.result, "name", slug)
    return slug


def delete_single_file(client, store_name: str, file_name: str) -> None:
    """Deletes a single file from Gemini File Search Store."""
    try:
        client.file_search_stores.files.delete(
            file_search_store_name=store_name,
            file_name=file_name,
        )
    except Exception as e:
        print(f"  [warn] Failed to delete file from store ({file_name}): {e}")


def _wait_for_operation(op, label: str, timeout: int = 120):
    """Poll until the upload operation completes or times out."""
    elapsed = 0
    while elapsed < timeout:
        if hasattr(op, "done") and callable(op.done):
            if op.done():
                return
        elif hasattr(op, "result"):
            return
        else:
            return  # No polling mechanism available, assume done
        time.sleep(2)
        elapsed += 2

    print(f"  [warn] {label}: Operation not completed after {timeout}s, continuing...")
