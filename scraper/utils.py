import hashlib
import re


def slugify(title: str, fallback_id) -> str:
    """title -> safe slug for filename. Fallback to article id if title is empty."""
    if not title:
        return str(fallback_id)
    slug = title.strip().lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)   # remove special chars
    slug = re.sub(r"[\s_]+", "-", slug)        # spaces to hyphens
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or str(fallback_id)


def content_hash(text: str) -> str:
    """SHA-256 hash of content, used to detect article changes (Part 3)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_markdown_with_frontmatter(article: dict, body_md: str) -> str:
    """Attach YAML frontmatter (metadata) to the top of the .md file to serve:
    - quoting Article URL when AI assistant replies
    - detecting delta (updated_at, hash) in daily job (Part 3)
    """
    frontmatter = (
        "---\n"
        f"article_id: {article['id']}\n"
        f"title: \"{article['title'].replace(chr(34), chr(39))}\"\n"
        f"source_url: {article['html_url']}\n"
        f"updated_at: {article['updated_at']}\n"
        f"content_hash: {content_hash(body_md)}\n"
        "---\n\n"
    )
    return frontmatter + body_md
