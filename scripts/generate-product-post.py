#!/usr/bin/env python3
"""
Auto-generate a B2B product recommendation blog post.

Each day this script:
  1. Scrapes the mecrt.com shop page for product URLs
  2. Picks one product that hasn't been featured yet
  3. Scrapes the product page (title, images, product intro, supplier info)
  4. Sends the material to DeepSeek to write a B2B buying-guide article
     that guides wholesale buyers toward sending an inquiry (not a retail purchase)
  5. Saves the article as content/posts/YYYY-MM-DD-slug.md
     with category "Product Recommendations"
"""

import os
import sys
import re
import json
import time
import random
import requests
from datetime import datetime, timezone, timedelta

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: beautifulsoup4 is required. Install it via: pip install beautifulsoup4")
    sys.exit(1)

# ============================================
# Constants
# ============================================
MECRT_SHOP_URL = "https://mecrt.com/shop/"
MECRT_SITE_URL = "https://mecrt.com"
POSTS_DIR = "content/posts"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# ============================================
# DeepSeek API (shared with generate-post.py, improved)
# ============================================
def call_api(prompt, api_key, model, api_url, temperature=0.85, attempts=3):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": 4096,
    }
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(
                f"{api_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=(15, 120),
            )
            if not resp.ok:
                body = resp.text[:500]
                raise RuntimeError(f"HTTP {resp.status_code}: {body}")
            resp_data = resp.json()
            choice = resp_data["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("API returned empty content")
            if choice.get("finish_reason") == "length":
                raise ValueError("Response truncated (max_tokens reached)")
            return content
        except (requests.RequestException, KeyError, TypeError, ValueError, RuntimeError) as exc:
            last_error = exc
            if attempt == attempts:
                break
            delay = 2 ** (attempt - 1)
            print(f"API attempt {attempt}/{attempts} failed: {exc}; retrying in {delay}s")
            time.sleep(delay)
    raise RuntimeError(f"AI API failed after {attempts} attempts: {last_error}")


# ============================================
# Slugify & title helpers (mirrors generate-post.py)
# ============================================
def slugify(text):
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s-]+", "-", slug)
    return slug[:60].strip("-")


def extract_title(text):
    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("# "):
            return line.lstrip("# ").strip()[:80]
        if line and not line.startswith("#") and not line.startswith("---"):
            return re.sub(r"[*_`#]", "", line).strip()[:80]
    return "Untitled"


