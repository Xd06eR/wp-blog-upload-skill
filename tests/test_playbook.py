"""Tests for the playbook module — frontmatter index + journal.

Isolation mirrors test_workspace: patch workspace.Path.cwd to a temp dir so
playbooks land in <tmp>/blog-upload-workspace/data/playbooks/.

Run from the skill root:
    PYTHONPATH=. python3 -B -m unittest tests.test_playbook -v
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.tools import playbook, workspace


class PlaybookTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self._tmp.name).resolve()
        self._cwd_patch = mock.patch.object(workspace.Path, "cwd", return_value=self.cwd)
        self._cwd_patch.start()

    def tearDown(self) -> None:
        self._cwd_patch.stop()
        self._tmp.cleanup()

    # --- frontmatter parse / serialize -------------------------------------

    def test_frontmatter_roundtrip(self) -> None:
        text = "---\nsummary: A short fact\naliases: brandx, brand-y\n---\n# body\n"
        meta, body = playbook._parse_frontmatter(text)
        self.assertEqual(meta["summary"], "A short fact")
        self.assertEqual(meta["aliases"], ["brandx", "brand-y"])
        self.assertEqual(body, "# body\n")
        # serialize emits summary then aliases, fenced
        out = playbook._serialize_frontmatter(meta)
        self.assertEqual(out, "---\nsummary: A short fact\naliases: brandx, brand-y\n---\n")

    def test_no_frontmatter_is_passthrough(self) -> None:
        text = "# Playbook — x\n\n## 2026-01-01 — hi\n\nbody\n"
        meta, body = playbook._parse_frontmatter(text)
        self.assertEqual(meta, {})
        self.assertEqual(body, text)

    def test_body_horizontal_rule_not_treated_as_frontmatter(self) -> None:
        # A `---` that is NOT at the very top must be left in the body.
        text = "# Playbook\n\nsome prose\n\n---\n\nmore\n"
        meta, body = playbook._parse_frontmatter(text)
        self.assertEqual(meta, {})
        self.assertEqual(body, text)

    # --- build_index hybrid -------------------------------------------------

    def test_index_prefers_curated_summary(self) -> None:
        playbook.append_lesson(
            "alpha", "Newest headline", "lesson body",
            summary="Curated one-liner", aliases=["alphabrand"],
        )
        idx = {r["slug"]: r for r in playbook.build_index()}
        self.assertEqual(idx["alpha"]["summary"], "Curated one-liner")
        self.assertEqual(idx["alpha"]["aliases"], ["alphabrand"])
        self.assertEqual(idx["alpha"]["source"], "summary")

    def test_index_falls_back_to_newest_headline(self) -> None:
        # No summary set -> index uses the latest dated headline (legacy shape).
        playbook.append_lesson("beta", "First lesson", "b1")
        playbook.append_lesson("beta", "Second lesson", "b2")
        rec = next(r for r in playbook.build_index() if r["slug"] == "beta")
        self.assertEqual(rec["summary"], "Second lesson")
        self.assertEqual(rec["source"], "headline")
        self.assertEqual(rec["aliases"], [])

    def test_index_skips_archive_files(self) -> None:
        playbook.append_lesson("gamma", "h", "g")
        # create a stray archive file; it must not appear as its own client
        playbook._slug_path("gamma", archive=True).write_text("# archive\n")
        slugs = [r["slug"] for r in playbook.build_index()]
        self.assertIn("gamma", slugs)
        self.assertNotIn("gamma.archive", slugs)

    # --- set_meta (backfill, no new entry) ---------------------------------

    def test_set_meta_curates_without_adding_entry(self) -> None:
        playbook.append_lesson("delta", "Only lesson", "d1")
        before = playbook.read("delta").count("## ")
        playbook.set_meta("delta", summary="Delta maps here", aliases=["deltabrand"])
        after_text = playbook.read("delta")
        self.assertEqual(after_text.count("## "), before)  # no new dated entry
        self.assertTrue(after_text.startswith("---\nsummary: Delta maps here"))
        self.assertIn("## 2", after_text)  # original entry preserved
        rec = next(r for r in playbook.build_index() if r["slug"] == "delta")
        self.assertEqual(rec["source"], "summary")
        self.assertEqual(rec["aliases"], ["deltabrand"])

    def test_aliases_merge_and_dedupe(self) -> None:
        playbook.set_meta("eps", aliases=["one"])
        playbook.set_meta("eps", aliases=["One", "two"])  # case-insensitive dupe
        meta, _ = playbook._parse_frontmatter(playbook.read("eps"))
        self.assertEqual(meta["aliases"], ["one", "two"])

    # --- interaction with rotation -----------------------------------------

    def test_frontmatter_survives_rotation(self) -> None:
        playbook.set_meta("zeta", summary="sticky fact", aliases=["z"])
        for i in range(playbook.MAX_LIVE_ENTRIES + 2):
            playbook.append_lesson("zeta", f"entry {i}", f"body {i}")
        live = playbook.read("zeta")
        # frontmatter still on top after rotation
        self.assertTrue(live.startswith("---\nsummary: sticky fact"))
        # only MAX_LIVE_ENTRIES entries remain live; rest archived
        self.assertEqual(len(playbook._ENTRY_HEADER.findall(live)), playbook.MAX_LIVE_ENTRIES)
        self.assertTrue(playbook._slug_path("zeta", archive=True).exists())
        # index still resolves the curated summary
        rec = next(r for r in playbook.build_index() if r["slug"] == "zeta")
        self.assertEqual(rec["summary"], "sticky fact")

    def test_append_then_reparse_is_stable(self) -> None:
        # Writing then re-parsing must not accumulate blank lines / drift.
        playbook.append_lesson("eta", "h1", "b1", summary="s", aliases=["a"])
        playbook.append_lesson("eta", "h2", "b2")
        meta, body = playbook._parse_frontmatter(playbook.read("eta"))
        self.assertEqual(meta["summary"], "s")
        self.assertFalse(body.startswith("\n"))  # no leading blank-line buildup


if __name__ == "__main__":
    unittest.main()
