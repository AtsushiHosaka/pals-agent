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
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from pals_agent import general_recipe_lane as lane
from pals_agent import sandbox
from pals_agent.recipe_instantiation import InstantiationRejected
from pals_agent.statement_grammar import StatementRejected, validate_proposition

PROBE_NAME: Final = "pals_probe"


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


def check_formal_statement(formal: str, *, allow_header: bool = False) -> str:
    """The closed proposition for a statement, validated against the allow-list grammar.

    ``allow_header`` is only for catalog cards (``example``/``theorem`` headers, a trailing
    ``:= by …`` placeholder and an ``open``/``universe`` preamble); a model-written or learner
    statement must already be a bare proposition.  Nothing but the grammar decides acceptance.
    """
    text = formal
    if allow_header:
        preamble, text = split_preamble(formal)
        _check_preamble(preamble)
        text = closed_statement(text)
    return validate_proposition(text)


_PREAMBLE_NAME = re.compile(r"[A-Za-z_][\w'.]*\Z")


def _check_preamble(preamble: str) -> None:
    """Only ``open``/``universe`` lines whose arguments are plain names outside code namespaces."""
    for line in preamble.splitlines():
        words = line.split()
        if not words or words[0] not in {"open", "universe"}:
            raise StatementRejected("preamble is not open/universe")
        for word in words[1:]:
            if word in {"scoped", "in"} and words[0] == "open" and word == "scoped":
                continue
            if _PREAMBLE_NAME.match(word) is None:
                raise StatementRejected("preamble argument is not a plain name")
            validate_proposition(word)  # reserved words and code namespaces are refused


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
    call: str | None = None
    tactic: str | None = None  # the tactic text of a portfolio attempt (for the clean re-check)


def build_unified(
    request: str,
    recipes: list[lane.PoolRecipe],
    portfolio: tuple[Tactic, ...] = PORTFOLIO,
    *,
    allow_header: bool = False,
) -> tuple[str, str, list[Attempt], lane.LaneSource | None]:
    proposition = check_formal_statement(request, allow_header=allow_header)
    preamble = split_preamble(request)[0] if allow_header else ""
    if preamble:
        recipes = []  # Recipes are compiled without the card's `open`/`universe` context
    attempts: list[Attempt] = []
    parts = [
        f"import Mathlib\n\ntheorem {PROBE_NAME} : True := trivial\n#print axioms {PROBE_NAME}\n",
        lane.AUTO_OPTIONS,
    ]
    if preamble:
        parts.append(preamble + "\n")
    parts.append(lane.reference_probe(proposition))
    source = None
    if recipes:
        try:
            source, _ = lane.build_source(recipes, proposition)
        except InstantiationRejected:
            source = None  # e.g. a statement outside the Recipe grammar: portfolio only
    if source is not None:
        parts.append(source.body)
        attempts += [
            Attempt("recipe", a.recipe.recipe_id, a.instance_name) for a in source.attempts
        ]
    for k, tactic in enumerate(portfolio):
        decl = f"_pals_portfolio_{k}"
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
    reason: str | None = None  # "rss" | "cpu" when the watchdog killed the process


def run_stream(
    runner: lane.LeanRunner, source: str, *, budget_s: float, stop: Any = None
) -> StreamResult:
    """Run Lean on a pty (line-buffered output); ``stop(line)`` True ends the process early."""
    master, slave = pty.openpty()
    with sandbox.new_scratch("pals-pf-") as directory:
        path = Path(directory) / "Portfolio.lean"
        path.write_text(source)
        t0 = time.monotonic()
        isolation = runner.isolation()
        proc = subprocess.Popen(
            sandbox.command([runner.lean_binary, str(path)], isolation, directory),
            stdout=slave,
            stderr=slave,
            **sandbox.popen_kwargs(isolation, directory, cpu_seconds=int(budget_s) + 5),
        )
        os.close(slave)
        dog = sandbox.Watchdog(
            proc, rss_bytes=sandbox.default_rss_bytes(), cpu_seconds=budget_s + 5
        )
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
        dog.stop()
        if killed or proc.poll() is None:
            sandbox.kill_group(proc)
        proc.wait()
        os.close(master)
    return StreamResult("\n".join(out), events, killed, time.monotonic() - t0, dog.reason)