def validate_title(text):
    title = extract_title(text)
    title = re.sub(r"[\x00-\x1f\x7f]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    if not title or title == "Untitled" or not slugify(title):
        raise ValueError("AI returned an unusable title")
    return title[:80]


# ============================================
# Scrape product URLs from mecrt.com shop pages
# ============================================
def fetch_page(url, timeout=20):
    """Fetch a page with a browser-like User-Agent."""
    resp = requests.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.text


def scrape_product_links(max_pages=50):
    """Scrape all product URLs from the shop page (paginated)."""
    all_links = []
    seen = set()

    for page_num in range(1, max_pages + 1):
        if page_num == 1:
            url = MECRT_SHOP_URL
        else:
            url = f"{MECRT_SHOP_URL}page/{page_num}/"

        print(f"Scraping shop page {page_num}: {url}")
        try:
            html = fetch_page(url)
        except requests.RequestException as exc:
            print(f"  Failed to fetch page {page_num}: {exc}")
            break

        soup = BeautifulSoup(html, "html.parser")
        links_on_page = []

        # WooCommerce product links are <a href=".../product/...">
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "/product/" in href and href.startswith(MECRT_SITE_URL):
                # Normalize: strip query/fragment, ensure trailing slash
                clean = href.split("?")[0].split("#")[0].rstrip("/")
                if clean not in seen:
                    seen.add(clean)
                    links_on_page.append(clean)

        if not links_on_page:
            print(f"  No products found on page {page_num}, stopping.")
            break

        all_links.extend(links_on_page)
        print(f"  Found {len(links_on_page)} products (total: {len(all_links)})")

        # Be polite but fast enough for 40+ pages
        time.sleep(0.5)

    return all_links


# ============================================
# Track used products (scan existing posts)
# ============================================
def get_used_product_urls():
    """Scan existing posts for 'product_url' in front matter."""
    used = set()
    if not os.path.exists(POSTS_DIR):
        return used

    for fname in os.listdir(POSTS_DIR):
        if not fname.endswith(".md"):
            continue
        filepath = os.path.join(POSTS_DIR, fname)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                in_front = False
                for line in f:
                    stripped = line.strip()
                    if stripped == "---":
                        in_front = not in_front
                        if not in_front:
                            break  # front matter ended
                        continue
                    if in_front and stripped.startswith("product_url:"):
                        val = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                        if val:
                            used.add(val)
        except (IOError, OSError):
            continue

    return used


def pick_product(all_products, used_products):
    """Pick a random product URL that hasn't been used yet."""
    available = [p for p in all_products if p not in used_products]
    if not available:
        print("ERROR: All products from mecrt.com have already been featured.")
        sys.exit(2)

    chosen = random.choice(available)
    print(f"Used products: {len(used_products)}/{len(all_products)}")
    print(f"Selected product: {chosen}")
    return chosen


# ============================================
# Scrape a single product page
# ============================================
def scrape_product(product_url):
    """Scrape a mecrt.com product page for key data."""
    print(f"Scraping product page: {product_url}")
    html = fetch_page(product_url)
    soup = BeautifulSoup(html, "html.parser")

    # --- Product title ---
    title = None
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)
    if not title:
        # Fallback: og:title meta
        og_title = soup.find("meta", property="og:title")
        if og_title:
            title = og_title.get("content", "").strip()
    if not title:
        title = "Untitled Product"
    print(f"  Title: {title}")

    # --- Product images ---
    images = []
    # Look for WooCommerce product gallery images
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-large_image") or ""
        if not src:
            continue
        # Only keep actual product images from uploads
        if "wp-content/uploads/" in src and ("600" in src or "1024" in src or "1536" in src or "original" in src):
            # Normalize to a larger version if possible
            clean = src.split("?")[0]
            if clean not in images:
                images.append(clean)

    # Fallback: og:image
    if not images:
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            images.append(og_img["content"].split("?")[0])

    main_image = images[0] if images else None
    if main_image:
        print(f"  Main image: {main_image}")
    else:
        print("  No product image found")

    # --- Product introduction ---
    product_intro = ""
    # Strategy 1: Look for "Product Introduction" heading and grab following text
    for heading in soup.find_all(["h2", "h3", "h4", "strong", "b"]):
        heading_text = heading.get_text(strip=True).lower()
        if "product introduction" in heading_text or "product description" in heading_text:
            # Grab the next sibling or parent's text content
            parent = heading.find_parent()
            if parent:
                # Get text from the parent, excluding the heading itself
                heading.extract()
                product_intro = parent.get_text(separator=" ", strip=True)
            break

    # Strategy 2: WooCommerce short description
    if not product_intro:
        short_desc = soup.find("div", class_="woocommerce-product-details__short-description")
        if short_desc:
            product_intro = short_desc.get_text(separator=" ", strip=True)

    # Strategy 3: Meta description
    if not product_intro:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            product_intro = meta_desc["content"].strip()

    if product_intro:
        print(f"  Product intro: {product_intro[:120]}...")
    else:
        print("  No product introduction found")

    # --- Supplier / company info ---
    supplier_info = ""
    for heading in soup.find_all(["h2", "h3", "h4", "strong", "b"]):
        heading_text = heading.get_text(strip=True).lower()
        if heading_text == "supplier" or "about" in heading_text and "mecrt" in heading_text:
            parent = heading.find_parent()
            if parent:
                heading.extract()
                supplier_info = parent.get_text(separator=" ", strip=True)
            break

    # Fallback: look for "Founded in 2015" text block
    if not supplier_info:
        page_text = soup.get_text(separator=" ", strip=True)
        match = re.search(r"(Founded in 2015.*?)(?:Read more|$)", page_text, re.DOTALL)
        if match:
            supplier_info = match.group(1).strip()

    if supplier_info:
        print(f"  Supplier info: {supplier_info[:120]}...")
    else:
        print("  No supplier info found")

    return {
        "url": product_url,
        "title": title,
        "main_image": main_image,
        "images": images[:5],  # Keep up to 5 images
        "product_intro": product_intro,
        "supplier_info": supplier_info,
    }


# ============================================
# Build DeepSeek prompts
# ============================================

