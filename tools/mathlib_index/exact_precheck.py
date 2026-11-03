"""Measure a model-free `exact?` check that would run after Sketch and before Prove.

Nothing here changes production. Each statement runs in its own Lean process with the verifier's
`--threads=1`, so wall time, CPU time and peak memory are per check. Lean decides closure on the
elaborated goal; a suggestion counts only after `ProofPipeline` verifies it with `LeanVerifier`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pals_agent.artifacts import FileArtifactStore, safe_artifact_segment
from pals_agent.generator import HybridLeanGenerator
from pals_agent.lean import LeanVerifier
from pals_agent.lean_source_policy import _masked_code, strip_lean_comments_and_strings
from pals_agent.models import (
    DEFAULT_MAX_REPAIR_ATTEMPTS,
    GeneratedDraft,
    GeneratedProof,
    GeneratedSketch,
    ProofRequest,
)
from pals_agent.openai import OpenAIResponsesClient
from pals_agent.pipeline import ProofPipeline, _sketch_adherence
from pals_agent.usage import usage_scope
from tools.mathlib_index.extract_premises import catalog_bundles, requested_jobs
from tools.mathlib_index.hint_ab import USD_PER_MTOK, GuardedClient, SpendGuard
from tools.mathlib_index.known_statement_check import header_of

_EXCLUDED_STATEMENT = re.compile(r"\(\s*\w+\s*\+\s*\w+\s*\)\s*\^\s*2\s*=")
_SUGGESTION_PREFIX = re.compile(r"\A\s*Try this:\s*(?:\[apply\]\s*)?")
_ENVIRONMENT_KEYS = ("PATH", "HOME", "LEAN_PATH", "TMPDIR", "LANG", "LC_ALL")
_DECLARATION = re.compile(
    r"^(?:(?:private|protected|noncomputable)\s+)*(?:theorem|lemma|example)\b", re.MULTILINE
)
_OPENING = "([{⟨"
_CLOSING = ")]}⟩"
_STAGES = (
    ("Write an informal natural-language", "draft"),
    ("Translate the informal Draft", "sketch"),
    ("Complete a Lean 4/mathlib proof", "prove"),
    ("Choose where the PALS", "repair_route"),
    ("Create the PALS repair handoff", "repair_instruction"),
)


def opens_of(header: str) -> str:
    # The harness check strips comments from generated code only, so the harness must have none.
    return "\n".join(
        line
        for line in strip_lean_comments_and_strings(header).splitlines()
        if line.strip() and not line.startswith(("import ", "--"))
    )


def card_problem(card: dict[str, Any], source: str) -> dict[str, Any]:
    header = header_of(source)
    target = re.sub(r"^example\b", "theorem pals_card_target", card["lean_target"].strip())
    opens = opens_of(header)
    return {
        "id": card["card_id"],
        "source_set": card["source_set"],
        "statement": card.get("statement_en") or card.get("statement_ja") or "",
        "formal_statement": (opens + "\n\n" if opens else "") + target,
    }


def load_problems(args: argparse.Namespace) -> list[dict[str, Any]]:
    catalog = sorted(
        (
            (hashlib.sha256(card["card_id"].encode()).hexdigest(), card, job["source"])
            for job in catalog_bundles(args.inventory, args.repo_root)
            for card in job["cards"].values()
        ),
        key=lambda item: item[0],
    )[args.catalog_skip : args.catalog_skip + args.catalog_sample]
    problems = [card_problem(card, source) for _, card, source in catalog]
    for job in requested_jobs(args.requested_corpus):
        problems.extend(card_problem(card, job["source"]) for card in job["cards"].values())
    return [p for p in problems if not _EXCLUDED_STATEMENT.search(p["formal_statement"])]


def run_measured(
    command: list[str], *, env: dict[str, str], timeout: float, output: Path
) -> dict[str, Any]:
    """Run one process and read its own rusage, which `subprocess.run` does not expose."""
    started = time.monotonic()
    with output.open("wb") as sink:
        pid = os.posix_spawn(
            command[0],
            command,
            env,
            file_actions=[
                (os.POSIX_SPAWN_DUP2, sink.fileno(), 1),
                (os.POSIX_SPAWN_DUP2, sink.fileno(), 2),
            ],
        )
    timed_out = False
    while True:
        finished, status, usage = os.wait4(pid, os.WNOHANG)
        if finished == pid:
            break
        if time.monotonic() - started > timeout and not timed_out:
            timed_out = True
            os.kill(pid, signal.SIGKILL)
        time.sleep(0.05)
    # macOS reports ru_maxrss in bytes and Linux in KiB.
    rss_bytes = usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024
    return {
        "wall_seconds": round(time.monotonic() - started, 2),
        "cpu_seconds": round(usage.ru_utime + usage.ru_stime, 2),
        "peak_rss_gib": round(rss_bytes / 2**30, 2),
        "returncode": os.waitstatus_to_exitcode(status),
        "timed_out": timed_out,
    }


def parse_exact_output(text: str) -> dict[str, Any]:
    proof: str | None = None
    errors: list[str] = []
    for line in text.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        data = str(message.get("data", ""))
        if message.get("severity") == "error":
            errors.append(data)
        elif "Try this" in data and proof is None:
            proof = _SUGGESTION_PREFIX.sub("", data).strip()
    if errors:
        joined = " ".join(errors)
        if "could not close" in joined:
            outcome = "not_closed"
        elif "heartbeats" in joined:
            outcome = "heartbeat_limit"
        else:
            outcome = "statement_error"
        return {"outcome": outcome, "proof": None, "error": errors[0][:300]}
    if proof is None:
        return {"outcome": "no_result", "proof": None, "error": None}
    return {"outcome": "closed", "proof": proof, "error": None}


def check_source(
    source: str, *, lean: str, threads: int, timeout: float, env: dict[str, str]
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Check.lean"
        path.write_text(source, encoding="utf-8")
        log = Path(tmp) / "out.jsonl"
        measured = run_measured(
            [lean, "--json", f"--threads={threads}", str(path)],
            env=env,
            timeout=timeout,
            output=log,
        )
        parsed = parse_exact_output(log.read_text(encoding="utf-8", errors="replace"))
    if measured["timed_out"]:
        parsed = {"outcome": "timeout", "proof": None, "error": None}
    return {**measured, **parsed}


def precheck_source(imports: str, formal_statement: str) -> str:
    return f"{imports}\n\n{formal_statement.strip()} := by\n  exact?\n"


def closed_source(imports: str, formal_statement: str, proof: str) -> str:
    body = "\n".join("  " + line for line in proof.splitlines())
    return f"{imports}\n\n{formal_statement.strip()} := by\n{body}\n"


def split_sketch(code: str) -> tuple[str, str] | None:
    """Return the import lines and a proof-free target, dropping `sorry`-backed helper lemmas.

    Lean later elaborates this text, so this only locates the proof; it never decides identity.
    """
    masked = _masked_code(code)
    declarations = list(_DECLARATION.finditer(masked))
    if not declarations:
        return None
    target = declarations[-1].start()
    depth = 0
    end = None
    for position in range(target, len(masked)):
        char = masked[position]
        if char in _OPENING:
            depth += 1
        elif char in _CLOSING:
            depth -= 1
        elif depth == 0 and masked.startswith(":=", position):
            end = position
            break
    if end is None:
        return None
    lines = code[:target].splitlines()
    imports = [line for line in lines if line.startswith("import ")]
    preamble: list[str] = []
    skipping = False
    for line in lines:
        if line.startswith("import "):
            continue
        if _DECLARATION.match(line):
            skipping = True
        elif skipping and line and not line[0].isspace():
            skipping = False
        if not skipping:
            preamble.append(line)
    statement = "\n".join([*preamble, code[target:end].rstrip()]).strip()
    return "\n".join(imports) or "import Mathlib", statement


def lean_env() -> dict[str, str]:
    return {key: os.environ[key] for key in _ENVIRONMENT_KEYS if key in os.environ}


def command_measure(args: argparse.Namespace) -> None:
    problems = load_problems(args)
    env = lean_env()

    def run(problem: dict[str, Any]) -> dict[str, Any]:
        result = check_source(
            precheck_source("import Mathlib", problem["formal_statement"]),
            lean=args.lean,
            threads=args.threads,
            timeout=args.timeout,
            env=env,
        )
        load = round(os.getloadavg()[0], 1)
        row = {**problem, "threads": args.threads, "load_1m": load, **result}
        with args.out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(row["id"], row["outcome"], row["wall_seconds"], row["cpu_seconds"], flush=True)
        return row

    done = set()
    if args.out.exists():
        done = {json.loads(line)["id"] for line in args.out.open(encoding="utf-8")}
    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(run, [p for p in problems if p["id"] not in done]))


@dataclass(slots=True)
class ReplayGenerator:
    """Feeds a fixed Draft, Sketch and proof through the real pipeline without any model call."""

    draft: str
    sketch: str
    proof: str
    model: str = "exact-precheck"

    def generate_draft(self, request: ProofRequest, feedback: Any = None) -> GeneratedDraft:
        return GeneratedDraft(text=self.draft, model=self.model, raw_model_output=self.draft)

    def generate_sketch(
        self, request: ProofRequest, draft: GeneratedDraft, feedback: Any = None
    ) -> GeneratedSketch:
        return GeneratedSketch(
            lean_code=self.sketch,
            model=self.model,
            raw_model_output=self.sketch,
            has_gaps=True,
        )

    def generate_proof(
        self,
        request: ProofRequest,
        draft: GeneratedDraft,
        sketch: GeneratedSketch,
        feedback: Any = None,
    ) -> GeneratedProof:
        return GeneratedProof(
            lean_code=self.proof,
            model=self.model,
            raw_model_output=self.proof,
            draft=draft,
            sketch=sketch,
        )


class _StopAfterSketch(Exception):
    pass


@dataclass(slots=True)
class StageClient:
    """Tags each model call with its pipeline stage so spend after Sketch is attributable."""

    inner: Any
    calls: list[dict[str, Any]] = field(default_factory=list)

    def generate(self, *, model: str, prompt: str) -> str:
        stage = next((name for prefix, name in _STAGES if prompt.startswith(prefix)), "other")
        row = {"stage": stage, "model": model, "started": time.monotonic()}
        self.calls.append(row)
        try:
            return str(self.inner.generate(model=model, prompt=prompt))
        finally:
            row["seconds"] = round(time.monotonic() - row.pop("started"), 2)


@dataclass(slots=True)
class ShadowGenerator:
    """Runs the real generator and records the first Sketch; the proof path itself is untouched."""

    inner: HybridLeanGenerator
    stop_after_sketch: bool
    started: float
    draft: str | None = None
    sketch: str | None = None
    sketch_seconds: float | None = None
    prove_entry_seconds: float | None = None

    def generate_draft(self, request: ProofRequest, feedback: Any = None) -> GeneratedDraft:
        result = self.inner.generate_draft(request, feedback)
        if self.draft is None:
            self.draft = result.text
        return result

    def generate_sketch(
        self, request: ProofRequest, draft: GeneratedDraft, feedback: Any = None
    ) -> GeneratedSketch:
        result = self.inner.generate_sketch(request, draft, feedback)
        if self.sketch is None:
            self.sketch = result.lean_code
            self.sketch_seconds = round(time.monotonic() - self.started, 1)
        return result

    def generate_proof(
        self,
        request: ProofRequest,
        draft: GeneratedDraft,
        sketch: GeneratedSketch,
        feedback: Any = None,
    ) -> GeneratedProof:
        if self.prove_entry_seconds is None:
            self.prove_entry_seconds = round(time.monotonic() - self.started, 1)
        if self.stop_after_sketch:
            raise _StopAfterSketch
        return self.inner.generate_proof(request, draft, sketch, feedback)

    def select_repair_route(self, request: ProofRequest, feedback: Any) -> Any:
        if self.stop_after_sketch:
            raise _StopAfterSketch
        return self.inner.select_repair_route(request, feedback)

    def repair(self, request: ProofRequest, feedback: Any) -> GeneratedProof:
        if self.stop_after_sketch:
            raise _StopAfterSketch
        return self.inner.repair(request, feedback)


def estimated_usd(rows: list[dict[str, Any]]) -> float:
    return round(
        sum(
            row["input_tokens"] * USD_PER_MTOK[row["model"]][0]
            + row["output_tokens"] * USD_PER_MTOK[row["model"]][1]
            for row in rows
        )
        / 1e6,
        5,
    )


def run_flow(
    problem: dict[str, Any], *, args: argparse.Namespace, guard: SpendGuard
) -> dict[str, Any]:
    """Run the unmodified pipeline, or stop right after the first Sketch, and attribute spend."""
    openai = OpenAIResponsesClient(
        api_key=os.environ["OPENAI_API_KEY"],
        max_output_tokens=args.max_output_tokens,
        reasoning_effort=args.effort,
    )
    stages = StageClient(GuardedClient(openai, guard))
    started = time.monotonic()
    shadow = ShadowGenerator(
        HybridLeanGenerator(model=args.model, provider="openai", client=stages),
        stop_after_sketch=args.stop_after_sketch,
        started=started,
    )
    run_id = f"{args.run_label}-{problem['id']}"
    pipeline = ProofPipeline(
        generator=shadow,
        verifier=make_verifier(args),
        artifact_store=FileArtifactStore(args.artifacts),
        max_repair_attempts=args.max_repairs,
    )
    pinned = bool(args.pinned)
    usage: list[dict[str, Any]] = []

    def on_usage(row: dict[str, Any]) -> None:
        guard.add(row)
        usage.append(row)
        calls = [call for call in stages.calls if "input_tokens" not in call]
        if calls:
            calls[-1].update(
                input_tokens=row["input_tokens"],
                cached_input_tokens=row["cached_input_tokens"],
                output_tokens=row["output_tokens"],
            )

    state = "stopped_after_sketch"
    repairs = None
    termination = None
    with usage_scope(on_usage):
        try:
            result = pipeline.run_statement(
                statement=problem["statement"],
                formal_statement=problem["formal_statement"] if pinned else None,
                proof_job_id=run_id,
            )
            state = result.state
            metadata = json.loads(
                (args.artifacts / safe_artifact_segment(run_id) / "result.json").read_text("utf-8")
            )
            repairs = metadata.get("repairs_used")
            termination = metadata.get("termination_reason")
        except _StopAfterSketch:
            pass
    record = {
        "id": problem["id"],
        "source_set": problem.get("source_set"),
        "statement": problem["statement"],
        "pinned": pinned,
        "formal_statement": problem["formal_statement"],
        "model": args.model,
        "effort": args.effort,
        "state": state,
        "repairs_used": repairs,
        "termination_reason": termination,
        "elapsed_seconds": round(time.monotonic() - started, 1),
        "sketch_seconds": shadow.sketch_seconds,
        "prove_entry_seconds": shadow.prove_entry_seconds,
        "draft": shadow.draft,
        "sketch": shadow.sketch,
        "calls": stages.calls,
        "usd": estimated_usd(usage),
        "budget_stopped": guard.stopped,
    }
    print(record["id"], record["state"], record["elapsed_seconds"], record["usd"], flush=True)
    return record


def command_flow(args: argparse.Namespace) -> None:
    args.artifacts.mkdir(parents=True, exist_ok=True)
    args.scratch.mkdir(parents=True, exist_ok=True)
    problems = json.loads(args.problems.read_text(encoding="utf-8"))
    guard = SpendGuard(limit_usd=args.max_usd)
    done = set()
    if args.out.exists():
        done = {json.loads(line)["id"] for line in args.out.open(encoding="utf-8")}

    def run(problem: dict[str, Any]) -> None:
        if guard.stopped:
            return
        try:
            record = run_flow(problem, args=args, guard=guard)
        except Exception as exc:  # A failed run must not lose completed results.
            record = {
                "id": problem["id"],
                "error": type(exc).__name__,
                "message": str(exc)[:400],
            }
            print(json.dumps(record, ensure_ascii=False), flush=True)
        with args.out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(run, [p for p in problems if p["id"] not in done]))
    print(json.dumps({"estimated_usd": round(guard.spent_usd, 4), "stopped": guard.stopped}))


def command_flow_check(args: argparse.Namespace) -> None:
    """Run exact? on each recorded first Sketch, with its own imports and with all of Mathlib."""
    rows = [json.loads(line) for line in args.flow.open(encoding="utf-8")]
    env = lean_env()
    work: list[tuple[dict[str, Any], str, str, str]] = []
    done = set()
    if args.out.exists():
        done = {
            (row["id"], row["variant"])
            for row in map(json.loads, args.out.open(encoding="utf-8"))
        }
    for row in rows:
        split = split_sketch(row["sketch"]) if row.get("sketch") else None
        if split is None:
            continue
        imports, statement = split
        if row.get("pinned"):
            statement = row["formal_statement"]
        for variant, chosen in (("sketch_imports", imports), ("full_mathlib", "import Mathlib")):
            if (row["id"], variant) not in done:
                work.append((row, variant, chosen, statement))

    def run(item: tuple[dict[str, Any], str, str, str]) -> None:
        row, variant, imports, statement = item
        result = check_source(
            precheck_source(imports, statement),
            lean=args.lean,
            threads=args.threads,
            timeout=args.timeout,
            env=env,
        )
        record = {
            "id": row["id"],
            "variant": variant,
            "imports": imports,
            "formal_statement": statement,
            "statement": row["statement"],
            "pinned": row.get("pinned", False),
            "draft": row.get("draft"),
            "sketch_code": row.get("sketch"),
            "threads": args.threads,
            "load_1m": round(os.getloadavg()[0], 1),
            **result,
        }
        with args.out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(row["id"], variant, record["outcome"], record["wall_seconds"], flush=True)

    with ThreadPoolExecutor(args.workers) as pool:
        list(pool.map(run, work))


def _warm_mark(position: int) -> str:
    return (
        "#eval show IO Unit from do\n"
        f'  IO.println s!"PALS_MARK {position} {{← IO.monoMsNow}}"\n'
    )


def command_warm(args: argparse.Namespace) -> None:
    """Time exact? per statement in one long-lived process, to separate search from start-up."""
    rows = [json.loads(line) for line in args.measured.open(encoding="utf-8")]
    usable = [
        row
        for row in rows
        if row["outcome"] in {"closed", "not_closed"}
        and not re.search(r"^(?:def|structure|noncomputable)\b", row["formal_statement"], re.M)
    ][: args.limit]
    parts = ["import Mathlib\n"]
    for position, row in enumerate(usable):
        statement = re.sub(
            r"^theorem \S+", f"theorem pals_warm_{position}", row["formal_statement"], flags=re.M
        )
        parts.append(_warm_mark(position))
        parts.append(f"section\n{statement.strip()} := by\n  exact?\nend\n")
    parts.append(_warm_mark(len(usable)))
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "Warm.lean"
        path.write_text("\n".join(parts), encoding="utf-8")
        log = Path(tmp) / "out.jsonl"
        measured = run_measured(
            [args.lean, "--json", f"--threads={args.threads}", str(path)],
            env=lean_env(),
            timeout=args.timeout,
            output=log,
        )
        output = log.read_text(encoding="utf-8", errors="replace")
    marks: dict[int, int] = {}
    closed: dict[int, bool] = {}
    current = -1
    for line in output.splitlines():
        try:
            data = str(json.loads(line).get("data", ""))
        except json.JSONDecodeError:
            continue
        mark = re.match(r"PALS_MARK (\d+) (\d+)", data)
        if mark:
            current = int(mark.group(1))
            marks[current] = int(mark.group(2))
        elif "Try this" in data and current >= 0:
            closed[current] = True
    records = [
        {
            "id": row["id"],
            "position": position,
            "outcome_cold": row["outcome"],
            "closed_warm": closed.get(position, False),
            "seconds": round((marks[position + 1] - marks[position]) / 1000, 2)
            if position in marks and position + 1 in marks
            else None,
        }
        for position, row in enumerate(usable)
    ]
    args.out.write_text(
        json.dumps({"process": measured, "statements": records}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    print(json.dumps(measured))


def make_verifier(args: argparse.Namespace) -> LeanVerifier:
    return LeanVerifier(
        lean_binary=args.verifier_lean,
        lake_binary=args.verifier_lake,
        project_dir=args.lean_project,
        child_path=f"{Path(args.verifier_lean).parent}:/usr/bin:/bin",
        elan_home=str(args.elan_home),
        scratch_dir=args.scratch,
        timeout_seconds=args.lean_timeout,
    )


def replay(row: dict[str, Any], *, args: argparse.Namespace, label: str) -> dict[str, Any]:
    """Run the closed proof through `ProofPipeline`: harness check, Lean, axiom audit, no repair."""
    imports = row.get("imports", "import Mathlib")
    statement = row["formal_statement"]
    run_id = f"{label}-{row['id']}"
    pipeline = ProofPipeline(
        generator=ReplayGenerator(
            draft=row.get("draft") or row["statement"],
            sketch=closed_source(imports, statement, "sorry"),
            proof=closed_source(imports, statement, row["proof"]),
        ),
        verifier=make_verifier(args),
        artifact_store=FileArtifactStore(args.artifacts),
        max_repair_attempts=1,  # The replay generator has no `repair`, so none can run.
    )
    started = time.monotonic()
    result = pipeline.run_statement(
        statement=row["statement"] or row["id"],
        formal_statement=statement if row.get("pinned", True) else None,
        proof_job_id=run_id,
    )
    elapsed = time.monotonic() - started
    metadata = json.loads(
        (args.artifacts / safe_artifact_segment(run_id) / "result.json").read_text("utf-8")
    )
    attempts = metadata.get("attempts", [])
    verification = attempts[-1].get("verification", {}) if attempts else {}
    return {
        "id": row["id"],
        "variant": row.get("variant"),
        "state": result.state,
        "termination_reason": metadata.get("termination_reason"),
        "pipeline_seconds": round(elapsed, 1),
        "verify_seconds": round(verification.get("elapsed_ms", 0) / 1000, 1),
        "sketch_adherence": (
            _sketch_adherence(
                GeneratedProof(
                    lean_code=closed_source(imports, statement, row["proof"]),
                    model="exact-precheck",
                    raw_model_output="",
                    sketch=GeneratedSketch(
                        lean_code=row["sketch_code"], model="", raw_model_output=""
                    ),
                )
            )
            if row.get("sketch_code")
            else None
        ),
        "error_codes": sorted(
            {
                str(d.get("code"))
                for d in verification.get("diagnostics", [])
                if d.get("severity") == "error"
            }
        ),
        "error_message": next(
            (
                str(d.get("message"))[:400]
                for d in verification.get("diagnostics", [])
                if d.get("severity") == "error"
            ),
            None,
        ),
        "proof": row["proof"],
    }


def command_verify(args: argparse.Namespace) -> None:
    args.artifacts.mkdir(parents=True, exist_ok=True)
    args.scratch.mkdir(parents=True, exist_ok=True)
    rows = [json.loads(line) for line in args.measured.open(encoding="utf-8")]
    closed = [row for row in rows if row["outcome"] == "closed"]
    done = set()
    if args.out.exists():
        done = {
            (row["id"], row.get("variant"))
            for row in map(json.loads, args.out.open(encoding="utf-8"))
        }

    def run(row: dict[str, Any]) -> None:
        label = f"{args.label}-{row['variant']}" if row.get("variant") else args.label
        record = replay(row, args=args, label=label)
        with args.out.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(record["id"], record["state"], record["error_codes"], flush=True)

    with ThreadPoolExecutor(args.workers) as pool:
        list(
            pool.map(run, [row for row in closed if (row["id"], row.get("variant")) not in done])
        )


def add_verifier_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--verifier-lean", required=True, help="Usually the Elan proxy")
    parser.add_argument("--verifier-lake", required=True)
    parser.add_argument("--lean-project", type=Path, required=True)
    parser.add_argument("--elan-home", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--lean-timeout", type=float, default=300.0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    measure = commands.add_parser("measure", help="Run exact? on card statements")
    measure.add_argument("--inventory", type=Path, required=True)
    measure.add_argument("--repo-root", type=Path, required=True)
    measure.add_argument("--requested-corpus", type=Path, required=True)
    measure.add_argument("--lean", required=True, help="Real Lean binary with LEAN_PATH set")
    measure.add_argument("--out", type=Path, required=True)
    measure.add_argument("--catalog-sample", type=int, default=80)
    measure.add_argument("--catalog-skip", type=int, default=0)
    measure.add_argument("--workers", type=int, default=4)
    measure.add_argument("--threads", type=int, default=1)
    measure.add_argument("--timeout", type=float, default=600.0)
    measure.set_defaults(handler=command_measure)
    verify = commands.add_parser("verify", help="Replay closed proofs through ProofPipeline")
    verify.add_argument("--measured", type=Path, required=True)
    verify.add_argument("--out", type=Path, required=True)
    verify.add_argument("--label", default="exact-precheck")
    verify.add_argument("--workers", type=int, default=3)
    add_verifier_arguments(verify)
    verify.set_defaults(handler=command_verify)
    warm = commands.add_parser("warm", help="Run exact? on many statements in one process")
    warm.add_argument("--measured", type=Path, required=True)
    warm.add_argument("--out", type=Path, required=True)
    warm.add_argument("--lean", required=True)
    warm.add_argument("--limit", type=int, default=40)
    warm.add_argument("--threads", type=int, default=1)
    warm.add_argument("--timeout", type=float, default=3000.0)
    warm.set_defaults(handler=command_warm)
    flow = commands.add_parser("flow", help="Run real Draft/Sketch/Prove and attribute model spend")
    flow.add_argument("--problems", type=Path, required=True)
    flow.add_argument("--out", type=Path, required=True)
    flow.add_argument("--run-label", required=True)
    flow.add_argument("--model", default="gpt-6-luna")
    flow.add_argument("--effort", default="low")
    flow.add_argument("--pinned", action="store_true", help="Fix the card's Lean statement")
    flow.add_argument("--stop-after-sketch", action="store_true")
    flow.add_argument("--max-repairs", type=int, default=DEFAULT_MAX_REPAIR_ATTEMPTS)
    flow.add_argument("--max-output-tokens", type=int, default=16384)
    flow.add_argument("--max-usd", type=float, required=True)
    flow.add_argument("--workers", type=int, default=3)
    add_verifier_arguments(flow)
    flow.set_defaults(handler=command_flow)
    flow_check = commands.add_parser("flow-check", help="Run exact? on recorded first Sketches")
    flow_check.add_argument("--flow", type=Path, required=True)
    flow_check.add_argument("--out", type=Path, required=True)
    flow_check.add_argument("--lean", required=True)
    flow_check.add_argument("--workers", type=int, default=4)
    flow_check.add_argument("--threads", type=int, default=1)
    flow_check.add_argument("--timeout", type=float, default=600.0)
    flow_check.set_defaults(handler=command_flow_check)
    args = parser.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