_AX = re.compile(
    r"'(_?pals_\w+)' (?:depends on axioms: \[([^\]]*)\]|does not depend on any axioms)"
)
_LEMMA = re.compile(r"\[apply\] .*?exact\s+(\(?[\w.'?!]+)")
_CALL = re.compile(r"\[apply\] (?:\(expose_names;\s*)?exact\s+(.+?)\)?\s*$", re.M)


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
    call: str | None = None
    tactic: str | None = None
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
    allow_header: bool = False,
) -> SolveResult:
    try:
        proposition = check_formal_statement(request_formal, allow_header=allow_header)
    except InstantiationRejected as error:
        return SolveResult(
            "miss",
            code="statement_not_plain",
            proposition=None,
            attempts=[Attempt("none", str(error), "-")],
        )
    ranked = lane.rank_candidates(proposition, pool)[:candidates] if use_recipes else []
    text, proposition, attempts, source = build_unified(
        request_formal, [r for _, r in ranked], portfolio, allow_header=allow_header
    )
    by_decl = {a.decl: a for a in attempts}
    recipe_by_decl = {a.instance_name: a for a in source.attempts} if source else {}
    first_ok: list[str] = []
    seen_lines: list[str] = []
    pending_error = [False]

    def stop(line: str) -> bool:
        seen_lines.append(line)
        if lane._ERROR_LINE.search(line):
            pending_error[0] = True
        match = _AX.search(line)
        if not match:
            return False
        had_error, pending_error[0] = pending_error[0], False
        name = match.group(1)
        if name not in by_decl or name == PROBE_NAME:
            return False
        if had_error or _verdict(match.group(2)) is not None:
            return False
        # the Recipe back-check runs BEFORE stopping, so a failed back-check cannot end the run
        # and leave the portfolio un-run
        if (
            name in recipe_by_decl
            and source is not None
            and lane.back_check(source, recipe_by_decl[name], "\n".join(seen_lines)) is not None
        ):
            return False
        first_ok.append(name)
        return stop_on_accept

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
        self._runner, self._source = runner, worker_source.resolve()
        self._start()

    def alive(self) -> bool:
        return self.proc.poll() is None

    def restart(self) -> None:
        """Replace a killed or stuck worker (the Mathlib import is paid again)."""
        if self.alive():
            self.proc.kill()
        self.proc.wait()
        self._dir.cleanup()
        self._start()

    def _start(self) -> None:
        runner, worker_source = self._runner, self._source
        self._dir = sandbox.new_scratch("pals-warm-")
        isolation = sandbox.Isolation(
            runner.lean_binary, runner.lean_path, extra_read=(str(worker_source),)
        )
        self.proc = subprocess.Popen(
            sandbox.command(
                [runner.lean_binary, "--run", str(worker_source)], isolation, self._dir.name
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            **sandbox.popen_kwargs(isolation, self._dir.name),
        )
        t0 = time.monotonic()
        self._buf = b""
        self._dog = sandbox.Watchdog(
            self.proc,
            rss_bytes=sandbox.default_rss_bytes(),
            cpu_seconds=sandbox.default_worker_cpu_seconds(),
        )
        if self._read_line(time.monotonic() + 120.0) != "PALS_READY":
            raise RuntimeError("warm worker did not start")
        self.startup_s = time.monotonic() - t0
        self._counter = 0

    def check(self, source: str, *, timeout_s: float = 60.0) -> tuple[str, float]:
        """Elaborate ``source`` in the warm environment.

        A timeout or a dead worker kills and reaps the process (``alive()`` becomes False, the
        caller restarts it), so output of one request can never be read as the next one's.
        """
        path = self._write(source, "lean")
        return self._request(str(path), path, timeout_s)

    def check_statement(
        self, term: str, opens: str = "", *, mode: str = "CHECK", timeout_s: float = 30.0
    ) -> tuple[bool, str]:
        """Parse-only statement check inside the worker (never elaborates the statement).

        Returns ``(accepted, reason)``.  ``mode="KINDS"`` returns the syntax kinds instead.
        """
        if "\n" in term or "\n" in opens:
            return False, "multi-line input"
        path = self._write(opens + "\n" + term + "\n", "txt")
        out, _ = self._request(f"{mode} {path}", path, timeout_s)
        if mode == "KINDS":
            return True, out
        if "PALS_CHECK_OK" in out and "PALS_CHECK_REFUSED" not in out:
            return True, ""
        reason = next((ln for ln in out.splitlines() if "PALS_CHECK_REFUSED" in ln), "no verdict")
        return False, reason.replace("PALS_CHECK_REFUSED", "").strip()

    def _write(self, text: str, suffix: str) -> Path:
        self._counter += 1
        path = Path(self._dir.name) / f"req{self._counter}.{suffix}"
        path.write_text(text)
        return path

    def _request(self, line: str, path: Path, timeout_s: float) -> tuple[str, float]:
        assert self.proc.stdin is not None
        t0 = time.monotonic()
        try:
            self.proc.stdin.write((line + "\n").encode())
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            self._reap()
            raise RuntimeError("warm worker is not running") from error
        out: list[str] = []
        done = f"PALS_DONE {path}"
        deadline = t0 + timeout_s
        while True:
            reply = self._read_line(deadline)
            if reply is None:
                self._reap()
                raise TimeoutError("warm worker timeout")
            if reply == done:
                break
            out.append(reply + "\n")
        return "".join(out), time.monotonic() - t0

    def _read_line(self, deadline: float) -> str | None:
        """One output line, or None at the deadline; a dead worker raises RuntimeError."""
        assert self.proc.stdout is not None
        fd = self.proc.stdout.fileno()
        while b"\n" not in self._buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            ready, _, _ = select.select([fd], [], [], min(0.2, remaining))
            if not ready:
                if self.proc.poll() is not None:
                    self._reap()
                    raise RuntimeError(f"warm worker exited ({self._dog.reason or 'died'})")
                continue
            data = os.read(fd, 65536)
            if not data:
                self._reap()
                raise RuntimeError(f"warm worker exited ({self._dog.reason or 'died'})")
            self._buf += data
        raw, self._buf = self._buf.split(b"\n", 1)
        return raw.decode(errors="replace")

    def killed_reason(self) -> str | None:
        """ "rss" or "cpu" when the watchdog killed the worker (it must then be replaced)."""
        return self._dog.reason

    def _reap(self) -> None:
        self._dog.stop()
        sandbox.kill_group(self.proc)

    def prewarm_search(self) -> float:
        """Build the ``exact?`` index once (seconds), so no request pays for it."""
        t0 = time.monotonic()
        self.check(
            "theorem pals_prewarm : ∀ n : ℕ, n ≤ n + 1 := by\n  intros; exact?\n", timeout_s=120.0
        )
        return time.monotonic() - t0

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
    deadline: float | None = None,
    allow_header: bool = False,
    bound_stage: bool = False,
) -> SolveResult:
    """Staged first-success run on a warm worker: Recipe candidates, then each tactic in turn.

    ``deadline`` (``time.monotonic()``) is a hard budget: no attempt is started after it and the
    running one is killed by the worker timeout.
    """
    t0 = time.monotonic()
    try:
        proposition = check_formal_statement(request_formal, allow_header=allow_header)
    except InstantiationRejected as error:
        return SolveResult(
            "miss", code="statement_not_plain", attempts=[Attempt("none", str(error), "-")]
        )
    preamble = split_preamble(request_formal)[0] if allow_header else ""
    ranked_all = [] if preamble else lane.rank_candidates(proposition, pool)
    ranked = ranked_all[:candidates]
    prefix = lane.AUTO_OPTIONS + (preamble + "\n" if preamble else "")
    result = SolveResult("miss", proposition=proposition, code="no_attempt_succeeded")
    # the request's statement alone must elaborate to a closed Prop (autoImplicit is off)
    ref_out, _ = worker.check(prefix + lane.reference_probe(proposition), timeout_s=20.0)
    if "PALS_REF_OK=true" not in ref_out or lane._ERROR_LINE.search(ref_out):
        result.code = "statement_not_elaborated"
        result.total_s = time.monotonic() - t0
        return result

    def recipe_stage(with_bound: bool) -> bool:
        """Compile the Recipe candidates; True when one is accepted (result is filled)."""
        stage = ranked_all[: lane.BOUND_CANDIDATES] if with_bound else ranked
        try:
            source, _ = lane.build_source([r for _, r in stage], proposition, with_bound=with_bound)
        except InstantiationRejected:
            return False  # not a plain Recipe instance request (e.g. outside the Recipe grammar)
        if not source.attempts:
            return False
        try:
            output, seconds = worker.check(
                source.source.split("\n\n", 1)[1],
                timeout_s=60.0 if deadline is None else max(1.0, deadline - time.monotonic()),
            )
        except TimeoutError:
            result.code = "budget_exhausted"
            return False
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
                return True
        return False

    if recipe_stage(False):
        return result
    for k, tactic in enumerate(portfolio):
        if deadline is not None and time.monotonic() >= deadline:
            result.code = "budget_exhausted"
            break
        decl = f"_pals_portfolio_{k}"
        text = prefix + (
            f"set_option maxHeartbeats {tactic.heartbeats} in\n"
            f"theorem {decl} : {proposition} := by\n  {tactic.text}\n#print axioms {decl}\n"
        )
        remaining = 60.0 if deadline is None else max(0.5, deadline - time.monotonic())
        try:
            output, seconds = worker.check(text, timeout_s=min(60.0, remaining))
        except TimeoutError:
            result.code = "budget_exhausted"
            break
        match = _AX.search(output)
        attempt = Attempt("portfolio", tactic.name, decl)
        attempt.tactic = tactic.text
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
            calls = _CALL.findall(output)
            attempt.call = calls[-1].strip() if tactic.name == "exact?" and calls else None
        result.attempts.append(attempt)
        if attempt.verdict is None:
            result.outcome, result.route, result.by, result.code = (
                "answered",
                "portfolio",
                tactic.name,
                None,
            )
            result.lemma = attempt.lemma
            result.call = attempt.call
            result.tactic = attempt.tactic
            result.answered_s = attempt.at_s
            break
    # last: the many-alternative bound-argument closers (the costliest stage)
    if (
        bound_stage
        and result.outcome != "answered"
        and ranked_all
        and ranked_all[0][0] >= lane.BOUND_MIN_SCORE
        and result.code != "budget_exhausted"
        and (deadline is None or time.monotonic() < deadline)
    ):
        recipe_stage(True)
    result.total_s = time.monotonic() - t0
    return result


