import importlib.util
import json
import unittest
from unittest.mock import patch
from pathlib import Path

import yaml


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate-post.py"
SPEC = importlib.util.spec_from_file_location("generate_post", SCRIPT)
generate_post = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_post)

FACTS = {
    "stock_moq": 12,
    "oem_moq": 1200,
    "approved_claims": ["Verified claim."],
}


class GeneratorSafetyTests(unittest.TestCase):
    def test_rejects_unverified_moq(self):
        with self.assertRaisesRegex(ValueError, "Unverified MOQ"):
            generate_post.validate_commercial_claims("Our MOQ is 500 pieces.", FACTS)

    def test_accepts_verified_moq(self):
        generate_post.validate_commercial_claims(
            "The stock MOQ is 12 pieces; OEM minimum order is 1200 pieces.", FACTS
        )

    def test_rejects_script_html(self):
        with self.assertRaisesRegex(ValueError, "dangerous HTML"):
            generate_post.validate_commercial_claims("<script>alert(1)</script>", FACTS)

    def test_rejects_unverified_lead_time(self):
        with self.assertRaisesRegex(ValueError, "lead time"):
            generate_post.validate_commercial_claims("Lead time is 3 weeks.", FACTS)

    def test_rejects_fake_sales_experience(self):
        with self.assertRaisesRegex(ValueError, "Unverified first-person"):
            generate_post.validate_editorial_quality(
                "We've been getting a lot of orders from parish shops lately."
            )

    def test_rejects_canned_editorial_phrase(self):
        with self.assertRaisesRegex(ValueError, "Canned editorial phrase"):
            generate_post.validate_editorial_quality(
                "This product stands out as the perfect choice."
            )

    def test_title_uses_first_clean_line(self):
        self.assertEqual(generate_post.validate_title("# Safe title\nextra"), "Safe title")

    def test_h2_and_h3_headings_are_counted(self):
        words = " ".join("detail" for _ in range(850))
        article = f"## First\n\n{words}\n\n### Second\n\nText\n\n## Third\n\nText"
        self.assertEqual(generate_post.validate_article(article, FACTS), article)

    def test_faq_rejects_script_breakout(self):
        raw = json.dumps({
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": [
                {
                    "@type": "Question",
                    "name": "Can I order stock?",
                    "acceptedAnswer": {"@type": "Answer", "text": "Stock MOQ is 12 pieces."},
                },
                {
                    "@type": "Question",
                    "name": "Can I customize?",
                    "acceptedAnswer": {"@type": "Answer", "text": "OEM MOQ is 1200 pieces. </script>"},
                },
            ],
        })
        with self.assertRaisesRegex(ValueError, "dangerous HTML"):
            generate_post.parse_and_validate_faq(raw, FACTS)

    def test_front_matter_quotes_are_yaml_safe(self):
        _, content = generate_post.build_markdown(
            'A "quoted" title with \\ slash',
            'keyword "quoted"',
            "## One\n\nText\n\n## Two\n\nText\n\n## Three\n\nText",
            {"store": "https://example.com", "products": []},
            None,
            "",
        )
        front = content.split("---", 2)[1]
        parsed = yaml.safe_load(front)
        self.assertEqual(parsed["title"], 'A "quoted" title with \\ slash')

    def test_invalid_draft_is_rewritten(self):
        store = "https://store.example.com/"
        product = "https://store.example.com/product"
        alibaba = {"store": store, "products": [product]}
        useful_words = " ".join("detail" for _ in range(850))
        valid_draft = (
            f"## Buyer requirements\n\n{useful_words}\n\n"
            f"## Product checks\n\nReview the approved [store]({store}) and "
            f"[product]({product}).\n\n"
            "## Ordering decision\n\nConfirm the selected item's current specification before ordering."
        )
        with patch.object(generate_post, "call_api", side_effect=["No headings here", valid_draft]) as mocked:
            result = generate_post.generate_validated_article(
                "test keyword", alibaba, FACTS, "key", "model", "https://api.example.com", draft_attempts=2
            )
        self.assertEqual(result, valid_draft)
        self.assertEqual(mocked.call_count, 2)


if __name__ == "__main__":
    unittest.main()
