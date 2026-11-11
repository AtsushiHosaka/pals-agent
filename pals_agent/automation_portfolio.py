"""Mathlib as the general-Recipe library: a fixed automation portfolio behind the Recipe lane.

For a request's formal statement ``P`` one Lean process elaborates, in order,

  (a) the general-Recipe candidates of ``general_recipe_lane`` (same templates and back-checks),
  (b) a fixed portfolio of automation, each as its own declaration ``theorem pals_portfolio_k : P``
      with its own deterministic time limit (``maxHeartbeats``), cheap tactics first, and
  (c) Mathlib lemma search (``exact?``) last, because its first use builds an index (seconds).

The declared type is always ``P`` and nothing here changes it; a candidate is accepted only if its
``#print axioms`` lists the standard three (``sorryAx`` means the attempt failed).  The accepted
lemma name of ``exact?`` is recorded: it is the general theorem an explanation should cite.

Output is read through a pty so each ``#print axioms`` arrives as soon as Lean finishes that
declaration; ``stop_on_accept`` kills the process at the first accepted attempt.  Model-free.
"""

from __future__ import annotations

import hashlib
import os
import pty
import re
import select
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from pals_agent import general_recipe_lane as lane
from pals_agent.recipe_instantiation import InstantiationRejected

PROBE_NAME: Final = "pals_probe"
_FORBIDDEN_WORDS = re.compile(
    r"(?<![\w'.])(sorry|admit|axiom|native_decide|theorem|lemma|example|def|instance|open|"
    r"namespace|section|end|import|macro|syntax|notation|attribute)(?![\w'.])|#|--|/-|-/|\"|;|@\["
)


@dataclass(frozen=True, slots=True)
class Tactic:
    name: str
    text: str
    heartbeats: int = 30000


# Chosen from what the pinned Mathlib (8b62164, Lean 4.32.0-rc1) provides and ordered by cost.
# `intros` first so ∀/→ goals reach the automation; no hint terms that would need bound names.
PORTFOLIO: Final = (
    Tactic("fun_prop", "intros; fun_prop"),
    Tactic("positivity", "intros; positivity"),
    Tactic("norm_num", "intros; norm_num"),
    Tactic("simp", "intros; simp"),
    Tactic("ring", "intros; ring"),
    Tactic("omega", "intros; omega"),
    Tactic("decide", "intros; decide"),
    Tactic("linarith", "intros; linarith"),
    Tactic("tauto", "intros; tauto"),
    Tactic("gcongr", "intros; gcongr"),
    Tactic("bound", "intros; bound"),
    Tactic("field_simp_ring", "intros; field_simp <;> ring"),
    Tactic(
        "constructor_simp", "intros; constructor <;> (intros; first | simp | positivity | linarith)"
    ),
    Tactic("nlinarith", "intros; nlinarith"),
    Tactic("continuity", "intros; continuity"),
    Tactic("measurability", "intros; measurability"),
    Tactic("simp_all", "intros; simp_all"),
    Tactic("induction_simp_all", "intro n; induction n <;> simp_all"),
    Tactic("aesop", "intros; aesop"),
    Tactic("grind", "intros; grind"),
    Tactic("exact?", "intros; exact?", 100000),
)


_PREAMBLE_COMMAND = re.compile(
    r"(?<![\w'.])(open|universe)((?:\s+(?:scoped|in|[\w.]+))+?)(?=\s+(?:open|universe|theorem|lemma|example)\b)"
)


def split_preamble(formal: str) -> tuple[str, str]:
    """Leading ``open``/``universe`` commands of a full-file statement (scheme cards), if any.

    Only those two commands with identifier arguments are accepted; anything else before the
    declaration is left in place so the statement check rejects it.
    """
    text = " ".join(formal.split())
    text = re.sub(r"^import Mathlib\s*", "", text)
    lines: list[str] = []
    while True:
        match = _PREAMBLE_COMMAND.match(text)
        if match is None:
            break
        lines.append(f"{match.group(1)}{match.group(2)}")
        text = text[match.end() :].strip()
    return "\n".join(lines), text