# --- values: Lean normalises, the answer is re-proved as a closed statement ----------------------
VALUE_TYPES: Final = frozenset({"ℕ", "ℤ", "ℚ", "ℝ"})
VALUE_TACTICS: Final = (
    "norm_num <;> rfl",
    "simp <;> rfl",
    "norm_num [Matrix.det_fin_two, Nat.choose, Nat.factorial, Finset.sum_range_succ,"
    " integral_pow] <;> rfl",
)
_LITERAL = re.compile(r"^-?\d+(?:\s*/\s*\d+)?$")


def _first_term(text: str) -> str | None:
    """The first argument of ``Exists.intro`` in printed output."""
    text = text.lstrip()
    if not text:
        return None
    if text[0] != "(":
        return text.split()[0]
    depth = 0
    for index, ch in enumerate(text):
        depth += ch == "("
        depth -= ch == ")"
        if depth == 0:
            return text[: index + 1]
    return None


def derive_value(
    worker: WarmWorker, expression: str, type_symbol: str, *, deadline: float | None = None
) -> str | None:
    """Ask Lean for the value of a closed expression by normalisation (no ``#eval``).

    ``∃ v : T, e = v`` is proved by ``norm_num``/``simp`` rewriting ``e`` and closing ``n = ?v`` by
    ``rfl``; the value is read from the printed witness and accepted only if it is a numeral or a
    fraction of numerals different from the expression itself.  The caller re-proves ``e = v`` as
    a closed statement, so a wrong reading can only make that proof fail.
    """
    if type_symbol not in VALUE_TYPES:
        return None
    expr = validate_proposition(expression)
    for tactic in VALUE_TACTICS:
        if deadline is not None and time.monotonic() >= deadline:
            return None
        src = (
            lane.AUTO_OPTIONS
            + "set_option maxHeartbeats 30000 in\n"
            + f"theorem _pals_value : ∃ v : {type_symbol}, {expr} = v := ⟨_, by {tactic}⟩\n"
            + "set_option pp.proofs true in\n#print _pals_value\n#print axioms _pals_value\n"
        )
        try:
            out, _ = worker.check(
                src,
                timeout_s=15.0
                if deadline is None
                else max(1.0, min(15.0, deadline - time.monotonic())),
            )
        except (TimeoutError, RuntimeError):
            return None
        if lane._ERROR_LINE.search(out):
            continue
        match = re.search(r"'_pals_value' (?:depends on axioms: \[([^\]]*)\]|does not depend)", out)
        if match is None or "sorryAx" in (match.group(1) or ""):
            continue
        marker = out.find("Exists.intro")
        term = _first_term(out[marker + len("Exists.intro") :]) if marker >= 0 else None
        if term is None:
            continue
        value = term.strip()
        if value.startswith("(") and value.endswith(")"):
            value = value[1:-1].strip()
        if _LITERAL.match(value) and "".join(value.split()) != "".join(expr.split()):
            return value
    return None


