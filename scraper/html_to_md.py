"""
html_to_md.py
--------------
Convert HTML body of a Zendesk article to clean Markdown.

Note: The `body` field from Zendesk API only contains the article content (no
nav/sidebar/footer of the whole page, since that's page-chrome not in API).
However, many OptiSigns articles still embed noise blocks inside the body:
  - ads div/section, "related articles", banner CTAs
  - redundant script/style
  - iframe (video) -> keep as links instead of dropping them
The clean_html() function handles noise removal before converting.
"""

import re
from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

# Common classes/ids for banners/ads/sub-navs in Help Center themes
NOISE_SELECTORS = [
    "nav", "footer", "aside",
    ".article-relatives", ".article-more-questions",
    ".promoted-articles", ".article-votes",
    ".cta", ".banner", ".ad", ".ads",
    "#article-nav", ".breadcrumbs",
    ".tabs-menu", ".tab-buttons", '[role="tablist"]',
    ".hidden", ".hide", '[style*="display: none"]', '[style*="display:none"]'
]


def clean_html(raw_html: str) -> BeautifulSoup:
    soup = BeautifulSoup(raw_html or "", "html.parser")

    # Always drop script/style tags
    for tag in soup(["script", "style"]):
        tag.decompose()

    # Drop nav/ads/related blocks according to listed selectors
    for sel in NOISE_SELECTORS:
        for tag in soup.select(sel):
            tag.decompose()

    # Convert iframe (embedded video, usually Youtube) into a markdown-friendly link
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src", "")
        if src:
            replacement = soup.new_tag("a", href=src)
            replacement.string = f"[video] {src}"
            iframe.replace_with(replacement)
        else:
            iframe.decompose()

    # Unwrap <strong>/<b> tags nested inside headings
    for heading in soup.find_all(re.compile('^h[1-6]$')):
        for strong in heading.find_all(['strong', 'b']):
            strong.unwrap()

    # Convert pseudo-heading <p><strong> into <h3>
    for p in soup.find_all('p'):
        if p.find('strong') and p.text.strip() == p.find('strong').text.strip():
            p.name = 'h3'

    # Convert Callout/Note tables into blockquotes
    for table in soup.find_all('table'):
        text_content = table.get_text(strip=True).lower()
        if 'note' in text_content[:15] or len(table.find_all('td')) <= 2:
            bq = soup.new_tag('blockquote')
            bq.string = table.get_text(separator="\n").strip()
            table.replace_with(bq)

    return soup


class ArticleMarkdownConverter(MarkdownConverter):
    """
    Customize markdownify to:
    - Keep relative links as is (don't convert to absolute).
    - Code block (<pre><code>) -> fenced code block ```lang.
    - Keep heading levels (h1..h6 -> #..######).
    """

    def convert_a(self, el, text, **kwargs):
        href = el.get("href", "")
        if not text.strip():
            text = href
        
        left_space = " " if text.startswith(" ") else ""
        right_space = " " if text.endswith(" ") else ""
        stripped_text = text.strip()
        
        return f"{left_space}[{stripped_text}]({href}){right_space}" if href else text


    def convert_pre(self, el, text, **kwargs):
        code_tag = el.find("code")
        lang = ""
        if code_tag and code_tag.get("class"):
            for c in code_tag.get("class"):
                if c.startswith("language-"):
                    lang = c.replace("language-", "")
        code_text = code_tag.get_text() if code_tag else el.get_text()
        code_text = code_text.strip("\n")
        return f"\n```{lang}\n{code_text}\n```\n"

    def convert_img(self, el, text, **kwargs):
        alt = el.attrs.get('alt', None) or ''
        src = el.attrs.get('src', None) or ''
        
        if not alt.strip() or alt.endswith('.png') or alt.endswith('.jpg') or 'screenshot' in alt.lower():
            title = el.attrs.get('title', '')
            alt = title if title else "Image from OptiSigns Help Center"
            
        return f"![{alt}]({src})"


def html_to_markdown(raw_html: str) -> str:
    soup = clean_html(raw_html)
    converter = ArticleMarkdownConverter(heading_style="ATX")
    md = converter.convert_soup(soup)

    # Clean up redundant spaces: >2 consecutive blank lines -> 1 blank line
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md


if __name__ == "__main__":
    sample = """
    <div>
      <nav>Home / Articles</nav>
      <h1>How to add a YouTube video</h1>
      <p>Follow these <strong>steps</strong> to add a video. See <a href="/hc/en-us/articles/123-other">related article</a>.</p>
      <pre><code class="language-python">print("hello")</code></pre>
      <div class="promoted-articles">You may also like...</div>
    </div>
    """
    print(html_to_markdown(sample))
