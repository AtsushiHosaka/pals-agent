"""The import-graph test selector (pals#487): what it selects, and when it says ALL."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "select_impacted_tests.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("select_impacted_tests", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


selector = _load()


def write(root: Path, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    write(
        tmp_path,
        {
            "pals_agent/__init__.py": "",
            "pals_agent/base.py": "X = 1\n",
            "pals_agent/mid.py": "from pals_agent.base import X\n",
            "pals_agent/top.py": "from pals_agent import mid\n",
            "pals_agent/rel.py": "from .base import X\n",
            "pals_agent/dyn.py": (
                "import importlib\nm = importlib.import_module('pals_agent.base')\n"
            ),
            "pals_agent/lonely.py": "Y = 2\n",
            "scripts/tool.py": "from pals_agent.lonely import Y\n",
            "tests/__init__.py": "",
            "tests/unit/__init__.py": "",
            "tests/unit/test_base.py": "import pals_agent.base\n",
            "tests/unit/test_top.py": "from pals_agent.top import mid\n",
            "tests/unit/test_rel.py": "import pals_agent.rel\n",
            "tests/unit/test_dyn.py": "import pals_agent.dyn\n",
            "tests/unit/test_lonely.py": "import pals_agent.lonely\n",
            "tests/unit/test_tool.py": "import importlib.util\nfrom scripts import tool\n",
            "tests/unit/test_none.py": "def test(): pass\n",
            "tests/unit/helper.py": "from pals_agent.lonely import Y\n",
            "tests/unit/test_helper.py": "from tests.unit import helper\n",
        },
    )
    return tmp_path


def test_a_change_selects_direct_and_transitive_importers(repo: Path) -> None:
    assert selector.select(["pals_agent/base.py"], repo) == [
        "tests/unit/test_base.py",
        "tests/unit/test_dyn.py",
        "tests/unit/test_rel.py",
        "tests/unit/test_top.py",
    ]


def test_a_changed_test_selects_itself_only(repo: Path) -> None:
    assert selector.select(["tests/unit/test_none.py"], repo) == ["tests/unit/test_none.py"]


def test_a_changed_test_helper_selects_the_tests_that_import_it(repo: Path) -> None:
    assert selector.select(["tests/unit/helper.py"], repo) == ["tests/unit/test_helper.py"]


def test_a_script_is_part_of_the_graph(repo: Path) -> None:
    assert selector.select(["pals_agent/lonely.py"], repo) == [
        "tests/unit/test_helper.py",
        "tests/unit/test_lonely.py",
        "tests/unit/test_tool.py",
    ]


def test_a_string_naming_a_project_module_counts_as_an_import(repo: Path) -> None:
    assert "tests/unit/test_dyn.py" in selector.select(["pals_agent/base.py"], repo)


def test_documentation_selects_nothing(repo: Path) -> None:
    assert selector.select(["docs/a.md", "README.md", "history/x/y.txt", "LICENSE"], repo) == []


@pytest.mark.parametrize(
    "path",
    [
        ".github/workflows/application-regression.yml",
        "pyproject.toml",
        "uv.lock",
        "tests/conftest.py",
        "tests/unit/conftest.py",
        "tests/fixtures/a.lean",
        "tests/qualification/agent_regression_manifest.json",
        "scripts/agent_regression_gate.py",
        "lean-workspace/lakefile.toml",
        "Dockerfile.local",
        "docker/entry.sh",
        "pals_agent/data.json",
        "testdata/case.json",
    ],
)
def test_changes_the_graph_cannot_see_select_all(repo: Path, path: str) -> None:
    assert selector.select(["pals_agent/base.py", path], repo) == ["ALL"]


def test_a_new_python_file_outside_the_graph_selects_all(repo: Path) -> None:
    write(repo, {"other/x.py": ""})
    assert selector.select(["other/x.py"], repo) == ["ALL"]


def test_a_deleted_python_file_alone_selects_nothing(repo: Path) -> None:
    assert selector.select(["pals_agent/gone.py"], repo) == []


def test_main_prints_one_path_per_line(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert selector.main(["--root", str(repo), "pals_agent/mid.py"]) == 0
    assert capsys.readouterr().out.splitlines() == ["tests/unit/test_top.py"]
