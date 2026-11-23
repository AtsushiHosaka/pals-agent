"""The verifier189 qualification must survive later event-only follow-up commits."""

from __future__ import annotations

import ast
import contextlib
import io
import os
import re
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[2]
_ANCHOR = "189b44378e6e63e5ab7c92d9c5b7d6507acd80f0"


class AgentRegressionSourceScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        workflow = (_ROOT / ".github/workflows/application-regression.yml").read_text()
        cls.code = textwrap.dedent(
            workflow.split("python - <<'PY_SCOPE'\n", 1)[1].split("\n          PY_SCOPE", 1)[0]
        )
        ast.parse(cls.code)
        core = re.search(r"^      CORE_TEST_FILES: >-\n((?:        \S+\n)+)", workflow, re.M)
        assert core is not None
        cls.directory = tempfile.TemporaryDirectory(prefix="pals-source-scope-")
        cls.addClassCleanup(cls.directory.cleanup)
        cls.git_dir = Path(cls.directory.name) / "fixture.git"
        cls.environment = {
            key: value for key, value in os.environ.items()
            if key not in {"GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE", "GIT_COMMON_DIR"}
        }
        subprocess.run(
            ["git", "clone", "--quiet", "--bare", "--shared", str(_ROOT), str(cls.git_dir)],
            env=cls.environment, capture_output=True, check=True, timeout=15,
        )
        cls.environment.update(
            GIT_DIR=str(cls.git_dir),
            GIT_INDEX_FILE=str(Path(cls.directory.name) / "fixture.index"),
            GIT_AUTHOR_NAME="Source qualification fixture",
            GIT_AUTHOR_EMAIL="fixture@example.invalid",
            GIT_COMMITTER_NAME="Source qualification fixture",
            GIT_COMMITTER_EMAIL="fixture@example.invalid",
            CORE_TEST_FILES=" ".join(core.group(1).split()),
        )
        cls.git("read-tree", _ANCHOR)
        cls.update_blob("pals_agent/worker.py", "\n# Private unqualified-worker fixture.\n")
        cls.worker = cls.commit("fixture: unqualified worker change", _ANCHOR)
        cls.update_blob("README.md", "\nPrivate README-only follow-up fixture.\n")
        cls.followup = cls.commit("fixture: README-only follow-up", cls.worker)
        cls.git("read-tree", _ANCHOR)
        cls.nonancestor = cls.commit("fixture: identical source without anchor ancestry")

    @classmethod
    def git(cls, *arguments: str, input: bytes | None = None) -> str:
        return subprocess.check_output(
            ["git", *arguments], env=cls.environment, input=input, timeout=15,
        ).decode().strip()

    @classmethod
    def update_blob(cls, path: str, addition: str) -> None:
        mode = cls.git("ls-tree", _ANCHOR, "--", path).split()[0]
        raw = subprocess.check_output(
            ["git", "show", _ANCHOR + ":" + path], env=cls.environment, timeout=15,
        )
        blob = cls.git("hash-object", "-w", "--stdin", input=raw + addition.encode())
        cls.git("update-index", "--add", "--cacheinfo", mode, blob, path)

    @classmethod
    def commit(cls, message: str, parent: str | None = None) -> str:
        tree = cls.git("write-tree")
        return cls.git("commit-tree", tree, *(["-p", parent] if parent else []), "-m", message)

    def rejected(self, head: str, before: str, reason: str) -> None:
        self.git("update-ref", "refs/heads/qualification-probe", head)
        self.git("symbolic-ref", "HEAD", "refs/heads/qualification-probe")
        # Model a main push or PR whose event baseline already contains the bad worker.
        self.git("update-ref", "refs/remotes/origin/main", head)
        environment = {**self.environment, "PUSH_BEFORE": before, "REVIEW_BASE": before}
        with (
            patch.dict(os.environ, environment, clear=True),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(AssertionError, reason),
        ):
            exec(compile(self.code, "workflow-source-scope", "exec"), {})

    def test_unqualified_worker_change_is_refused(self) -> None:
        self.rejected(self.worker, _ANCHOR, r"pals_agent/worker[.]py")

    def test_readme_followup_cannot_hide_the_unqualified_worker(self) -> None:
        self.rejected(self.followup, self.worker, r"pals_agent/worker[.]py")

    def test_identical_tree_without_anchor_ancestry_is_refused(self) -> None:
        self.rejected(self.nonancestor, _ANCHOR, "anchor must be an ancestor")
