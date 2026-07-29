#!/usr/bin/env python3
"""Fail the build when generated content is structurally unsafe or inconsistent."""

import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml


ROOT = Path(__file__).resolve().parents[1]
POSTS = ROOT / "content" / "posts"
DANGEROUS_HTML = re.compile(
    r"(?is)<\s*/?\s*(?:script|iframe|object|embed|form|svg|math)\b"
)
LEGACY_FAQ = re.compile(
    r'(?is)<script\s+type=["\']application/ld\+json["\']\s*>(.*?)</script>'
)


def split_front_matter(raw, path):
    match = re.match(r"\A---\s*\r?\n(.*?)\r?\n---\s*\r?\n(.*)\Z", raw, re.DOTALL)
    if not match:
        raise ValueError(f"{path}: missing or malformed YAML front matter")
    front = yaml.safe_load(match.group(1))
    if not isinstance(front, dict):
        raise ValueError(f"{path}: front matter is not a mapping")
    return front, match.group(2)


def validate_faq(raw_json, path):
    if "<" in raw_json or ">" in raw_json:
        raise ValueError(f"{path}: FAQ JSON contains an unsafe literal angle bracket")
    faq = json.loads(raw_json)
    if faq.get("@context") != "https://schema.org" or faq.get("@type") != "FAQPage":
        raise ValueError(f"{path}: invalid FAQ schema type")
    entities = faq.get("mainEntity")
    if not isinstance(entities, list) or not 2 <= len(entities) <= 3:
        raise ValueError(f"{path}: verified FAQ must contain 2-3 questions")
    for item in entities:
        answer = item.get("acceptedAnswer", {})
        if item.get("@type") != "Question" or answer.get("@type") != "Answer":
            raise ValueError(f"{path}: invalid FAQ question/answer")
        if not str(item.get("name", "")).strip() or not str(answer.get("text", "")).strip():
            raise ValueError(f"{path}: empty FAQ question/answer")


def remove_valid_legacy_faq(body, path):
    def replace(match):
        faq = json.loads(match.group(1))
        if faq.get("@type") != "FAQPage":
            raise ValueError(f"{path}: unexpected legacy JSON-LD script")
        return ""

    return LEGACY_FAQ.sub(replace, body)


def main():
    errors = []
    titles = {}
    keywords = {}
    product_urls = {}
    count = 0

    try:
        config = yaml.safe_load((ROOT / "blog-config.yaml").read_text(encoding="utf-8"))
        configured_keywords = config.get("keywords", [])
        folded_keywords = [str(value).strip().casefold() for value in configured_keywords]
        if not folded_keywords or len(folded_keywords) != len(set(folded_keywords)):
            raise ValueError("blog-config.yaml: keywords must be non-empty and unique")
        facts = config.get("business_facts", {})
        for field in ("stock_moq", "oem_moq", "approved_claims"):
            if not facts.get(field):
                raise ValueError(f"blog-config.yaml: missing business_facts.{field}")
        for field in ("alibaba_store_url",):
            parsed = urlparse(str(config.get(field, "")))
            if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith("alibaba.com"):
                raise ValueError(f"blog-config.yaml: {field} must be an HTTPS Alibaba URL")
        for product_url in config.get("alibaba_products", []):
            parsed = urlparse(str(product_url))
            if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith("alibaba.com"):
                raise ValueError("blog-config.yaml: every product URL must be an HTTPS Alibaba URL")
    except Exception as exc:
        errors.append(str(exc))

    for path in sorted(POSTS.glob("*.md")):
        count += 1
        try:
            raw = path.read_text(encoding="utf-8")
            front, body = split_front_matter(raw, path.name)
            for field in ("title", "date", "keyword", "draft"):
                if field not in front:
                    raise ValueError(f"{path.name}: missing required field {field}")
            if front["draft"] is not False:
                raise ValueError(f"{path.name}: generated post must not be a draft")

            title = str(front["title"]).strip().casefold()
            keyword = str(front["keyword"]).strip().casefold()
            if not title or not keyword:
                raise ValueError(f"{path.name}: title and keyword must be non-empty")
            if title in titles:
                raise ValueError(f"{path.name}: duplicate title also used by {titles[title]}")
            if keyword in keywords:
                raise ValueError(f"{path.name}: duplicate keyword also used by {keywords[keyword]}")
            titles[title] = path.name
            keywords[keyword] = path.name

            # Product recommendation posts carry a product_url field
            product_url = front.get("product_url")
            if product_url:
                product_url = str(product_url).strip()
                if not product_url.startswith("https://"):
                    raise ValueError(f"{path.name}: product_url must use HTTPS")
                if product_url in product_urls:
                    raise ValueError(f"{path.name}: duplicate product_url also used by {product_urls[product_url]}")
                product_urls[product_url] = path.name

            image = front.get("featureimage")
            if image and not str(image).startswith("https://"):
                raise ValueError(f"{path.name}: feature image must use HTTPS")

            if front.get("faqVerified"):
                faq_json = front.get("faqJson")
                if not isinstance(faq_json, str):
                    raise ValueError(f"{path.name}: verified FAQ is missing faqJson")
                validate_faq(faq_json, path.name)

            sanitized_body = remove_valid_legacy_faq(body, path.name)
            if DANGEROUS_HTML.search(sanitized_body):
                raise ValueError(f"{path.name}: dangerous raw HTML element detected")
        except Exception as exc:
            errors.append(str(exc))

    if errors:
        print("Content validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"Validated {count} posts: front matter, uniqueness, FAQ JSON, HTTPS images, and HTML safety OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
