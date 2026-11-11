"""The stepwise Draft-Sketch-Prove lane, scripted models and Lean (no model, no Lean)."""

import re
import threading
import time
from collections.abc import Callable

import pytest

from pals_agent import dsp_stepwise as dsp
from pals_agent.models import Diagnostic, VerificationResult

FORMAL = "theorem t (a b c : ℝ) (hab : a ≤ b) (hbc : b ≤ c) : a ≤ c"
SKELETON = (
    "-- PALS-PROOF-BODY\n"
    "  have h1 : a ≤ b := by sorry\n"
    "  have h2 : b ≤ c := by\n"
    "    sorry\n"
    "  exact le_trans h1 h2\n"
)
CANARY = "RAWLEANTEXT-xyzzy"
_STEP = re.compile(r"^  have (\w+) [^\n]*:= by\n((?:    [^\n]*\n?)*)", re.MULTILINE)


def result(ok: bool, line: int = 5) -> VerificationResult:
    diags = (
        []
        if ok
        else [Diagnostic(severity="error", code="lean.error", line=line, column=2, message=CANARY)]
    )
    return VerificationResult(success=ok, diagnostics=diags, stdout="", stderr="", elapsed_ms=1)


class FakeLean:
    """A source is accepted when no step body holds BAD, and an automation body only for steps in
    ``auto_ok``. ``sorry`` bodies are accepted (a skeleton check); ``skeleton_ok`` gates that."""

    def __init__(
        self, auto_ok: set[str] = frozenset(), skeleton_ok: Callable[[str], bool] | None = None
    ):
        self.auto_ok = set(auto_ok)
        self.skeleton_ok = skeleton_ok or (lambda code: True)
        self.sources: list[str] = []
        self.lock = threading.Lock()

    def __call__(self, code: str) -> VerificationResult:
        with self.lock:
            self.sources.append(code)
        if not self.skeleton_ok(code):
            return result(False)
        for name, body in _STEP.findall(code):
            if "BAD" in body:
                return result(False)
            if "first |" in body and name not in self.auto_ok:
                return result(False)
        return result(True)


def lane(model: Callable[[str, str], str], lean: FakeLean, **kw) -> dsp.StepwiseLane:
    return dsp.StepwiseLane(
        statement="Show a ≤ c.", formal_statement=FORMAL, call_model=model, verify=lean, **kw
    )


class ScriptedModel:
    def __init__(self, script: dict[str, list[str]]):
        self.script = {k: list(v) for k, v in script.items()}
        self.calls: list[tuple[str, str]] = []
        self.lock = threading.Lock()

    def __call__(self, kind: str, prompt: str) -> str:
        with self.lock:
            self.calls.append((kind, prompt))
            queue = self.script[kind]
            return queue.pop(0) if len(queue) > 1 else queue[0]

    def count(self, kind: str) -> int:
        return sum(1 for k, _ in self.calls if k == kind)


def fenced(text: str) -> str:
    return f"```lean\n{text}\n```"


def test_flag_default_off_and_strict(monkeypatch):
    monkeypatch.delenv(dsp.STEPWISE_ENV, raising=False)
    assert dsp.stepwise_enabled() is False
    monkeypatch.setenv(dsp.STEPWISE_ENV, "true")
    assert dsp.stepwise_enabled() is True
    monkeypatch.setenv(dsp.STEPWISE_ENV, "yes")
    with pytest.raises(ValueError):
        dsp.stepwise_enabled()


def test_parse_skeleton_finds_named_steps_and_keeps_the_rest():
    code = dsp.assemble_skeleton(fenced(SKELETON), FORMAL)
    sk = dsp.parse_skeleton(code, FORMAL)
    assert sk is not None
    assert [s.name for s in sk.steps] == ["h1", "h2"]
    assert sk.steps[0].signature.strip() == ": a ≤ b"
    assert "exact le_trans h1 h2" in dsp.render(sk, {})
    assert FORMAL + " := by" in sk.prefix


