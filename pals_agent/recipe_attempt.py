"""The terminal, non-generative path from a selected Recipe to a v2 candidate.

This boundary deliberately does not import the proof-generation pipeline.  The catalog has
already authenticated a ``RecipeSelected`` value; this module only rechecks that the exact source
can declare the selected target and carries every receipt binding through without transformation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Protocol, cast

import rfc8785

from pals_agent.models import ProofRequest
from pals_agent.openmath import canonicalize_retrieval_openmath_xml
from pals_agent.openmath_v4_contract import require_openmath_c14n_v4_contract
from pals_agent.private_recipe_selection import (
    ClosedRecipeHeaderV1,
    DraftRevisionReference,
    FormalTarget,
    RecipeNotSelected,
    RecipeSelected,
    RecipeSelection,
    RecipeSelectionQuery,
    ToolchainFingerprintV1,
)


class RecipeSelectionPort(Protocol):
    """The agent's private, authenticated catalog boundary."""

    def select(self, query: RecipeSelectionQuery) -> RecipeSelection: ...


def exact_retrieved_draft_reference(
    request: ProofRequest,
) -> tuple[DraftRevisionReference, str | None] | None:
    """Resolve only one exact PFI result, never a similar or arbitrarily ranked Draft.

    Recompute the five-field v4 binding rather than reusing PFI's v3 lookup digest.
    The API subsequently re-fetches and independently revalidates this reference.
    """
    retrieval = request.proof_flow_result
    if not isinstance(retrieval, dict) or retrieval.get("outcome") != "match":
        return None
    # Typed evidence has its own validator/profile binding. Until a corresponding
    # Recipe alignment contract exists it must never be re-labelled as generic PFI.
    if retrieval.get("schema_version") not in {None, "pals.draft-retrieval.v1"} or (
        "profile_id" in retrieval
    ):
        return None
    contexts = retrieval.get("contexts")
    if not isinstance(contexts, list):
        raise ValueError("Recipe Draft retrieval contexts are invalid")
    exact = [
        item
        for item in contexts
        if isinstance(item, dict)
        and isinstance(item.get("evidence"), dict)
        and item["evidence"].get("exact_equivalence") is True
    ]
    if len(exact) != 1:
        return None
    draft = exact[0].get("draft")
    fields = {"id", "canonical_statement", "openmath_xml", "proof_strategy", "sketch_steps"}
    if not isinstance(draft, dict) or set(draft) != fields:
        raise ValueError("Recipe Draft payload is not closed")
    if any(
        not isinstance(draft[key], str) or not draft[key].strip()
        for key in fields - {"sketch_steps"}
    ):
        raise ValueError("Recipe Draft text is invalid")
    steps = draft["sketch_steps"]
    if not isinstance(steps, list) or any(
        not isinstance(step, str) or not step.strip() for step in steps
    ):
        raise ValueError("Recipe Draft sketch is invalid")
    require_openmath_c14n_v4_contract()
    payload = {**draft, "openmath_xml": canonicalize_retrieval_openmath_xml(draft["openmath_xml"])}
    digest = hashlib.sha256(rfc8785.dumps(cast(Any, payload))).hexdigest()
    methods = [
        context.selected_proof_method
        for context in request.related_draft_contexts
        if context.source_draft_id == draft["id"] and context.exact_equivalence
    ]
    if len(methods) != 1:
        raise ValueError("Recipe Draft method evidence is not uniquely bound")
    return DraftRevisionReference(draft_id=draft["id"], draft_payload_sha256=digest), methods[0]


@dataclass(frozen=True, slots=True)
class NoRecipeAttemptV1:
    """A separately traceable decision to keep the old generation path available."""

    exclusions: tuple[tuple[str, str | None, int | None], ...]
    request_sha256: str | None = None