def check_formal_statement(formal: str) -> str:
    """The closed proposition for a trusted-shape formal statement; no commands, no sorry."""
    text = closed_statement(split_preamble(formal)[1])
    if not text or len(text) > 4000 or "\x00" in text:
        raise InstantiationRejected("formal statement is empty or too long")
    has_let = re.search(r"(?<![\w'.])let(?![\w'.])", text) is not None
    probe = text.replace(":=", "").replace(";", "") if has_let else text
    if _FORBIDDEN_WORDS.search(probe) or ":=" in probe or (not has_let and ";" in text):
        raise InstantiationRejected("formal statement contains command or tactic syntax")
    depth = 0
    for ch in text:
        depth += ch in "([{⟨⦃"
        depth -= ch in ")]}⟩⦄"
        if depth < 0:
            raise InstantiationRejected("unbalanced brackets")
    if depth:
        raise InstantiationRejected("unbalanced brackets")
    return text


def closed_statement(formal: str) -> str:
    """``example``/``theorem NAME`` headers (with a trailing ``:= by …``) -> closed proposition."""
    text = " ".join(formal.split())
    for marker in (":= by", ":= sorry", ":=by"):
        cut = text.rfind(marker)
        if cut > 0 and text.startswith(("example", "theorem", "lemma")):
            text = text[:cut].strip()
            break
    text = re.sub(r"^(theorem|lemma)\s+[^\s:({\[⦃]+", "example", text)
    return lane.closed_proposition(text)


@dataclass(slots=True)
class Attempt:
    kind: str  # "recipe" | "portfolio"
    name: str  # recipe id or tactic name
    decl: str
    verdict: str | None = None  # None = accepted
    at_s: float | None = None  # seconds since process start when its verdict arrived
    lemma: str | None = None


def build_unified(
    request: str, recipes: list[lane.PoolRecipe], portfolio: tuple[Tactic, ...] = PORTFOLIO
) -> tuple[str, str, list[Attempt], lane.LaneSource | None]:
    proposition = check_formal_statement(request)
    preamble = split_preamble(request)[0]
    if preamble:
        recipes = []  # Recipes are compiled without the card's `open`/`universe` context
    attempts: list[Attempt] = []
    parts = [
        f"import Mathlib\n\ntheorem {PROBE_NAME} : True := trivial\n#print axioms {PROBE_NAME}\n"
    ]
    if preamble:
        parts.append(preamble + "\n")
    source = None
    if recipes:
        try:
            source, _ = lane.build_source(recipes, proposition)
        except InstantiationRejected:
            source = None  # e.g. a `let` statement: never a Recipe instance, portfolio only
    if source is not None:
        body = source.source.split("\n\n", 1)[1]  # drop the import header
        parts.append(body)
        attempts += [
            Attempt("recipe", a.recipe.recipe_id, a.instance_name) for a in source.attempts
        ]
    for k, tactic in enumerate(portfolio):
        decl = f"pals_portfolio_{k}"
        parts.append(
            f"set_option maxHeartbeats {tactic.heartbeats} in\n"
            f"theorem {decl} : {proposition} := by\n  {tactic.text}\n#print axioms {decl}\n"
        )
        attempts.append(Attempt("portfolio", tactic.name, decl))
    text = "\n".join(parts)
    return text, proposition, attempts, source


@dataclass(slots=True)
class StreamResult:
    output: str
    events: list[tuple[float, str]]
    killed: bool
    seconds: float


def run_stream(
    runner: lane.LeanRunner, source: str, *, budget_s: float, stop: Any = None
) -> StreamResult:
    """Run Lean on a pty (line-buffered output); ``stop(line)`` True ends the process early."""
    master, slave = pty.openpty()
    env = {
        "PATH": os.environ.get("PATH", ""),
        "LEAN_PATH": runner.lean_path,
        "HOME": os.environ.get("HOME", ""),
    }
    with tempfile.TemporaryDirectory(prefix="pals-pf-") as directory:
        path = Path(directory) / "Portfolio.lean"
        path.write_text(source)
        t0 = time.monotonic()
        proc = subprocess.Popen(
            [runner.lean_binary, str(path)],
            stdout=slave,
            stderr=slave,
            env=env,
            close_fds=True,
            start_new_session=True,
        )
        os.close(slave)
        buf, out, events, killed = b"", [], [], False
        while True:
            remaining = budget_s - (time.monotonic() - t0)
            if remaining <= 0:
                killed = True
                break
            ready, _, _ = select.select([master], [], [], min(0.2, remaining))
            if ready:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    break
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    line = raw.decode(errors="replace").rstrip("\r")
                    out.append(line)
                    events.append((time.monotonic() - t0, line))
                    if stop is not None and stop(line):
                        killed = True
                        break
                if killed:
                    break
            elif proc.poll() is not None:
                break
        if killed or proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                proc.kill()
        proc.wait()
        os.close(master)
    return StreamResult("\n".join(out), events, killed, time.monotonic() - t0)


