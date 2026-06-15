"""Tests for brief-intake dispatch (auto-detect .docx vs .md by extension)."""

from __future__ import annotations

import unittest

from scripts.tools import intake, parse_docx, parse_md


class ParserForTest(unittest.TestCase):
    def test_docx_routes_to_parse_docx(self) -> None:
        self.assertIs(intake.parser_for("brief.docx"), parse_docx)
        self.assertIs(intake.parser_for("/abs/path/Brief.DOCX"), parse_docx)  # case-insensitive

    def test_md_routes_to_parse_md(self) -> None:
        self.assertIs(intake.parser_for("brief.md"), parse_md)

    def test_unknown_extension_defaults_to_md(self) -> None:
        self.assertIs(intake.parser_for("brief.txt"), parse_md)
        self.assertIs(intake.parser_for("brief"), parse_md)

    def test_both_parsers_expose_same_surface(self) -> None:
        for mod in (parse_docx, parse_md):
            self.assertTrue(hasattr(mod, "parse"))
            self.assertTrue(hasattr(mod, "list_briefs"))


if __name__ == "__main__":
    unittest.main()