@pytest.mark.parametrize(
    "body",
    [
        "  exact le_trans hab hbc\n",  # no steps
        "  have h1 : a ≤ b := by sorry\n  have h1 : b ≤ c := by sorry\n  exact h1\n",  # duplicate
        "  have h1 : a ≤ b := by sorry\n  sorry\n",  # sorry outside a step
        "  have h1 : a ≤ b := by exact hab\n  exact le_trans h1 hbc\n",  # no sorry step at all
    ],
)
def test_parse_skeleton_rejects_unusable(body):
    code = dsp.assemble_skeleton(fenced("-- PALS-PROOF-BODY\n" + body), FORMAL)
    assert dsp.parse_skeleton(code, FORMAL) is None


def test_render_fills_only_given_steps():
    sk = dsp.parse_skeleton(dsp.assemble_skeleton(fenced(SKELETON), FORMAL), FORMAL)
    text = dsp.render(sk, {"h1": "exact hab"})
    assert "have h1 : a ≤ b := by\n    exact hab" in text
    assert text.count("sorry") == 1


@pytest.mark.parametrize(
    "proof",
    [
        "sorry",
        "exact hab\nlemma helper : True := trivial",
        "def f := 1\nexact hab",
        "set_option maxHeartbeats 0 in\nexact hab",
        "axiom bad : False\nexact hab",
        "native_decide",
        "",
    ],
)
def test_step_proofs_may_not_add_declarations_or_trust(proof):
    assert dsp.step_proof_rejection(proof) is not None


def test_step_proof_with_local_helper_is_allowed():
    ok = "have key : ∀ x : ℝ, 0 ≤ x ^ 2 := fun x => sq_nonneg x\nexact hab"
    assert dsp.step_proof_rejection(ok) is None


def test_stage0_closes_steps_with_zero_model_calls():
    model = ScriptedModel({"sketch": [fenced(SKELETON)]})
    res = lane(model, FakeLean(auto_ok={"h1", "h2"})).run()
    assert res.lean_code and "sorry" not in res.lean_code
    assert [s.status for s in res.steps] == ["automation", "automation"]
    assert model.count("sketch") == 1 and len(model.calls) == 1
    assert res.counts.model_calls == 1


def test_model_steps_run_in_parallel_and_frozen_steps_are_never_regenerated():
    gate = threading.Barrier(2, timeout=5)

    class Model(ScriptedModel):
        def __call__(self, kind, prompt):
            if kind in {"step:h1", "step:h2"}:
                gate.wait()  # both step calls must be in flight together
            return super().__call__(kind, prompt)

    model = Model(
        {
            "sketch": [fenced(SKELETON)],
            "step:h1": [fenced("exact hab")],
            "step:h2": [fenced("BAD")],
            "repair:h2": [fenced("exact hbc")],
        }
    )
    res = lane(model, FakeLean()).run()
    assert [s.status for s in res.steps] == ["model_first", "model_repair"]
    assert model.count("step:h1") == 1 and model.count("repair:h1") == 0
    assert model.count("repair:h2") == 1
    assert "exact hbc" in res.lean_code and "exact hab" in res.lean_code
    assert "sorry" not in res.lean_code


def test_repair_prompt_never_carries_raw_lean_text():
    model = ScriptedModel(
        {
            "sketch": [fenced(SKELETON)],
            "step:h1": [fenced("exact hab")],
            "step:h2": [fenced("BAD")],
            "repair:h2": [fenced("exact hbc")],
        }
    )
    lane(model, FakeLean()).run()
    repair_prompts = [p for k, p in model.calls if k.startswith("repair")]
    assert repair_prompts
    assert all(CANARY not in p for _, p in model.calls)


def test_step_that_never_verifies_is_bounded_then_resketched_once_keeping_frozen():
    resketch = (
        "-- PALS-PROOF-BODY\n"
        "  have h1 : a ≤ b := by sorry\n"  # unchanged: frozen proof is kept
        "  have h3 : b ≤ c := by sorry\n"  # replaces h2
        "  exact le_trans h1 h3\n"
    )
    model = ScriptedModel(
        {
            "sketch": [fenced(SKELETON)],
            "step:h1": [fenced("exact hab")],
            "step:h2": [fenced("BAD")],
            "repair:h2": [fenced("BAD")],
            "resketch": [fenced(resketch)],
            "step:h3": [fenced("exact hbc")],
        }
    )
    res = lane(model, FakeLean()).run()
    assert model.count("repair:h2") == dsp.STEP_MAX_REPAIRS
    assert model.count("resketch") == 1
    assert model.count("step:h1") == 1  # kept, not regenerated
    assert {s.name: s.status for s in res.steps} == {"h1": "model_first", "h3": "model_first"}
    assert res.resketched is True and "sorry" not in res.lean_code