# Multiple article structures + opening styles to randomize output
# so every post does not look identical (avoid AI-pattern detection).
ARTICLE_STRUCTURES = [
    {
        "name": "standard",
        "headings": [
            "Product Overview",
            "Material and Design Highlights",
            "Customization for Bulk Buyers",
            "What to Verify Before Ordering",
            "Next Steps",
        ],
    },
    {
        "name": "buyer-lens",
        "headings": [
            "What This Product Is",
            "Design and Craft Details",
            "Sourcing Options: Stock vs. Custom",
            "Questions to Ask Before Ordering",
            "How to Move Forward",
        ],
    },
    {
        "name": "checklist",
        "headings": [
            "The Product in Brief",
            "Specs and Build Quality",
            "Ordering: MOQ and Customization",
            "Checklist Before You Commit",
            "Where to Go from Here",
        ],
    },
    {
        "name": "compact",
        "headings": [
            "Overview",
            "Materials and Craftsmanship",
            "Bulk Ordering Details",
            "Closing Notes",
        ],
    },
    {
        "name": "scenario",
        "headings": [
            "Product Snapshot",
            "Who This Fits: Buyers and Use Cases",
            "Customization and OEM Options",
            "What to Confirm with the Supplier",
            "Next Step",
        ],
    },
    {
        "name": "trade-focus",
        "headings": [
            "At a Glance",
            "Construction and Materials",
            "Wholesale and OEM Terms",
            "Pre-Order Verification",
            "Wrapping Up",
        ],
    },
]

OPENING_STYLES = [
    "Open by stating what the product is and which buyers it serves",
    "Open with the buyer's need this product addresses, then introduce the product",
    "Open with a typical use case or setting where this product fits, then describe it",
    "Open by positioning the product within its category, then detail it",
    "Open with a sourcing angle \u2014 why a wholesale buyer would consider this item",
]


def build_title_prompt(product):
    return f"""Write one clear, professional blog post title for a B2B product recommendation article about this product:

Product name: {product['title']}

The title should:
- Be under 80 characters
- Appeal to wholesale buyers, importers, and church procurement officers
- Sound like a product buying guide, not a retail listing
- Use plain English without clickbait

Output ONLY the title."""


def build_article_prompt(product):
    # Truncate source material to avoid token overflow
    intro = (product.get("product_intro") or "")[:2000]
    supplier = (product.get("supplier_info") or "")[:1500]

    # Build image markdown if available
    image_md = ""
    if product.get("main_image"):
        image_md = f"\n![{product['title']}]({product['main_image']})\n"

    # Randomize structure & opening so posts do not all look identical
    structure = random.choice(ARTICLE_STRUCTURES)
    opening = random.choice(OPENING_STYLES)
    headings_block = "\n".join(f"  ## {h}" for h in structure["headings"])
    heading_count = len(structure["headings"])

    return f"""You are a B2B trade copywriter for a Catholic religious goods manufacturer (Mecrt / Yiwu International Trade Co., Ltd).
Write a product recommendation article for wholesale buyers, importers, and church procurement officers.

=== PRODUCT SOURCE MATERIAL (use as facts, do not invent beyond this) ===
Product title: {product['title']}
Product page: {product['url']}

Product introduction:
{intro}

Supplier / company background:
{supplier}
=== END SOURCE MATERIAL ===

ARTICLE REQUIREMENTS:
- 900-1300 words, English, B2B tone
- Category: Product Recommendations
- Use Markdown: ## for H2, ### for H3
- Use EXACTLY {heading_count} headings total (## and ### combined). NEVER use more than {heading_count + 1} headings.
- Use this structure (you may tweak a heading's wording slightly to fit the product, but keep this section flow and count):
{headings_block}
- Do NOT include an H1 title — we add it separately
- Do NOT include front matter, meta description, or JSON-LD
- Do NOT write a final "Request a Wholesale Quote" or CTA section — our system appends one automatically

CONTENT STRUCTURE:
- {opening}.
- Explain key material / craftsmanship / design points from the source material
- Discuss customization and OEM/ODM possibilities for bulk buyers
- Cover what a buyer should verify before placing a bulk order (specs, samples, MOQ)
- Close with a practical next step guiding the reader to send an inquiry (NOT "buy now")

B2B INQUIRY FOCUS (critical):
- This is a B2B wholesale site. Readers are sourcing professionals, not retail shoppers.
- Use language like "request a quote", "send an inquiry", "contact us for specifications"
- NEVER use retail language like "add to cart", "buy now", "order today", "limited time offer"
- Mention bulk pricing tiers if available in the source material
- Guide toward inquiry, not checkout

COMMERCIAL FACTS SAFETY:
- Only use facts from the source material above
- Do NOT invent prices, dimensions, lead times, certifications, or specifications
- If a detail is not in the source, say "contact us to confirm" or "varies by item"
- In-stock MOQ: 12 pieces; OEM/custom MOQ: 1200 pieces (you may mention these)

LINKS (important):
- Do NOT include the product page URL as a clickable hyperlink anywhere in the article body.
- You MAY mention "mecrt.com" as a brand name in plain text (e.g. "reach Mecrt through mecrt.com"), but never render the full product URL and never use Markdown link syntax [..](..) in the body.
- The only clickable link to the product page is appended automatically in a final CTA section — do not write that section yourself.
- Do NOT mention Alibaba, alibaba.com, or any Alibaba store — this article directs buyers to mecrt.com only

EDITORIAL RULES:
- Professional, calm, informative English — like a trade magazine article
- Avoid canned phrases: "in today's market", "stands out as", "game-changer", "perfect choice", "comprehensive guide", "in conclusion"
- Vary sentence and paragraph length naturally — do not write uniform blocks of the same length
- Do not fabricate customer reviews, sales data, or personal experience
- Use "we" or "our" sparingly, only for capabilities mentioned in the source material
- Include the product image at the top of the article body using this exact markdown:
{image_md}

Output ONLY the article in Markdown format, no preamble."""


