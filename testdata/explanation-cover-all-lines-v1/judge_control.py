# ruff: noqa: E501
"""Negative control for the reference-fit judge in run.py: two matching and two deliberately mismatched references."""

import importlib.util
import os
from pathlib import Path

from pals_agent.explanations import ExplanationSection, LeanLineReference
from pals_agent.openai import OpenAIResponsesClient

HERE = Path(__file__).resolve().parent


def main() -> None:
    spec = importlib.util.spec_from_file_location("run", HERE / "run.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    lean = (HERE / "group_square_one_a.lean").read_text()
    lines = lean.splitlines()

    def ref(a, b):
        return LeanLineReference(a, b, "\n".join(lines[a - 1 : b]))

    secs = [
        ExplanationSection("s1", "Every element is its own inverse", "Since $a\\cdot a=1$, multiplying on the left by $a^{-1}$ gives $a^{-1}=a$; the same argument gives $b^{-1}=b$.", (ref(12, 18), ref(19, 25))),  # fits, fits
        ExplanationSection("s2", "Conjugate is a", "From $(ab)^2=1$ we get $bab=a$ by cancelling.", (ref(3, 5),)),  # misfit: the statement
        ExplanationSection("s3", "Conclusion", "Hence $ba=ab$.", (ref(12, 18),)),  # misfit: the inverse lemma
        ExplanationSection("s4", "Commutation", "Multiplying $bab=a$ on the right by $b$ and using $b^2=1$ gives $ba=ab$.", (ref(34, 38),)),  # fits
    ]
    client = OpenAIResponsesClient(api_key=os.environ["OPENAI_API_KEY"], max_output_tokens=6000)
    stats = {"calls": {}, "tok": {}}
    for _ in range(2):
        print(m.judge(client, lean, secs, stats), "(expected: 2 misfits at lines 3-5 and 12-18 of section 3)")


if __name__ == "__main__":
    main()