@dataclass(frozen=True, slots=True)
class RecipeAttemptV1:
    """One exact Recipe source and its closed candidate-source binding.

    ``source_bytes`` is the exact UTF-8 conversion of the authenticated DTO member.  Callers must
    submit it directly to the verifier/candidate API; they must not pass it through prompting,
    raw-harness construction, or a repair loop.
    """

    selected: RecipeSelected
    source_bytes: bytes

    @property
    def source(self) -> str:
        return self.selected.materialized_source

    @property
    def source_sha256(self) -> str:
        return self.selected.materialized_source_sha256

    def candidate_source_payload(self) -> dict[str, object]:
        """Return the v2 Recipe binding without deriving or normalizing any DTO field."""

        return {
            "schema_version": "pals.candidate-source.v2",
            "candidate_source": "recipe",
            "recipe_id": self.selected.recipe_id,
            "recipe_revision": self.selected.recipe_revision,
            "alignment_id": self.selected.alignment_id,
            "alignment_revision": self.selected.alignment_revision,
            "selection_payload_sha256": self.selected.selection_payload_sha256,
            "selection_receipt_sha256": self.selected.selection_receipt_sha256,
            "materialized_source_sha256": self.selected.materialized_source_sha256,
            "target_sha256": self.selected.target_sha256,
            "toolchain_fingerprint_sha256": self.selected.toolchain_fingerprint_sha256,
            "compiler_receipt_sha256": self.selected.compiler_receipt_sha256,
            "source_author_principal": self.selected.source_author_principal,
        }


type RecipeAttemptDecisionV1 = RecipeAttemptV1 | NoRecipeAttemptV1


@dataclass(frozen=True, slots=True)
class RecipeAttemptPlannerV1:
    """Plan exactly one catalog lookup before any model or repair call."""

    selector: RecipeSelectionPort
    toolchain_fingerprint: ToolchainFingerprintV1

    def decide(
        self,
        *,
        formal_declaration: str | None,
        draft_revision: DraftRevisionReference | None = None,
        proof_method_tag: str | None = None,
        proof_job_id: str | None = None,
        mutation_claim_id: str | None = None,
    ) -> RecipeAttemptDecisionV1:
        formal_target = (
            FormalTarget.from_declaration(formal_declaration)
            if formal_declaration is not None
            else None
        )
        selection = self.selector.select(
            RecipeSelectionQuery(
                formal_target=formal_target,
                draft_revision=draft_revision,
                proof_method_tag=proof_method_tag,
                toolchain_fingerprint=self.toolchain_fingerprint,
                proof_job_id=proof_job_id,
                mutation_claim_id=mutation_claim_id,
            )
        )
        if isinstance(selection, RecipeNotSelected):
            return NoRecipeAttemptV1(
                request_sha256=selection.request_sha256,
                exclusions=tuple(
                    (item.reason_code, item.recipe_id, item.recipe_revision)
                    for item in selection.exclusions
                ),
            )
        if not isinstance(selection, RecipeSelected):
            raise ValueError("Recipe selection has an invalid result type")
        return _accepted_recipe_attempt(selection, formal_target=formal_target)


def _accepted_recipe_attempt(
    selected: RecipeSelected,
    *,
    formal_target: FormalTarget | None,
) -> RecipeAttemptV1:
    """Apply the Recipe-only preflight after all authenticated DTO checks.

    The generic generated-code preflight expects an LLM harness and therefore is intentionally not
    used here.  This verifies the only accepted target relationship from the materialized bytes.
    """

    source_bytes = selected.materialized_source_bytes
    if hashlib.sha256(source_bytes).hexdigest() != selected.materialized_source_sha256:
        raise ValueError("selected materialized source digest is invalid")
    header = ClosedRecipeHeaderV1.extract(selected.materialized_source)
    if header is None:
        raise ValueError("selected materialized source has no closed declaration")
    materialized_target_sha256 = hashlib.sha256(header.target_source.encode("utf-8")).hexdigest()
    if materialized_target_sha256 != selected.target_sha256:
        raise ValueError("selected materialized source target digest is invalid")
    if formal_target is not None and formal_target.target_sha256 != selected.target_sha256:
        raise ValueError("selected materialized source target differs from the formal request")
    return RecipeAttemptV1(selected=selected, source_bytes=source_bytes)
