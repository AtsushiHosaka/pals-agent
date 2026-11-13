from pathlib import Path

from tools.mathlib_index.extract_stacks_tags import extract


def _tags(tmp_path: Path, source: str) -> dict[str, list[dict[str, object]]]:
    root = tmp_path / "Mathlib"
    root.mkdir()
    (root / "A.lean").write_text(source, encoding="utf-8")
    return extract(root)


def _names(tags: dict[str, list[dict[str, object]]], tag: str) -> list[object]:
    return [entry["name"] for entry in tags.get(tag, [])]


def test_names_are_qualified_by_namespaces_and_sections(tmp_path: Path) -> None:
    source = (
        "namespace Foo\nnoncomputable section Bar\n"
        "@[stacks 0AAA]\ntheorem t1 : True := trivial\n"
        "end Bar\n@[stacks 0BBB]\nlemma t2 : True := trivial\nend Foo\n"
        "@[stacks 0CCC]\ntheorem _root_.Outside.t3 : True := trivial\n"
    )
    tags = _tags(tmp_path, source)
    assert _names(tags, "0AAA") == ["Foo.t1"]
    assert _names(tags, "0BBB") == ["Foo.t2"]
    assert _names(tags, "0CCC") == ["Outside.t3"]


def test_public_irreducible_def_and_attribute_lists(tmp_path: Path) -> None:
    source = (
        "@[stacks 0DDD] public lemma a1 : True := trivial\n"
        "@[stacks 0EEE \"first part\"] protected irreducible_def rank : Nat := 0\n"
        "@[simp, stacks 0FFF] theorem a2 : True := trivial\n"
        "@[stacks 0GGG, stacks 0HHH]\ntheorem a3 : True := trivial\n"
    )
    tags = _tags(tmp_path, source)
    assert _names(tags, "0DDD") == ["a1"]
    assert _names(tags, "0EEE") == ["rank"]
    assert _names(tags, "0FFF") == ["a2"]
    assert _names(tags, "0GGG") == ["a3"] and _names(tags, "0HHH") == ["a3"]


def test_universe_suffix_and_instance_priority(tmp_path: Path) -> None:
    source = (
        "@[stacks 0NNN]\ntheorem w.{u} : True := trivial\n"
        "@[stacks 0OOO]\ninstance (priority := 100) foo : Bar := baz\n"
        "@[stacks 0PPP]\ninstance : Bar := baz\n"
    )
    tags = _tags(tmp_path, source)
    assert _names(tags, "0NNN") == ["w"]
    assert _names(tags, "0OOO") == ["foo"]
    assert _names(tags, "0PPP") == [None]


def test_attribute_does_not_leak_onto_a_later_tactic_line(tmp_path: Path) -> None:
    source = "@[stacks 0III] public instance : Foo := bar\n" + "\n" * 12 + "  classical\n"
    tags = _tags(tmp_path, source)
    assert _names(tags, "0III") == [None]


def test_private_names_comments_and_unmatched_attributes_are_dropped(tmp_path: Path) -> None:
    source = (
        "-- @[stacks 0JJJ]\n/- @[stacks 0KKK] theorem x : True := trivial -/\n"
        "@[stacks 0LLL] private lemma hidden : True := trivial\n"
        "@[stacks 0MMM]\n" + "\n" * 12 + "theorem far : True := trivial\n"
    )
    tags = _tags(tmp_path, source)
    assert tags == {}


def test_shipped_index_has_the_checked_entries() -> None:
    import json

    path = Path("pals_agent/content_dictionaries/mathlib-stacks-tags-v1.json")
    tags = json.loads(path.read_text(encoding="utf-8"))["tags"]
    assert "AlgebraicGeometry.IsFinite.iff_isProper_and_locallyQuasiFinite" in [
        entry["name"] for entry in tags["02LS"]
    ]
    assert [entry["name"] for entry in tags["09G3"]] == ["Module.rank"]
    names = [entry["name"] for entries in tags.values() for entry in entries]
    assert not any(name and (name.endswith(".ical") or name.endswith(".")) for name in names)
