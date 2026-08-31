"""Fail-closed verification of the shared OpenMath C14N v4 contract artifact."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from importlib import resources
from typing import Any, cast

import rfc8785

from .openmath import MathXMLValidationError, canonicalize_retrieval_openmath_xml

_ARTIFACT_NAME = "openmath-cdbase-alpha-c14n-v4-vectors.json"
_SCHEMA_VERSION = "pals.openmath-cdbase-alpha-c14n-v4-vectors.v2"
_CANONICALIZER_VERSION = "openmath-cdbase-alpha-c14n-v4"
_SOURCE_PATH = "pals_agent/openmath.py"
_ENTRY_POINT = "canonicalize_retrieval_openmath_xml"
_ARTIFACT_SHA256 = "b61936c81392ddbb6aca727b7919db6ac9c833061fd59446dc47bc31bb1703c3"
_HEX64 = re.compile(r"^[0-9a-f]{64}$", re.ASCII)


class OpenMathV4ContractError(ValueError):
    """The immutable OpenMath C14N v4 contract is malformed or no longer matches code."""


class _JsonPairs(list[tuple[str, Any]]):
    pass


def require_openmath_c14n_v4_contract() -> None:
    """Verify the packaged v4 vectors and their bound reference implementation before use."""
    artifact = resources.files("pals_agent.contracts").joinpath(_ARTIFACT_NAME).read_bytes()
    if hashlib.sha256(artifact).hexdigest() != _ARTIFACT_SHA256:
        raise OpenMathV4ContractError("OpenMath C14N v4 artifact digest does not match")
    source = resources.files("pals_agent").joinpath("openmath.py").read_bytes()
    validate_openmath_c14n_v4_contract(artifact_bytes=artifact, openmath_source_bytes=source)


def validate_openmath_c14n_v4_contract(
    *, artifact_bytes: bytes, openmath_source_bytes: bytes
) -> None:
    """Validate one closed v4 artifact against exact canonical XML and payload digest vectors."""
    payload = _decode_artifact(artifact_bytes)
    root = _mapping(payload, "artifact")
    _require_keys(
        root,
        {
            "schema_version",
            "canonicalizer_version",
            "reference_implementation",
            "algorithm",
            "vectors",
        },
        "artifact",
    )
    if root["schema_version"] != _SCHEMA_VERSION:
        raise OpenMathV4ContractError("OpenMath C14N v4 artifact schema is invalid")
    if root["canonicalizer_version"] != _CANONICALIZER_VERSION:
        raise OpenMathV4ContractError("OpenMath C14N v4 artifact version is invalid")

    _validate_reference(
        _mapping(root["reference_implementation"], "reference implementation"),
        openmath_source_bytes,
    )
    _validate_algorithm(_mapping(root["algorithm"], "algorithm"))
    _validate_vectors(root["vectors"])


def _decode_artifact(artifact_bytes: bytes) -> object:
    if not isinstance(artifact_bytes, bytes):
        raise OpenMathV4ContractError("OpenMath C14N v4 artifact bytes are invalid")
    try:
        decoded = json.loads(artifact_bytes.decode("utf-8"), object_pairs_hook=_JsonPairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OpenMathV4ContractError("OpenMath C14N v4 artifact is not valid JSON") from exc
    return _reject_duplicate_members(decoded)


def _reject_duplicate_members(value: object) -> object:
    if isinstance(value, _JsonPairs):
        result: dict[str, object] = {}
        for key, child in value:
            if key in result:
                raise OpenMathV4ContractError("OpenMath C14N v4 artifact has duplicate members")
            result[key] = _reject_duplicate_members(child)
        return result
    if isinstance(value, list):
        return [_reject_duplicate_members(item) for item in value]
    return value


def _validate_reference(reference: Mapping[str, object], source_bytes: bytes) -> None:
    _require_keys(
        reference,
        {"repository", "revision", "source_path", "source_sha256", "entry_point", "runtime"},
        "reference implementation",
    )
    if (
        reference["repository"] != "pals-agent"
        or reference["revision"] != "WORKING: source_sha256 is the immutable authority"
        or reference["source_path"] != _SOURCE_PATH
        or reference["entry_point"] != _ENTRY_POINT
        or reference["runtime"] != "CPython 3.12 standard-library xml.etree.ElementTree"
    ):
        raise OpenMathV4ContractError("OpenMath C14N v4 reference implementation is invalid")
    if not isinstance(source_bytes, bytes):
        raise OpenMathV4ContractError("OpenMath C14N v4 reference source bytes are invalid")
    expected = _hex64(reference["source_sha256"], "reference source digest")
    actual = hashlib.sha256(source_bytes).hexdigest()
    if actual != expected:
        raise OpenMathV4ContractError("OpenMath C14N v4 reference source digest does not match")


def _validate_algorithm(algorithm: Mapping[str, object]) -> None:
    _require_keys(
        algorithm,
        {"authority", "input_profile", "steps", "payload_preimage"},
        "algorithm",
    )
    for name in ("authority", "input_profile", "payload_preimage"):
        if not isinstance(algorithm[name], str) or not algorithm[name]:
            raise OpenMathV4ContractError("OpenMath C14N v4 algorithm field is invalid")
    steps = algorithm["steps"]
    if (
        not isinstance(steps, list)
        or len(steps) != 5
        or any(not isinstance(step, str) or not step for step in steps)
    ):
        raise OpenMathV4ContractError("OpenMath C14N v4 algorithm steps are invalid")


def _validate_vectors(value: object) -> None:
    if not isinstance(value, list) or not value:
        raise OpenMathV4ContractError("OpenMath C14N v4 vectors are invalid")
    vector_ids: set[str] = set()
    accepted = 0
    rejected = 0
    for index, raw_vector in enumerate(value, start=1):
        vector = _mapping(raw_vector, f"vectors[{index}]")
        vector_id = _string(vector.get("id"), f"vectors[{index}].id")
        if vector_id in vector_ids:
            raise OpenMathV4ContractError("OpenMath C14N v4 vectors repeat an ID")
        vector_ids.add(vector_id)
        if vector.get("expected_outcome") == "reject":
            _validate_reject_vector(vector, index=index)
            rejected += 1
        else:
            _validate_accepted_vector(vector, index=index)
            accepted += 1
    if accepted == 0 or rejected == 0:
        raise OpenMathV4ContractError("OpenMath C14N v4 vectors must cover accept and reject")


def _validate_accepted_vector(vector: Mapping[str, object], *, index: int) -> None:
    _require_keys(
        vector,
        {
            "id",
            "input_openmath_xml",
            "canonical_openmath_xml",
            "payload",
            "payload_jcs",
            "payload_sha256",
        },
        f"vectors[{index}]",
    )
    input_xml = _string(vector["input_openmath_xml"], f"vectors[{index}].input_openmath_xml")
    canonical_xml = _string(
        vector["canonical_openmath_xml"], f"vectors[{index}].canonical_openmath_xml"
    )
    try:
        actual_canonical = canonicalize_retrieval_openmath_xml(input_xml)
    except MathXMLValidationError as exc:
        raise OpenMathV4ContractError("OpenMath C14N v4 accepted vector was rejected") from exc
    if actual_canonical != canonical_xml:
        raise OpenMathV4ContractError("OpenMath C14N v4 canonical XML does not match")

    payload = _mapping(vector["payload"], f"vectors[{index}].payload")
    _require_keys(
        payload,
        {"id", "canonical_statement", "proof_strategy", "sketch_steps"},
        f"vectors[{index}].payload",
    )
    sketch_steps = payload["sketch_steps"]
    if not isinstance(sketch_steps, list) or any(
        not isinstance(step, str) for step in sketch_steps
    ):
        raise OpenMathV4ContractError("OpenMath C14N v4 payload sketch steps are invalid")
    preimage: dict[str, object] = {
        "id": _string(payload["id"], f"vectors[{index}].payload.id"),
        "canonical_statement": _string(
            payload["canonical_statement"], f"vectors[{index}].payload.canonical_statement"
        ),
        "openmath_xml": canonical_xml,
        "proof_strategy": _string(
            payload["proof_strategy"], f"vectors[{index}].payload.proof_strategy"
        ),
        "sketch_steps": sketch_steps,
    }
    try:
        actual_jcs = rfc8785.dumps(cast(Any, preimage))
    except (TypeError, ValueError) as exc:
        raise OpenMathV4ContractError("OpenMath C14N v4 payload is not JCS serializable") from exc
    expected_jcs = _string(vector["payload_jcs"], f"vectors[{index}].payload_jcs")
    if actual_jcs != expected_jcs.encode("utf-8"):
        raise OpenMathV4ContractError("OpenMath C14N v4 payload JCS does not match")
    expected_digest = _hex64(vector["payload_sha256"], f"vectors[{index}].payload_sha256")
    if hashlib.sha256(actual_jcs).hexdigest() != expected_digest:
        raise OpenMathV4ContractError("OpenMath C14N v4 payload digest does not match")


def _validate_reject_vector(vector: Mapping[str, object], *, index: int) -> None:
    _require_keys(
        vector,
        {"id", "input_openmath_xml", "expected_outcome"},
        f"vectors[{index}]",
    )
    if vector["expected_outcome"] != "reject":
        raise OpenMathV4ContractError("OpenMath C14N v4 reject vector outcome is invalid")
    input_xml = _string(vector["input_openmath_xml"], f"vectors[{index}].input_openmath_xml")
    try:
        canonicalize_retrieval_openmath_xml(input_xml)
    except MathXMLValidationError:
        return
    raise OpenMathV4ContractError("OpenMath C14N v4 reject vector was accepted")


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise OpenMathV4ContractError(f"OpenMath C14N v4 {label} must be an object")
    return cast(Mapping[str, object], value)


def _require_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise OpenMathV4ContractError(f"OpenMath C14N v4 {label} fields are invalid")


def _string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise OpenMathV4ContractError(f"OpenMath C14N v4 {label} is invalid")
    return value


def _hex64(value: object, label: str) -> str:
    text = _string(value, label)
    if _HEX64.fullmatch(text) is None:
        raise OpenMathV4ContractError(f"OpenMath C14N v4 {label} is invalid")
    return text
