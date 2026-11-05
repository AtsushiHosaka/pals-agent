# Retained-worker clarification claim compatibility

Working contract: [pals#236](https://github.com/AtsushiHosaka/pals/issues/236),
related [#232](https://github.com/AtsushiHosaka/pals/issues/232). Owner: Codex,
[chat](codex://threads/01a1aa9a-9621-7a10-a10b-5a2c46083d1a).
Base is the exact retained production worker source
`6e5c58dec2459962b2df498385d47cd8d6abe3a2`.

## Trigger and repair

The current API's `ProofClarificationClaimResponse` serializes its resource's
nullable `output_language` member. The retained worker rejects every additional
resource member before generation, including this supported API field. A claim
with a null or supported explicit language therefore fails the closed resource
validation before the authoritative worker-input language is loaded.

The API internal route, response schema, domain model and application service
files are byte-identical between the live API source `9f45a39` and coupon36 source
`5c1a2fd791b63228c60376527cbf9f5c18014939`. This is a pre-existing API/worker
incompatibility, not a regression introduced by the coupon source. It does not
establish the cause of the separately reported Japanese-to-English response.

Only four production lines are backported from the already accepted Agent #55
fix (`0f68acf`): permit `output_language` when present, accept null, and validate
non-null values with the existing strict supported-language helper. The four
supported values remain `en`, `ja`, `zh-Hans` and `zh-Hant`. Older claims without
the member remain valid. Unknown fields, unsupported values, malformed states,
identity and timestamp mismatches remain rejected.

This optional transport member does not select or override the generation
language. Authoritative worker-input language validation, lease/state handling,
saved-parent identity, source excerpts and review hashes are unchanged. Later
quality telemetry, prompt and saved-parent compatibility changes from Agent #51
are not imported into this backport.

## Verification

An offline cross-repository probe used the actual API5c response DTO's
`model_validate(...).model_dump(mode="json")` and actual worker
`_parse_claim_envelope`, with null and all four supported languages. The unchanged
worker rejected all five with `clarification claim resource identity/fields are
invalid`; the patched worker accepted all five as `acquired`. No HTTP request,
database, model, Lean execution or AWS operation was made. Synthetic input only
exercised the claim boundary; it is not a generated mathematical answer.

The five-result baseline JSON SHA-256 is
`a092730cdbf47bfd2f5d1d1ae3aacc96b5283e2944be8c6de20b2d4c739494ba`;
the fixed result JSON SHA-256 is
`11f2326b41ffa024d2db76a315f0e5f7c2ac8be27e966ceaeefcee8ddf9bf9fe`.
Raw records remain outside Git. Null has the same meaning in both probes; no
fallback language is synthesized.

Executed with the existing Python 3.12 environments:

```text
python -m pytest -q tests/unit/test_clarification_claim_language_compatibility.py tests/unit/test_worker_claim_spec.py
117 passed: 35 new closed-claim cases and 82 existing claim/lease/review cases

ruff check pals_agent/worker.py tests/unit/test_clarification_claim_language_compatibility.py
PASS
mypy --follow-imports=silent pals_agent/worker.py
PASS for the changed worker module
git diff --check
PASS
```

The full `mypy pals_agent/worker.py` command reports seven diagnostics in imported
unchanged `openmath.py` and `proof_reuse_usage.py`. The same command was rerun on
the exact unmodified 6e5c58d source and returned the same seven diagnostics. They
were preserved; this change does not claim a repository-wide typecheck pass.

## Release impact and limits

The current signed seq21 coupon candidate and all source/image pins remain
unchanged. Using this backport requires a new worker image, new source/receipt
pins and a distinct future candidate with its own release verification and
authority. This branch is not a deployment and must not silently replace the
retained worker in the existing candidate.

End-to-end authenticated clarification generation, saved-parent newline/hash
compatibility from Agent #55/API #60, UI Lean-line behavior and production Plus
acceptance remain separate checks. The five DTO acceptances and 117 unit cases
do not prove those flows or close #232/#236.