def build_faq_prompt(product, title, article_md):
    return f"""Generate 2-3 FAQ items (JSON-LD format) for a B2B product recommendation article titled "{title}".

Product: {product['title']}
Product page: {product['url']}

The article is about wholesale sourcing of this product. Focus FAQ on buyer concerns: MOQ, customization, lead times, samples, bulk pricing.

--- ARTICLE CONTEXT ---
{article_md[:2000]}
--- END ---

Anti-AI rules for FAQ answers:
- Do NOT start answers with "Yes, " or "Absolutely, "
- Keep answers short: 1-3 sentences
- Include numbers only from verified facts (MOQ 12 in-stock, 1200 OEM)
- Never invent prices, lead times, dimensions, or certifications
- If a detail is unknown, tell the buyer to contact us

Output ONLY valid JSON-LD for a FAQPage (schema.org format), no markdown, no explanation.
Example:
{{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {{
      "@type": "Question",
      "name": "Question here?",
      "acceptedAnswer": {{
        "@type": "Answer",
        "text": "Answer here..."
      }}
    }}
  ]
}}
"""


# ============================================
# Validation (lighter than keyword articles)
# ============================================
def validate_product_article(article_md, product):
    article_md = article_md.strip()
    if not article_md:
        raise ValueError("Article is empty")
    if article_md.startswith("---"):
        raise ValueError("Article unexpectedly contains front matter")
    if article_md.startswith("```"):
        raise ValueError("Article is wrapped in a code fence")
    if re.search(r"(?m)^#\s+", article_md):
        raise ValueError("Article unexpectedly contains an H1 title")

    heading_count = len(re.findall(r"(?m)^#{2,3}\s+", article_md))
    if not 3 <= heading_count <= 12:
        raise ValueError(f"Article heading count {heading_count} is outside 3-12")

    word_count = len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", article_md))
    if not 700 <= word_count <= 1800:
        raise ValueError(f"Article word count {word_count} is outside 700-1800")

    # Must not contain retail CTAs
    retail_phrases = [
        "add to cart",
        "buy now",
        "order today",
        "limited time offer",
        "add to basket",
        "shop now",
    ]
    lowered = article_md.casefold()
    for phrase in retail_phrases:
        if phrase in lowered:
            raise ValueError(f"Retail phrase detected: '{phrase}'")

    # Must mention the product URL or mecrt.com
    if product["url"] not in article_md and "mecrt.com" not in article_md:
        raise ValueError("Article does not reference the product or mecrt.com")

    return article_md


def parse_and_validate_faq(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json|jsonld)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    faq = json.loads(raw)
    if faq.get("@context") != "https://schema.org" or faq.get("@type") != "FAQPage":
        raise ValueError("FAQ must be a schema.org FAQPage")
    entities = faq.get("mainEntity")
    if not isinstance(entities, list) or not 2 <= len(entities) <= 3:
        raise ValueError("FAQ must contain 2-3 questions")
    for item in entities:
        answer = item.get("acceptedAnswer", {})
        if item.get("@type") != "Question" or answer.get("@type") != "Answer":
            raise ValueError("FAQ contains an invalid question or answer")
        if not isinstance(item.get("name"), str) or not isinstance(answer.get("text"), str):
            raise ValueError("FAQ question and answer must be strings")
    normalized = json.dumps(faq, ensure_ascii=False, separators=(",", ":"))
    return normalized.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# ============================================
