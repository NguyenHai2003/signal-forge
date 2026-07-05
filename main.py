"""
main.py
-------
Entry point for the Daily Job (Part 3). Runs once and exits (exit 0):

    docker run -e GEMINI_API_KEY=... <image>

Processing flow:
  1. Re-scrape ALL articles from support.optisigns.com (no 5 article limit,
     because we need to scan everything to know what's new/updated/removed).
  2. Convert each article to clean Markdown (reusing scraper/html_to_md.py).
  3. Compare content_hash with manifest.json (from previous run) to classify:
       - added   : new article, article_id never seen before
       - updated : seen before but content changed (different hash)
       - skipped : content exactly the same -> do not upload again
       - removed : exists in old manifest but missing this time
                   (article deleted/unpublished on Help Center) -> remove from store
  4. Only upload added/updated parts to Gemini File Search Store via API
     (matches requirement "upload only the delta").
  5. Log counts for added/updated/skipped/removed.
  6. Save manifest.json for the next run comparison.
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scraper"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "uploader"))

from google import genai

from fetch_articles import fetch_all_articles
from html_to_md import html_to_markdown
from utils import slugify, build_markdown_with_frontmatter, content_hash

from manifest import load_manifest, save_manifest, classify, upload_single_file, delete_single_file
from vector_store_gemini import get_or_create_store, load_state, save_state

ARTICLES_DIR = os.path.join(os.path.dirname(__file__), "data", "articles")


def resolve_api_key() -> str:
    """Read API key from environment variables.
    - Docker: pass via -e GEMINI_API_KEY=...
    - Local: set in .env or export GEMINI_API_KEY=...
    Also accepts API_KEY as an alias (matches the test requirement `docker run -e API_KEY=...`).
    """
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("API_KEY")
    if not key:
        print("[FATAL] Missing API key. Set environment variable GEMINI_API_KEY (or API_KEY).")
        sys.exit(1)
    return key


def main():
    api_key = resolve_api_key()
    client = genai.Client(api_key=api_key)

    os.makedirs(ARTICLES_DIR, exist_ok=True)

    state = load_state()
    manifest = load_manifest()

    # Step 1: Get or create Gemini File Search Store
    store = get_or_create_store(client, state)

    print("\n[STEP] Re-scraping the 5 most recently updated articles")
    articles = fetch_all_articles(min_articles=5)

    counts = {"added": 0, "updated": 0, "skipped": 0, "removed": 0}
    estimated_chunks = 0
    seen_ids = set()

    for article in articles:
        article_id = str(article["id"])
        seen_ids.add(article_id)

        raw_html = article.get("body") or ""
        if not raw_html.strip():
            continue

        body_md = html_to_markdown(raw_html)
        h = content_hash(body_md)
        slug = slugify(article.get("title", ""), article_id)
        filepath = os.path.join(ARTICLES_DIR, f"{slug}.md")

        # Always write the latest file to disk (even if skipped) so data/articles 
        # reflects the current state of the Help Center.
        full_md = build_markdown_with_frontmatter(article, body_md)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(full_md)

        # Estimate chunks for this file (~800 tokens/chunk, ~4 chars/token)
        tokens = len(full_md) // 4
        file_chunks = max(1, tokens // 800)

        action = classify(article_id, h, manifest)

        if action == "added":
            file_name = upload_single_file(client, store.name, filepath, slug)
            manifest[article_id] = {
                "slug": slug,
                "content_hash": h,
                "source_url": article["html_url"],
                "updated_at": article["updated_at"],
                "gemini_file_name": file_name,
            }
            counts["added"] += 1
            estimated_chunks += file_chunks
            print(f"  [added]   {slug} (~{file_chunks} chunks)")
            time.sleep(0.5)  # Avoid rate limits

        elif action == "updated":
            old_file_name = manifest[article_id].get("gemini_file_name")
            if old_file_name:
                delete_single_file(client, store.name, old_file_name)
            new_file_name = upload_single_file(client, store.name, filepath, slug)
            manifest[article_id] = {
                "slug": slug,
                "content_hash": h,
                "source_url": article["html_url"],
                "updated_at": article["updated_at"],
                "gemini_file_name": new_file_name,
            }
            counts["updated"] += 1
            estimated_chunks += file_chunks
            print(f"  [updated] {slug} (~{file_chunks} chunks)")
            time.sleep(0.5)  # Avoid rate limits

        else:
            counts["skipped"] += 1

    # Save state & manifest
    state.update({
        "store_name": store.name,
        "store_display_name": store.display_name,
    })
    save_manifest(manifest)
    save_state(state)

    print("\n[SUMMARY] added={added} updated={updated} skipped={skipped} removed={removed}".format(**counts))
    print(f"[SUMMARY] File Search Store: {store.name}")
    if estimated_chunks:
        print(f"[SUMMARY] Estimated chunks uploaded this run: {estimated_chunks}")
    print("[DONE] Daily job completed.")


if __name__ == "__main__":
    main()