def test_second_failure_after_resketch_gives_up_without_a_third_sketch():
    model = ScriptedModel(
        {
            "sketch": [fenced(SKELETON)],
            "step:h1": [fenced("exact hab")],
            "step:h2": [fenced("BAD")],
            "repair:h2": [fenced("BAD")],
            "resketch": [fenced(SKELETON)],
        }
    )
    res = lane(model, FakeLean()).run()
    assert res.lean_code == ""
    assert res.fallback_reason == "step_unresolved"
    assert model.count("resketch") == 1
    assert {s.name: s.status for s in res.steps}["h2"] == "failed"
    assert {s.name: s.status for s in res.steps}["h1"] == "model_first"


def test_skeleton_that_does_not_compile_is_repaired_once_then_given_up():
    lean = FakeLean(skeleton_ok=lambda code: "have h1 : a ≤ b" not in code)
    model = ScriptedModel({"sketch": [fenced(SKELETON)], "skeleton_repair": [fenced(SKELETON)]})
    res = lane(model, lean).run()
    assert res.lean_code == "" and res.fallback_reason == "skeleton_invalid"
    assert model.count("skeleton_repair") == dsp.SKELETON_MAX_REPAIRS
    assert CANARY not in "".join(p for _, p in model.calls)
    assert not any(k.startswith("step") for k, _ in model.calls)  # no step work before a skeleton


def test_skeleton_repair_then_success():
    state = {"n": 0}

    def ok(code: str) -> bool:
        state["n"] += 1
        return state["n"] > 1

    model = ScriptedModel({"sketch": [fenced(SKELETON)], "skeleton_repair": [fenced(SKELETON)]})
    res = lane(model, FakeLean(skeleton_ok=ok, auto_ok={"h1", "h2"})).run()
    assert res.lean_code and model.count("skeleton_repair") == 1


def test_the_model_cannot_replace_the_fixed_statement():
    other = "theorem t (a b c : ℝ) : a ≤ c := by\n  have h1 : a ≤ b := by sorry\n  sorry\n"
    model = ScriptedModel({"sketch": [fenced(other)], "skeleton_repair": [fenced(other)]})
    res = lane(model, FakeLean()).run()
    assert res.lean_code == ""
    assert res.fallback_reason == "skeleton_invalid"


def test_no_steps_means_the_lane_does_not_apply():
    model = ScriptedModel({"sketch": [fenced("-- PALS-PROOF-BODY\n  exact le_trans hab hbc\n")]})
    res = lane(model, FakeLean()).run()
    assert res.lean_code == "" and res.fallback_reason == "skeleton_invalid"


def test_accounting_counts_every_call_and_compile_and_times_stages():
    model = ScriptedModel(
        {
            "sketch": [fenced(SKELETON)],
            "step:h1": [fenced("exact hab")],
            "step:h2": [fenced("BAD")],
            "repair:h2": [fenced("exact hbc")],
        }
    )
    lean = FakeLean()
    res = lane(model, lean).run()
    assert res.counts.model_calls == len(model.calls) == 4
    assert res.counts.compiles == len(lean.sources)
    assert res.counts.compiles_by_kind["skeleton"] == 1
    assert res.counts.compiles_by_kind["stage0"] == 2
    assert {"sketch_s", "skeleton_check_s", "stage0_s", "steps_s", "total_s"} <= set(res.timings)


def test_a_failed_model_call_is_counted_and_the_step_goes_on_to_repair():
    class Flaky(ScriptedModel):
        def __call__(self, kind, prompt):
            out = super().__call__(kind, prompt)
            if kind == "step:h2" and self.count("step:h2") == 1:
                raise RuntimeError("provider down")
            return out

    model = Flaky(
        {
            "sketch": [fenced(SKELETON)],
            "step:h1": [fenced("exact hab")],
            "step:h2": [fenced("exact hbc")],
            "repair:h2": [fenced("exact hbc")],
        }
    )
    res = lane(model, FakeLean()).run()
    assert res.counts.model_calls == 4  # sketch, h1, the raising h2 call, its repair
    assert res.lean_code


