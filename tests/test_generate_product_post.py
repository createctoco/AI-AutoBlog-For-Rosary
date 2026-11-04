import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate-product-post.py"
SPEC = importlib.util.spec_from_file_location("generate_product_post", SCRIPT)
generate_product_post = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_product_post)


class ProductPostFilenameTests(unittest.TestCase):
    def test_new_product_post_filename_has_no_date_prefix(self):
        filepath, _ = generate_product_post.build_markdown(
            "Wholesale Wooden Rosary Cross Pendant",
            {"url": "https://example.com/product", "title": "Example product"},
            "## Overview",
            "",
        )
        self.assertEqual(filepath, "content/posts/wholesale-wooden-rosary-cross-pendant.md")


if __name__ == "__main__":
    unittest.main()
