"""Bounded real-provider PFR-017 interpretation smoke; no API/DB/Lean claim.

Uses the existing worker environment. Never prints credentials or provider bodies.
"""

from __future__ import annotations

import json
import time

from pals_agent.openai import OpenAIResponsesClient
from pals_agent.proof_input import ProofInputInterpreter
from pals_agent.settings import AgentSettings
from pals_agent.usage import usage_scope


def main() -> None:
    settings = AgentSettings.from_env()
    interpreter = ProofInputInterpreter(OpenAIResponsesClient(
        settings.openai_api_key, base_url=settings.openai_base_url
    ))
    original = "Prove n²+n is even for every real n."
    request = {"statement": original, "output_language": "en", "context_turns": []}
    cases = [
        ("integer_correction", "amend", "Integers, not reals.", []),
        ("positive_integer_correction", "amend", "Only positive integers, please.",
         [{"text": "Integers, not reals.", "status": "amend"}]),
        ("ambiguous", "needs_intent", "What about integers?", []),
        ("separate", "independent", "Separately, prove there are infinitely many primes.", []),
        ("mixed", "mixed", "Integers, not reals. Separately, prove there are infinitely many "
         "primes.", []),
    ]
    usage: list[dict] = []
    for name, expected, text, prior in cases:
        work = {"original_statement": original, "text": text,
                "prior_inputs": prior, "confirmed_intent": None}
        started = time.monotonic()
        with usage_scope(usage.append):
            decision = interpreter.interpret(request, work)
        print(json.dumps({"case": name, "expected": expected, "actual": decision["kind"],
                          "decision": decision, "elapsed_seconds": round(
                              time.monotonic() - started, 2)}, ensure_ascii=False), flush=True)
        if decision["kind"] != expected:
            raise RuntimeError("Real provider interpretation did not match expected behavior")
    print(json.dumps({"cases": len(cases), "provider_calls": len(usage),
                      "input_tokens": sum(item["input_tokens"] for item in usage),
                      "output_tokens": sum(item["output_tokens"] for item in usage)}))


if __name__ == "__main__":
    main()