_AX = re.compile(r"'(pals_\w+)' (?:depends on axioms: \[([^\]]*)\]|does not depend on any axioms)")
_LEMMA = re.compile(r"\[apply\] .*?exact\s+(\(?[\w.'?!]+)")


def _verdict(axioms: str | None) -> str | None:
    items = {a.strip() for a in axioms.split(",")} if axioms else set()
    if "sorryAx" in items:
        return "failed"
    if not items <= lane.ALLOWED_AXIOMS:
        return "nonstandard_axiom"
    return None


@dataclass(slots=True)
class SolveResult:
    outcome: str  # "answered" | "miss"
    route: str | None = None  # recipe | portfolio
    by: str | None = None
    lemma: str | None = None
    proposition: str | None = None
    source_sha256: str | None = None
    model_calls: int = 0
    startup_s: float | None = None
    answered_s: float | None = None
    total_s: float = 0.0
    attempts: list[Attempt] = field(default_factory=list)
    code: str | None = None


def solve(
    request_formal: str,
    pool: list[lane.PoolRecipe],
    runner: lane.LeanRunner,
    *,
    candidates: int = lane.DEFAULT_CANDIDATES,
    portfolio: tuple[Tactic, ...] = PORTFOLIO,
    budget_s: float = 60.0,
    stop_on_accept: bool = True,
    use_recipes: bool = True,
) -> SolveResult:
    try:
        proposition = check_formal_statement(request_formal)
    except InstantiationRejected as error:
        return SolveResult(
            "miss",
            code="statement_not_plain",
            proposition=None,
            attempts=[Attempt("none", str(error), "-")],
        )
    ranked = lane.rank_candidates(proposition, pool)[:candidates] if use_recipes else []
    text, proposition, attempts, source = build_unified(
        request_formal, [r for _, r in ranked], portfolio
    )
    by_decl = {a.decl: a for a in attempts}
    first_ok: list[str] = []

    pending_error = [False]

    def stop(line: str) -> bool:
        if lane._ERROR_LINE.search(line):
            pending_error[0] = True
        match = _AX.search(line)
        if not match:
            return False
        had_error, pending_error[0] = pending_error[0], False
        if match.group(1) not in by_decl or match.group(1) == PROBE_NAME:
            return False
        if not had_error and _verdict(match.group(2)) is None:
            first_ok.append(match.group(1))
            return stop_on_accept
        return False

    res = run_stream(runner, text, budget_s=budget_s, stop=stop)
    result = SolveResult(
        "miss",
        proposition=proposition,
        total_s=res.seconds,
        attempts=attempts,
        code="no_attempt_succeeded",
    )
    probe_at = None
    # per-declaration arrival times and verdicts (the probe line marks the end of startup)
    full = res.output
    errored = lane.errored_declarations(full)
    for at, line in res.events:
        for match in _AX.finditer(line):
            name = match.group(1)
            if name == PROBE_NAME:
                probe_at = at
                continue
            attempt = by_decl.get(name)
            if attempt is None or attempt.at_s is not None:
                continue
            attempt.at_s = round(at, 3)
            attempt.verdict = "error_logged" if name in errored else _verdict(match.group(2))
    result.startup_s = round(probe_at, 3) if probe_at is not None else None
    if "Try this" in full:
        found = _LEMMA.findall(full)
        for attempt in attempts:
            if attempt.name == "exact?" and attempt.verdict is None and found:
                attempt.lemma = found[-1].strip().lstrip("(")
    for attempt in attempts:
        if attempt.verdict is None and attempt.at_s is not None:
            if attempt.kind == "recipe" and source is not None:
                recipe_attempt = next(a for a in source.attempts if a.instance_name == attempt.decl)
                if lane.back_check(source, recipe_attempt, full) is not None:
                    attempt.verdict = "backcheck_failed"
                    continue
            result.outcome, result.route, result.by = "answered", attempt.kind, attempt.name
            result.lemma = attempt.lemma
            result.answered_s = attempt.at_s
            result.code = None
            result.source_sha256 = hashlib.sha256(text.encode()).hexdigest()
            break
    return result


