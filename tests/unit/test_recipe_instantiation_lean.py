"""The mechanical instance is accepted by the real, pinned Lean through the production verifier."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from pals_agent.lean import LeanVerifier
from pals_agent.recipe_instantiation import INSTANCE_NAME, instantiate

PINNED = Path.home() / ".elan/toolchains/leanprover--lean4---v4.32.0-rc1/bin/lean"
pytestmark = pytest.mark.skipif(
    not PINNED.exists() or shutil.which("prlimit") is None and os.uname().sysname == "Linux",
    reason="pinned Lean v4.32.0-rc1 is required (PATH lean 4.35 is the wrong toolchain)",
)
EXAMPLE = "example : ∀ (n : Nat), 0 < 2 ^ n := fun n => Nat.two_pow_pos n\n"
NAMED = "theorem add_comm_nat (a b : Nat) : a + b = b + a := Nat.add_comm a b\n"


def verifier() -> LeanVerifier:
    return LeanVerifier(lean_binary=str(PINNED), timeout_seconds=120.0)


def test_pinned_toolchain_is_the_expected_release():
    version = subprocess.run([str(PINNED), "--version"], capture_output=True, text=True).stdout
    assert "4.32.0-rc1" in version


@pytest.mark.parametrize(("source", "bindings"), [
    (EXAMPLE, [("n", "3")]), (EXAMPLE, [("n", "0")]), (NAMED, [("a", "3"), ("b", "4")]),
])
def test_instances_pass_production_verifier_policy_compile_and_axiom_audit(source, bindings):
    result = verifier().verify(instantiate(source, bindings).source)
    assert result.success, result.diagnostics


def test_recipe_itself_and_instance_declare_exactly_the_audited_theorems():
    instance = instantiate(EXAMPLE, [("n", "2")])
    assert instance.source.count("theorem ") == 2 and INSTANCE_NAME in instance.source


def test_a_wrong_instance_statement_is_rejected_by_lean_not_by_this_module():
    instance = instantiate(EXAMPLE, [("n", "3")])
    tampered = instance.source.replace("0 < 2 ^ 3", "0 < 2 ^ 4")
    assert tampered != instance.source
    assert not verifier().verify(tampered).success


def test_an_argument_outside_the_statement_scope_does_not_typecheck():
    instance = instantiate(NAMED, [("a", "3"), ("b", "4")])
    wrong = instance.source.replace("add_comm_nat 3 4", "add_comm_nat 3 5")
    assert not verifier().verify(wrong).success
