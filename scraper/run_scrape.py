"""
run_scrape.py
--------------
Entry point for Part 1: scrape >=30 articles from support.optisigns.com,
convert to clean Markdown, save to data/articles/<slug>.md with frontmatter.

Run: python scraper/run_scrape.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from fetch_articles import fetch_all_articles
from html_to_md import html_to_markdown
from utils import slugify, build_markdown_with_frontmatter

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "articles")


def main(min_articles=30):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    articles = fetch_all_articles(min_articles=min_articles)

    saved = 0
    skipped_empty = 0

    for article in articles:
        raw_html = article.get("body") or ""
        if not raw_html.strip():
            skipped_empty += 1
            continue

        body_md = html_to_markdown(raw_html)
        full_md = build_markdown_with_frontmatter(article, body_md)

        slug = slugify(article.get("title", ""), article["id"])
        filepath = os.path.join(OUTPUT_DIR, f"{slug}.md")

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(full_md)

        saved += 1

    print(f"\n[DONE] Saved {saved} markdown files to {OUTPUT_DIR}")
    if skipped_empty:
        print(f"[INFO] Skipped {skipped_empty} articles with no content (empty body).")


if __name__ == "__main__":
    main()
