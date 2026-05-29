"""Tests for workspace root resolution.

Resolution order (no override flag, no env var):
    1. DOWNWARD search: the nearest blog-upload-workspace/ in a sub-folder of
       $PWD (breadth-first, shallowest wins; skips hidden + heavy dirs)
    2. else create $PWD/blog-upload-workspace in the current directory

Run from the skill root:
    PYTHONPATH=. python3 -B -m unittest tests.test_workspace -v
"""

from __future__ import annotations

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

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _patched(self, cwd: Path):
        return mock.patch.object(workspace.Path, "home", return_value=self.home), \
            mock.patch.object(workspace.Path, "cwd", return_value=cwd)

    def test_creates_at_cwd_when_nothing_found(self) -> None:
        # No workspace below → create in the current directory.
        cwd = self.home / "proj" / "deep"
        cwd.mkdir(parents=True)
        home_p, cwd_p = self._patched(cwd)
        with home_p, cwd_p:
            self.assertEqual(workspace.root(), (cwd / WS).resolve())

    def test_finds_workspace_in_a_subfolder(self) -> None:
        # Launch above; the workspace is nested below — downward search finds it.
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

    def test_skips_hidden_and_heavy_dirs(self) -> None:
        # A workspace buried in node_modules / a hidden dir must NOT be picked up.
        (self.home / "node_modules" / WS).mkdir(parents=True)
        (self.home / ".cache" / WS).mkdir(parents=True)
        home_p, cwd_p = self._patched(self.home)
        with home_p, cwd_p:
            self.assertEqual(workspace.root(), (self.home / WS).resolve())

    def test_env_var_is_ignored(self) -> None:
        cwd = self.home / "x"
        cwd.mkdir()
        home_p, cwd_p = self._patched(cwd)
        with home_p, cwd_p, mock.patch.dict(
            os.environ, {"BLOG_UPLOAD_WORKSPACE": str(self.home / "ELSEWHERE")}
        ):
            self.assertEqual(workspace.root(), (cwd / WS).resolve())


if __name__ == "__main__":
    unittest.main()
