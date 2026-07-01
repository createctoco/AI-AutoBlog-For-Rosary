#!/usr/bin/env python3
"""
Auto-generate a B2B SEO blog post using DeepSeek API.
Saves output as content/posts/YYYY-MM-DD-slug.md
Supports multiple posts per day with unique filenames.
Features:
  - Pexels API for featured images (with local images/ fallback)
  - Markdown output for TOC compatibility
  - Hero image support (Blowfish theme)
"""

import os
import sys
import re
import random
import glob
import json
import time
import yaml
import requests
from datetime import datetime, timezone, timedelta

# ============================================
# Load Configuration
# ============================================
def load_config():
    with open("blog-config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_alibaba(config):
    return {
        "store": config.get("alibaba_store_url", ""),
        "products": config.get("alibaba_products", [])
    }

def get_business_facts(config):
    facts = config.get("business_facts", {})
    required = ("stock_moq", "oem_moq", "approved_claims")
    missing = [key for key in required if not facts.get(key)]
    if missing:
        raise ValueError(f"Missing required business_facts: {', '.join(missing)}")
    return facts

# ============================================
# Pick Keyword (avoid duplicates, random selection)
# ============================================
def pick_keyword(config):
    keywords = config.get("keywords", [])
    if not keywords:
        print("ERROR: no keywords found in blog-config.yaml")
        sys.exit(1)

    posts_dir = "content/posts"
    used = set()
    if os.path.exists(posts_dir):
        for fname in os.listdir(posts_dir):
            if not fname.endswith(".md"):
                continue
            filepath = os.path.join(posts_dir, fname)
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("keyword:"):
                        val = line.split(":", 1)[1].strip().strip('"').strip("'")
                        used.add(val)

    available = [k for k in keywords if k not in used]
    if not available:
        print("ERROR: all configured keywords have already been used; add new keywords before publishing again")
        sys.exit(2)

    chosen = random.choice(available)
    print(f"Used keywords: {len(used)}/{len(keywords)}")
    print(f"Selected keyword: {chosen}")
    return chosen

# ============================================
# Fetch Featured Image from Pexels API
# ============================================

def is_japanese_image(photo):
    """
    Check if a Pexels photo is Japanese-themed and should be excluded.
    Returns True if the image should be SKIPPED.
    """
    # Blacklisted Pexels photo IDs (confirmed bad images)
    BLACKLISTED_PHOTO_IDS = {
        "9566267",   # Japanese-themed image, confirmed by user
    }

    photo_id = str(photo.get("id", ""))
    if photo_id in BLACKLISTED_PHOTO_IDS:
        print(f"  Skipping blacklisted photo ID: {photo_id}")
        return True

    # Check alt text for Japanese-related keywords
    alt_text = (photo.get("alt") or "").lower()
    japanese_keywords = [
        "japan", "japanese", "tokyo", "kyoto", "osaka", "hiroshima",
        "shinto", "torii", "geisha", "kimono", "sake", "matcha",
        "zen garden", "bonsai", "origami", "sushi", "ramen",
    ]
    for kw in japanese_keywords:
        if kw in alt_text:
            print(f"  Skipping Japanese-themed photo (alt: ...{alt_text[:60]}...)")
            return True

    # Check photographer name for CJK characters (Japanese/Chinese/Korean)
    photographer = photo.get("photographer", "")
    if __import__('re').search(r'[぀-ゟ゠-ヿ一-鿿]', photographer):
        print(f"  Skipping photo by CJK photographer: {photographer}")
        return True

    return False


def fetch_pexels_image(keyword, api_key):
    """Fetch a Pexels image URL (no local download, avoid repo bloat)"""
    if not api_key:
        print("No Pexels API key provided, skipping Pexels")
        return None

    search_terms = [
        keyword.replace("wholesale", "").replace("bulk", "").replace("OEM", "").replace("guide", "").strip(),
        "catholic rosary beads",
        "rosary",
        "catholic prayer"
    ]

    for search_term in search_terms:
        if not search_term.strip():
            continue
        try:
            print(f"Searching Pexels for: {search_term}")
            response = requests.get(
                "https://api.pexels.com/v1/search",
                params={"query": search_term, "per_page": 15, "size": "large"},
                headers={"Authorization": api_key},
                timeout=15
            )
            response.raise_for_status()
            data = response.json()

            if data.get("photos"):
                # Filter out Japanese-themed images
                filtered_photos = [p for p in data["photos"] if not is_japanese_image(p)]
                if not filtered_photos:
                    print(f"  All {len(data['photos'])} photos filtered out (Japanese-themed), trying next search term...")
                    continue
                photo = random.choice(filtered_photos)
                image_url = photo["src"]["large2x"]
                photographer = photo.get("photographer", "Pexels")
                print(f"Pexels image URL: {image_url} (by {photographer})")
                return image_url  # Return URL directly, no local download

        except Exception as e:
            print(f"Warning: Pexels search failed for '{search_term}': {e}")
            continue

    print("Warning: Could not fetch any image from Pexels")
    return None

# ============================================
# Fallback: Random Image from Local images/ Folder
# ============================================
def fetch_local_fallback_image():
    """Pick a random image from static/images/ (no copy, avoid repo bloat)"""
    images_dir = "static/images"
    if not os.path.exists(images_dir):
        images_dir = "images"
    if not os.path.exists(images_dir):
        print("No local images/ folder found, skipping fallback")
        return None

    extensions = ('*.jpg', '*.jpeg', '*.png', '*.webp', '*.gif')
    image_files = []
    for ext in extensions:
        image_files.extend(glob.glob(os.path.join(images_dir, ext)))
        image_files.extend(glob.glob(os.path.join(images_dir, ext.upper())))

    if not image_files:
        print("No images found in images/ folder, skipping fallback")
        return None

    chosen = random.choice(image_files)
    basename = os.path.basename(chosen)
    print(f"Local fallback image: {basename}")
    return f"https://rosarysupply.com/images/{basename}"  # Absolute URL for Blowfish hotlinkFeatureImage


# ============================================
# Get Featured Image (Pexels first, local fallback)
# ============================================
def get_featured_image(keyword, pexels_api_key):
    """Try Pexels API first; fallback to local random image if fails"""
    image_url = fetch_pexels_image(keyword, pexels_api_key)
    if image_url:
        return image_url

    print("Pexels failed, trying local images/ fallback...")
    local_image = fetch_local_fallback_image()
    if local_image:
        return local_image

    print("Warning: no feature image available for this post")
    return None

# ============================================
# Call DeepSeek API
# ============================================
def call_api(prompt, api_key, model, api_url, temperature=0.85, attempts=3):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": 2500
    }
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(
                f"{api_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
                timeout=(15, 120)
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("API returned empty content")
            return content
        except (requests.RequestException, KeyError, TypeError, ValueError) as exc:
            last_error = exc
            if attempt == attempts:
                break
            delay = 2 ** (attempt - 1)
            print(f"API attempt {attempt}/{attempts} failed: {exc}; retrying in {delay}s")
            time.sleep(delay)
    raise RuntimeError(f"AI API failed after {attempts} attempts: {last_error}")

# ============================================
# Build Prompts
# ============================================
def build_title_prompt(keyword):
    return f"Generate a short, SEO-friendly blog post title about: {keyword}. Output ONLY the title, nothing else."

def format_business_facts(facts):
    claims = "\n".join(f"- {claim}" for claim in facts["approved_claims"])
    return f"""VERIFIED BUSINESS FACTS (the only commercial facts you may state):
- In-stock MOQ: {facts['stock_moq']} pieces
- OEM/custom-logo MOQ: {facts['oem_moq']} pieces
{claims}"""

def build_faq_prompt(keyword, title, article_md, facts):
    return f"""Generate 2-3 FAQ items (JSON-LD format) related to the blog post titled "{title}" with keyword "{keyword}".
The topic is Catholic religious goods wholesale/B2B.

{format_business_facts(facts)}

Use the article below only for topic context. Do not repeat a claim unless it is present in the verified facts above.
--- ARTICLE ---
{article_md}
--- END ARTICLE ---

Anti-AI rules for FAQ answers:
- Do NOT start answers with "Yes, " or "Absolutely, " — get straight to the point
- Use plain, conversational English — like a factory sales rep answering a buyer's question
- Keep answers short: 1-3 sentences max
- Include a number only when it appears in the verified facts
- Never invent prices, lead times, dimensions, materials, certifications, shipping terms, stock status, or product origins
- If a requested detail is not in the verified facts, tell the buyer to contact us for the current specification

Output ONLY valid JSON-LD for a FAQPage (schema.org format), no markdown, no explanation.
Example format:
{{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [
    {{
      "@type": "Question",
      "name": "Actual buyer question here?",
      "acceptedAnswer": {{
        "@type": "Answer",
        "text": "Natural sounding answer..."
      }}
    }}
  ]
}}
"""

def build_article_prompt(keyword, alibaba, facts):
    products = alibaba["products"]
    store = alibaba["store"]
    product_list = "\n".join([f"  - {p}" for p in products]) if products else ""

    return f"""You are an experienced B2B content writer for a Catholic rosary beads factory.

{format_business_facts(facts)}

FACTUAL SAFETY RULES:
- Never invent product dimensions, materials, prices, certifications, shipping terms, lead times, stock status, production locations, or sales volume.
- Only state commercial facts included in VERIFIED BUSINESS FACTS.
- When a specification is unknown, say that it varies by item and ask the buyer to confirm it with us.

=== 花撸AI味根除指令（必须严格执行，违反任何一条即为废稿） ===

【禁止的 AI 高频固定句式 — 出现即废稿】
- "in today's market" / "in today's competitive market" / "in the modern market"
- "it's worth mentioning" / "it is worth noting" / "it's important to note"
- "key advantage" / "stands out as" / "game-changer" / "must-have"
- "ideal choice" / "perfect choice" / "excellent choice" / "go-to choice"
- "elevate your" / "elevating your" / "enhance your" / "enhancing your"
- "in the world of" / "in the realm of" / "in the landscape of"
- "comprehensive guide" / "ultimate guide" / "complete guide"
- "transform your" / "make a statement"
- "timeless addition" / "timeless piece"
- "whether you're X or Y" / "whether you are X or Y"
- "not only X but also Y" (not only...but also 整个句式禁用)
- "looking to" + verb (如 "looking to elevate", "looking to enhance")
- "In conclusion" / "To sum up" / "In summary" / "All in all" / "Ultimately"
- "首先/其次/最后" 等模板过渡词

【句式打散规则 — 必须遵守】
- 长短句穿插：有的句子5-8词，有的15-20词，不要每句都12-15词
- 拆分长复合句：一个超过25词的句子，拆成2个短句
- 偶尔用口语化补充，比如：
  "Many catholic believers pick this handmade rosary for baptism gifts."
  "We've been getting a lot of orders from parish gift shops lately."
  "Honestly, the 8mm size outsells everything else by a mile."
- 允许不完整句、反问句、感叹句，打破 AI 文本熵特征
- 段落长度随机：有的2-3句，有的只有1句

【排比句禁令】
- 禁止连续3个以上结构相同的句子
- 禁止每段字数高度一致

【写作人设】
- 用「我们」而不是「该厂」「该工厂」
- 写作风格参考真实工厂老板/销售写的博客：直接、带点个人观点、偶尔跑题
- 可以适度使用反问句、感叹句

=== 产品信息安全要求 ===

只在文章主题相关时，自然使用上方 VERIFIED BUSINESS FACTS。不要为了凑数量加入无关事实，也不要扩写出未经验证的新参数。

=== IMPORTANT CONSTRAINT ===
This is a CATHOLIC/CHRISTIAN religious goods website.
- ONLY write about Catholic and Christian religious items.
- NEVER write about Islamic prayer beads (tasbih, misbaha), Buddhist mala, Hindu jewelry, or any non-Catholic/non-Christian religious topics.

Write a 900-1200 word English blog post targeting: {keyword}

Requirements:
- B2B English, targeting wholesale buyers, importers, church procurement
- Use Markdown: ## for H2, ### for H3
- Do NOT follow a fixed structure — let the content flow naturally
- Vary paragraph length wildly: some 1-sentence paragraphs, some long ones
- Include 3-5 headings total (not always the same number)
- Naturally mention the Alibaba store ({store}) and 2-3 product links in the body:
{product_list}
- End with a conclusion, but keep it natural (no "In conclusion" or similar AI clichés)
- Do NOT include a title (H1) — we add it separately
- Do NOT include meta description or JSON-LD (we add separately)
- Tone: like a real factory owner writing — direct, personal, occasionally imperfect English is OK

Output ONLY the article in Markdown format, no preamble.
"""

# ============================================
# Parse Title
# ============================================
def extract_title(text):
    for line in text.split('\n'):
        line = line.strip()
        if line.startswith('# '):
            title = line.lstrip('# ').strip()
            return title[:80]
        if line and not line.startswith('#') and not line.startswith('---'):
            title = re.sub(r'[*_`#]', '', line)
            return title.strip()[:80]
    return "Untitled"

def slugify(text):
    slug = text.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s-]+', '-', slug)
    return slug[:60].strip('-')