# Build markdown file
# ============================================
def build_markdown(title, product, article_md, faq_json):
    tz_bj = timezone(timedelta(hours=8))
    now = datetime.now(tz_bj)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S")
    slug = slugify(title)
    filepath = f"{POSTS_DIR}/{date_str}-{slug}.md"

    if os.path.exists(filepath):
        filepath = f"{POSTS_DIR}/{date_str}-{time_str}-{slug}.md"

    iso_date = now.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    safe_title = json.dumps(title, ensure_ascii=False)
    safe_product_url = json.dumps(product["url"], ensure_ascii=False)
    # Use product title as keyword for uniqueness tracking in validate-site.py
    safe_keyword = json.dumps(product["title"][:80], ensure_ascii=False)

    # Pick category by product type so taxonomy pages stay meaningful,
    # and don't duplicate the "wholesale / product-recommendation / B2B" tag cluster.
    title_lower = title.lower()
    if "rosary" in title_lower:
        category_value = "Rosary"
    else:
        category_value = "Catholic Gifts"

    front_matter_lines = [
        "---",
        f"title: {safe_title}",
        f"date: {iso_date}",
        "draft: false",
        f"keyword: {safe_keyword}",
        f"product_url: {safe_product_url}",
        'tags: ["wholesale", "B2B"]',
        f'categories: ["{category_value}"]',
    ]
    if product.get("main_image"):
        front_matter_lines.append(f'featureimage: {json.dumps(product["main_image"])}')
        front_matter_lines.append(f'thumbnail: {json.dumps(product["main_image"])}')
    if faq_json and faq_json.strip():
        front_matter_lines.append("faqVerified: true")
        front_matter_lines.append("faqJson: |")
        for line in faq_json.strip().split("\n"):
            front_matter_lines.append("  " + line)
    front_matter_lines.append("---")
    front_matter = "\n".join(front_matter_lines)

    # CTA block — inquiry focused, mecrt.com product link at the very end
    cta = "## Request a Wholesale Quote\n\n"
    cta += f"Interested in sourcing **{title}** for your store, parish, or distribution network? "
    cta += f"**[View this product on mecrt.com]({product['url']})** to review specifications and send an inquiry. "
    cta += "Our team responds within 24 hours with pricing, MOQ, and customization options.\n"

    content = f"""{front_matter}

{article_md}

---

{cta}
"""
    return filepath, content


# ============================================
# Main
# ============================================
def main():
    api_key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("AI_MODEL") or "deepseek-v4-flash"
    api_url = os.environ.get("AI_API_URL") or "https://api.deepseek.com/v1"

    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable not set")
        sys.exit(1)

    # 1. Scrape product list from mecrt.com
    print("Step 1: Scraping product list from mecrt.com...")
    all_products = scrape_product_links(max_pages=50)
    if not all_products:
        print("ERROR: No products found on mecrt.com shop page")
        sys.exit(1)
    print(f"Found {len(all_products)} products on mecrt.com")

    # 2. Pick an unused product
    print("\nStep 2: Selecting product...")
    used_products = get_used_product_urls()
    product_url = pick_product(all_products, used_products)

    # 3. Scrape product details
    print("\nStep 3: Scraping product details...")
    product = scrape_product(product_url)
    if not product["product_intro"] and not product["supplier_info"]:
        print("WARNING: Could not extract product intro or supplier info; article quality may be limited")

    # 4. Generate title
    print("\nStep 4: Generating title...")
    title_raw = call_api(build_title_prompt(product), api_key, model, api_url, temperature=0.7)
    title = validate_title(title_raw)
    print(f"Title: {title}")

    # 5. Generate article (with retry on validation failure)
    print("\nStep 5: Generating article...")
    base_prompt = build_article_prompt(product)
    article_md = None
    for attempt in range(1, 4):
        prompt = base_prompt
        if attempt > 1:
            prompt += f"\n\nREWRITE REQUIRED: Previous draft was rejected: {validation_error}\nWrite a new draft."
        print(f"  Article draft {attempt}/3...")
        draft = call_api(prompt, api_key, model, api_url, temperature=0.65)
        try:
            article_md = validate_product_article(draft, product)
            break
        except ValueError as exc:
            validation_error = str(exc)
            print(f"  Draft {attempt} rejected: {validation_error}")
    if article_md is None:
        print(f"ERROR: No article draft passed validation after 3 attempts: {validation_error}")
        sys.exit(1)

    # 6. Generate FAQ
    print("\nStep 6: Generating FAQ...")
    try:
        faq_raw = call_api(
            build_faq_prompt(product, title, article_md),
            api_key, model, api_url, temperature=0.3,
        )
        faq_json = parse_and_validate_faq(faq_raw)
        print("FAQ generated and validated")
    except Exception as exc:
        print(f"Warning: FAQ generation failed: {exc}")
        faq_json = ""

    # 7. Save file
    os.makedirs(POSTS_DIR, exist_ok=True)
    filepath, content = build_markdown(title, product, article_md, faq_json)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"\nSaved: {filepath}")
    print("Done!")


if __name__ == "__main__":
    main()