# --- long-lived worker (Mathlib imported once) --------------------------------------------------
class WarmWorker:
    """Drives ``scripts/eval/warm_worker.lean``: a process that imports Mathlib once and then
    elaborates one command file per request from the same immutable environment.

    This is a measurement harness, not a replacement for the verifier: it has no sandbox, no
    resource limits and no policy checks.  It shows what per-request time is left once the Lean
    start-up is paid up front.
    """

    def __init__(self, runner: lane.LeanRunner, worker_source: Path) -> None:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "LEAN_PATH": runner.lean_path,
            "HOME": os.environ.get("HOME", ""),
        }
        t0 = time.monotonic()
        self.proc = subprocess.Popen(
            [runner.lean_binary, "--run", str(worker_source)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            bufsize=1,
        )
        assert self.proc.stdout is not None
        line = self.proc.stdout.readline().strip()
        if line != "PALS_READY":
            raise RuntimeError("warm worker did not start")
        self.startup_s = time.monotonic() - t0
        self._dir = tempfile.TemporaryDirectory(prefix="pals-warm-")

    def check(self, source: str, *, timeout_s: float = 60.0) -> tuple[str, float]:
        assert self.proc.stdin is not None and self.proc.stdout is not None
        path = Path(self._dir.name) / "req.lean"
        path.write_text(source)
        t0 = time.monotonic()
        self.proc.stdin.write(str(path) + "\n")
        self.proc.stdin.flush()
        out: list[str] = []
        while True:
            if time.monotonic() - t0 > timeout_s:
                self.proc.kill()
                raise TimeoutError("warm worker timeout")
            line = self.proc.stdout.readline()
            if not line or line.strip() == "PALS_DONE":
                break
            out.append(line)
        return "".join(out), time.monotonic() - t0

    def close(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.close()
        self.proc.wait(timeout=10)
        self._dir.cleanup()


def solve_warm(
    request_formal: str,
    pool: list[lane.PoolRecipe],
    worker: WarmWorker,
    *,
    candidates: int = lane.DEFAULT_CANDIDATES,
    portfolio: tuple[Tactic, ...] = PORTFOLIO,
) -> SolveResult:
    """Staged first-success run on a warm worker: Recipe candidates, then each tactic in turn."""
    t0 = time.monotonic()
    try:
        proposition = check_formal_statement(request_formal)
    except InstantiationRejected as error:
        return SolveResult(
            "miss", code="statement_not_plain", attempts=[Attempt("none", str(error), "-")]
        )
    preamble = split_preamble(request_formal)[0]
    ranked = [] if preamble else lane.rank_candidates(proposition, pool)[:candidates]
    prefix = preamble + "\n" if preamble else ""
    result = SolveResult("miss", proposition=proposition, code="no_attempt_succeeded")
    source = None
    if ranked:
        try:
            source, _ = lane.build_source([r for _, r in ranked], proposition)
        except InstantiationRejected:
            source = None  # not a plain Recipe instance request (e.g. a `let` statement)
    if source is not None:
        body = source.source.split("\n\n", 1)[1]
        output, seconds = worker.check(body)
        for recipe_attempt in source.attempts:
            attempt = Attempt(
                "recipe", recipe_attempt.recipe.recipe_id, recipe_attempt.instance_name
            )
            attempt.at_s = round(time.monotonic() - t0, 3)
            attempt.verdict = lane.back_check(source, recipe_attempt, output)
            result.attempts.append(attempt)
            if attempt.verdict is None:
                result.outcome, result.route, result.by, result.code = (
                    "answered",
                    "recipe",
                    attempt.name,
                    None,
                )
                result.answered_s = round(time.monotonic() - t0, 3)
                result.total_s = time.monotonic() - t0
                return result
    for k, tactic in enumerate(portfolio):
        decl = f"pals_portfolio_{k}"
        text = prefix + (
            f"set_option maxHeartbeats {tactic.heartbeats} in\n"
            f"theorem {decl} : {proposition} := by\n  {tactic.text}\n#print axioms {decl}\n"
        )
        output, seconds = worker.check(text)
        match = _AX.search(output)
        attempt = Attempt("portfolio", tactic.name, decl)
        attempt.at_s = round(time.monotonic() - t0, 3)
        errored = lane.errored_declarations(output)
        attempt.verdict = (
            "failed"
            if not match
            else "error_logged"
            if decl in errored
            else _verdict(match.group(2))
        )
        if attempt.verdict is None:
            found = _LEMMA.findall(output)
            attempt.lemma = (
                found[-1].strip().lstrip("(") if tactic.name == "exact?" and found else None
            )
        result.attempts.append(attempt)
        if attempt.verdict is None:
            result.outcome, result.route, result.by, result.code = (
                "answered",
                "portfolio",
                tactic.name,
                None,
            )
            result.lemma = attempt.lemma
            result.answered_s = attempt.at_s
            break
    result.total_s = time.monotonic() - t0
    return result
