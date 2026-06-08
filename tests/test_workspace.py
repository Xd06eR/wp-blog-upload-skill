"""Tests for workspace root resolution.

Resolution order (no override flag, no env var):
    1. DOWNWARD search: nearest blog-upload-workspace/ in a sub-folder of $PWD
       (breadth-first, shallowest wins; skips hidden + heavy dirs)
    2. UPWARD search: first blog-upload-workspace/ beside an ancestor of $PWD
    3. BESIDE THE SKILL: <skill>/../blog-upload-workspace — used if it exists,
       and the create target otherwise

`_canonical_workspace` (the beside-skill anchor, derived from __file__) is
patched per test so the suite never touches the real workspace.

Run from the skill root:
    PYTHONPATH=. python3 -B -m unittest tests.test_workspace -v
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts.tools import workspace

WS = "blog-upload-workspace"


class WorkspaceResolutionTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.home = Path(self._tmp.name).resolve()
        # Anchor the beside-skill canonical workspace inside the tmp tree so no
        # test can resolve the real one. Not created unless a test creates it.
        self.canonical = self.home / "skillparent" / WS
        self._canon = mock.patch.object(
            workspace, "_canonical_workspace", return_value=self.canonical
        )
        self._canon.start()

    def tearDown(self) -> None:
        self._canon.stop()
        self._tmp.cleanup()

    def _patched(self, cwd: Path):
        return mock.patch.object(workspace.Path, "home", return_value=self.home), \
            mock.patch.object(workspace.Path, "cwd", return_value=cwd)

    # --- create target: beside the skill -----------------------------------

    def test_creates_beside_skill_when_nothing_found(self) -> None:
        cwd = self.home / "proj" / "deep"
        cwd.mkdir(parents=True)
        home_p, cwd_p = self._patched(cwd)
        with home_p, cwd_p:
            self.assertEqual(workspace.root(), self.canonical.resolve())

    def test_skips_hidden_and_heavy_dirs(self) -> None:
        # Workspaces buried in node_modules / a hidden dir are ignored -> fall
        # through to the beside-skill canonical path.
        (self.home / "node_modules" / WS).mkdir(parents=True)
        (self.home / ".cache" / WS).mkdir(parents=True)
        home_p, cwd_p = self._patched(self.home)
        with home_p, cwd_p:
            self.assertEqual(workspace.root(), self.canonical.resolve())

    def test_env_var_is_ignored(self) -> None:
        cwd = self.home / "x"
        cwd.mkdir()
        home_p, cwd_p = self._patched(cwd)
        with home_p, cwd_p, mock.patch.dict(
            os.environ, {"BLOG_UPLOAD_WORKSPACE": str(self.home / "ELSEWHERE")}
        ):
            self.assertEqual(workspace.root(), self.canonical.resolve())

    def test_ensure_creates_beside_skill(self) -> None:
        cwd = self.home / "anywhere"
        cwd.mkdir()
        home_p, cwd_p = self._patched(cwd)
        with home_p, cwd_p:
            workspace.ensure()
        self.assertTrue(self.canonical.exists())
        self.assertTrue((self.canonical / "data" / "playbooks").exists())
        self.assertFalse((cwd / WS).exists())  # NOT created at cwd

    # --- downward search ----------------------------------------------------

    def test_finds_workspace_in_a_subfolder(self) -> None:
        ws = self.home / "proj" / "client-work" / WS
        ws.mkdir(parents=True)
        home_p, cwd_p = self._patched(self.home)
        with home_p, cwd_p:
            self.assertEqual(workspace.root(), ws.resolve())

    def test_shallowest_subfolder_wins(self) -> None:
        deep = self.home / "a" / "b" / WS
        deep.mkdir(parents=True)
        near = self.home / "near" / WS
        near.mkdir(parents=True)
        home_p, cwd_p = self._patched(self.home)
        with home_p, cwd_p:
            self.assertEqual(workspace.root(), near.resolve())

    # --- upward search (the skill/workspace siblings layout) ---------------

    def test_finds_workspace_in_parent_sibling(self) -> None:
        # blog_automation/{blog-upload (cwd), blog-upload-workspace}
        parent = self.home / "blog_automation"
        real_ws = parent / WS
        real_ws.mkdir(parents=True)
        skill = parent / "blog-upload"
        skill.mkdir()
        home_p, cwd_p = self._patched(skill)
        with home_p, cwd_p:
            # Found via upward search, NOT the (different) canonical anchor.
            self.assertEqual(workspace.root(), real_ws.resolve())

    def test_downward_beats_upward(self) -> None:
        parent = self.home / "p"
        (parent / WS).mkdir(parents=True)
        cwd = parent / "here"
        below = cwd / "sub" / WS
        below.mkdir(parents=True)
        home_p, cwd_p = self._patched(cwd)
        with home_p, cwd_p:
            self.assertEqual(workspace.root(), below.resolve())

    # --- find(): resolve-only, never creates -------------------------------

    def test_find_returns_none_when_absent(self) -> None:
        cwd = self.home / "nowhere"
        cwd.mkdir()
        home_p, cwd_p = self._patched(cwd)
        with home_p, cwd_p:
            self.assertIsNone(workspace.find())

    def test_find_resolves_parent_sibling(self) -> None:
        parent = self.home / "ba"
        real_ws = parent / WS
        real_ws.mkdir(parents=True)
        skill = parent / "skill"
        skill.mkdir()
        home_p, cwd_p = self._patched(skill)
        with home_p, cwd_p:
            self.assertEqual(workspace.find(), real_ws.resolve())

    def test_find_resolves_canonical_when_it_exists(self) -> None:
        self.canonical.mkdir(parents=True)
        cwd = self.home / "elsewhere"
        cwd.mkdir()
        home_p, cwd_p = self._patched(cwd)
        with home_p, cwd_p:
            self.assertEqual(workspace.find(), self.canonical)

    def test_read_command_does_not_create_workspace(self) -> None:
        # (b): a read command (playbook-index) run where no workspace exists
        # must print empty and create NOTHING.
        from scripts import run
        cwd = self.home / "isolated"
        cwd.mkdir()
        with mock.patch.object(workspace.Path, "cwd", return_value=cwd):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = run.main(["playbook-index"])
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue().strip(), "[]")
        self.assertFalse(self.canonical.exists())
        self.assertFalse((cwd / WS).exists())


if __name__ == "__main__":
    unittest.main()
