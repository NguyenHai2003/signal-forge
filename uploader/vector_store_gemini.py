import glob
import json
import os
import time

import sys

from dotenv import dotenv_values
from google import genai
from google.genai import types

# Add parent directory (project root) to sys.path for importing system_prompt
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from system_prompt import SYSTEM_PROMPT  # noqa: E402

# Paths relative to this file's location (uploader/)
ARTICLES_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "articles")
STATE_FILE = os.path.join(os.path.dirname(__file__), "state_gemini.json")
STORE_DISPLAY_NAME = "optibot-kb"
MODEL = "gemini-2.5-flash"


# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ---------------------------------------------------------------------------
# File Search Store
# ---------------------------------------------------------------------------

def get_or_create_store(client: genai.Client, state: dict) -> types.FileSearchStore:
    """Reuse an existing store or create a new one if none exists."""
    store_name = state.get("store_name")
    if store_name:
        try:
            store = client.file_search_stores.get(name=store_name)
            print(f"[store] Reusing existing File Search Store: {store.name}")
            return store
        except Exception:
            print("[store] Previous store_name no longer exists, creating a new one...")

    store = client.file_search_stores.create(
        config=types.CreateFileSearchStoreConfig(
            display_name=STORE_DISPLAY_NAME,
        )
    )
    print(f"[store] Created new File Search Store: {store.name}")
    return store


# ---------------------------------------------------------------------------
# Upload documents
# ---------------------------------------------------------------------------

def upload_all_articles(client: genai.Client, store_name: str):
    """
    Upload each .md file to the File Search Store.
    Gemini automatically chunks and embeds content (default white_space_config).
    """
    md_files = sorted(glob.glob(os.path.join(ARTICLES_DIR, "*.md")))
    if not md_files:
        raise SystemExit(
            f"No .md files found in {ARTICLES_DIR}. "
            "Run scraper/run_scrape.py first."
        )

    print(f"[upload] Preparing to upload {len(md_files)} files to store {store_name}...")

    # Estimate chunk count (Gemini splits by whitespace/paragraphs)
    # Using ~800 tokens/chunk to match OpenAI auto strategy
    estimated_chunks = 0
    completed = 0
    failed = 0

    for idx, path in enumerate(md_files, 1):
        slug = os.path.splitext(os.path.basename(path))[0]

        # Estimate chunks for this file
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        tokens = len(content) // 4  # ~1 token per 4 characters
        file_chunks = max(1, tokens // 800)
        estimated_chunks += file_chunks

        try:
            op = client.file_search_stores.upload_to_file_search_store(
                file_search_store_name=store_name,
                file=path,
                config=types.UploadToFileSearchStoreConfig(
                    display_name=slug,
                    mime_type="text/plain",
                    # chunking_config defaults to white_space_config (auto)
                ),
            )
            # Wait for the upload operation to complete (polling)
            _wait_for_operation(op, slug)

            print(f"[upload] ({idx:3}/{len(md_files)}) ✓ {slug} (~{file_chunks} chunks)")
            completed += 1

        except Exception as e:
            print(f"[upload] ({idx:3}/{len(md_files)}) ✗ {slug} — Error: {e}")
            failed += 1

        # Avoid rate limits: short pause between requests
        time.sleep(0.5)

    print(f"\n[upload] Done: {completed} succeeded, {failed} failed")
    print(f"[upload] Estimated total chunks (Auto ~800 tokens): {estimated_chunks}")
    return md_files, completed, failed, estimated_chunks


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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Read API key directly from .env file (not via os.environ)
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env.sample")
    env_vars = dotenv_values(env_path)

    api_key = env_vars.get("GEMINI_API_KEY")
    if not api_key:
        raise SystemExit("GEMINI_API_KEY not found in .env.sample.")

    client = genai.Client(api_key=api_key)
    state = load_state()

    # Step 1: Get or create File Search Store
    store = get_or_create_store(client, state)

    # Step 2: Upload all .md files
    md_files, completed, failed, estimated_chunks = upload_all_articles(
        client, store.name
    )

    # Step 3: Refresh store info after upload
    store_refreshed = client.file_search_stores.get(name=store.name)

    # Step 4: Save state for reuse
    state.update(
        {
            "store_name": store.name,
            "store_display_name": store.display_name,
            "model": MODEL,
            "last_upload": {
                "total_files": len(md_files),
                "completed": completed,
                "failed": failed,
                "estimated_chunks": estimated_chunks,
            },
            "store_stats": {
                "active_documents": store_refreshed.active_documents_count,
                "pending_documents": store_refreshed.pending_documents_count,
                "failed_documents": store_refreshed.failed_documents_count,
                "size_bytes": store_refreshed.size_bytes,
            },
        }
    )
    save_state(state)

    print("\n===== SUMMARY =====")
    print(f"File Search Store Name    : {store.name}")
    print(f"File Search Store Display : {store.display_name}")
    print(f"Model                     : {MODEL}")
    print(f"Total .md files uploaded  : {len(md_files)}")
    print(f"  ✓ Succeeded             : {completed}")
    print(f"  ✗ Failed                : {failed}")
    print(f"Documents in store        : active={store_refreshed.active_documents_count}, "
          f"pending={store_refreshed.pending_documents_count}, "
          f"failed={store_refreshed.failed_documents_count}")
    print(f"Estimated chunks (~800 tokens/chunk): {estimated_chunks} chunks")
    print("(Gemini auto-embeds on upload, chunking by whitespace/paragraphs)")
    print(f"\nState saved to: {STATE_FILE}")


if __name__ == "__main__":
    main()