def closed_value_statement(expression: str, value: str, type_symbol: str) -> str:
    return validate_proposition(f"({expression}) = (({value}) : {type_symbol})")


# --- clean re-check of an accepted answer in a FRESH verifier worker -----------------------------
FINAL_NAME: Final = "_pals_final"


def replay_tactic(solved: SolveResult) -> str | None:
    """The tactic text to replay for an accepted portfolio answer (no search is repeated).

    A closer from the fixed portfolio is replayed as is; an ``exact?`` answer is replayed as the
    term it found (``intros; expose_names; exact <call>``), so the verifier never searches.
    """
    if solved.route != "portfolio" or not solved.by:
        return None
    if solved.by == "exact?":
        call = (solved.call or "").strip()
        if not call or any(ch in call for ch in "\n;"):
            return None
        validate_proposition(call)  # the recorded term must itself be a plain term
        return f"intros; expose_names; exact {call}"
    known = {t.name: t.text for t in PORTFOLIO}
    return known.get(solved.by)


def recheck(
    verifier: WarmWorker, statement: str, solved: SolveResult, *, preamble: str = ""
) -> tuple[bool, str]:
    """Re-prove ``statement`` in a worker that never ran the search for it.

    The verdict of a model- or learner-written statement is this one: a fresh process, the
    statement elaborated once under ``autoImplicit false`` with the standard checks (reference
    probe, no logged error, standard axioms only).  Tampering inside the search worker cannot
    change it.
    """
    tactic = replay_tactic(solved)
    if tactic is None:
        return False, "nothing_to_replay"
    text = (
        lane.AUTO_OPTIONS
        + (preamble + "\n" if preamble else "")
        + lane.reference_probe(statement)
        + "set_option maxHeartbeats 100000 in\n"
        + f"theorem {FINAL_NAME} : {statement} := by\n  {tactic}\n#print axioms {FINAL_NAME}\n"
    )
    try:
        output, _ = verifier.check(text, timeout_s=30.0)
    except (TimeoutError, RuntimeError):
        return False, "verifier_unavailable"
    if "PALS_REF_OK=true" not in output:
        return False, "statement_not_elaborated"
    match = re.search(
        rf"'{FINAL_NAME}' (?:depends on axioms: \[([^\]]*)\]|does not depend)", output
    )
    if match is None:
        return False, "no_verdict"
    errors_after_ref = [ln for ln in output.splitlines() if lane._ERROR_LINE.search(ln)]
    if errors_after_ref:
        return False, "error_logged"
    axioms = {a.strip() for a in (match.group(1) or "").split(",") if a.strip()}
    if "sorryAx" in axioms or not axioms <= lane.ALLOWED_AXIOMS:
        return False, "nonstandard_axiom"
    return True, ""