def validate_title(text):
    title = extract_title(text)
    title = re.sub(r"[\x00-\x1f\x7f]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    if not title or title == "Untitled" or not slugify(title):
        raise ValueError("AI returned an unusable title")
    return title[:80]

def validate_commercial_claims(text, facts):
    allowed_moq = {int(facts["stock_moq"]), int(facts["oem_moq"])}
    moq_patterns = (
        r"(?i)(?:MOQ|minimum order(?: quantity)?)[^.\n]{0,100}?(\d[\d,]*)\s*(?:pieces|pcs|units|packs|sets)",
        r"(?i)(\d[\d,]*)\s*(?:pieces|pcs|units|packs|sets)[^.\n]{0,40}?(?:MOQ|minimum)",
    )
    for pattern in moq_patterns:
        for value in re.findall(pattern, text):
            number = int(value.replace(",", ""))
            if number not in allowed_moq:
                raise ValueError(f"Unverified MOQ detected: {number}")

    unsupported_patterns = {
        "price": r"(?i)(?:US?\$|USD\s*)\d",
        "lead time": r"(?i)lead\s*time[^.\n]{0,60}\d",
        "delivery promise": r"(?i)(?:ships?|deliver(?:y|ed)?)[^.\n]{0,50}\b\d+\s*(?:business\s*)?(?:days?|weeks?)",
        "dangerous HTML": r"(?is)<\s*/?\s*(?:script|iframe|object|embed|form|svg|math)\b",
    }
    for label, pattern in unsupported_patterns.items():
        if re.search(pattern, text):
            raise ValueError(f"Unverified or unsafe {label} detected")

def validate_article(article_md, facts):
    article_md = article_md.strip()
    validate_commercial_claims(article_md, facts)
    word_count = len(re.findall(r"\b[A-Za-z][A-Za-z'-]*\b", article_md))
    if not 850 <= word_count <= 1400:
        raise ValueError(f"Article word count {word_count} is outside 850-1400")
    if article_md.startswith("---"):
        raise ValueError("Article unexpectedly contains front matter")
    if article_md.startswith("```"):
        raise ValueError("Article is wrapped in a Markdown code fence")
    if re.search(r"(?m)^#\s+", article_md):
        raise ValueError("Article unexpectedly contains an H1 title")
    heading_count = len(re.findall(r"(?m)^##{2,3}\s+", article_md))
    if not 3 <= heading_count <= 7:
        raise ValueError(f"Article heading count {heading_count} is outside 3-7")
    return article_md

def parse_and_validate_faq(raw, facts):
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
    validate_commercial_claims(normalized, facts)
    # Prevent a JSON string from closing the surrounding script element.
    return normalized.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

# ============================================
# Build Markdown File Content
# ============================================
def build_markdown(title, keyword, article_md, alibaba, featured_image, faq_json):
    # Use Beijing time (UTC+8) consistently
    tz_bj = timezone(timedelta(hours=8))
    now = datetime.now(tz_bj)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H%M%S")
    slug = slugify(title)
    filepath = f"content/posts/{date_str}-{slug}.md"

    # If file already exists, append time suffix to avoid collision
    if os.path.exists(filepath):
        filepath = f"content/posts/{date_str}-{time_str}-{slug}.md"

    store = alibaba["store"]
    products = alibaba["products"]
    random_links = random.sample(products, min(2, len(products))) if products else []

    iso_date = now.strftime("%Y-%m-%dT%H:%M:%S+08:00")

    # Escape double quotes in title for safe YAML
    safe_title = json.dumps(title, ensure_ascii=False)
    safe_keyword = json.dumps(keyword, ensure_ascii=False)
    # Build front matter
    front_matter_lines = [
        '---',
        f'title: {safe_title}',
        f'date: {iso_date}',
        'draft: false',
        f'keyword: {safe_keyword}',
        'tags: ["wholesale", "catholic", "rosary", "B2B"]',
        'categories: ["Rosary Beads"]',
    ]
    if featured_image:
        front_matter_lines.append(f'featureimage: {json.dumps(featured_image)}')
        front_matter_lines.append(f'thumbnail: {json.dumps(featured_image)}')
    # Store FAQ JSON in front matter (YAML multiline string)
    if faq_json and faq_json.strip():
        front_matter_lines.append('faqVerified: true')
        front_matter_lines.append('faqJson: |')
        for line in faq_json.strip().split('\n'):
            front_matter_lines.append('  ' + line)
    front_matter_lines.append('---')
    front_matter = '\n'.join(front_matter_lines)

    # CTA block in Markdown
    cta = "## Shop Wholesale Rosary Beads\n\n"
    cta += f"Looking for wholesale catholic rosary beads? Visit our **[Alibaba Store]({store})** for factory-direct pricing.\n\n"
    if random_links:
        cta += "### Featured Products\n\n"
        for link in random_links:
            cta += f"- [View Product on Alibaba]({link})\n"

    content = f"""{front_matter}

{article_md}

---

{cta}
"""

    return filepath, content

# ============================================
# Main Flow
# ============================================
def main():
    config = load_config()
    keyword = pick_keyword(config)
    facts = get_business_facts(config)

    api_key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("AI_MODEL") or "deepseek-chat"
    api_url = os.environ.get("AI_API_URL") or "https://api.deepseek.com/v1"
    pexels_api_key = os.environ.get("PEXELS_API_KEY", "")

    if not api_key:
        print("ERROR: OPENAI_API_KEY environment variable not set")
        sys.exit(1)

    # 1. Generate title
    print("Generating title...")
    title_raw = call_api(build_title_prompt(keyword), api_key, model, api_url)
    title = validate_title(title_raw)
    print(f"Title: {title}")

    # 2. Fetch featured image (Pexels API → local images/ fallback)
    print("Fetching featured image...")
    featured_image = get_featured_image(keyword, pexels_api_key)
    if featured_image:
        print(f"Featured image: {featured_image}")
    else:
        print("No featured image for this post")

    # 3. Generate article (Markdown format for TOC compatibility)
    print("Generating article...")
    alibaba = get_alibaba(config)
    article_md = call_api(build_article_prompt(keyword, alibaba, facts), api_key, model, api_url, temperature=0.75)
    article_md = validate_article(article_md, facts)

    # 3b. Generate FAQ dynamically
    print("Generating FAQ...")
    try:
        faq_raw = call_api(
            build_faq_prompt(keyword, title, article_md, facts),
            api_key,
            model,
            api_url,
            temperature=0.3,
        )
        faq_json = parse_and_validate_faq(faq_raw, facts)
        print("FAQ generated and validated successfully")
    except Exception as e:
        print(f"Warning: FAQ generation failed: {e}")
        faq_json = ""

    # 4. Save file
    os.makedirs("content/posts", exist_ok=True)
    filepath, content = build_markdown(title, keyword, article_md, alibaba, featured_image, faq_json)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"Saved: {filepath}")
    print("Done!")

if __name__ == "__main__":
    main()
