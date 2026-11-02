#!/usr/bin/env python3
"""Check, build and replay the textbook Recipe/Draft authoring cards.

No database, provider, signature or network access happens here. Run with the API
environment and both repositories on PYTHONPATH (see README.md).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import xml.sax.saxutils
from collections import Counter
from pathlib import Path

import rfc8785
import yaml
from app.domain.recipe_catalog_admission import (
    RecipeAuthoringManifestV1,
    RecipeMaterializerV1,
    validate_materialized_recipe,
)
from pals_agent import openmath as om

ROOT = Path(__file__).resolve().parent
CARDS = ROOT / "cards"
GENERATED = ROOT / "generated"
AUTHOR = "pals.principal.v1/claude/textbook-catalog-20261102"
TOOLCHAIN = {
    "fingerprint": {
        "lake_manifest_sha256": "290f048c4a499d34a3b21f8db30ade48a2b8d05b0fe79709f1868fa6748944fa",
        "lean_version": "leanprover/lean4:v4.32.0-rc1",
        "materializer_version": "pals.recipe-materializer.v1",
        "schema_version": "pals.lean-toolchain-fingerprint.v1",
        "verifier_sha256": "8a13da18825fc857f150220dc7aec489318dc7d2354a05bb955207e4764f284f",
    },
    "toolchain_id": "lean-4.32.0-rc1-mathlib-8b62164d-aws-v2",
}
ALLOWED_AXIOMS = {"propext", "Classical.choice", "Quot.sound"}
CARD_KEYS = {
    "id", "kind", "level", "topic", "statement", "statement_en", "assumptions", "quantifiers",
    "conclusion", "answer", "strategy", "sketch", "openmath", "hard_negative", "target", "proof",
}  # fmt: skip
KINDS = {"gap", "textbook", "named"}
SLUG = re.compile(r"^[a-z0-9][a-z0-9_]{0,70}$")
STEP = re.compile(r"^[a-z_]+: \S")
CD_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
JAPANESE = re.compile(r"[ぁ-んァ-ヶ一-龠]")

STANDARD = {
    "and": ("logic1", "and"), "or": ("logic1", "or"), "not": ("logic1", "not"),
    "->": ("logic1", "implies"), "<->": ("logic1", "equivalent"),
    "=": ("relation1", "eq"), "!=": ("relation1", "neq"), "<": ("relation1", "lt"),
    "<=": ("relation1", "leq"), ">": ("relation1", "gt"), ">=": ("relation1", "geq"),
    "+": ("arith1", "plus"), "*": ("arith1", "times"), "-": ("arith1", "minus"),
    "neg": ("arith1", "unary_minus"), "/": ("arith1", "divide"), "^": ("arith1", "power"),
    "abs": ("arith1", "abs"), "gcd": ("arith1", "gcd"), "lcm": ("arith1", "lcm"),
    "root": ("arith1", "root"), "sum": ("arith1", "sum"), "product": ("arith1", "product"),
    "sin": ("transc1", "sin"), "cos": ("transc1", "cos"), "tan": ("transc1", "tan"),
    "exp": ("transc1", "exp"), "ln": ("transc1", "ln"),
    "diff": ("calculus1", "diff"), "defint": ("calculus1", "defint"),
    "oriented_interval": ("interval1", "oriented_interval"),
    "in": ("set1", "in"), "notin": ("set1", "notin"), "subset": ("set1", "subset"),
    "prsubset": ("set1", "prsubset"), "inter": ("set1", "intersect"),
    "union": ("set1", "union"), "setdiff": ("set1", "setdiff"),
    "cartesian": ("set1", "cartesian_product"), "image": ("set1", "map"),
    "suchthat": ("set1", "suchthat"), "set": ("set1", "set"), "size": ("set1", "size"),
}  # fmt: skip
CONSTANTS = {
    "R": ("setname1", "R"), "N": ("setname1", "N"), "Z": ("setname1", "Z"),
    "Q": ("setname1", "Q"), "C": ("setname1", "C"), "P": ("setname1", "P"),
    "emptyset": ("set1", "emptyset"), "true": ("logic1", "true"), "false": ("logic1", "false"),
}  # fmt: skip
PALS1 = {
    "compact", "continuous_on", "continuous_at", "has_limit_at", "converges_to", "apply",
    "sequence_apply", "dimension", "domain", "finite_dimensional", "linear_map", "nullity",
    "rank", "constant_function", "function_add", "function_sub", "function_mul", "function_div",
    "function_compose", "function_neg", "function_scale", "sequence_add", "sequence_sub",
    "sequence_mul", "sequence_div", "sequence_scale", "sequence_compose", "sequence_neg",
    "index_succ", "index_to_real",
}  # fmt: skip
BINDERS = {
    "forall": ("quant1", "forall"),
    "exists": ("quant1", "exists"),
    "lambda": ("fns1", "lambda"),
}
PALS1_BINDERS = {
    "forall_real_function", "exists_real_function", "forall_real_sequence",
    "exists_real_sequence", "sequence_lambda",
}  # fmt: skip
PALS1_CONSTANTS = {"identity_function", "index_zero"}


class CardError(ValueError):
    pass


def load_vocabulary() -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for path in sorted((ROOT / "vocabulary").glob("*.yaml")):
        for name, spec in (yaml.safe_load(path.read_text()) or {}).items():
            if not CD_NAME.match(name) or name in STANDARD or name in PALS1 or name in BINDERS or name in PALS1_BINDERS:
                raise CardError(f"{path.name}: invalid or built-in vocabulary name {name}")
            if set(spec) != {"args", "returns", "meaning"} or spec["returns"] not in {
                "prop",
                "term",
            }:
                raise CardError(f"{path.name}: {name} needs exactly args/returns/meaning")
            key = (tuple(spec["args"]), spec["returns"])
            if name in merged and (tuple(merged[name]["args"]), merged[name]["returns"]) != key:
                raise CardError(f"vocabulary conflict for {name}: {path.name} differs")
            merged.setdefault(name, spec)
    return merged


@contextlib.contextmanager
def extended_profile(vocabulary: dict[str, dict]):
    """Layer the proposed vocabulary over the runtime tables for authoring validation only."""
    symbols, sorts = dict(om._SUPPORTED_SYMBOLS), dict(om._RETRIEVAL_FUNCTION_ARGUMENT_SORTS)
    dictionaries = om._PROFILE_CONTENT_DICTIONARIES
    for name, spec in vocabulary.items():
        identity = (om.PALS_OPENMATH_CDBASE, "pals2", name)
        arity = len(spec["args"])
        proposition = spec["returns"] == "prop"
        om._SUPPORTED_SYMBOLS[identity] = (
            om._SymbolSpec("constant", returns_proposition=proposition)
            if arity == 0
            else om._SymbolSpec("application", arity, arity, returns_proposition=proposition)
        )
        if any(argument != "term" for argument in spec["args"]):
            om._RETRIEVAL_FUNCTION_ARGUMENT_SORTS[identity] = tuple(spec["args"])
    om._PROFILE_CONTENT_DICTIONARIES = dictionaries | {(om.PALS_OPENMATH_CDBASE, "pals2")}
    try:
        yield
    finally:
        om._SUPPORTED_SYMBOLS.clear()
        om._SUPPORTED_SYMBOLS.update(symbols)
        om._RETRIEVAL_FUNCTION_ARGUMENT_SORTS.clear()
        om._RETRIEVAL_FUNCTION_ARGUMENT_SORTS.update(sorts)
        om._PROFILE_CONTENT_DICTIONARIES = dictionaries


def parse_sexpr(text: str):
    tokens = re.findall(r"[()]|[^\s()]+", text)

    def read(position: int):
        if position >= len(tokens):
            raise CardError("openmath: unexpected end")
        if tokens[position] == "(":
            items, position = [], position + 1
            while position < len(tokens) and tokens[position] != ")":
                item, position = read(position)
                items.append(item)
            if position >= len(tokens):
                raise CardError("openmath: missing )")
            return items, position + 1
        if tokens[position] == ")":
            raise CardError("openmath: unexpected )")
        return tokens[position], position + 1

    value, end = read(0)
    if end != len(tokens):
        raise CardError("openmath: trailing tokens")
    return value


def _oms(cd: str, name: str, *, pals: bool = False) -> str:
    base = f' cdbase="{om.PALS_OPENMATH_CDBASE}"' if pals else ""
    return f'<OMS{base} cd="{cd}" name="{xml.sax.saxutils.escape(name)}"/>'


def to_xml(node, scope: frozenset[str], vocabulary: dict[str, dict]) -> str:
    if isinstance(node, str):
        if re.fullmatch(r"-?\d+", node):
            return f"<OMI>{node}</OMI>"
        if node in scope:
            return f'<OMV name="{node}"/>'
        if node in CONSTANTS:
            return _oms(*CONSTANTS[node])
        if node in PALS1_CONSTANTS:
            return _oms("pals1", node, pals=True)
        if node in vocabulary and not vocabulary[node]["args"]:
            return _oms("pals2", node, pals=True)
        raise CardError(f"openmath: `{node}` is neither bound nor a known constant")
    if not node or not isinstance(node[0], str):
        raise CardError("openmath: an application needs a symbol head")
    head, *rest = node
    if head in BINDERS or head in PALS1_BINDERS:
        if len(rest) != 2 or not isinstance(rest[0], list) or not rest[0]:
            raise CardError(f"openmath: ({head} (vars) body) expected")
        names = rest[0]
        if any(
            not isinstance(name, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name)
            for name in names
        ):
            raise CardError("openmath: invalid bound variable")
        binder = _oms(*BINDERS[head]) if head in BINDERS else _oms("pals1", head, pals=True)
        variables = "".join(f'<OMV name="{name}"/>' for name in names)
        body = to_xml(rest[1], scope | set(names), vocabulary)
        return f"<OMBIND>{binder}<OMBVAR>{variables}</OMBVAR>{body}</OMBIND>"
    if head in STANDARD:
        operator = _oms(*STANDARD[head])
    elif head in PALS1:
        operator = _oms("pals1", head, pals=True)
    elif head in vocabulary:
        operator = _oms("pals2", head, pals=True)
    else:
        raise CardError(f"openmath: unknown head `{head}` (add it to your vocabulary file)")
    return f"<OMA>{operator}{''.join(to_xml(item, scope, vocabulary) for item in rest)}</OMA>"


def openmath_for(card: dict, vocabulary: dict[str, dict]) -> tuple[str, str]:
    """Return canonical XML and whether the unmodified runtime profile accepts it."""
    body = to_xml(parse_sexpr(card["openmath"]), frozenset(), vocabulary)
    document = f'<OMOBJ xmlns="{om.OPENMATH_NAMESPACE}" version="2.0">{body}</OMOBJ>'
    try:
        return om.canonicalize_retrieval_openmath_xml(document), "generic_now"
    except om.MathXMLValidationError as baseline:
        with extended_profile(vocabulary):
            try:
                return om.canonicalize_retrieval_openmath_xml(document), "needs_vocabulary"
            except om.MathXMLValidationError as error:
                raise CardError(f"openmath rejected: {error} (runtime: {baseline})") from error


def clean(card: dict, key: str) -> str:
    value = card.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CardError(f"{key} must be non-empty text")
    return value.strip()


def manifest_bytes(recipe_id: str, target: str, proof: str) -> bytes:
    return rfc8785.dumps(
        {
            "author_profile": {
                "schema_version": "pals.recipe-author-profile.v1",
                "source_author_principal": AUTHOR,
            },
            "environment": {"namespace": None, "opens": []},
            "imports": ["Mathlib"],
            "kind": "exact_target_proof",
            "proof_body": proof,
            "recipe_id": recipe_id,
            "revision": 1,
            "schema_version": "pals.recipe-authoring-manifest.v1",
            "source_author_principal": AUTHOR,
            "target_source": target,
            "toolchain": TOOLCHAIN,
        }
    )


def validate_card(card: object, domain: str, vocabulary: dict[str, dict]) -> dict:
    if not isinstance(card, dict):
        raise CardError("card must be a mapping")
    if set(card) != CARD_KEYS:
        raise CardError(
            f"fields differ: missing {sorted(CARD_KEYS - set(card))}, "
            f"extra {sorted(set(card) - CARD_KEYS)}"
        )
    if not SLUG.match(str(card["id"])):
        raise CardError("id must match [a-z0-9_]+")
    if card["kind"] not in KINDS or card["level"] not in {1, 2, 3, 4}:
        raise CardError("kind must be gap/textbook/named and level 1..4")
    for key in ("assumptions", "quantifiers", "sketch"):
        if not isinstance(card[key], list) or any(
            not isinstance(item, str) or not item.strip() for item in card[key]
        ):
            raise CardError(f"{key} must be a list of text")
    if not 2 <= len(card["sketch"]) <= 10 or any(not STEP.match(step) for step in card["sketch"]):
        raise CardError("sketch needs 2..10 `kind: text` steps with a lowercase kind")
    negative = card["hard_negative"]
    if not isinstance(negative, dict) or set(negative) != {"statement", "reason"}:
        raise CardError("hard_negative needs statement and reason")
    if not JAPANESE.search(clean(card, "answer")) or not JAPANESE.search(clean(card, "statement")):
        raise CardError("statement and answer must be Japanese")
    for key in ("topic", "statement_en", "conclusion", "strategy", "target", "proof"):
        clean(card, key)
    document, tier = openmath_for(card, vocabulary)
    recipe_id = f"textbook.{domain}.{card['id']}"
    manifest = manifest_bytes(recipe_id, clean(card, "target"), clean(card, "proof"))
    parsed = RecipeAuthoringManifestV1.parse(manifest)
    source = RecipeMaterializerV1.materialize(parsed)
    validate_materialized_recipe(parsed, source)
    return {
        "recipe_id": recipe_id,
        "domain": domain,
        "card": card,
        "xml": document,
        "tier": tier,
        "manifest": manifest,
        "source": source,
    }


def lean_environment() -> tuple[str, dict[str, str]]:
    workspace = Path(os.environ.get("PALS_LEAN_WORKSPACE", ""))
    if not (workspace / ".lake/packages/mathlib").is_dir():
        raise SystemExit("set PALS_LEAN_WORKSPACE to an existing compiled pinned lean-workspace")
    binary = Path.home() / ".elan/toolchains/leanprover--lean4---v4.32.0-rc1/bin/lean"
    packages = sorted((workspace / ".lake/packages").iterdir())
    search_path = ":".join(str(package / ".lake/build/lib/lean") for package in packages)
    return str(binary), dict(os.environ, LEAN_PATH=search_path)


AXIOMS = re.compile(
    r"'(pals_card_\d+)' (?:depends on axioms: \[([^\]]*)\]|does not depend on any axioms)", re.S
)
DIAGNOSTIC = re.compile(
    r"^[^\n:]*:(\d+):(\d+): error: (.*?)(?=^[^\n:]*:\d+:\d+: |^'pals_card_|\Z)", re.S | re.M
)


def compile_batch(entries: list[dict], timeout: int = 1800) -> dict[str, list[str]]:
    """Compile named audit copies in one file and return per-card failures."""
    binary, env = lean_environment()
    lines = ["import Mathlib", ""]
    spans: list[tuple[int, int, dict]] = []
    for index, entry in enumerate(entries):
        start = len(lines) + 1
        target, proof = clean(entry["card"], "target"), clean(entry["card"], "proof")
        text = f"theorem pals_card_{index} : {target} := {proof}"
        lines += [*text.split("\n"), f"#print axioms pals_card_{index}", ""]
        spans.append((start, len(lines), entry))
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "Batch.lean"
        path.write_text("\n".join(lines))
        result = subprocess.run(
            [binary, str(path)], env=env, capture_output=True, text=True, timeout=timeout
        )
    output = result.stdout + result.stderr
    failures: dict[str, list[str]] = {}
    for match in DIAGNOSTIC.finditer(output):
        line = int(match[1])
        owner = next(((start, entry) for start, end, entry in spans if start <= line < end), None)
        key = owner[1]["recipe_id"] if owner else "<batch>"
        relative = line - owner[0] + 1 if owner else line
        failures.setdefault(key, []).append(f"line {relative}: {match[3].strip()[:1200]}")
    audited = {}
    for match in AXIOMS.finditer(output):
        names = (match[2] or "").replace("\n", " ").split(",")
        audited[int(match[1].rsplit("_", 1)[1])] = {name.strip() for name in names if name.strip()}
    for index, entry in enumerate(entries):
        if entry["recipe_id"] in failures:
            continue
        axioms = audited.get(index)
        if axioms is None:
            failures[entry["recipe_id"]] = ["no axiom report; the declaration did not elaborate"]
        elif axioms - ALLOWED_AXIOMS:
            failures[entry["recipe_id"]] = [f"forbidden axioms: {sorted(axioms - ALLOWED_AXIOMS)}"]
    if result.returncode != 0 and not failures:
        failures["<batch>"] = [output[-2000:]]
    return failures


def load_file(path: Path, vocabulary: dict[str, dict]) -> tuple[list[dict], dict[str, list[str]]]:
    raw = yaml.safe_load(path.read_text()) or []
    entries, errors = [], {}
    seen: set[str] = set()
    for card in raw:
        label = f"textbook.{path.stem}.{card.get('id') if isinstance(card, dict) else '?'}"
        try:
            if label in seen:
                raise CardError("duplicate id in this file")
            seen.add(label)
            entries.append(validate_card(card, path.stem, vocabulary))
        except Exception as error:  # every contract failure is reported per card
            errors[label] = [str(error)[:1200]]
    return entries, errors


def command_check(args: argparse.Namespace) -> int:
    vocabulary = load_vocabulary()
    entries, errors = load_file(CARDS / f"{args.domain}.yaml", vocabulary)
    selected = [entry for entry in entries if not args.only or entry["card"]["id"] in args.only]
    if selected and not args.no_compile:
        errors.update(compile_batch(selected))
    for key, messages in sorted(errors.items()):
        print(f"FAIL {key}")
        for message in messages:
            print(f"  {message}")
    summary = {
        "valid_contract": len(entries),
        "failed": len(errors),
        "kinds": Counter(entry["card"]["kind"] for entry in entries),
        "levels": Counter(entry["card"]["level"] for entry in entries),
        "tiers": Counter(entry["tier"] for entry in entries),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if errors else 0


def normalized(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def all_entries() -> list[dict]:
    vocabulary = load_vocabulary()
    entries: list[dict] = []
    for path in sorted(CARDS.glob("*.yaml")):
        if path.stem.startswith("_"):
            continue
        loaded, errors = load_file(path, vocabulary)
        if errors:
            raise SystemExit(f"{path.name} has invalid cards: {sorted(errors)[:10]}")
        entries += loaded
    return entries


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=1, sort_keys=True) + "\n")


def search_text(card: dict, domain: str) -> str:
    parts = [
        card["statement"],
        card["statement_en"],
        card["topic"],
        domain.replace("_", " "),
        *card["assumptions"],
        card["strategy"],
    ]
    return "\n".join(normalized(str(part)) for part in parts)


def command_build(_: argparse.Namespace) -> int:
    entries = all_entries()
    keys = (
        ("target", lambda entry: normalized(entry["card"]["target"])),
        ("openmath", lambda entry: entry["xml"]),
        ("statement", lambda entry: normalized(entry["card"]["statement_en"]).lower()),
    )
    for label, key in keys:
        counts = Counter(key(entry) for entry in entries)
        repeated = [entry["recipe_id"] for entry in entries if counts[key(entry)] > 1]
        if repeated:
            raise SystemExit(f"duplicate {label}: {repeated}")
    (GENERATED / "manifests").mkdir(parents=True, exist_ok=True)
    for stale in (GENERATED / "manifests").glob("*.json"):
        stale.unlink()
    index, drafts, searches, negatives = [], [], [], []
    for entry in entries:
        card = entry["card"]
        (GENERATED / "manifests" / f"{entry['recipe_id']}.json").write_bytes(entry["manifest"])
        draft_id = entry["recipe_id"].replace(".", "_")
        index.append(
            {
                "recipe_id": entry["recipe_id"],
                "draft_id": draft_id,
                "domain": entry["domain"],
                "kind": card["kind"],
                "level": card["level"],
                "topic": card["topic"],
                "tier": entry["tier"],
                "manifest_sha256": hashlib.sha256(entry["manifest"]).hexdigest(),
                "materialized_source_sha256": hashlib.sha256(entry["source"]).hexdigest(),
            }
        )
        drafts.append(
            {
                "id": draft_id,
                "canonical_statement": normalized(card["statement_en"]),
                "openmath_xml": entry["xml"],
                "proof_strategy": normalized(card["strategy"]),
                "sketch_steps": card["sketch"],
                "tier": entry["tier"],
            }
        )
        searches.append(
            {
                "recipe_id": entry["recipe_id"],
                "recipe_revision": 1,
                "statement": normalized(card["statement"]),
                "domain": normalized(card["topic"]),
                "assumptions": card["assumptions"],
                "quantifiers": card["quantifiers"],
                "conclusion": normalized(card["conclusion"]),
                "proof_method_tag": None,
                "search_text": search_text(card, entry["domain"]),
                "output_language": "ja",
                "answer": card["answer"].strip(),
            }
        )
        negatives.append({"recipe_id": entry["recipe_id"], **card["hard_negative"]})
    write_json(
        GENERATED / "index.json",
        {"schema_version": "pals.textbook-catalog-index.v1", "cases": index},
    )
    write_json(
        GENERATED / "drafts.json",
        {"schema_version": "pals.textbook-draft-candidates.v1", "drafts": drafts},
    )
    write_json(
        GENERATED / "search-candidates.json",
        {"schema_version": "pals.textbook-search-candidates.v1", "candidates": searches},
    )
    write_json(
        GENERATED / "hard-negatives.json",
        {"schema_version": "pals.textbook-hard-negatives.v1", "negatives": negatives},
    )
    vocabulary = load_vocabulary()
    used = {
        name
        for draft in drafts
        for name in re.findall(r'cd="pals2"[^>]*name="([a-z0-9_]+)"', draft["openmath_xml"])
    }
    write_json(
        GENERATED / "vocabulary.json",
        {
            "schema_version": "pals.textbook-openmath-vocabulary.v1",
            "cd": "pals2",
            "symbols": {key: value for key, value in sorted(vocabulary.items()) if key in used},
        },
    )
    summary = {
        "cards": len(entries),
        "domains": Counter(entry["domain"] for entry in entries),
        "kinds": Counter(entry["card"]["kind"] for entry in entries),
        "levels": Counter(entry["card"]["level"] for entry in entries),
        "tiers": Counter(entry["tier"] for entry in entries),
        "vocabulary": len(used),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return 0


def _replay(entry: dict, binary: str, env: dict[str, str], temp: str) -> dict:
    name = hashlib.sha256(entry["recipe_id"].encode()).hexdigest()[:24]
    path = Path(temp) / f"R{name}.lean"
    path.write_bytes(entry["source"])
    started = time.monotonic()
    try:
        done = subprocess.run(
            [binary, str(path)], env=env, capture_output=True, text=True, timeout=300
        )
        code, output = done.returncode, done.stdout + done.stderr
    except subprocess.TimeoutExpired:
        code, output = -1, "timeout"
    return {
        "recipe_id": entry["recipe_id"],
        "exit_code": code,
        "seconds": round(time.monotonic() - started, 3),
        "materialized_source_sha256": hashlib.sha256(entry["source"]).hexdigest(),
        "has_error": code != 0 or " error:" in output,
        "warned_sorry": "declaration uses" in output and "sorry" in output,
        "output_tail": output[-600:] if code != 0 else "",
    }


def command_verify(args: argparse.Namespace) -> int:
    entries = all_entries()
    binary, env = lean_environment()
    failures: dict[str, list[str]] = {}
    domains = sorted({entry["domain"] for entry in entries})
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        batches = pool.map(
            lambda domain: compile_batch([e for e in entries if e["domain"] == domain]), domains
        )
        for result in batches:
            failures.update(result)
    with (
        tempfile.TemporaryDirectory() as temp,
        concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as pool,
    ):
        results = list(pool.map(lambda entry: _replay(entry, binary, env, temp), entries))
    bad = [row for row in results if row["has_error"] or row["warned_sorry"]]
    seconds = sorted(row["seconds"] for row in results)
    version = subprocess.run([binary, "--version"], capture_output=True, text=True).stdout.strip()
    report = {
        "schema_version": "pals.textbook-catalog-local-replay.v1",
        "lean": version,
        "cases": len(results),
        "materialized_failures": len(bad),
        "axiom_audit_failures": len(failures),
        "seconds_median": seconds[len(seconds) // 2],
        "seconds_max": seconds[-1],
        "index_sha256": hashlib.sha256((GENERATED / "index.json").read_bytes()).hexdigest(),
        "results": results,
    }
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, indent=1))
    for row in bad[:40]:
        print("FAIL", row["recipe_id"], row["output_tail"][:400])
    for key, messages in list(failures.items())[:40]:
        print("AXIOM-FAIL", key, messages[0][:400])
    slowest = sorted(((row["seconds"], row["recipe_id"]) for row in results), reverse=True)[:8]
    print("slowest:", slowest)
    return 1 if bad or failures else 0


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(required=True)
    check = commands.add_parser("check")
    check.add_argument("domain")
    check.add_argument("--only", nargs="*", default=[])
    check.add_argument("--no-compile", action="store_true")
    check.set_defaults(run=command_check)
    commands.add_parser("build").set_defaults(run=command_build)
    verify = commands.add_parser("verify")
    verify.add_argument("--output", required=True)
    verify.add_argument("--jobs", type=int, default=8)
    verify.set_defaults(run=command_verify)
    args = parser.parse_args()
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