def test_progress_exposes_structure_only():
    model = ScriptedModel(
        {
            "sketch": [fenced(SKELETON)],
            "step:h1": [fenced("exact hab")],
            "step:h2": [fenced("BAD")],
            "repair:h2": [fenced("BAD")],
            "resketch": [fenced(SKELETON)],
        }
    )
    res = lane(model, FakeLean()).run()
    progress = res.progress()
    assert progress == [
        {"name": "h1", "status": "model_first", "verified": True},
        {"name": "h2", "status": "failed", "verified": False},
    ]


def test_stage_timing_is_measured_with_a_slow_compiler():
    class Slow(FakeLean):
        def __call__(self, code):
            time.sleep(0.01)
            return super().__call__(code)

    model = ScriptedModel({"sketch": [fenced(SKELETON)]})
    res = lane(model, Slow(auto_ok={"h1", "h2"})).run()
    assert res.timings["stage0_s"] > 0


def test_eval_runner_has_a_stepwise_arm_and_the_selection_is_in_the_manifests():
    import importlib.util
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("run_stages", root / "scripts/eval/run_stages.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.ARM_FLAGS["stepwise"] == {"stepwise"}
    env = module.set_arm("stepwise")
    assert env[module.FLAG_NAMES["stepwise"]] == "true"
    assert module.set_arm("base")[module.FLAG_NAMES["stepwise"]] == "false"
    manifest = module.load_manifest(
        module.DEFAULT_MANIFEST, [root / "testdata/dsp-stepwise-eval/manifest.json"]
    )
    wanted = json.loads((root / "testdata/dsp-stepwise-eval/selection.json").read_text())
    ids = wanted["reported"] + [x["id"] for k in ("multi_step", "regression") for x in wanted[k]]
    picked = module.select(manifest, ",".join(ids), None)  # KeyError on a held-out id
    assert len(picked) == len(ids) == 15
    assert all("(x+y)^2" not in p["statement"].replace(" ", "") for p in picked)


def test_without_a_fixed_statement_the_models_own_theorem_and_marker_line_parse():
    raw = (
        "```lean\nimport Mathlib\n\ntheorem t (a b c : ℝ) (hab : a ≤ b) (hbc : b ≤ c) :\n"
        "    a ≤ c := by\n-- PALS-PROOF-BODY\n  have h1 : a ≤ b := by sorry\n"
        "  have h2 : b ≤ c := by sorry\n  exact le_trans h1 h2\n```"
    )
    code = dsp.assemble_skeleton(raw, None)
    sk = dsp.parse_skeleton(code, None)
    assert sk is not None and [s.name for s in sk.steps] == ["h1", "h2"]
    assert "PALS-PROOF-BODY" not in code


HARNESS = (
    "import Mathlib\nopen MeasureTheory\n\nuniverse u\n"
    "theorem t (a b c : ℝ) (hab : a ≤ b) (hbc : b ≤ c) : a ≤ c := by"
)


def test_a_fixed_statement_with_imports_universe_and_trailing_by_is_split_and_kept():
    raw = (
        "```lean\nimport Mathlib\nopen Foo\n\n-- PALS-PROOF-BODY\n"
        "  have h1 : a ≤ b := by sorry\n  have h2 : b ≤ c := by sorry\n"
        "  exact le_trans h1 h2\n```"
    )
    code = dsp.assemble_skeleton(raw, HARNESS)
    assert code.startswith("import Mathlib\nopen MeasureTheory\n\nuniverse u\n")
    assert "open Foo" not in code  # the harness preamble is verbatim, the model's is dropped
    assert code.count(":= by") >= 3 and "a ≤ c := by\n  have h1" in code
    sk = dsp.parse_skeleton(code, HARNESS)
    assert sk is not None and [s.name for s in sk.steps] == ["h1", "h2"]
