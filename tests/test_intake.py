"""Tests for brief-intake dispatch (auto-detect .docx vs .md by extension)."""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
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


class ListBriefsErrorTest(unittest.TestCase):
    """The list-briefs CLI must surface a corrupt .docx as a clean error line,
    not an uncaught DocxError traceback (run.py caught only ParseError)."""

    def test_corrupt_docx_exits_cleanly(self) -> None:
        from scripts import run

        tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        tmp.write(b"this is not a zip")  # unreadable -> docx_reader raises DocxError
        tmp.close()
        self.addCleanup(os.unlink, tmp.name)

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = run.main(["list-briefs", "--doc", tmp.name])

        self.assertEqual(rc, 1)
        self.assertIn("ERROR", err.getvalue())
        self.assertIn("readable .docx", err.getvalue())


if __name__ == "__main__":
    unittest.main()
