from __future__ import annotations

import base64
import binascii
import copy
import hashlib
import re
import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, Protocol, cast

import rfc8785

OPENMATH_NAMESPACE = "http://www.openmath.org/OpenMath"
OMDOC_NAMESPACE = "http://www.mathweb.org/omdoc"
DUBLIN_CORE_NAMESPACE = "http://purl.org/dc/elements/1.1/"
XML_NAMESPACE = "http://www.w3.org/XML/1998/namespace"
OPENMATH_STANDARD_CDBASE = "http://www.openmath.org/cd"
PALS_OPENMATH_CDBASE = "urn:pals:openmath:cd:v1"

_OPENMATH_ROOT = f"{{{OPENMATH_NAMESPACE}}}OMOBJ"
_OMDOC_ROOT = f"{{{OMDOC_NAMESPACE}}}omdoc"
_OMDOC_METADATA = f"{{{OMDOC_NAMESPACE}}}metadata"
_OMDOC_THEORY = f"{{{OMDOC_NAMESPACE}}}theory"
_OMDOC_ASSERTION = f"{{{OMDOC_NAMESPACE}}}assertion"
_OMDOC_CMP = f"{{{OMDOC_NAMESPACE}}}CMP"
_OMDOC_FMP = f"{{{OMDOC_NAMESPACE}}}FMP"
_DUBLIN_CORE_RELATION = f"{{{DUBLIN_CORE_NAMESPACE}}}relation"
_XML_ID = f"{{{XML_NAMESPACE}}}id"
_INTEGER_RE = re.compile(r"-?(?:0|[1-9][0-9]*|x[0-9A-Fa-f]+)\Z")
_BASE64_RE = re.compile(r"(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?\Z")
_BASE64_IGNORABLE_RE = re.compile(r"[\r\n \f\t]")
_OMF_DECIMAL_RE = re.compile(
    r"(?:-?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE]-?[0-9]+)?|INF|-INF|NaN)\Z"
)
_OMF_HEX_RE = re.compile(r"[0-9A-F]{16}\Z")
_DRAFT_RELATION_RE = re.compile(
    r"urn:pals:draft-relation:([a-z][a-z0-9-]*):([A-Za-z_][A-Za-z0-9_.-]*)\Z"
)
DRAFT_RELATION_PREDICATES = {
    "generalizes": "The source theorem family strictly generalizes the target family.",
    "same-proof-construction": "Source and target share the same proof construction.",
    "same-proof-family": "Source and target belong to the same theorem/proof family.",
    "same-proof-technique": "Source and target use the same local proof technique.",
    "simpler-than": "The source is a simpler instance or prerequisite of the target.",
    "uses-epsilon-split": "Source and target both use an epsilon-budget split.",
    "uses-local-bound": "Source and target both use a local-bounding technique.",
}
_STATEMENT_VARIABLE_RE = re.compile(
    r"(?<![A-Za-z0-9_])"
    r"(?P<name>[A-Za-zΑ-Ωα-ω](?:_[A-Za-z0-9]+|[0-9]+)?)"
    r"(?![A-Za-z0-9_])"
)
_JAPANESE_CONTINUITY_TARGET_RE = re.compile(
    r"(?:不連続(?:である)?|連続(?:では|で)ない|連続(?:する|である|となる|な)?)"
    r"\s*ことを|"
    r"(?:不連続|連続)性を"
)
_JAPANESE_CONTINUITY_FINAL_RE = re.compile(r"(?:不連続|連続)\s*[。.!！?？]?\s*$")
_JAPANESE_ASSUMPTION_FOLLOW_RE = re.compile(
    r"\s*(?:(?:まず|一旦|先に)\s*)?(?:仮定|前提|用い|使い|使って|利用)"
)
_JAPANESE_ASSUMPTION_WORD_RE = re.compile(r"(?:仮定|前提)")
_JAPANESE_NEGATED_ASSUMPTION_RE = re.compile(r"(?:仮定\s*せず|前提\s*と?\s*せず)")
_JAPANESE_PROOF_VERB_RE = re.compile(r"(?:示|証明|確かめ)")
_ENGLISH_CONTINUITY_TARGET_RE = re.compile(
    r"\b(?:(?:is|are)\s+(?:not\s+)?continuous|continuity|discontinuous)\b",
    re.IGNORECASE,
)
_ENGLISH_CONTINUITY_FINAL_RE = re.compile(
    r"\b(?:is|are)\s+(?:not\s+)?continuous"
    r"(?:\s+on\b[^,.!?]*)?\s*[.!?]*\s*$|"
    r"\bdiscontinuous\s*[.!?]*\s*$",
    re.IGNORECASE,
)
_ENGLISH_PROOF_COMMAND_RE = re.compile(r"\b(?:show|prove)\b", re.IGNORECASE)
_ENGLISH_ASSUMPTION_START_RE = re.compile(
    r"^(?:if|assuming|given|under\s+the\s+assumption)\b",
    re.IGNORECASE,
)
_ENGLISH_CONTINUITY_ASSUMPTION_RE = re.compile(
    r"\b(?:assuming|given(?:\s+that)?|"
    r"under\s+the\s+assumption(?:\s+(?:that|of))?)\b"
    r"[^,.;]*?\b(?:(?:is|are)\s+continuous|(?:the\s+)?continuity\s+of)\b",
    re.IGNORECASE,
)
_EPSILON_DELTA_METHOD_RE = re.compile(
    r"イプシロン\s*デルタ|ε\s*[-‐‑‒–—ー]?\s*δ|epsilon\s*[- ]?\s*delta",
    re.IGNORECASE,
)
_THEOREM_EXISTENCE_RE = re.compile(
    r"(?:存在すること|存在)\s*を\s*"
    r"(?:示せ|示す|示しなさい|証明する|証明せよ|証明しなさい)"
    r"\s*[。.!！?？]*\s*$|"
    r"^\s*(?:show|prove)(?:\s+that)?\s+there\s+exists\b|"
    r"^\s*there\s+exists",
    re.IGNORECASE,
)
_NEGATIVE_CONTINUITY_RE = re.compile(
    r"不連続|連続(?:では|で)ない|not\s+continuous|discontinuous",
    re.IGNORECASE,
)
_POWER_EXPONENT_RE = re.compile(r"(?:\^|\*\*)\s*([0-9]+)")
_SUPERSCRIPT_POWER_RE = re.compile(r"(?<!⁻)[⁰¹²³⁴⁵⁶⁷⁸⁹]+")
_SUPERSCRIPT_DIGITS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹", "0123456789")
_PLACEHOLDER_NAMES = {
    "expression",
    "placeholder",
    "statement",
    "tbd",
    "todo",
    "unknown",
    "unsupported",
}
_MAX_STRUCTURING_REPAIRS = 2

_LOCAL_REFERENCE_ATTRIBUTES = {
    "assertion",
    "base",
    "consistency",
    "existence",
    "for",
    "from",
    "generated-from",
    "href",
    "induced-by",
    "just-by",
    "links",
    "local",
    "theory",
    "to",
    "uniqueness",
    "xref",
}


@dataclass(frozen=True, slots=True)
class _SymbolSpec:
    role: Literal["application", "binder", "constant"]
    minimum_arity: int | None = None
    maximum_arity: int | None = None
    returns_proposition: bool = False
    proposition_arguments: bool = False


_SymbolIdentity = tuple[str, str, str]
_RetrievalSort = Literal[
    "term",
    "proposition",
    "term_function",
    "predicate_function",
]
_ContinuitySort = Literal[
    "natural_index",
    "proposition",
    "real_function",
    "real_sequence",
    "term",
]


_UNARY_TERM = _SymbolSpec("application", 1, 1)
_BINARY_TERM = _SymbolSpec("application", 2, 2)
_NARY_TERM = _SymbolSpec("application", 2, None)
_UNARY_PREDICATE = _SymbolSpec("application", 1, 1, returns_proposition=True)
_BINARY_PREDICATE = _SymbolSpec("application", 2, 2, returns_proposition=True)
_NARY_CONNECTIVE = _SymbolSpec(
    "application",
    2,
    None,
    returns_proposition=True,
    proposition_arguments=True,
)
_BINARY_CONNECTIVE = _SymbolSpec(
    "application",
    2,
    2,
    returns_proposition=True,
    proposition_arguments=True,
)
_SUPPORTED_SYMBOLS: dict[_SymbolIdentity, _SymbolSpec] = {
    **{
        (OPENMATH_STANDARD_CDBASE, "relation1", name): _BINARY_PREDICATE
        for name in ("approx", "eq", "geq", "gt", "leq", "lt", "neq")
    },
    **{
        (OPENMATH_STANDARD_CDBASE, "logic1", name): _NARY_CONNECTIVE
        for name in ("and", "nand", "nor", "or", "xnor", "xor")
    },
    (OPENMATH_STANDARD_CDBASE, "logic1", "equivalent"): _BINARY_CONNECTIVE,
    (OPENMATH_STANDARD_CDBASE, "logic1", "implies"): _BINARY_CONNECTIVE,
    (OPENMATH_STANDARD_CDBASE, "logic1", "not"): _SymbolSpec(
        "application",
        1,
        1,
        returns_proposition=True,
        proposition_arguments=True,
    ),
    (OPENMATH_STANDARD_CDBASE, "logic1", "false"): _SymbolSpec(
        "constant", returns_proposition=True
    ),
    (OPENMATH_STANDARD_CDBASE, "logic1", "true"): _SymbolSpec("constant", returns_proposition=True),
    **{
        (OPENMATH_STANDARD_CDBASE, "arith1", name): _NARY_TERM
        for name in ("gcd", "lcm", "plus", "times")
    },
    **{(OPENMATH_STANDARD_CDBASE, "arith1", name): _UNARY_TERM for name in ("abs", "unary_minus")},
    **{
        (OPENMATH_STANDARD_CDBASE, "arith1", name): _BINARY_TERM
        for name in ("divide", "minus", "power", "product", "root", "sum")
    },
    **{
        (OPENMATH_STANDARD_CDBASE, "set1", name): _BINARY_PREDICATE
        for name in ("in", "notin", "notprsubset", "notsubset", "prsubset", "subset")
    },
    **{
        (OPENMATH_STANDARD_CDBASE, "set1", name): _NARY_TERM
        for name in ("cartesian_product", "intersect", "union")
    },
    **{
        (OPENMATH_STANDARD_CDBASE, "set1", name): _BINARY_TERM
        for name in ("map", "setdiff", "suchthat")
    },
    (OPENMATH_STANDARD_CDBASE, "set1", "set"): _SymbolSpec("application", 1, None),
    (OPENMATH_STANDARD_CDBASE, "set1", "size"): _UNARY_TERM,
    (OPENMATH_STANDARD_CDBASE, "set1", "emptyset"): _SymbolSpec("constant"),
    **{
        (OPENMATH_STANDARD_CDBASE, "setname1", name): _SymbolSpec("constant")
        for name in ("C", "N", "P", "Q", "R", "Z")
    },
    (OPENMATH_STANDARD_CDBASE, "alg1", "one"): _SymbolSpec("constant"),
    (OPENMATH_STANDARD_CDBASE, "alg1", "zero"): _SymbolSpec("constant"),
    (OPENMATH_STANDARD_CDBASE, "quant1", "exists"): _SymbolSpec("binder", returns_proposition=True),
    (OPENMATH_STANDARD_CDBASE, "quant1", "forall"): _SymbolSpec("binder", returns_proposition=True),
    (OPENMATH_STANDARD_CDBASE, "fns1", "lambda"): _SymbolSpec("binder"),
    (PALS_OPENMATH_CDBASE, "pals1", "compact"): _UNARY_PREDICATE,
    (PALS_OPENMATH_CDBASE, "pals1", "continuous_on"): _BINARY_PREDICATE,
    (PALS_OPENMATH_CDBASE, "pals1", "continuous_at"): _BINARY_PREDICATE,
    (PALS_OPENMATH_CDBASE, "pals1", "has_limit_at"): _SymbolSpec(
        "application", 3, 3, returns_proposition=True
    ),
    (PALS_OPENMATH_CDBASE, "pals1", "converges_to"): _BINARY_PREDICATE,
    (PALS_OPENMATH_CDBASE, "pals1", "apply"): _BINARY_TERM,
    (PALS_OPENMATH_CDBASE, "pals1", "sequence_apply"): _BINARY_TERM,
    (PALS_OPENMATH_CDBASE, "pals1", "constant_function"): _UNARY_TERM,
    (PALS_OPENMATH_CDBASE, "pals1", "identity_function"): _SymbolSpec("constant"),
    **{
        (PALS_OPENMATH_CDBASE, "pals1", name): _BINARY_TERM
        for name in (
            "function_add",
            "function_sub",
            "function_mul",
            "function_div",
            "function_compose",
            "sequence_add",
            "sequence_sub",
            "sequence_mul",
            "sequence_div",
            "sequence_scale",
            "sequence_compose",
        )
    },
    **{
        (PALS_OPENMATH_CDBASE, "pals1", name): _UNARY_TERM
        for name in ("function_neg", "sequence_neg", "index_succ", "index_to_real")
    },
    (PALS_OPENMATH_CDBASE, "pals1", "function_scale"): _BINARY_TERM,
    (PALS_OPENMATH_CDBASE, "pals1", "index_zero"): _SymbolSpec("constant"),
    **{
        (PALS_OPENMATH_CDBASE, "pals1", name): _SymbolSpec("binder", returns_proposition=True)
        for name in (
            "forall_real_function",
            "exists_real_function",
            "forall_real_sequence",
            "exists_real_sequence",
        )
    },
    (PALS_OPENMATH_CDBASE, "pals1", "sequence_lambda"): _SymbolSpec("binder"),
    (PALS_OPENMATH_CDBASE, "pals1", "dimension"): _UNARY_TERM,
    (PALS_OPENMATH_CDBASE, "pals1", "domain"): _UNARY_TERM,
    (PALS_OPENMATH_CDBASE, "pals1", "finite_dimensional"): _UNARY_PREDICATE,
    (PALS_OPENMATH_CDBASE, "pals1", "linear_map"): _UNARY_PREDICATE,
    (PALS_OPENMATH_CDBASE, "pals1", "nullity"): _UNARY_TERM,
    (PALS_OPENMATH_CDBASE, "pals1", "rank"): _UNARY_TERM,
}
_RETRIEVAL_FUNCTION_ARGUMENT_SORTS: dict[_SymbolIdentity, tuple[_RetrievalSort, ...]] = {
    (OPENMATH_STANDARD_CDBASE, "arith1", "sum"): ("term", "term_function"),
    (OPENMATH_STANDARD_CDBASE, "arith1", "product"): (
        "term",
        "term_function",
    ),
    (OPENMATH_STANDARD_CDBASE, "set1", "map"): ("term_function", "term"),
    (OPENMATH_STANDARD_CDBASE, "set1", "suchthat"): (
        "term",
        "predicate_function",
    ),
    (PALS_OPENMATH_CDBASE, "pals1", "continuous_on"): (
        "term",
        "term_function",
    ),
}
_PROFILE_CONTENT_DICTIONARIES = frozenset((cdbase, cd) for cdbase, cd, _name in _SUPPORTED_SYMBOLS)


class MathXMLValidationError(ValueError):
    """Raised when OpenMath or OMDoc XML violates the supported contract."""


class OpenMathStructuringError(RuntimeError):
    """Raised when the configured LLM cannot produce valid OpenMath XML."""


class TextGenerationClient(Protocol):
    def generate(self, *, model: str, prompt: str) -> str: ...


class StatementOpenMathStructurer(Protocol):
    def structure(self, statement: str) -> str: ...


@dataclass(frozen=True, slots=True)
class LLMStatementOpenMathStructurer:
    client: TextGenerationClient
    model: str
    provider: str

    def structure(self, statement: str) -> str:
        normalized = " ".join(statement.strip().split())
        if not normalized:
            raise OpenMathStructuringError("A non-empty statement is required for OpenMath.")

        previous_xml: str | None = None
        validation_error: str | None = None
        for attempt in range(_MAX_STRUCTURING_REPAIRS + 1):
            try:
                output = self.client.generate(
                    model=self.model,
                    prompt=_openmath_prompt(
                        normalized,
                        previous_xml=previous_xml,
                        validation_error=validation_error,
                    ),
                )
            except Exception as exc:
                raise OpenMathStructuringError(
                    f"{self.provider} OpenMath structuring failed: {exc}"
                ) from exc

            candidate = output.strip()
            try:
                candidate = _strict_xml_payload(output)
                validate_openmath_statement_semantics(candidate, normalized)
                canonical = canonicalize_openmath_xml(candidate)
                return canonical
            except MathXMLValidationError as exc:
                previous_xml = candidate
                validation_error = str(exc)
                if attempt == _MAX_STRUCTURING_REPAIRS:
                    raise OpenMathStructuringError(
                        f"{self.provider} returned invalid OpenMath XML after "
                        f"{attempt + 1} attempts: {exc}"
                    ) from exc

        raise AssertionError("OpenMath structuring retry loop did not terminate")


def validate_openmath_xml(xml: str) -> ET.Element:
    root = _parse_xml(xml, document_type="OpenMath")
    _validate_openmath_tree(root)
    return root


def canonicalize_openmath_xml(xml: str) -> str:
    root = validate_openmath_xml(xml)
    canonical_root = copy.deepcopy(root)
    _alpha_normalize_openmath_tree(canonical_root)
    _remove_ignorable_whitespace(canonical_root)
    serialized = ET.tostring(canonical_root, encoding="unicode")
    return ET.canonicalize(serialized)


def canonicalize_openmath_xml_v4(xml: str) -> str:
    """Return valid parent-PFI v4 bytes for one focused-profile proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("OpenMath XML exceeds the retrieval byte bound.")
    root = validate_openmath_xml(xml)
    _validate_retrieval_openmath_profile(root, require_closed=False)
    return _canonicalize_openmath_v4_root(root)


def _canonicalize_openmath_v4_root(root: ET.Element) -> str:
    canonical_root = copy.deepcopy(root)
    _alpha_normalize_openmath_tree(canonical_root)
    _remove_ignorable_whitespace(canonical_root)
    serialized = ET.tostring(canonical_root, encoding="unicode")
    raw = ET.canonicalize(
        serialized,
        with_comments=False,
        strip_text=False,
        rewrite_prefixes=True,
        qname_aware_tags=set(),
        qname_aware_attrs=set(),
        exclude_tags=set(),
        exclude_attrs=set(),
    )
    transport_artifact = ' xmlns:n0=""'
    if raw.count(transport_artifact) != 1:
        raise MathXMLValidationError("OpenMath C14N v4 transport artifact is invalid.")
    canonical = raw.replace(transport_artifact, "", 1)
    try:
        ET.fromstring(canonical)
    except ET.ParseError as exc:
        raise MathXMLValidationError("OpenMath C14N v4 bytes are not parseable XML.") from exc
    return canonical


def canonicalize_retrieval_openmath_xml(xml: str) -> str:
    """Return the parent-PFI v4 bytes for one closed retrieval proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("OpenMath XML exceeds the retrieval byte bound.")
    root = validate_openmath_xml(xml)
    _validate_retrieval_openmath_profile(root, require_closed=True)
    return _canonicalize_openmath_v4_root(root)


def canonicalize_continuity_v1_openmath_xml(xml: str) -> str:
    """Validate and canonicalize one closed typed ``continuity-v1`` proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("OpenMath XML exceeds the retrieval byte bound.")
    root = validate_openmath_xml(xml)
    if not _contains_continuity_v1_construct(root):
        raise MathXMLValidationError("OpenMath XML is not a continuity-v1 typed proposition.")
    _validate_continuity_v1_profile(root)
    return _canonicalize_openmath_v4_root(root)


def continuity_v1_novelty_key(
    coverage_signature: Mapping[str, object],
    canonical_openmath_xml: str,
) -> str:
    """Return the fixed PFI-008 novelty digest without opening any external input."""
    _validate_continuity_coverage_signature(coverage_signature)
    canonical = validate_canonical_retrieval_openmath_xml(canonical_openmath_xml)
    root = validate_openmath_xml(canonical)
    if not _contains_continuity_v1_construct(root):
        raise MathXMLValidationError("OpenMath XML is not a continuity-v1 typed proposition.")
    try:
        preimage = rfc8785.dumps(
            {
                "coverage_signature": dict(coverage_signature),
                "openmath_xml_sha256": "sha256:"
                + hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
            }
        )
    except (TypeError, ValueError) as exc:
        raise MathXMLValidationError("continuity-v1 coverage is not JCS serializable.") from exc
    return "sha256:" + hashlib.sha256(preimage).hexdigest()


def _validate_continuity_coverage_signature(
    coverage_signature: Mapping[str, object],
) -> None:
    fields = {
        "context",
        "operators",
        "prerequisites",
        "proof_schema",
        "representation",
        "stratum",
        "topic",
    }
    if set(coverage_signature) != fields:
        raise MathXMLValidationError("continuity-v1 coverage has an invalid field set.")
    for name in fields - {"operators", "prerequisites"}:
        value = coverage_signature[name]
        if not isinstance(value, str) or not value:
            raise MathXMLValidationError("continuity-v1 coverage scalar is invalid.")
    for name in ("operators", "prerequisites"):
        value = coverage_signature[name]
        if (
            not isinstance(value, list)
            or any(not isinstance(item, str) or not item for item in value)
            or value != sorted(value, key=lambda item: item.encode("utf-8"))
            or len(value) != len(set(value))
        ):
            raise MathXMLValidationError("continuity-v1 coverage vector is invalid.")


def validate_canonical_retrieval_openmath_xml(xml: str) -> str:
    """Accept only one valid-XML, already-canonical closed PFI proposition."""
    if len(xml.encode("utf-8")) > 65_536:
        raise MathXMLValidationError("OpenMath XML exceeds the retrieval byte bound.")
    transport_artifact = ' xmlns:n0=""'
    if transport_artifact in xml:
        raise MathXMLValidationError("OpenMath XML is not exact retrieval canonical bytes.")
    root = validate_openmath_xml(xml)
    _validate_retrieval_openmath_profile(root, require_closed=True)
    canonical = _canonicalize_openmath_v4_root(root)
    if canonical != xml:
        raise MathXMLValidationError("OpenMath XML is not exact retrieval canonical bytes.")
    return canonical


def retrieval_openmath_structural_features(xml: str) -> Counter[str]:
    """Return the exact parent-PFI weighted feature multiset for canonical XML."""
    canonical = validate_canonical_retrieval_openmath_xml(xml)
    root = validate_openmath_xml(canonical)
    return _structural_features(root)


def openmath_structural_similarity(query_xml: str, candidate_xml: str) -> float:
    query_root = validate_openmath_xml(canonicalize_openmath_xml(query_xml))
    candidate_root = validate_openmath_xml(canonicalize_openmath_xml(candidate_xml))
    query_features = _structural_features(query_root)
    candidate_features = _structural_features(candidate_root)
    overlap = sum((query_features & candidate_features).values())
    query_weight = sum(query_features.values())
    candidate_weight = sum(candidate_features.values())
    if query_weight == 0 or candidate_weight == 0:
        return 0.0
    query_coverage = overlap / query_weight
    candidate_precision = overlap / candidate_weight
    return min(1.0, max(0.0, 0.85 * query_coverage + 0.15 * candidate_precision))


def validate_openmath_statement_semantics(xml: str, statement: str) -> None:
    root = validate_openmath_xml(xml)
    parents = _openmath_parents(root)
    if any(_local_name(element) == "OMSTR" for element in root.iter()):
        raise MathXMLValidationError("OMSTR is not allowed in structured statement OpenMath.")

    for element in root.iter():
        if _local_name(element) not in {"OMS", "OMV"}:
            continue
        name = (element.get("name") or "").strip().lower().replace("-", "_")
        if name in _PLACEHOLDER_NAMES:
            raise MathXMLValidationError(
                f"OpenMath contains placeholder name `{element.get('name')}`."
            )

    _validate_supported_symbol_profile(root)
    expression = list(root)[0]
    if _is_emptyset_only(expression, parents=parents):
        raise MathXMLValidationError(
            "OpenMath expression is an empty-set placeholder, not a proposition."
        )
    if not _is_proposition(expression, parents=parents):
        raise MathXMLValidationError("OpenMath expression does not encode a predicate/proposition.")
    continuity_goal = _statement_continuity_goal_fragment(statement)
    if continuity_goal is not None:
        symbols = {
            symbol
            for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS")
            if (symbol := _operator_symbol(element, parents=parents)) is not None
        }
        if (PALS_OPENMATH_CDBASE, "pals1", "continuous_on") not in symbols:
            raise MathXMLValidationError(
                "The statement asks for continuity, but the OpenMath expression does not use "
                "`pals1:continuous_on`. Proof-method instructions such as epsilon-delta must "
                "not replace the theorem-level continuity proposition."
            )
        if (
            _EPSILON_DELTA_METHOD_RE.search(statement)
            and not _THEOREM_EXISTENCE_RE.search(statement)
            and (OPENMATH_STANDARD_CDBASE, "quant1", "exists") in symbols
        ):
            raise MathXMLValidationError(
                "The OpenMath expression introduces an existential quantifier from the "
                "epsilon-delta proof method, although the source theorem is not an existence "
                "claim. Keep proof construction outside the theorem-level proposition."
            )
        negative_statement = bool(_NEGATIVE_CONTINUITY_RE.search(continuity_goal))
        required_polarity = negative_statement
        continuity_occurrences = _continuity_goal_occurrences(
            expression,
            statement=statement,
            parents=parents,
        )
        matching_occurrences = [
            occurrence
            for polarity, occurrence in continuity_occurrences
            if polarity is required_polarity
        ]
        if not matching_occurrences:
            expected = "negated" if negative_statement else "positive"
            raise MathXMLValidationError(
                f"The statement requires a {expected} continuity proposition, but the "
                "OpenMath logical polarity does not match."
            )
        target_text = _statement_continuity_target_text(statement)
        target_function_names = _statement_continuity_target_function_names(statement)
        if target_function_names:
            matching_occurrences = [
                occurrence
                for occurrence in matching_occurrences
                if _openmath_variable_name(list(occurrence)[2]) in target_function_names
            ]
            if not matching_occurrences:
                expected_names = ", ".join(sorted(target_function_names))
                raise MathXMLValidationError(
                    "The OpenMath continuity target function variable does not match the "
                    f"natural-language target: {expected_names}."
                )
        target_callee_names = _statement_function_callee_names(target_text)
        if target_callee_names:
            matching_occurrences = [
                occurrence
                for occurrence in matching_occurrences
                if _openmath_function_callee_names(list(occurrence)[2]) == target_callee_names
            ]
            if not matching_occurrences:
                expected_names = ", ".join(sorted(target_callee_names))
                raise MathXMLValidationError(
                    "The OpenMath continuity target function application does not match the "
                    f"natural-language callee(s): {expected_names}."
                )
        required_shape = _statement_arithmetic_shape(
            target_text,
            context_statement=statement,
        )
        if required_shape is not None:
            matching_occurrences = [
                occurrence
                for occurrence in matching_occurrences
                if (
                    _openmath_arithmetic_shape(
                        list(occurrence)[2],
                        parents=parents,
                        erase_point_applications="apply(" not in required_shape,
                        explicit_point_markers="p:" in required_shape,
                    )
                    == required_shape
                    or _direct_function_matches_simple_application(
                        list(occurrence)[2],
                        required_shape,
                    )
                )
            ]
            if not matching_occurrences:
                raise MathXMLValidationError(
                    "The OpenMath continuity target arithmetic structure does not match the "
                    f"natural-language target: {required_shape}."
                )
        required_symbols = _required_continuity_symbols(target_text)
        required_exponents = _statement_power_exponents(target_text)
        required_literals = _statement_target_integer_literals(target_text)
        required_operator_literals = _statement_operator_literal_edges(target_text)
        candidate_details: list[
            tuple[
                set[_SymbolIdentity],
                set[int],
                set[int],
                set[tuple[str, int]],
                ET.Element,
            ]
        ] = []
        for occurrence in matching_occurrences:
            _operator, _domain, function = list(occurrence)
            occurrence_symbols = {
                symbol
                for element in function.iter(f"{{{OPENMATH_NAMESPACE}}}OMS")
                if (symbol := _operator_symbol(element, parents=parents)) is not None
            }
            occurrence_exponents = _openmath_integer_power_exponents(
                function,
                parents=parents,
            )
            occurrence_literals = _openmath_integer_literals(function)
            occurrence_operator_literals = _openmath_operator_literal_edges(
                function,
                parents=parents,
            )
            if (
                required_symbols.issubset(occurrence_symbols)
                and required_exponents.issubset(occurrence_exponents)
                and required_literals.issubset(occurrence_literals)
                and required_operator_literals.issubset(occurrence_operator_literals)
            ):
                break
            candidate_details.append(
                (
                    occurrence_symbols,
                    occurrence_exponents,
                    occurrence_literals,
                    occurrence_operator_literals,
                    occurrence,
                )
            )
        else:
            (
                best_symbols,
                best_exponents,
                best_literals,
                best_operator_literals,
                _best_occurrence,
            ) = min(
                candidate_details,
                key=lambda candidate: (
                    len(required_symbols - candidate[0])
                    + len(required_exponents - candidate[1])
                    + len(required_literals - candidate[2])
                    + len(required_operator_literals - candidate[3]),
                    len(required_symbols - candidate[0]),
                ),
            )
            missing_symbols = sorted(required_symbols - best_symbols)
            if missing_symbols:
                formatted = ", ".join(f"{cd}:{name}" for _cdbase, cd, name in missing_symbols)
                raise MathXMLValidationError(
                    "The OpenMath continuity proposition omits operator(s) explicitly named "
                    f"by the statement: {formatted}. A single continuity proposition must "
                    "contain the complete target expression."
                )
            missing_exponents = sorted(required_exponents - best_exponents)
            if missing_exponents:
                missing = ", ".join(str(value) for value in missing_exponents)
                raise MathXMLValidationError(
                    "The OpenMath power expression omits explicit statement exponent(s): "
                    f"{missing}. A single continuity proposition must contain the complete "
                    "target expression."
                )
            missing_literals = sorted(required_literals - best_literals)
            if missing_literals:
                missing = ", ".join(str(value) for value in missing_literals)
                raise MathXMLValidationError(
                    "The OpenMath continuity target omits explicit integer literal(s): "
                    f"{missing}. A single continuity proposition must contain the complete "
                    "target expression."
                )
            missing_edges = sorted(required_operator_literals - best_operator_literals)
            missing = ", ".join(f"{operator}:{value}" for operator, value in missing_edges)
            raise MathXMLValidationError(
                "The OpenMath continuity target omits operator/literal relation(s): "
                f"{missing}. Integer literals must occur as direct arguments of the "
                "corresponding target operator."
            )
        unused_variables = _leading_forall_variables_missing_from_continuity(
            expression,
            parents=parents,
        )
        if unused_variables:
            joined = ", ".join(unused_variables)
            raise MathXMLValidationError(
                "Leading universal variable(s) are not used by any continuity proposition: "
                f"{joined}. A domain predicate already binds continuity points; do not add "
                "redundant point quantifiers from the proof method."
            )
    if continuity_goal is None:
        _validate_non_continuity_implication_premises(
            expression,
            statement=statement,
            parents=parents,
        )
        _validate_named_non_continuity_conclusion(
            expression,
            statement=statement,
            parents=parents,
        )
    _validate_statement_variable_faithfulness(root, statement)


def _validate_non_continuity_implication_premises(
    expression: ET.Element,
    *,
    statement: str,
    parents: dict[ET.Element, ET.Element],
) -> None:
    if not _english_assumption_clauses(statement) and not re.search(
        r"(?:とき|なら|ならば|であれば|仮定)",
        statement,
    ):
        return
    expected = _statement_premise_atoms(statement)
    if not expected:
        return
    candidate = expression
    if _local_name(candidate) == "OMBIND":
        binder, _variables, body = list(candidate)
        if _operator_symbol(binder, parents=parents) == (
            OPENMATH_STANDARD_CDBASE,
            "quant1",
            "forall",
        ):
            candidate = body
    if _local_name(candidate) != "OMA":
        raise MathXMLValidationError(
            "The statement declares assumptions, but OpenMath does not encode an implication."
        )
    operator, *arguments = list(candidate)
    if _operator_symbol(operator, parents=parents) != (
        OPENMATH_STANDARD_CDBASE,
        "logic1",
        "implies",
    ):
        raise MathXMLValidationError(
            "The statement declares assumptions, but OpenMath does not encode an implication."
        )
    actual = _openmath_premise_atoms(arguments[0], parents=parents)
    if actual != expected:
        raise MathXMLValidationError(
            "The OpenMath implication premises do not match the natural-language assumptions."
        )


def _validate_named_non_continuity_conclusion(
    expression: ET.Element,
    *,
    statement: str,
    parents: dict[ET.Element, ET.Element],
) -> None:
    conclusion = expression
    if _local_name(conclusion) == "OMBIND":
        binder, _variables, body = list(conclusion)
        if _operator_symbol(binder, parents=parents) == (
            OPENMATH_STANDARD_CDBASE,
            "quant1",
            "forall",
        ):
            conclusion = body
    implication = _application_arguments(
        conclusion,
        (OPENMATH_STANDARD_CDBASE, "logic1", "implies"),
        parents=parents,
        arity=2,
    )
    if implication is not None:
        conclusion = implication[1]

    if re.search(r"\brank\b.*\bnullity\b.*\b(?:dim|dimension)\b", statement, re.I):
        equality = _application_arguments(
            conclusion,
            (OPENMATH_STANDARD_CDBASE, "relation1", "eq"),
            parents=parents,
            arity=2,
        )
        if equality is None or not _is_rank_nullity_equality(
            equality[0],
            equality[1],
            parents=parents,
        ):
            raise MathXMLValidationError(
                "The OpenMath conclusion does not encode the stated rank-nullity equality."
            )

    image_match = re.search(
        r"\bimage\s+([A-Za-zΑ-Ωα-ω])\s*\(\s*([A-Za-zΑ-Ωα-ω])\s*\)",
        statement,
        re.IGNORECASE,
    )
    if image_match is not None and re.search(r"\bcompact\b", statement, re.I):
        compact = _application_arguments(
            conclusion,
            (PALS_OPENMATH_CDBASE, "pals1", "compact"),
            parents=parents,
            arity=1,
        )
        image = (
            None
            if compact is None
            else _application_arguments(
                compact[0],
                (OPENMATH_STANDARD_CDBASE, "set1", "map"),
                parents=parents,
                arity=2,
            )
        )
        if (
            image is None
            or _openmath_variable_name(image[0]) != image_match.group(1)
            or _openmath_variable_name(image[1]) != image_match.group(2)
        ):
            raise MathXMLValidationError(
                "The OpenMath conclusion does not encode the stated compact image."
            )


def _application_arguments(
    element: ET.Element,
    symbol: _SymbolIdentity,
    *,
    parents: dict[ET.Element, ET.Element],
    arity: int,
) -> tuple[ET.Element, ...] | None:
    if _local_name(element) != "OMA":
        return None
    operator, *arguments = list(element)
    if _operator_symbol(operator, parents=parents) != symbol or len(arguments) != arity:
        return None
    return tuple(arguments)


def _is_rank_nullity_equality(
    left: ET.Element,
    right: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> bool:
    summands = _application_arguments(
        left,
        (OPENMATH_STANDARD_CDBASE, "arith1", "plus"),
        parents=parents,
        arity=2,
    )
    if summands is None:
        return False
    rank = _application_arguments(
        summands[0],
        (PALS_OPENMATH_CDBASE, "pals1", "rank"),
        parents=parents,
        arity=1,
    )
    nullity = _application_arguments(
        summands[1],
        (PALS_OPENMATH_CDBASE, "pals1", "nullity"),
        parents=parents,
        arity=1,
    )
    dimension = _application_arguments(
        right,
        (PALS_OPENMATH_CDBASE, "pals1", "dimension"),
        parents=parents,
        arity=1,
    )
    domain = (
        None
        if dimension is None
        else _application_arguments(
            dimension[0],
            (PALS_OPENMATH_CDBASE, "pals1", "domain"),
            parents=parents,
            arity=1,
        )
    )
    if rank is None or nullity is None or domain is None:
        return False
    names = tuple(_openmath_variable_name(value) for value in (rank[0], nullity[0], domain[0]))
    return names[0] is not None and names[0] == names[1] == names[2]


def _validate_supported_symbol_profile(
    root: ET.Element,
    *,
    enforce_continuity_function_shape: bool = True,
) -> None:
    parents = _openmath_parents(root)
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        symbol = _operator_symbol(element, parents=parents)
        if symbol is None:
            continue
        spec = _SUPPORTED_SYMBOLS.get(symbol)
        if spec is None:
            raise MathXMLValidationError(
                f"`{symbol[1]}:{symbol[2]}` at cdbase `{symbol[0]}` is not in the "
                "supported OpenMath symbol profile."
            )

        usage = _symbol_construction_usage(element, parents)
        if usage is not None and usage != spec.role:
            raise MathXMLValidationError(
                f"`{symbol[1]}:{symbol[2]}` has OpenMath role `{spec.role}` and cannot "
                f"be used with `{usage}` role."
            )

    for application in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMA"):
        operator, *arguments = list(application)
        symbol = _operator_symbol(operator, parents=parents)
        if symbol is None:
            continue
        spec = _SUPPORTED_SYMBOLS.get(symbol)
        if spec is None or spec.role != "application":
            continue
        _validate_symbol_arity(symbol, len(arguments), spec)
        if spec.proposition_arguments:
            for index, argument in enumerate(arguments, start=1):
                if not _is_proposition(argument, parents=parents):
                    raise MathXMLValidationError(
                        f"Argument {index} of `{symbol[1]}:{symbol[2]}` must be a "
                        "predicate/proposition."
                    )

        if enforce_continuity_function_shape and symbol == (
            PALS_OPENMATH_CDBASE,
            "pals1",
            "continuous_on",
        ):
            function = arguments[1]
            if not _is_openmath_function(function, parents=parents):
                raise MathXMLValidationError(
                    "The function argument of `pals1:continuous_on` must be an OMV "
                    "or a term-valued OMBIND with binder `fns1:lambda`; a proposition-valued "
                    "lambda is not a mathematical function term."
                )

    for binding in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMBIND"):
        binder, _variables, body = list(binding)
        symbol = _operator_symbol(binder, parents=parents)
        if symbol is None:
            continue
        spec = _SUPPORTED_SYMBOLS.get(symbol)
        if (
            spec is not None
            and spec.returns_proposition
            and not _is_proposition(body, parents=parents)
        ):
            raise MathXMLValidationError(
                f"The body of `{symbol[1]}:{symbol[2]}` must be a predicate/proposition."
            )


def _symbol_construction_usage(
    symbol: ET.Element,
    parents: dict[ET.Element, ET.Element],
) -> Literal["application", "attribution", "binder", "error"] | None:
    constructed_object = symbol
    parent = parents.get(constructed_object)
    while (
        parent is not None
        and _local_name(parent) == "OMATTR"
        and len(parent) == 2
        and parent[1] is constructed_object
    ):
        constructed_object = parent
        parent = parents.get(constructed_object)

    if parent is None:
        return None
    children = list(parent)
    local_name = _local_name(parent)
    if local_name == "OMA" and children[0] is constructed_object:
        return "application"
    if local_name == "OMBIND" and children[0] is constructed_object:
        return "binder"
    if local_name == "OME" and children[0] is constructed_object:
        return "error"
    if local_name == "OMATP" and any(child is constructed_object for child in children[::2]):
        return "attribution"
    return None


def _validate_symbol_arity(
    symbol: _SymbolIdentity,
    received: int,
    spec: _SymbolSpec,
) -> None:
    minimum = spec.minimum_arity
    maximum = spec.maximum_arity
    if minimum is not None and maximum == minimum and received != minimum:
        requirement = f"exactly {minimum}"
    elif minimum is not None and received < minimum:
        requirement = f"at least {minimum}"
    elif maximum is not None and received > maximum:
        requirement = f"at most {maximum}"
    else:
        return
    raise MathXMLValidationError(
        f"`{symbol[1]}:{symbol[2]}` requires {requirement} argument(s); received {received}."
    )


def _validate_statement_variable_faithfulness(
    root: ET.Element,
    statement: str,
) -> None:
    if _statement_continuity_goal_fragment(statement) is not None:
        statement_variables = _statement_variables(_statement_continuity_target_text(statement))
        statement_variables.update(
            variable
            for _kind, variable, _negated in _statement_premise_atoms(statement)
            if variable != "@point"
        )
    else:
        statement_variables = _statement_variables(statement)
    if _EPSILON_DELTA_METHOD_RE.search(statement) and not _THEOREM_EXISTENCE_RE.search(statement):
        statement_variables.difference_update({"ε", "δ"})
    statement_variables.difference_update(_statement_domain_point_variables(statement))
    statement_variables.difference_update(_statement_function_argument_variables(statement))
    if not statement_variables:
        return
    referenced_variables = _referenced_variable_identities(root)
    expected = len(statement_variables)
    received = len(referenced_variables)
    if received >= expected:
        return
    if received == 0:
        raise MathXMLValidationError(
            "OpenMath expression omits variables present in the statement: "
            f"expected at least {expected} distinct variable identities; found 0."
        )
    variables = ", ".join(sorted(statement_variables))
    raise MathXMLValidationError(
        "OpenMath expression collapses distinct variables from the statement: "
        f"expected at least {expected} identities ({variables}); found {received}."
    )


def _statement_variables(statement: str) -> set[str]:
    matches = list(_STATEMENT_VARIABLE_RE.finditer(statement))
    counts = Counter(match.group("name") for match in matches)
    return {
        match.group("name")
        for match in matches
        if not _is_english_indefinite_article(statement, match, counts)
    }


def _statement_domain_point_variables(statement: str) -> set[str]:
    variable = r"[A-Za-zΑ-Ωα-ω](?:_[A-Za-z0-9]+|[0-9]+)?"
    variables = set(re.findall(rf"0\s*でない点\s*({variable})", statement))
    for match in re.finditer(rf"({variable})\s*(?:≠|!=)\s*0", statement):
        if re.match(r"\s*(?:で|において|上で)\s*連続", statement[match.end() :]):
            variables.add(match.group(1))
    return variables


def _statement_function_argument_variables(statement: str) -> set[str]:
    variable = r"[A-Za-zΑ-Ωα-ω](?:_[A-Za-z0-9]+|[0-9]+)?"
    arguments: set[str] = set()
    for match in re.finditer(rf"{variable}\s*\(\s*({variable})\s*\)", statement):
        arguments.add(match.group(1))
    return arguments


def _is_english_indefinite_article(
    statement: str,
    match: re.Match[str],
    counts: Counter[str],
) -> bool:
    if match.group("name") != "a" or counts["a"] != 1:
        return False
    before_match = re.search(r"([A-Za-z]+)\s+\Z", statement[: match.start()])
    after_match = re.match(r"\s+([A-Za-z]{2,})", statement[match.end() :])
    if after_match is None:
        return False
    previous_word = before_match.group(1).lower() if before_match is not None else ""
    next_word = after_match.group(1).lower()
    if next_word in {"equals", "in", "is"}:
        return False
    return previous_word in {
        "as",
        "be",
        "being",
        "for",
        "from",
        "has",
        "is",
        "of",
        "with",
        "without",
    }


def _referenced_variable_identities(root: ET.Element) -> set[str]:
    identities: set[str] = set()
    free_variables: dict[str, str] = {}
    counter = [0]

    def visit(element: ET.Element, environment: dict[str, str]) -> None:
        local_name = _local_name(element)
        if local_name == "OMV":
            name = element.get("name")
            if name is None:
                return
            identity = environment.get(name)
            if identity is None:
                identity = free_variables.setdefault(name, f"free:{name}")
            identities.add(identity)
            return
        if local_name == "OMBVAR":
            return
        if local_name != "OMBIND":
            for child in element:
                visit(child, environment)
            return

        binder, variables, body = list(element)
        visit(binder, environment)
        body_environment = dict(environment)
        for declaration in variables:
            name = _bound_variable_name(declaration)
            counter[0] += 1
            body_environment[name] = f"bound:{counter[0]}"
        visit(body, body_environment)

    visit(root, {})
    return identities


def _bound_variable_name(declaration: ET.Element) -> str:
    if _local_name(declaration) == "OMV":
        name = declaration.get("name")
        if name is None:
            raise MathXMLValidationError("Bound OMV is missing `name`.")
        return name
    return _bound_variable_name(list(declaration)[1])


def _required_continuity_symbols(statement: str) -> set[_SymbolIdentity]:
    normalized = " ".join(statement.lower().split())
    required: set[_SymbolIdentity] = set()
    if "^" in normalized or "**" in normalized or _SUPERSCRIPT_POWER_RE.search(normalized):
        required.add((OPENMATH_STANDARD_CDBASE, "arith1", "power"))
    if "べき" in normalized or "冪" in normalized or "power" in normalized:
        required.add((OPENMATH_STANDARD_CDBASE, "arith1", "power"))
    if (
        "絶対値" in normalized
        or "absolute value" in normalized
        or re.search(
            r"\|[^|]+\|",
            normalized,
        )
    ):
        required.add((OPENMATH_STANDARD_CDBASE, "arith1", "abs"))
    if (
        "逆数" in normalized
        or "reciprocal" in normalized
        or re.search(
            r"(?:^|\W)1\s*/",
            normalized,
        )
    ):
        required.add((OPENMATH_STANDARD_CDBASE, "arith1", "divide"))
    if "一次関数" in normalized or "affine" in normalized:
        required.update(
            {
                (OPENMATH_STANDARD_CDBASE, "arith1", "plus"),
                (OPENMATH_STANDARD_CDBASE, "arith1", "times"),
            }
        )
    if "+" in normalized:
        required.add((OPENMATH_STANDARD_CDBASE, "arith1", "plus"))
    if re.search(r"(?<!\*)\*(?!\*)", normalized):
        required.add((OPENMATH_STANDARD_CDBASE, "arith1", "times"))
    if re.search(r"(?<=[A-Za-zΑ-Ωα-ω0-9_)])\s*-\s*(?=[A-Za-zΑ-Ωα-ω0-9_(])", normalized):
        required.add((OPENMATH_STANDARD_CDBASE, "arith1", "minus"))
    if re.search(r"の\s*和", normalized) or "sum of" in normalized:
        required.add((OPENMATH_STANDARD_CDBASE, "arith1", "plus"))
    if re.search(r"の\s*積", normalized) or "product of" in normalized:
        required.add((OPENMATH_STANDARD_CDBASE, "arith1", "times"))
    return required


def _statement_continuity_goal_fragment(statement: str) -> str | None:
    japanese_goals = _japanese_continuity_goal_matches(statement)
    if japanese_goals:
        return japanese_goals[0].group(0)
    japanese_final = _JAPANESE_CONTINUITY_FINAL_RE.search(statement)
    if japanese_final is not None:
        return japanese_final.group(0)
    english_final = _ENGLISH_CONTINUITY_FINAL_RE.search(statement)
    if english_final is not None:
        return english_final.group(0)

    for command in _ENGLISH_PROOF_COMMAND_RE.finditer(statement):
        clause = _english_command_conclusion_clause(statement[command.end() :])
        target = _ENGLISH_CONTINUITY_TARGET_RE.search(clause)
        if target is not None:
            return target.group(0)
    if _ENGLISH_ASSUMPTION_START_RE.match(statement):
        clause = _english_command_conclusion_clause(statement)
        target = _ENGLISH_CONTINUITY_TARGET_RE.search(clause)
        if target is not None:
            return target.group(0)
    return None


def _japanese_continuity_goal_matches(statement: str) -> tuple[re.Match[str], ...]:
    matches: list[re.Match[str]] = []
    for match in _JAPANESE_CONTINUITY_TARGET_RE.finditer(statement):
        suffix = statement[match.end() :]
        proof_verb = _JAPANESE_PROOF_VERB_RE.search(suffix)
        if proof_verb is None:
            continue
        before_verb = _JAPANESE_NEGATED_ASSUMPTION_RE.sub(
            "",
            suffix[: proof_verb.start()],
        )
        if not _JAPANESE_ASSUMPTION_FOLLOW_RE.match(
            before_verb
        ) and not _JAPANESE_ASSUMPTION_WORD_RE.search(before_verb):
            matches.append(match)
    return tuple(matches)


def _english_command_conclusion_clause(value: str) -> str:
    clause = value.strip()
    clause = re.sub(r"^that\b", "", clause, count=1, flags=re.IGNORECASE)
    clause = clause.lstrip(" ,:;")
    if _ENGLISH_ASSUMPTION_START_RE.match(clause):
        split = re.split(r"\bthen\b", clause, maxsplit=1, flags=re.IGNORECASE)
        if len(split) == 1:
            split = re.split(r",", clause, maxsplit=1)
        if len(split) > 1:
            return re.sub(
                r"^\s*then\b",
                "",
                split[1],
                count=1,
                flags=re.IGNORECASE,
            ).strip()
        return _ENGLISH_CONTINUITY_ASSUMPTION_RE.sub("", clause)
    return clause


def _statement_continuity_target_function_names(statement: str) -> set[str]:
    variable = r"[A-Za-zΑ-Ωα-ω](?:_[A-Za-z0-9]+|[0-9]+)?"
    names: set[str] = set()
    japanese_boundary = re.compile(
        rf"(?:^|[、,]\s*|において\s*|(?:なら(?:ば)?|とき|であれば)\s*|"
        rf"(?:実数|ℝ)上で\s*|"
        rf"(?:関数|写像)\s*)({variable})\s*(?:が|は)\s*$"
    )
    for goal in _japanese_continuity_goal_matches(statement):
        target = japanese_boundary.search(statement[: goal.start()])
        if target is not None:
            names.add(target.group(1))
    japanese_final = re.search(
        rf"^\s*({variable})\s*(?:が|は)\s*(?:不連続|連続)"
        r"\s*[。.!！?？]?\s*$",
        statement,
    )
    if japanese_final is not None:
        names.add(japanese_final.group(1))
    for command in _ENGLISH_PROOF_COMMAND_RE.finditer(statement):
        clause = _english_command_conclusion_clause(statement[command.end() :])
        match = re.match(
            rf"\s*(?:(?:the\s+)?(?:function|map)\s+)?({variable})"
            r"\s+(?:is|are)\s+(?:not\s+)?continuous\b",
            clause,
            re.IGNORECASE,
        )
        if match is not None:
            names.add(match.group(1))
    final = re.search(
        rf"(?:^|[.!?]\s*|,\s*|\bthen\s+|"
        rf"(?:the\s+)?(?:function|map)\s+)({variable})"
        r"\s+(?:is|are)\s+(?:not\s+)?continuous"
        r"(?:\s+on\b[^,.!?]*)?\s*[.!?]*\s*$",
        statement,
        re.IGNORECASE,
    )
    if final is not None:
        names.add(final.group(1))
    return names


def _statement_continuity_target_text(statement: str) -> str:
    japanese_goals = _japanese_continuity_goal_matches(statement)
    if japanese_goals:
        prefix = statement[: japanese_goals[0].start()]
        clause = re.split(
            r"[、,]|(?:を)?(?:用いて|使って|利用して)",
            prefix,
        )[-1]
        return re.sub(r"\s*(?:が|は)\s*$", "", clause).strip()

    for command in _ENGLISH_PROOF_COMMAND_RE.finditer(statement):
        clause = _english_command_conclusion_clause(statement[command.end() :])
        target = _ENGLISH_CONTINUITY_TARGET_RE.search(clause)
        if target is not None:
            return clause[: target.end()]

    if _ENGLISH_ASSUMPTION_START_RE.match(statement):
        clause = _english_command_conclusion_clause(statement)
        target = _ENGLISH_CONTINUITY_TARGET_RE.search(clause)
        if target is not None:
            return clause[: target.end()]

    japanese_final = _JAPANESE_CONTINUITY_FINAL_RE.search(statement)
    if japanese_final is not None:
        prefix = statement[: japanese_final.start()]
        return re.sub(r"\s*(?:が|は)\s*$", "", prefix).strip()
    if _ENGLISH_CONTINUITY_FINAL_RE.search(statement):
        return re.split(r",|\bthen\b", statement, flags=re.IGNORECASE)[-1].strip()
    return statement


def _statement_power_exponents(statement: str) -> set[int]:
    exponents = {int(match) for match in _POWER_EXPONENT_RE.findall(statement)}
    exponents.update(
        int(match.group(0).translate(_SUPERSCRIPT_DIGITS))
        for match in _SUPERSCRIPT_POWER_RE.finditer(statement)
    )
    return exponents


def _statement_target_integer_literals(statement: str) -> set[int]:
    literals = _statement_power_exponents(statement)
    patterns = (
        r"\+\s*(-?[0-9]+)",
        r"(-?[0-9]+)\s*\+",
        r"(?<!\*)\*\s*(-?[0-9]+)",
        r"(-?[0-9]+)\s*\*(?!\*)",
        r"/\s*(-?[0-9]+)",
        r"(-?[0-9]+)\s*/",
    )
    for pattern in patterns:
        literals.update(int(value) for value in re.findall(pattern, statement))
    return literals


def _openmath_integer_literals(root: ET.Element) -> set[int]:
    literals = {
        _parse_openmath_integer(element.text or "")
        for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMI")
    }
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        if element.get("cd") == "alg1" and element.get("name") == "zero":
            literals.add(0)
        if element.get("cd") == "alg1" and element.get("name") == "one":
            literals.add(1)
    return literals


def _statement_operator_literal_edges(statement: str) -> set[tuple[str, int]]:
    edges: set[tuple[str, int]] = set()
    right_patterns = {
        "plus": r"\+\s*(-?[0-9]+)",
        "times": r"(?<!\*)\*\s*(-?[0-9]+)",
        "divide": r"/\s*(-?[0-9]+)",
        "power": r"(?:\^|\*\*)\s*(-?[0-9]+)",
    }
    for operator, pattern in right_patterns.items():
        edges.update((operator, int(value)) for value in re.findall(pattern, statement))
    left_patterns = {
        "plus": r"(?<![A-Za-z0-9_])(-?[0-9]+)\s*\+",
        "times": r"(?<![A-Za-z0-9_])(-?[0-9]+)\s*\*(?!\*)",
        "divide": r"(?<![A-Za-z0-9_])(-?[0-9]+)\s*/",
    }
    for operator, pattern in left_patterns.items():
        for match in re.finditer(pattern, statement):
            if re.search(r"(?:\^|\*\*)\s*$", statement[: match.start()]):
                continue
            edges.add((operator, int(match.group(1))))
    edges.update(
        ("power", int(match.group(0).translate(_SUPERSCRIPT_DIGITS)))
        for match in _SUPERSCRIPT_POWER_RE.finditer(statement)
    )
    return edges


def _openmath_operator_literal_edges(
    root: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> set[tuple[str, int]]:
    edges: set[tuple[str, int]] = set()
    supported = {"divide", "plus", "power", "times"}
    for application in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMA"):
        operator, *arguments = list(application)
        symbol = _operator_symbol(operator, parents=parents)
        if (
            symbol is None
            or symbol[:2] != (OPENMATH_STANDARD_CDBASE, "arith1")
            or symbol[2] not in supported
        ):
            continue
        for argument in arguments:
            literal = _openmath_integer_literal_value(argument)
            if literal is not None:
                edges.add((symbol[2], literal))
    return edges


def _openmath_integer_literal_value(element: ET.Element) -> int | None:
    if _local_name(element) == "OMI":
        return _parse_openmath_integer(element.text or "")
    if _local_name(element) == "OMS" and element.get("cd") == "alg1":
        if element.get("name") == "zero":
            return 0
        if element.get("name") == "one":
            return 1
    return None


def _arithmetic_shape(operator: str, arguments: list[str]) -> str:
    if operator in {"plus", "times"}:
        flattened: list[str] = []
        prefix = f"{operator}("
        for argument in arguments:
            if argument.startswith(prefix) and argument.endswith(")"):
                flattened.extend(_shape_arguments(argument[len(prefix) : -1]))
            else:
                flattened.append(argument)
        arguments = flattened
    return f"{operator}({','.join(arguments)})"


def _shape_arguments(value: str) -> list[str]:
    arguments: list[str] = []
    depth = 0
    start = 0
    for index, character in enumerate(value):
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        elif character == "," and depth == 0:
            arguments.append(value[start:index])
            start = index + 1
    arguments.append(value[start:])
    return arguments


def _statement_arithmetic_shape(
    statement: str,
    *,
    context_statement: str | None = None,
) -> str | None:
    normalized = _SUPERSCRIPT_POWER_RE.sub(
        lambda match: "^" + match.group(0).translate(_SUPERSCRIPT_DIGITS),
        statement,
    )
    normalized = re.sub(r"\|([^|]+)\|", r"abs(\1)", normalized)
    english_continuity = re.search(
        r"\b(?:is|are)\s+(?:not\s+)?continuous\b",
        normalized,
        re.IGNORECASE,
    )
    if english_continuity is not None:
        normalized = normalized[: english_continuity.start()]
    normalized = re.sub(
        r"^\s*(?:that\s+)?(?:(?:the\s+)?(?:function|map)\s+)?",
        "",
        normalized,
        count=1,
        flags=re.IGNORECASE,
    )
    sources = [normalized]
    expanded_product = re.sub(
        r"(?:the\s+)?product\s+of\s+"
        r"([A-Za-zΑ-Ωα-ω])([A-Za-zΑ-Ωα-ω])"
        r"(?![A-Za-zΑ-Ωα-ω])",
        r"\1*\2",
        normalized,
        flags=re.IGNORECASE,
    )
    expanded_product = re.sub(
        r"(?:[A-Za-zΑ-Ωα-ω]\s*(?:と|[,、])\s*"
        r"[A-Za-zΑ-Ωα-ω]\s*の\s*)?積\s*"
        r"([A-Za-zΑ-Ωα-ω])([A-Za-zΑ-Ωα-ω])"
        r"(?![A-Za-zΑ-Ωα-ω])",
        r"\1*\2",
        expanded_product,
    )
    if expanded_product != normalized:
        sources.append(expanded_product)
    chunks = [
        chunk.strip()
        for source in sources
        for chunk in re.findall(
            r"[A-Za-zΑ-Ωα-ω0-9_+\-*/^()\s]+",
            source,
        )
        if re.search(
            r"\*\*|[+\-*/^]|[A-Za-zΑ-Ωα-ω][A-Za-z0-9_]*\s*\(",
            chunk,
        )
    ]
    chunks.sort(
        key=lambda chunk: (len(re.findall(r"\*\*|[+\-*/^]", chunk)), len(chunk)),
        reverse=True,
    )
    declared_points = _statement_declared_point_variables(
        _statement_point_scope(context_statement or statement)
    )
    for chunk in chunks:
        shape = _parse_arithmetic_shape(chunk, declared_points=declared_points)
        if shape is not None:
            return shape
    return None


def _statement_function_callee_names(statement: str) -> set[str]:
    variable = r"[A-Za-zΑ-Ωα-ω](?:_[A-Za-z0-9]+|[0-9]+)?"
    return set(re.findall(rf"(?<![A-Za-z0-9_])({variable})\s*\(", statement))


def _openmath_function_callee_names(expression: ET.Element) -> set[str]:
    if _local_name(expression) == "OMV":
        name = expression.get("name")
        return {name} if name is not None else set()
    return {
        name
        for application in expression.iter(f"{{{OPENMATH_NAMESPACE}}}OMA")
        if (children := list(application))
        and _local_name(children[0]) == "OMV"
        and (name := children[0].get("name")) is not None
    }


def _direct_function_matches_simple_application(
    expression: ET.Element,
    required_shape: str,
) -> bool:
    if _local_name(expression) != "OMV":
        return False
    name = expression.get("name")
    return name is not None and required_shape == f"apply({name},p:0)"


def _statement_declared_point_variables(statement: str) -> set[str]:
    variable = r"[A-Za-zΑ-Ωα-ω](?:_[A-Za-z0-9]+|[0-9]+)?"
    points = set(
        re.findall(
            rf"(?<![A-Za-z0-9_])({variable})\s*"
            r"(?:について|に関して|を変数として|↦|→|->)",
            statement,
        )
    )
    points.update(
        re.findall(
            rf"\b(?:with\s+respect\s+to|as\s+a\s+function\s+of)\s+({variable})\b",
            statement,
            re.IGNORECASE,
        )
    )
    return points


def _parse_arithmetic_shape(
    expression: str,
    *,
    declared_points: set[str],
) -> str | None:
    compact = re.sub(r"\s+", "", expression)
    tokens = re.findall(
        r"\*\*|[()+\-*/^]|[0-9]+|[A-Za-zΑ-Ωα-ω][A-Za-z0-9_]*",
        compact,
    )
    if "".join(tokens) != compact or not tokens:
        return None
    # Juxtaposition such as `ax` is ambiguous without a real math parser. Leave it to
    # the established operator/literal checks instead of inventing a wrong AST.
    if any(
        len(token) > 1
        and re.fullmatch(r"[A-Za-zΑ-Ωα-ω]+", token)
        and (index + 1 >= len(tokens) or tokens[index + 1] != "(")
        for index, token in enumerate(tokens)
    ):
        return None
    point_names = declared_points | {
        token
        for index, token in enumerate(tokens)
        if 0 < index < len(tokens) - 1
        and tokens[index - 1] == "("
        and tokens[index + 1] == ")"
        and (index < 2 or tokens[index - 2].lower() != "abs")
        and re.fullmatch(r"[A-Za-zΑ-Ωα-ω][A-Za-z0-9_]*", token)
    }
    points = {name: f"p:{index}" for index, name in enumerate(sorted(point_names))}
    variables = {
        name: f"v:{index}"
        for index, name in enumerate(
            sorted(
                {
                    token
                    for index, token in enumerate(tokens)
                    if re.fullmatch(r"[A-Za-zΑ-Ωα-ω][A-Za-z0-9_]*", token)
                    and token not in point_names
                    and (index + 1 >= len(tokens) or tokens[index + 1] != "(")
                }
            )
        )
    }
    position = 0

    def parse_addition() -> str | None:
        nonlocal position
        left = parse_multiplication()
        while left is not None and position < len(tokens) and tokens[position] in {"+", "-"}:
            operator = "plus" if tokens[position] == "+" else "minus"
            position += 1
            right = parse_multiplication()
            if right is None:
                return None
            left = _arithmetic_shape(operator, [left, right])
        return left

    def parse_multiplication() -> str | None:
        nonlocal position
        left = parse_power()
        while left is not None and position < len(tokens) and tokens[position] in {"*", "/"}:
            operator = "times" if tokens[position] == "*" else "divide"
            position += 1
            right = parse_power()
            if right is None:
                return None
            left = _arithmetic_shape(operator, [left, right])
        return left

    def parse_power() -> str | None:
        nonlocal position
        left = parse_primary()
        if left is not None and position < len(tokens) and tokens[position] in {"^", "**"}:
            position += 1
            right = parse_power()
            if right is None:
                return None
            return _arithmetic_shape("power", [left, right])
        return left

    def parse_primary() -> str | None:
        nonlocal position
        if position >= len(tokens):
            return None
        token = tokens[position]
        if token == "-":
            position += 1
            value = parse_primary()
            return None if value is None else f"neg({value})"
        if token == "(":
            position += 1
            value = parse_addition()
            if value is None or position >= len(tokens) or tokens[position] != ")":
                return None
            position += 1
            return value
        position += 1
        if token.isdigit():
            return f"n:{int(token)}"
        if re.fullmatch(r"[A-Za-zΑ-Ωα-ω][A-Za-z0-9_]*", token):
            if position < len(tokens) and tokens[position] == "(":
                position += 1
                argument = parse_addition()
                if argument is None or position >= len(tokens) or tokens[position] != ")":
                    return None
                position += 1
                if token.lower() == "abs":
                    return _arithmetic_shape("abs", [argument])
                return f"apply({token},{argument})"
            return points.get(token, variables.get(token))
        return None

    result = parse_addition()
    return result if result is not None and position == len(tokens) else None


def _openmath_arithmetic_shape(
    expression: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
    variables: dict[str, str] | None = None,
    bound_points: dict[str, str] | None = None,
    erase_point_applications: bool = False,
    explicit_point_markers: bool = False,
) -> str | None:
    if variables is None:
        bound_names = {
            name
            for binding in expression.iter(f"{{{OPENMATH_NAMESPACE}}}OMBIND")
            if len(children := list(binding)) == 3 and _local_name(children[1]) == "OMBVAR"
            for declaration in children[1]
            if (name := declaration.get("name")) is not None
        }
        names = sorted(
            {
                name
                for variable in expression.iter(f"{{{OPENMATH_NAMESPACE}}}OMV")
                if (name := variable.get("name")) is not None and name not in bound_names
            }
        )
        variables = {name: f"v:{index}" for index, name in enumerate(names)}
    if bound_points is None:
        bound_points = {}
    local_name = _local_name(expression)
    if local_name == "OMBIND":
        binder, declarations, body = list(expression)
        if _operator_symbol(binder, parents=parents) == (
            OPENMATH_STANDARD_CDBASE,
            "fns1",
            "lambda",
        ):
            point_names = {
                name: (
                    f"p:{len(bound_points) + index}"
                    if explicit_point_markers
                    else f"v:{len(variables) + len(bound_points) + index}"
                )
                for index, declaration in enumerate(declarations)
                if (name := declaration.get("name")) is not None
            }
            return _openmath_arithmetic_shape(
                body,
                parents=parents,
                variables=variables,
                bound_points={**bound_points, **point_names},
                erase_point_applications=erase_point_applications,
                explicit_point_markers=explicit_point_markers,
            )
        return None
    if local_name == "OMV":
        name = expression.get("name")
        if name is None:
            return None
        return bound_points.get(name, variables.get(name))
    literal = _openmath_integer_literal_value(expression)
    if literal is not None:
        return f"n:{literal}"
    if local_name != "OMA":
        return None
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if (
        symbol is not None
        and symbol[:2]
        == (
            OPENMATH_STANDARD_CDBASE,
            "arith1",
        )
        and symbol[2]
        in {
            "abs",
            "divide",
            "minus",
            "plus",
            "power",
            "times",
            "unary_minus",
        }
    ):
        argument_shapes = [
            _openmath_arithmetic_shape(
                argument,
                parents=parents,
                variables=variables,
                bound_points=bound_points,
                erase_point_applications=erase_point_applications,
                explicit_point_markers=explicit_point_markers,
            )
            for argument in arguments
        ]
        if any(shape is None for shape in argument_shapes):
            return None
        if symbol[2] == "unary_minus":
            return f"neg({argument_shapes[0]})"
        return _arithmetic_shape(
            symbol[2],
            [shape for shape in argument_shapes if shape is not None],
        )
    if _local_name(operator) == "OMV":
        name = operator.get("name")
        if name is None:
            return None
        argument_shapes = [
            _openmath_arithmetic_shape(
                argument,
                parents=parents,
                variables=variables,
                bound_points=bound_points,
                erase_point_applications=erase_point_applications,
                explicit_point_markers=explicit_point_markers,
            )
            for argument in arguments
        ]
        if any(shape is None for shape in argument_shapes):
            return None
        if erase_point_applications and all(
            _local_name(argument) == "OMV" and argument.get("name") in bound_points
            for argument in arguments
        ):
            return variables.get(name)
        return f"apply({name},{','.join(shape for shape in argument_shapes if shape is not None)})"
    return None


def _openmath_integer_power_exponents(
    root: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> set[int]:
    exponents: set[int] = set()
    for application in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMA"):
        operator, *arguments = list(application)
        if _operator_symbol(operator, parents=parents) != (
            OPENMATH_STANDARD_CDBASE,
            "arith1",
            "power",
        ):
            continue
        exponent = arguments[1]
        if _local_name(exponent) == "OMI":
            exponents.add(_parse_openmath_integer(exponent.text or ""))
    return exponents


def _continuity_goal_occurrences(
    expression: ET.Element,
    *,
    statement: str,
    parents: dict[ET.Element, ET.Element],
) -> tuple[tuple[bool, ET.Element], ...]:
    occurrences: list[tuple[bool, ET.Element]] = []
    expected_premises = _statement_premise_atoms(statement)

    def visit(element: ET.Element, negated: bool, premises_checked: bool) -> None:
        if _local_name(element) == "OMBIND":
            binder, _variables, body = list(element)
            symbol = _operator_symbol(binder, parents=parents)
            if not negated and symbol in {
                (OPENMATH_STANDARD_CDBASE, "quant1", "exists"),
                (OPENMATH_STANDARD_CDBASE, "quant1", "forall"),
            }:
                visit(body, negated, premises_checked)
            return
        if _local_name(element) == "OMA":
            operator, *arguments = list(element)
            symbol = _operator_symbol(operator, parents=parents)
            if symbol == (OPENMATH_STANDARD_CDBASE, "logic1", "not"):
                visit(arguments[0], not negated, premises_checked)
                return
            if (
                not negated
                and symbol == (OPENMATH_STANDARD_CDBASE, "logic1", "implies")
                and _constant_proposition_value(arguments[0], parents=parents) is not False
                and _antecedent_matches_statement(
                    arguments[0],
                    statement=statement,
                    parents=parents,
                )
            ):
                visit(arguments[1], negated, True)
                return
            if symbol == (
                PALS_OPENMATH_CDBASE,
                "pals1",
                "continuous_on",
            ):
                domain_premises = _direct_continuity_premise_atoms(
                    element,
                    parents=parents,
                )
                normalized_expected = _normalize_domain_bound_atoms(expected_premises)
                required_domain_premises = {
                    atom for atom in normalized_expected if atom[0] == "domain-nonzero"
                }
                if (
                    domain_premises is not None
                    and premises_checked
                    and domain_premises == required_domain_premises
                ) or (
                    domain_premises is not None
                    and not premises_checked
                    and domain_premises == normalized_expected
                ):
                    occurrences.append((negated, element))
            return

    visit(expression, False, False)
    return tuple(occurrences)


def _direct_continuity_premise_atoms(
    occurrence: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> set[tuple[str, str, bool]] | None:
    _operator, domain, _function = list(occurrence)
    if _operator_symbol(domain, parents=parents) == (
        OPENMATH_STANDARD_CDBASE,
        "setname1",
        "R",
    ):
        return set()
    if _local_name(domain) != "OMA":
        return None
    domain_operator, *domain_arguments = list(domain)
    domain_symbol = _operator_symbol(domain_operator, parents=parents)
    if domain_symbol == (OPENMATH_STANDARD_CDBASE, "set1", "setdiff"):
        if _operator_symbol(domain_arguments[0], parents=parents) == (
            OPENMATH_STANDARD_CDBASE,
            "setname1",
            "R",
        ) and _is_zero_singleton(domain_arguments[1], parents=parents):
            return {("domain-nonzero", "@point", False)}
        return None
    if domain_symbol == (OPENMATH_STANDARD_CDBASE, "set1", "suchthat"):
        predicate = domain_arguments[1]
        if _operator_symbol(domain_arguments[0], parents=parents) == (
            OPENMATH_STANDARD_CDBASE,
            "setname1",
            "R",
        ) and _lambda_is_nonzero_predicate(predicate, parents=parents):
            return {("domain-nonzero", "@point", False)}
    return None


def _normalize_domain_bound_atoms(
    atoms: set[tuple[str, str, bool]],
) -> set[tuple[str, str, bool]]:
    return {
        (kind, "@point" if kind == "domain-nonzero" else variable, negated)
        for kind, variable, negated in atoms
    }


def _is_zero_singleton(
    expression: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> bool:
    if _local_name(expression) != "OMA":
        return False
    operator, *arguments = list(expression)
    return (
        _operator_symbol(operator, parents=parents) == (OPENMATH_STANDARD_CDBASE, "set1", "set")
        and len(arguments) == 1
        and _is_zero_omi(arguments[0])
    )


def _lambda_is_nonzero_predicate(
    expression: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> bool:
    if _local_name(expression) != "OMBIND":
        return False
    binder, variables, body = list(expression)
    if (
        _operator_symbol(binder, parents=parents)
        != (
            OPENMATH_STANDARD_CDBASE,
            "fns1",
            "lambda",
        )
        or len(variables) != 1
        or _local_name(body) != "OMA"
    ):
        return False
    variable = _openmath_variable_name(list(variables)[0])
    operator, *arguments = list(body)
    return (
        variable is not None
        and _operator_symbol(operator, parents=parents)
        == (OPENMATH_STANDARD_CDBASE, "relation1", "neq")
        and _variable_compared_with_zero(arguments) == variable
    )


def _antecedent_matches_statement(
    antecedent: ET.Element,
    *,
    statement: str,
    parents: dict[ET.Element, ET.Element],
) -> bool:
    actual = _openmath_premise_atoms(antecedent, parents=parents)
    if actual is None:
        return False
    expected = _statement_premise_atoms(statement)
    required = {atom for atom in expected if atom[0] != "domain-nonzero"}
    domain_mirrors = {
        ("nonzero", variable, negated)
        for kind, variable, negated in expected
        if kind == "domain-nonzero"
    }
    return actual == required or actual == required | domain_mirrors


def _statement_premise_atoms(statement: str) -> set[tuple[str, str, bool]]:
    atoms: set[tuple[str, str, bool]] = set()
    premise_statement = _JAPANESE_NEGATED_ASSUMPTION_RE.sub(
        "",
        _statement_premise_scope(statement),
    )
    power_statement = (
        _statement_continuity_target_text(premise_statement)
        if _statement_continuity_goal_fragment(premise_statement) is not None
        else premise_statement
    )
    variable = r"[A-Za-zΑ-Ωα-ω](?:_[A-Za-z0-9]+|[0-9]+)?"
    variable_list = rf"{variable}(?:\s*(?:[,、]|と|\band\b)\s*{variable})*"

    for name in re.findall(rf"(?:\^|\*\*)\s*({variable})", power_statement):
        kind = "real" if _statement_declares_real_variable(premise_statement, name) else "natural"
        atoms.add((kind, name, False))
    for match in re.finditer(rf"実数係数\s+({variable_list})", premise_statement):
        for name in _premise_variable_names(match.group(1)):
            atoms.add(("real", name, False))
    for match in re.finditer(
        rf"実数値\s*(?<!不)連続関数\s+({variable_list})",
        premise_statement,
    ):
        for name in _premise_variable_names(match.group(1)):
            atoms.add(("continuous", name, False))
            atoms.add(("real-valued", name, False))
    for match in re.finditer(
        rf"(?<!不)連続関数\s+({variable_list})",
        premise_statement,
    ):
        for name in _premise_variable_names(match.group(1)):
            atoms.add(("continuous", name, False))
    for match in re.finditer(rf"不連続関数\s+({variable_list})", premise_statement):
        for name in _premise_variable_names(match.group(1)):
            atoms.add(("continuous", name, True))
    for match in re.finditer(
        rf"({variable})\s*が\s*(不)?連続(?:である)?"
        r"(?:とき|なら|ならば|であれば|ことを[^、,]*仮定)",
        premise_statement,
    ):
        atoms.add(("continuous", match.group(1), match.group(2) is not None))
    for match in re.finditer(rf"0\s*でない点\s*({variable})", premise_statement):
        atoms.add(("domain-nonzero", match.group(1), False))
    for match in re.finditer(rf"({variable})\s*(?:≠|!=)\s*0", premise_statement):
        suffix = premise_statement[match.end() :]
        kind = (
            "domain-nonzero" if re.match(r"\s*(?:で|において|上で)\s*連続", suffix) else "nonzero"
        )
        atoms.add((kind, match.group(1), False))
    for clause in _english_assumption_clauses(statement):
        for match in re.finditer(
            rf"(?<![A-Za-z0-9_])({variable_list})(?![A-Za-z0-9_])"
            r"\s+(?:is|are)\s+real\b",
            clause,
            re.IGNORECASE,
        ):
            for name in _premise_variable_names(match.group(1)):
                atoms.add(("real", name, False))
        for match in re.finditer(
            rf"(?<![A-Za-z0-9_])({variable_list})(?![A-Za-z0-9_])"
            r"\s+(?:is|are)\s+(?:a\s+)?natural(?:\s+numbers?)?\b",
            clause,
            re.IGNORECASE,
        ):
            for name in _premise_variable_names(match.group(1)):
                atoms.add(("natural", name, False))
        for match in re.finditer(
            rf"(?<![A-Za-z0-9_])({variable_list})(?![A-Za-z0-9_])"
            r"\s+(?:is|are)\s+(?:a\s+)?(not\s+)?continuous\b",
            clause,
            re.IGNORECASE,
        ):
            for name in _premise_variable_names(match.group(1)):
                atoms.add(("continuous", name, match.group(2) is not None))
        for match in re.finditer(
            rf"(?<![A-Za-z0-9_])({variable_list})(?![A-Za-z0-9_])"
            r"\s+(?:is|are)\s+(?:a\s+)?continuous\s+real-valued"
            r"(?:\s+functions?)?\b",
            clause,
            re.IGNORECASE,
        ):
            for name in _premise_variable_names(match.group(1)):
                atoms.add(("real-valued", name, False))
        for match in re.finditer(
            rf"(?<![A-Za-z0-9_])({variable_list})(?![A-Za-z0-9_])"
            r"\s+(?:is|are)\s+compact\b",
            clause,
            re.IGNORECASE,
        ):
            for name in _premise_variable_names(match.group(1)):
                atoms.add(("compact", name, False))
        for match in re.finditer(
            rf"(?<![A-Za-z0-9_])({variable})(?![A-Za-z0-9_])"
            r"\s+is\s+a\s+linear\s+map\b",
            clause,
            re.IGNORECASE,
        ):
            atoms.add(("linear-map", match.group(1), False))
        for match in re.finditer(
            rf"\bdomain\s+(?:of\s+)?({variable})(?![A-Za-z0-9_])"
            r"\s+is\s+finite-dimensional\b",
            clause,
            re.IGNORECASE,
        ):
            atoms.add(("finite-dimensional-domain", match.group(1), False))
        for match in re.finditer(
            rf"(?:the\s+)?continuity\s+of\s+"
            rf"(?<![A-Za-z0-9_])({variable_list})(?![A-Za-z0-9_])",
            clause,
            re.IGNORECASE,
        ):
            for name in _premise_variable_names(match.group(1)):
                atoms.add(("continuous", name, False))
    if re.search(
        r"\bcontinuous\s+on\s+(?:ℝ|R)\s*(?:\\|∖)\s*\{\s*0\s*\}",
        statement,
        re.IGNORECASE,
    ):
        atoms.add(("domain-nonzero", "@point", False))
    return atoms


def _statement_premise_scope(statement: str) -> str:
    if _statement_continuity_goal_fragment(statement) is None:
        return statement
    commands = list(_ENGLISH_PROOF_COMMAND_RE.finditer(statement))
    if not commands and _ENGLISH_ASSUMPTION_START_RE.match(statement):
        return " ".join(
            (
                _statement_continuity_target_text(statement),
                *_english_assumption_clauses(statement),
            )
        )
    if commands:
        command = commands[-1]
        parts = [_statement_continuity_target_text(statement)]
        parts.extend(_english_assumption_clauses(statement))
        prefix = statement[: command.start()].strip(" ,:;.!?")
        point_declarations = list(
            re.finditer(
                r"(?:^|[,.!?])\s*"
                r"((?:with\s+respect\s+to|as\s+a\s+function\s+of)\s+"
                r"[A-Za-zΑ-Ωα-ω](?:_[A-Za-z0-9]+|[0-9]+)?)\b",
                prefix,
                re.IGNORECASE,
            )
        )
        if point_declarations:
            parts.append(point_declarations[-1].group(1))
        target_clause = _english_command_conclusion_clause(statement[command.end() :])
        trailing_point = re.search(
            r"\b(?:is|are)\s+(?:not\s+)?continuous\s+"
            r"((?:with\s+respect\s+to|as\s+a\s+function\s+of)\s+"
            r"[A-Za-zΑ-Ωα-ω](?:_[A-Za-z0-9]+|[0-9]+)?)\b",
            target_clause,
            re.IGNORECASE,
        )
        if trailing_point is not None:
            parts.append(trailing_point.group(1))
        return " ".join(part for part in parts if part)
    japanese_goals = _japanese_continuity_goal_matches(statement)
    scope = statement[: japanese_goals[0].end()] if japanese_goals else statement
    return re.sub(
        r"(?:^|[、,])[^、,]*(?:を)?(?:用いて|使って|利用して)[、,]?",
        "",
        scope,
    )


def _statement_point_scope(statement: str) -> str:
    commands = list(_ENGLISH_PROOF_COMMAND_RE.finditer(statement))
    if not commands:
        if _ENGLISH_ASSUMPTION_START_RE.match(statement):
            target_clause = _english_command_conclusion_clause(statement)
            parts = [_statement_continuity_target_text(statement)]
            trailing_point = re.search(
                r"\b(?:is|are)\s+(?:not\s+)?continuous\s+"
                r"((?:with\s+respect\s+to|as\s+a\s+function\s+of)\s+"
                r"[A-Za-zΑ-Ωα-ω](?:_[A-Za-z0-9]+|[0-9]+)?)\b",
                target_clause,
                re.IGNORECASE,
            )
            if trailing_point is not None:
                parts.append(trailing_point.group(1))
            return " ".join(parts)
        return _statement_premise_scope(statement)
    command = commands[-1]
    parts = [_statement_continuity_target_text(statement)]
    prefix = statement[: command.start()].strip(" ,:;.!?")
    point_declarations = list(
        re.finditer(
            r"(?:^|[,.!?])\s*"
            r"((?:with\s+respect\s+to|as\s+a\s+function\s+of)\s+"
            r"[A-Za-zΑ-Ωα-ω](?:_[A-Za-z0-9]+|[0-9]+)?)\b",
            prefix,
            re.IGNORECASE,
        )
    )
    if point_declarations:
        parts.append(point_declarations[-1].group(1))
    target_clause = _english_command_conclusion_clause(statement[command.end() :])
    trailing_point = re.search(
        r"\b(?:is|are)\s+(?:not\s+)?continuous\s+"
        r"((?:with\s+respect\s+to|as\s+a\s+function\s+of)\s+"
        r"[A-Za-zΑ-Ωα-ω](?:_[A-Za-z0-9]+|[0-9]+)?)\b",
        target_clause,
        re.IGNORECASE,
    )
    if trailing_point is not None:
        parts.append(trailing_point.group(1))
    return " ".join(parts)


def _premise_variable_names(value: str) -> tuple[str, ...]:
    return tuple(match.group("name") for match in _STATEMENT_VARIABLE_RE.finditer(value))


def _statement_declares_real_variable(statement: str, variable: str) -> bool:
    escaped = re.escape(variable)
    return bool(
        re.search(
            rf"(?:任意の\s*)?実数\s*{escaped}(?![A-Za-z0-9_])|"
            rf"(?<![A-Za-z0-9_]){escaped}\s*(?:は|が)?\s*実数|"
            rf"(?<![A-Za-z0-9_]){escaped}\s*∈\s*(?:ℝ|R\b)|"
            rf"\b(?:real(?:\s+number)?\s+{escaped}|{escaped}\s+is\s+real)\b",
            statement,
            re.IGNORECASE,
        )
    )


def _english_assumption_clauses(statement: str) -> tuple[str, ...]:
    clauses: list[str] = []
    pattern = re.compile(
        r"\b(?:if|assuming|given(?:\s+that)?|"
        r"under\s+the\s+assumption(?:\s+(?:that|of))?)\b"
        r"(?P<body>.*?)(?=,\s*(?:then|show|prove)\b|"
        r"\bthen\b|\bshow\b|\bprove\b|[.;]|$)",
        re.IGNORECASE,
    )
    for match in pattern.finditer(statement):
        body = match.group("body")
        if not re.search(
            r"\b(?:then|show|prove)\b",
            statement[match.start() :],
            re.IGNORECASE,
        ):
            body = body.split(",", maxsplit=1)[0]
        clauses.append(body)
    variable = r"[A-Za-zΑ-Ωα-ω](?:_[A-Za-z0-9]+|[0-9]+)?"
    variable_list = rf"{variable}(?:\s*(?:,|\band\b)\s*{variable})*"
    for command in _ENGLISH_PROOF_COMMAND_RE.finditer(statement):
        prefix = statement[: command.start()].strip(" ,:;.!?")
        declarations = (
            rf"^for\s+continuous\s+(?P<leading>{variable_list})$|"
            rf"^for\s+(?P<trailing>{variable_list})\s+continuous$|"
            rf"^let\s+(?P<let>{variable_list})\s+be\s+continuous$"
        )
        for segment in re.split(r"[.!?]", prefix):
            segment = re.split(
                r",\s*(?:using|by|with)\b",
                segment,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0]
            declaration = re.match(
                declarations,
                segment.strip(" ,:;"),
                re.IGNORECASE,
            )
            if declaration is not None:
                names = next(value for value in declaration.groupdict().values() if value)
                clauses.append(f"{names} are continuous")
        break
    return tuple(clauses)


def _openmath_premise_atoms(
    antecedent: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> set[tuple[str, str, bool]] | None:
    atoms: set[tuple[str, str, bool]] = set()

    def visit(element: ET.Element, negated: bool) -> bool:
        symbol = _operator_symbol(element, parents=parents)
        if symbol == (OPENMATH_STANDARD_CDBASE, "logic1", "true"):
            return not negated
        if _local_name(element) != "OMA":
            return False
        operator, *arguments = list(element)
        symbol = _operator_symbol(operator, parents=parents)
        if symbol == (OPENMATH_STANDARD_CDBASE, "logic1", "and") and not negated:
            return all(visit(argument, False) for argument in arguments)
        if symbol == (OPENMATH_STANDARD_CDBASE, "logic1", "not"):
            return visit(arguments[0], not negated)
        if symbol == (PALS_OPENMATH_CDBASE, "pals1", "continuous_on"):
            name = _openmath_variable_name(arguments[1])
            if name is None:
                return False
            atoms.add(("continuous", name, negated))
            return True
        if symbol == (OPENMATH_STANDARD_CDBASE, "set1", "in"):
            name = _openmath_variable_name(arguments[0])
            codomain = _operator_symbol(arguments[1], parents=parents)
            if name is None or negated:
                return False
            if codomain == (OPENMATH_STANDARD_CDBASE, "setname1", "N"):
                atoms.add(("natural", name, False))
                return True
            if codomain == (OPENMATH_STANDARD_CDBASE, "setname1", "R"):
                atoms.add(("real", name, False))
                return True
            return False
        if symbol == (OPENMATH_STANDARD_CDBASE, "set1", "subset"):
            name = _mapped_variable_name(arguments[0], parents=parents)
            target = _operator_symbol(arguments[1], parents=parents)
            if name is None or negated or target != (OPENMATH_STANDARD_CDBASE, "setname1", "R"):
                return False
            atoms.add(("real-valued", name, False))
            return True
        if symbol == (PALS_OPENMATH_CDBASE, "pals1", "compact"):
            name = _openmath_variable_name(arguments[0])
            if name is None:
                return False
            atoms.add(("compact", name, negated))
            return True
        if symbol == (PALS_OPENMATH_CDBASE, "pals1", "linear_map"):
            name = _openmath_variable_name(arguments[0])
            if name is None or negated:
                return False
            atoms.add(("linear-map", name, False))
            return True
        if symbol == (PALS_OPENMATH_CDBASE, "pals1", "finite_dimensional"):
            domain = arguments[0]
            if _local_name(domain) != "OMA" or negated:
                return False
            domain_operator, *domain_arguments = list(domain)
            if _operator_symbol(domain_operator, parents=parents) != (
                PALS_OPENMATH_CDBASE,
                "pals1",
                "domain",
            ):
                return False
            name = _openmath_variable_name(domain_arguments[0])
            if name is None:
                return False
            atoms.add(("finite-dimensional-domain", name, False))
            return True
        if symbol == (OPENMATH_STANDARD_CDBASE, "relation1", "neq"):
            name = _variable_compared_with_zero(arguments)
            if name is None:
                return False
            atoms.add(("nonzero", name, negated))
            return True
        return False

    if not visit(antecedent, False):
        return None
    return atoms


def _openmath_variable_name(element: ET.Element) -> str | None:
    if _local_name(element) != "OMV":
        return None
    return element.get("name")


def _mapped_variable_name(
    element: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> str | None:
    if _local_name(element) != "OMA":
        return None
    operator, *arguments = list(element)
    if _operator_symbol(operator, parents=parents) != (
        OPENMATH_STANDARD_CDBASE,
        "set1",
        "map",
    ):
        return None
    return _openmath_variable_name(arguments[0])


def _variable_compared_with_zero(arguments: list[ET.Element]) -> str | None:
    left, right = arguments
    if _openmath_variable_name(left) is not None and _is_zero_omi(right):
        return _openmath_variable_name(left)
    if _openmath_variable_name(right) is not None and _is_zero_omi(left):
        return _openmath_variable_name(right)
    return None


def _is_zero_omi(element: ET.Element) -> bool:
    return _local_name(element) == "OMI" and _parse_openmath_integer(element.text or "") == 0


def _constant_proposition_value(
    expression: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> bool | None:
    symbol = _operator_symbol(expression, parents=parents)
    if symbol == (OPENMATH_STANDARD_CDBASE, "logic1", "true"):
        return True
    if symbol == (OPENMATH_STANDARD_CDBASE, "logic1", "false"):
        return False
    if _local_name(expression) == "OMBIND":
        binder, _variables, body = list(expression)
        binder_symbol = _operator_symbol(binder, parents=parents)
        if binder_symbol in {
            (OPENMATH_STANDARD_CDBASE, "quant1", "exists"),
            (OPENMATH_STANDARD_CDBASE, "quant1", "forall"),
        }:
            return _constant_proposition_value(body, parents=parents)
        return None
    if _local_name(expression) != "OMA":
        return None

    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    values = [_constant_proposition_value(argument, parents=parents) for argument in arguments]
    if symbol == (OPENMATH_STANDARD_CDBASE, "logic1", "not"):
        return None if values[0] is None else not values[0]
    if symbol in {
        (OPENMATH_STANDARD_CDBASE, "logic1", "and"),
        (OPENMATH_STANDARD_CDBASE, "logic1", "nand"),
    }:
        value = False if False in values else True if all(values) else None
        if symbol[2] == "nand" and value is not None:
            return not value
        return value
    if symbol in {
        (OPENMATH_STANDARD_CDBASE, "logic1", "or"),
        (OPENMATH_STANDARD_CDBASE, "logic1", "nor"),
    }:
        value = (
            True if True in values else False if all(value is False for value in values) else None
        )
        if symbol[2] == "nor" and value is not None:
            return not value
        return value
    if symbol == (OPENMATH_STANDARD_CDBASE, "logic1", "implies"):
        antecedent, consequent = values
        if antecedent is False or consequent is True:
            return True
        if antecedent is True and consequent is not None:
            return consequent
        return None
    if symbol in {
        (OPENMATH_STANDARD_CDBASE, "logic1", "equivalent"),
        (OPENMATH_STANDARD_CDBASE, "logic1", "xnor"),
        (OPENMATH_STANDARD_CDBASE, "logic1", "xor"),
    } and all(value is not None for value in values):
        truth_count = sum(value is True for value in values)
        if symbol[2] == "xor":
            return truth_count % 2 == 1
        if symbol[2] == "xnor":
            return truth_count % 2 == 0
        return values[0] == values[1]
    if symbol is not None and symbol[:2] == (
        OPENMATH_STANDARD_CDBASE,
        "relation1",
    ):
        return _constant_relation_value(symbol[2], arguments)
    return None


def _constant_relation_value(
    relation: str,
    arguments: list[ET.Element],
) -> bool | None:
    left, right = arguments
    left_xml = ET.canonicalize(ET.tostring(left, encoding="unicode"))
    right_xml = ET.canonicalize(ET.tostring(right, encoding="unicode"))
    if left_xml == right_xml:
        return relation in {"eq", "geq", "leq"}
    if _local_name(left) != "OMI" or _local_name(right) != "OMI":
        return None
    left_value = _parse_openmath_integer(left.text or "")
    right_value = _parse_openmath_integer(right.text or "")
    comparisons = {
        "eq": left_value == right_value,
        "geq": left_value >= right_value,
        "gt": left_value > right_value,
        "leq": left_value <= right_value,
        "lt": left_value < right_value,
        "neq": left_value != right_value,
    }
    return comparisons.get(relation)


def _parse_openmath_integer(value: str) -> int:
    normalized = "".join(value.split())
    sign = -1 if normalized.startswith("-") else 1
    unsigned = normalized[1:] if sign == -1 else normalized
    if unsigned.startswith("x"):
        return sign * int(unsigned[1:], 16)
    return sign * int(unsigned, 10)


def _leading_forall_variables_missing_from_continuity(
    expression: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> tuple[str, ...]:
    environment: dict[str, str] = {}
    leading_names: dict[str, str] = {}
    current = expression
    counter = [0]

    while _local_name(current) == "OMBIND":
        binder, variables, body = list(current)
        if _operator_symbol(binder, parents=parents) != (
            OPENMATH_STANDARD_CDBASE,
            "quant1",
            "forall",
        ):
            break
        for declaration in variables:
            name = _bound_variable_name(declaration)
            identity = f"leading:{counter[0]}"
            counter[0] += 1
            environment[name] = identity
            leading_names[identity] = name
        current = body

    if not leading_names:
        return ()

    used_by_continuity: set[str] = set()

    def collect_references(element: ET.Element, scope: dict[str, str]) -> None:
        local_name = _local_name(element)
        if local_name == "OMV":
            name = element.get("name")
            if name is not None and name in scope:
                used_by_continuity.add(scope[name])
            return
        if local_name == "OMBVAR":
            return
        if local_name == "OMBIND":
            _binder, variables, body = list(element)
            nested_scope = dict(scope)
            for declaration in variables:
                name = _bound_variable_name(declaration)
                nested_scope[name] = f"nested:{counter[0]}"
                counter[0] += 1
            collect_references(body, nested_scope)
            return
        for child in element:
            collect_references(child, scope)

    def find_continuity(element: ET.Element, scope: dict[str, str]) -> None:
        local_name = _local_name(element)
        if local_name == "OMBIND":
            _binder, variables, body = list(element)
            nested_scope = dict(scope)
            for declaration in variables:
                name = _bound_variable_name(declaration)
                nested_scope[name] = f"nested:{counter[0]}"
                counter[0] += 1
            find_continuity(body, nested_scope)
            return
        if local_name == "OMA":
            operator, *_arguments = list(element)
            if _operator_symbol(operator, parents=parents) == (
                PALS_OPENMATH_CDBASE,
                "pals1",
                "continuous_on",
            ):
                collect_references(element, scope)
                return
        for child in element:
            find_continuity(child, scope)

    find_continuity(current, environment)
    return tuple(
        leading_names[identity] for identity in leading_names if identity not in used_by_continuity
    )


def _is_openmath_function(
    element: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> bool:
    local_name = _local_name(element)
    if local_name == "OMV":
        return True
    if local_name != "OMBIND":
        return False
    binder, _variables, body = list(element)
    return _operator_symbol(binder, parents=parents) == (
        OPENMATH_STANDARD_CDBASE,
        "fns1",
        "lambda",
    ) and not _is_proposition(body, parents=parents)


def _structural_features(root: ET.Element) -> Counter[str]:
    features: Counter[str] = Counter()
    parents = _openmath_parents(root)
    for element in root.iter():
        local_name = _local_name(element)
        features[f"kind:{local_name}"] += 1
        if local_name == "OMS":
            symbol = _operator_symbol(element, parents=parents)
            if symbol is not None:
                features[f"symbol:{symbol!r}"] += 2
        elif local_name == "OMI":
            features[f"integer:{''.join((element.text or '').split())}"] += 3

        if local_name == "OMA":
            operator, *arguments = list(element)
            operator_symbol = _operator_symbol(operator, parents=parents)
            if operator_symbol is not None:
                features[f"operator:{operator_symbol!r}"] += 5
                argument_kinds = ",".join(_local_name(argument) for argument in arguments)
                features[f"operator-shape:{operator_symbol!r}:{argument_kinds}"] += 12
                for index, argument in enumerate(arguments):
                    kind = _local_name(argument)
                    features[f"argument-kind:{operator_symbol!r}:{index}:{kind}"] += 8
                    literal = _literal_signature(argument)
                    if literal is not None:
                        features[f"argument-literal:{operator_symbol!r}:{index}:{literal}"] += 10
        elif local_name == "OMBIND":
            binder, variables, _body = list(element)
            binder_symbol = _operator_symbol(binder, parents=parents)
            if binder_symbol is not None:
                features[f"binder:{binder_symbol!r}"] += 5
            features[f"bound-count:{len(variables)}"] += 4

        if local_name in {"OMA", "OMATTR", "OMBIND"}:
            features[f"subtree:{_shape_signature(element, parents=parents)}"] += 8
    return features


def _shape_signature(
    element: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> str:
    local_name = _local_name(element)
    if local_name == "OMS":
        return f"OMS({_operator_symbol(element, parents=parents)!r})"
    if local_name == "OMV":
        return "OMV"
    literal = _literal_signature(element)
    if literal is not None:
        return f"{local_name}({literal})"
    children = ",".join(_shape_signature(child, parents=parents) for child in element)
    return f"{local_name}({children})"


def _literal_signature(element: ET.Element) -> str | None:
    local_name = _local_name(element)
    if local_name == "OMI":
        return "".join((element.text or "").split())
    if local_name == "OMF":
        if element.get("dec") is not None:
            return f"dec:{element.get('dec')}"
        return f"hex:{element.get('hex')}"
    return None


def validate_omdoc_xml(xml: str) -> ET.Element:
    root = _parse_xml(xml, document_type="OMDoc")
    if root.tag != _OMDOC_ROOT:
        raise MathXMLValidationError(
            f"OMDoc root must be `omdoc` in namespace `{OMDOC_NAMESPACE}`."
        )
    if root.get("version") != "1.2":
        raise MathXMLValidationError('OMDoc root must declare version="1.2".')

    parents = {child: parent for parent in root.iter() for child in parent}
    for element in root.iter():
        namespace, local_name = _split_tag(element.tag)
        if namespace == DUBLIN_CORE_NAMESPACE:
            if not _has_ancestor(element, parents, _OMDOC_METADATA):
                raise MathXMLValidationError(
                    "Dublin Core elements are only allowed inside OMDoc metadata."
                )
            continue
        if namespace not in {OMDOC_NAMESPACE, OPENMATH_NAMESPACE}:
            raise MathXMLValidationError(
                f"Unexpected namespace `{namespace or '(none)'}` on `{local_name}`."
            )

    openmath_root = _validate_omdoc_application_profile(root)
    _validate_openmath_tree(openmath_root)
    _validate_supported_symbol_profile(openmath_root)
    if not _is_proposition(
        list(openmath_root)[0],
        parents=_openmath_parents(openmath_root),
    ):
        raise MathXMLValidationError(
            "OMDoc FMP OpenMath object must encode a predicate/proposition."
        )
    _validate_ids_and_local_references(root)
    return root


def _validate_omdoc_application_profile(root: ET.Element) -> ET.Element:
    _require_container_whitespace(root, "OMDoc root")
    root_children = list(root)
    child_index = 0
    if root_children and root_children[0].tag == _OMDOC_METADATA:
        _validate_omdoc_metadata(root_children[0])
        child_index = 1
    if len(root_children) != child_index + 1 or root_children[child_index].tag != _OMDOC_THEORY:
        raise MathXMLValidationError(
            "Supported OMDoc must contain optional metadata followed by exactly one theory."
        )

    theory = root_children[child_index]
    _require_container_whitespace(theory, "OMDoc theory")
    theory_children = list(theory)
    if len(theory_children) != 1 or theory_children[0].tag != _OMDOC_ASSERTION:
        raise MathXMLValidationError(
            "Supported OMDoc theory must contain exactly one direct assertion."
        )

    assertion = theory_children[0]
    _require_container_whitespace(assertion, "OMDoc assertion")
    assertion_children = list(assertion)
    if assertion_children and assertion_children[0].tag == _OMDOC_CMP:
        if list(assertion_children[0]):
            raise MathXMLValidationError("Supported OMDoc CMP must contain text only.")
        assertion_children = assertion_children[1:]
    if len(assertion_children) != 1 or assertion_children[0].tag != _OMDOC_FMP:
        raise MathXMLValidationError(
            "Supported OMDoc assertion must contain optional CMP followed by exactly one FMP."
        )

    fmp = assertion_children[0]
    _require_container_whitespace(fmp, "OMDoc FMP")
    fmp_children = list(fmp)
    if len(fmp_children) != 1 or fmp_children[0].tag != _OPENMATH_ROOT:
        raise MathXMLValidationError(
            "Supported OMDoc FMP must contain exactly one direct OpenMath OMOBJ."
        )
    openmath_root = fmp_children[0]
    all_openmath_roots = list(root.iter(_OPENMATH_ROOT))
    if len(all_openmath_roots) != 1 or all_openmath_roots[0] is not openmath_root:
        raise MathXMLValidationError(
            "Supported OMDoc must contain exactly one OpenMath OMOBJ, directly under FMP."
        )
    return openmath_root


def _validate_omdoc_metadata(metadata: ET.Element) -> None:
    _require_container_whitespace(metadata, "OMDoc metadata")
    for element in metadata.iter():
        if element is metadata:
            continue
        namespace, local_name = _split_tag(element.tag)
        if namespace != DUBLIN_CORE_NAMESPACE:
            raise MathXMLValidationError(
                "Supported OMDoc metadata may contain only Dublin Core elements; "
                f"received `{local_name}` in `{namespace or '(none)'}`."
            )


def _require_container_whitespace(element: ET.Element, label: str) -> None:
    if (element.text or "").strip() or any((child.tail or "").strip() for child in element):
        raise MathXMLValidationError(f"{label} must not contain mixed text content.")


def extract_omdoc_draft_relations(xml: str) -> tuple[tuple[str, str], ...]:
    root = validate_omdoc_xml(xml)
    relations: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for element in root.iter(_DUBLIN_CORE_RELATION):
        value = (element.text or "").strip()
        match = _DRAFT_RELATION_RE.fullmatch(value)
        if match is None:
            raise MathXMLValidationError(
                "OMDoc dc:relation must use "
                "`urn:pals:draft-relation:<predicate>:<target-draft-id>`."
            )
        relation = (match.group(1), match.group(2))
        if relation[0] not in DRAFT_RELATION_PREDICATES:
            allowed = ", ".join(sorted(DRAFT_RELATION_PREDICATES))
            raise MathXMLValidationError(
                f"Unknown OMDoc Draft relation predicate `{relation[0]}`. "
                f"Allowed predicates: {allowed}."
            )
        if relation in seen:
            raise MathXMLValidationError(f"Duplicate OMDoc dc:relation `{value}`.")
        seen.add(relation)
        relations.append(relation)
    return tuple(relations)


def canonicalize_omdoc_xml(xml: str) -> str:
    root = validate_omdoc_xml(xml)
    canonical_root = copy.deepcopy(root)
    for openmath_root in canonical_root.iter(_OPENMATH_ROOT):
        _alpha_normalize_openmath_tree(openmath_root)
    _remove_ignorable_whitespace(canonical_root)
    serialized = ET.tostring(canonical_root, encoding="unicode")
    return ET.canonicalize(serialized)


def extract_omdoc_openmath_xml(xml: str) -> tuple[str, ...]:
    root = validate_omdoc_xml(xml)
    return tuple(
        canonicalize_openmath_xml(ET.tostring(element, encoding="unicode"))
        for element in root.iter(_OPENMATH_ROOT)
    )


def _parse_xml(xml: str, *, document_type: str) -> ET.Element:
    stripped = xml.strip()
    if not stripped:
        raise MathXMLValidationError(f"{document_type} XML must not be empty.")
    upper = stripped.upper()
    if "<!DOCTYPE" in upper or "<!ENTITY" in upper:
        raise MathXMLValidationError(
            f"{document_type} XML must not contain DTD or entity declarations."
        )
    try:
        return ET.fromstring(stripped)
    except ET.ParseError as exc:
        raise MathXMLValidationError(f"Malformed {document_type} XML: {exc}") from exc


def _validate_openmath_tree(root: ET.Element) -> None:
    if root.tag != _OPENMATH_ROOT:
        raise MathXMLValidationError(
            f"OpenMath root must be `OMOBJ` in namespace `{OPENMATH_NAMESPACE}`."
        )
    if root.get("version") != "2.0":
        raise MathXMLValidationError('OpenMath OMOBJ must declare version="2.0".')

    for element in root.iter():
        namespace, local_name = _split_tag(element.tag)
        if namespace != OPENMATH_NAMESPACE:
            raise MathXMLValidationError(
                f"OpenMath element `{local_name}` has namespace "
                f"`{namespace or '(none)'}` instead of `{OPENMATH_NAMESPACE}`."
            )
        _validate_openmath_element(element, local_name)
    _validate_pals_symbol_bases(root)
    _validate_ids_and_local_references(root)


def _validate_retrieval_openmath_profile(
    root: ET.Element,
    *,
    require_closed: bool,
) -> None:
    allowed = {"OMOBJ", "OMS", "OMV", "OMI", "OMB", "OMF", "OMA", "OMBIND", "OMBVAR"}
    nodes = list(root.iter())
    if len(nodes) > 4096:
        raise MathXMLValidationError("OpenMath retrieval tree exceeds 4,096 nodes.")
    parents = _openmath_parents(root)
    for element in nodes:
        local_name = _local_name(element)
        if local_name not in allowed:
            raise MathXMLValidationError(
                f"OpenMath element `{local_name}` is outside the retrieval profile."
            )
        if _element_depth(element, parents=parents) > 64:
            raise MathXMLValidationError("OpenMath retrieval tree exceeds depth 64.")
        if element.text is not None and len(element.text) > 20_000:
            raise MathXMLValidationError("OpenMath text exceeds 20,000 code points.")
        if element.tail is not None and element.tail.strip():
            raise MathXMLValidationError("OpenMath retrieval elements cannot have text tails.")
        if any(len(value) > 20_000 for value in element.attrib.values()):
            raise MathXMLValidationError("OpenMath attribute exceeds 20,000 code points.")
        _require_retrieval_attributes(element, local_name)
        if local_name == "OMBVAR":
            declarations = list(element)
            if not 1 <= len(declarations) <= 256 or any(
                _local_name(declaration) != "OMV" for declaration in declarations
            ):
                raise MathXMLValidationError(
                    "Retrieval OMBVAR requires 1..256 direct OMV declarations."
                )
        if local_name == "OMA":
            children = list(element)
            if not children or _local_name(children[0]) != "OMS":
                raise MathXMLValidationError("Retrieval OMA head must be an OMS.")
    _validate_supported_symbol_profile(root, enforce_continuity_function_shape=False)
    if _contains_continuity_v1_construct(root):
        _validate_continuity_v1_profile(root)
        return
    expression = list(root)[0]
    if _infer_retrieval_sort(expression, parents=parents) != "proposition":
        raise MathXMLValidationError("OpenMath retrieval root must be a proposition.")
    if require_closed:
        _validate_closed_retrieval_variables(root)


_CONTINUITY_V1_CONSTRUCTS = frozenset(
    {
        "apply",
        "constant_function",
        "converges_to",
        "continuous_at",
        "forall_real_function",
        "forall_real_sequence",
        "function_add",
        "function_compose",
        "function_div",
        "function_mul",
        "function_neg",
        "function_scale",
        "function_sub",
        "has_limit_at",
        "continuous_on",
        "identity_function",
        "index_succ",
        "index_to_real",
        "index_zero",
        "sequence_add",
        "sequence_apply",
        "sequence_compose",
        "sequence_div",
        "sequence_lambda",
        "sequence_mul",
        "sequence_neg",
        "sequence_scale",
    }
)


def _contains_continuity_v1_construct(root: ET.Element) -> bool:
    parents = _openmath_parents(root)
    return any(
        _operator_symbol(element, parents=parents)
        and _operator_symbol(element, parents=parents)[0:2] == (PALS_OPENMATH_CDBASE, "pals1")
        and _operator_symbol(element, parents=parents)[2] in _CONTINUITY_V1_CONSTRUCTS
        for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS")
    )


def _validate_continuity_v1_profile(root: ET.Element) -> None:
    expression = list(root)[0]
    parents = _openmath_parents(root)
    if (
        _infer_continuity_v1_sort(
            expression,
            parents=parents,
            bound_sorts={},
            sequence_lambda_depth=0,
        )
        != "proposition"
    ):
        raise MathXMLValidationError("continuity-v1 retrieval root must be a proposition.")


def _continuity_binding(
    expression: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
    bound_sorts: dict[str, _ContinuitySort],
    bound_sort: _ContinuitySort,
    body_sort: _ContinuitySort,
    sequence_lambda_depth: int,
) -> _ContinuitySort:
    _binder, variables, body = list(expression)
    names = [declaration.get("name") for declaration in variables]
    if (
        any(name is None or not name for name in names)
        or len(names) != len(set(names))
        or any(name in bound_sorts for name in names)
    ):
        raise MathXMLValidationError(
            "continuity-v1 binder variables must be nonempty, distinct, and non-shadowing."
        )
    nested_sorts = dict(bound_sorts)
    nested_sorts.update({cast(str, name): bound_sort for name in names})
    actual_body_sort = _infer_continuity_v1_sort(
        body,
        parents=parents,
        bound_sorts=nested_sorts,
        sequence_lambda_depth=sequence_lambda_depth,
    )
    if actual_body_sort != body_sort:
        raise MathXMLValidationError("continuity-v1 binder body has an incompatible semantic sort.")
    return "proposition" if body_sort == "proposition" else "real_function"


def _infer_continuity_v1_sort(
    expression: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
    bound_sorts: dict[str, _ContinuitySort],
    sequence_lambda_depth: int,
) -> _ContinuitySort:
    local_name = _local_name(expression)
    if local_name in {"OMB", "OMF", "OMI"}:
        return "term"
    if local_name == "OMV":
        name = expression.get("name")
        if name is None or name not in bound_sorts:
            raise MathXMLValidationError(
                f"continuity-v1 OMV `{name or ''}` is not lexically bound."
            )
        return bound_sorts[name]
    if local_name == "OMS":
        symbol = _operator_symbol(expression, parents=parents)
        if symbol in {
            (PALS_OPENMATH_CDBASE, "pals1", "identity_function"),
        }:
            return "real_function"
        if symbol == (PALS_OPENMATH_CDBASE, "pals1", "index_zero"):
            return "natural_index"
        spec = _SUPPORTED_SYMBOLS.get(symbol) if symbol is not None else None
        if spec is None or spec.role != "constant":
            raise MathXMLValidationError(
                "continuity-v1 values must be bound variables, literals, or constants."
            )
        return "proposition" if spec.returns_proposition else "term"
    if local_name == "OMBIND":
        binder, _variables, _body = list(expression)
        symbol = _operator_symbol(binder, parents=parents)
        if symbol in {
            (PALS_OPENMATH_CDBASE, "pals1", "forall_real_function"),
            (PALS_OPENMATH_CDBASE, "pals1", "exists_real_function"),
        }:
            return _continuity_binding(
                expression,
                parents=parents,
                bound_sorts=bound_sorts,
                bound_sort="real_function",
                body_sort="proposition",
                sequence_lambda_depth=sequence_lambda_depth,
            )
        if symbol in {
            (PALS_OPENMATH_CDBASE, "pals1", "forall_real_sequence"),
            (PALS_OPENMATH_CDBASE, "pals1", "exists_real_sequence"),
        }:
            return _continuity_binding(
                expression,
                parents=parents,
                bound_sorts=bound_sorts,
                bound_sort="real_sequence",
                body_sort="proposition",
                sequence_lambda_depth=sequence_lambda_depth,
            )
        if symbol in {
            (OPENMATH_STANDARD_CDBASE, "quant1", "forall"),
            (OPENMATH_STANDARD_CDBASE, "quant1", "exists"),
        }:
            return _continuity_binding(
                expression,
                parents=parents,
                bound_sorts=bound_sorts,
                bound_sort="term",
                body_sort="proposition",
                sequence_lambda_depth=sequence_lambda_depth,
            )
        if symbol == (OPENMATH_STANDARD_CDBASE, "fns1", "lambda"):
            binder, variables, body = list(expression)
            if len(variables) != 1:
                raise MathXMLValidationError(
                    "continuity-v1 fns1:lambda binds exactly one real variable."
                )
            return _continuity_binding(
                expression,
                parents=parents,
                bound_sorts=bound_sorts,
                bound_sort="term",
                body_sort="term",
                sequence_lambda_depth=sequence_lambda_depth,
            )
        if symbol == (PALS_OPENMATH_CDBASE, "pals1", "sequence_lambda"):
            _binder, variables, body = list(expression)
            if len(variables) != 1:
                raise MathXMLValidationError(
                    "continuity-v1 sequence_lambda binds exactly one natural index."
                )
            names = [declaration.get("name") for declaration in variables]
            if any(name is None or not name for name in names) or names[0] in bound_sorts:
                raise MathXMLValidationError("continuity-v1 sequence lambda binder is invalid.")
            nested_sorts = dict(bound_sorts)
            nested_sorts[cast(str, names[0])] = "natural_index"
            if (
                _infer_continuity_v1_sort(
                    body,
                    parents=parents,
                    bound_sorts=nested_sorts,
                    sequence_lambda_depth=sequence_lambda_depth + 1,
                )
                != "term"
            ):
                raise MathXMLValidationError(
                    "continuity-v1 sequence_lambda body must be a real term."
                )
            return "real_sequence"
        raise MathXMLValidationError("continuity-v1 OMBIND has an unsupported binder.")
    if local_name != "OMA":
        raise MathXMLValidationError(
            f"continuity-v1 element `{local_name}` cannot infer a semantic sort."
        )
    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    expected_sorts, result_sort = _continuity_application_signature(symbol, arguments)
    if symbol == (PALS_OPENMATH_CDBASE, "pals1", "sequence_apply") and sequence_lambda_depth != 1:
        raise MathXMLValidationError(
            "continuity-v1 sequence_apply is allowed only in a sequence_lambda body."
        )
    if len(arguments) != len(expected_sorts):
        raise MathXMLValidationError("continuity-v1 application arity is invalid.")
    for index, (argument, expected_sort) in enumerate(
        zip(arguments, expected_sorts, strict=True), start=1
    ):
        actual_sort = _infer_continuity_v1_sort(
            argument,
            parents=parents,
            bound_sorts=bound_sorts,
            sequence_lambda_depth=sequence_lambda_depth,
        )
        if actual_sort != expected_sort:
            if symbol == (PALS_OPENMATH_CDBASE, "pals1", "continuous_on"):
                raise MathXMLValidationError(
                    f"`pals1:continuous_on` must have sort `{expected_sort}` at argument {index}."
                )
            raise MathXMLValidationError(
                f"continuity-v1 argument {index} has sort `{actual_sort}`, not `{expected_sort}`."
            )
    return result_sort


def _continuity_application_signature(
    symbol: _SymbolIdentity | None,
    arguments: list[ET.Element],
) -> tuple[tuple[_ContinuitySort, ...], _ContinuitySort]:
    term_args = ("term",) * len(arguments)
    if symbol in {
        (OPENMATH_STANDARD_CDBASE, "logic1", "and"),
        (OPENMATH_STANDARD_CDBASE, "logic1", "nand"),
        (OPENMATH_STANDARD_CDBASE, "logic1", "nor"),
        (OPENMATH_STANDARD_CDBASE, "logic1", "or"),
        (OPENMATH_STANDARD_CDBASE, "logic1", "xnor"),
        (OPENMATH_STANDARD_CDBASE, "logic1", "xor"),
        (OPENMATH_STANDARD_CDBASE, "logic1", "equivalent"),
        (OPENMATH_STANDARD_CDBASE, "logic1", "implies"),
    }:
        return ("proposition",) * len(arguments), "proposition"
    if symbol == (OPENMATH_STANDARD_CDBASE, "logic1", "not"):
        return ("proposition",), "proposition"
    if symbol and symbol[0:2] == (OPENMATH_STANDARD_CDBASE, "relation1"):
        return ("term", "term"), "proposition"
    if symbol == (PALS_OPENMATH_CDBASE, "pals1", "continuous_on"):
        return ("term", "real_function"), "proposition"
    if symbol == (PALS_OPENMATH_CDBASE, "pals1", "continuous_at"):
        return ("real_function", "term"), "proposition"
    if symbol == (PALS_OPENMATH_CDBASE, "pals1", "has_limit_at"):
        return ("real_function", "term", "term"), "proposition"
    if symbol == (PALS_OPENMATH_CDBASE, "pals1", "converges_to"):
        return ("real_sequence", "term"), "proposition"
    if symbol == (PALS_OPENMATH_CDBASE, "pals1", "apply"):
        return ("real_function", "term"), "term"
    if symbol == (PALS_OPENMATH_CDBASE, "pals1", "sequence_apply"):
        return ("real_sequence", "natural_index"), "term"
    if symbol == (PALS_OPENMATH_CDBASE, "pals1", "constant_function"):
        return ("term",), "real_function"
    if symbol in {
        (PALS_OPENMATH_CDBASE, "pals1", "function_add"),
        (PALS_OPENMATH_CDBASE, "pals1", "function_sub"),
        (PALS_OPENMATH_CDBASE, "pals1", "function_mul"),
        (PALS_OPENMATH_CDBASE, "pals1", "function_div"),
        (PALS_OPENMATH_CDBASE, "pals1", "function_compose"),
    }:
        return ("real_function", "real_function"), "real_function"
    if symbol == (PALS_OPENMATH_CDBASE, "pals1", "function_neg"):
        return ("real_function",), "real_function"
    if symbol == (PALS_OPENMATH_CDBASE, "pals1", "function_scale"):
        return ("term", "real_function"), "real_function"
    if symbol in {
        (PALS_OPENMATH_CDBASE, "pals1", "sequence_add"),
        (PALS_OPENMATH_CDBASE, "pals1", "sequence_sub"),
        (PALS_OPENMATH_CDBASE, "pals1", "sequence_mul"),
        (PALS_OPENMATH_CDBASE, "pals1", "sequence_div"),
    }:
        return ("real_sequence", "real_sequence"), "real_sequence"
    if symbol == (PALS_OPENMATH_CDBASE, "pals1", "sequence_neg"):
        return ("real_sequence",), "real_sequence"
    if symbol == (PALS_OPENMATH_CDBASE, "pals1", "sequence_scale"):
        return ("term", "real_sequence"), "real_sequence"
    if symbol == (PALS_OPENMATH_CDBASE, "pals1", "sequence_compose"):
        return ("real_function", "real_sequence"), "real_sequence"
    if symbol == (PALS_OPENMATH_CDBASE, "pals1", "index_succ"):
        return ("natural_index",), "natural_index"
    if symbol == (PALS_OPENMATH_CDBASE, "pals1", "index_to_real"):
        return ("natural_index",), "term"
    spec = _SUPPORTED_SYMBOLS.get(symbol) if symbol is not None else None
    if spec is None or spec.role != "application":
        raise MathXMLValidationError("continuity-v1 application symbol is unsupported.")
    if spec.proposition_arguments:
        return ("proposition",) * len(arguments), "proposition"
    return term_args, "proposition" if spec.returns_proposition else "term"


def _element_depth(
    element: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> int:
    depth = 1
    current = element
    while current in parents:
        depth += 1
        current = parents[current]
    return depth


def _require_retrieval_attributes(element: ET.Element, local_name: str) -> None:
    expected: dict[str, tuple[set[str], set[str]]] = {
        "OMOBJ": ({"version"}, {"cdbase"}),
        "OMS": ({"cd", "name"}, {"cdbase"}),
        "OMV": ({"name"}, set()),
        "OMI": (set(), set()),
        "OMB": (set(), set()),
        "OMF": (set(), {"dec", "hex"}),
        "OMA": (set(), set()),
        "OMBIND": (set(), set()),
        "OMBVAR": (set(), set()),
    }
    required, optional = expected[local_name]
    present = set(element.attrib)
    if not required.issubset(present) or not present.issubset(required | optional):
        raise MathXMLValidationError(
            f"OpenMath retrieval element `{local_name}` has invalid attributes."
        )
    if local_name == "OMF" and len(present) != 1:
        raise MathXMLValidationError("Retrieval OMF requires exactly one numeric attribute.")


def _validate_closed_retrieval_variables(root: ET.Element) -> None:
    def walk(element: ET.Element, bound: frozenset[str]) -> None:
        local_name = _local_name(element)
        if local_name == "OMV":
            name = element.get("name")
            if name is None or name not in bound:
                raise MathXMLValidationError(
                    f"Retrieval OMV `{name or ''}` is not lexically bound."
                )
            return
        if local_name == "OMBIND":
            binder, variables, body = list(element)
            walk(binder, bound)
            names = [declaration.get("name") for declaration in variables]
            if any(name is None for name in names) or len(names) != len(set(names)):
                raise MathXMLValidationError(
                    "Retrieval OMBVAR declarations must be named and distinct."
                )
            walk(body, bound | frozenset(cast(str, name) for name in names))
            return
        for child in element:
            if _local_name(element) == "OMBVAR":
                continue
            walk(child, bound)

    walk(root, frozenset())


def _infer_retrieval_sort(
    expression: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> _RetrievalSort:
    """Infer one exact PFI retrieval sort for an already-profiled expression."""
    local_name = _local_name(expression)
    if local_name in {"OMB", "OMF", "OMI", "OMV"}:
        return "term"
    if local_name == "OMS":
        symbol = _operator_symbol(expression, parents=parents)
        spec = _SUPPORTED_SYMBOLS.get(symbol) if symbol is not None else None
        if spec is None or spec.role != "constant":
            raise MathXMLValidationError(
                "Retrieval values must be literals, OMV terms, or registered constants."
            )
        return "proposition" if spec.returns_proposition else "term"
    if local_name == "OMBIND":
        binder, _variables, body = list(expression)
        symbol = _operator_symbol(binder, parents=parents)
        body_sort = _infer_retrieval_sort(body, parents=parents)
        if symbol in {
            (OPENMATH_STANDARD_CDBASE, "quant1", "exists"),
            (OPENMATH_STANDARD_CDBASE, "quant1", "forall"),
        }:
            if body_sort != "proposition":
                raise MathXMLValidationError(
                    f"The body of `{symbol[1]}:{symbol[2]}` must have sort `proposition`."
                )
            return "proposition"
        if symbol == (OPENMATH_STANDARD_CDBASE, "fns1", "lambda"):
            if body_sort == "term":
                return "term_function"
            if body_sort == "proposition":
                return "predicate_function"
            raise MathXMLValidationError(
                "The body of `fns1:lambda` must have sort `term` or `proposition`."
            )
        raise MathXMLValidationError("Retrieval OMBIND has an unsupported binder.")
    if local_name != "OMA":
        raise MathXMLValidationError(
            f"OpenMath retrieval element `{local_name}` cannot infer a semantic sort."
        )

    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    spec = _SUPPORTED_SYMBOLS.get(symbol) if symbol is not None else None
    if spec is None or spec.role != "application" or symbol is None:
        raise MathXMLValidationError("Retrieval OMA must use a registered application symbol.")
    registered_sorts = _RETRIEVAL_FUNCTION_ARGUMENT_SORTS.get(symbol)
    if registered_sorts is None:
        expected_sorts = (
            ("proposition",) * len(arguments)
            if spec.proposition_arguments
            else ("term",) * len(arguments)
        )
    else:
        expected_sorts = registered_sorts
    for index, (argument, expected_sort) in enumerate(
        zip(arguments, expected_sorts, strict=True),
        start=1,
    ):
        actual_sort = _infer_retrieval_sort(argument, parents=parents)
        if actual_sort != expected_sort:
            raise MathXMLValidationError(
                f"Retrieval argument {index} of `{symbol[1]}:{symbol[2]}` must have "
                f"sort `{expected_sort}`; received `{actual_sort}`."
            )
    return "proposition" if spec.returns_proposition else "term"


def _validate_openmath_element(element: ET.Element, local_name: str) -> None:
    children = list(element)
    if local_name == "OMOBJ":
        _require_child_count(local_name, children, exact=1)
    elif local_name == "OMS":
        _require_no_children(local_name, children)
        _require_attributes(element, local_name, "cd", "name")
    elif local_name == "OMV":
        _require_no_children(local_name, children)
        _require_attributes(element, local_name, "name")
    elif local_name == "OMI":
        _require_no_children(local_name, children)
        value = "".join((element.text or "").split())
        if not _INTEGER_RE.fullmatch(value):
            raise MathXMLValidationError(f"OMI contains invalid integer `{value}`.")
    elif local_name == "OMB":
        _require_no_children(local_name, children)
        _validate_omb_base64(element.text or "")
    elif local_name == "OMSTR":
        _require_no_children(local_name, children)
    elif local_name == "OMF":
        _require_no_children(local_name, children)
        if (element.get("dec") is None) == (element.get("hex") is None):
            raise MathXMLValidationError("OMF must have exactly one of `dec` or `hex`.")
        _validate_omf_lexical_form(element)
    elif local_name == "OMA":
        _require_child_count(local_name, children, minimum=2)
    elif local_name == "OMBIND":
        _require_child_count(local_name, children, exact=3)
        if _local_name(children[1]) != "OMBVAR":
            raise MathXMLValidationError("OMBIND second child must be OMBVAR.")
    elif local_name == "OMBVAR":
        _require_child_count(local_name, children, minimum=1)
        if not all(_is_bound_variable_declaration(child) for child in children):
            raise MathXMLValidationError(
                "OMBVAR children must be OMV or attributed OMV declarations."
            )
    elif local_name == "OME":
        _require_child_count(local_name, children, minimum=1)
        if _local_name(children[0]) != "OMS":
            raise MathXMLValidationError("OME first child must be OMS.")
    elif local_name == "OMATTR":
        _require_child_count(local_name, children, exact=2)
        if _local_name(children[0]) != "OMATP":
            raise MathXMLValidationError("OMATTR first child must be OMATP.")
    elif local_name == "OMATP":
        if len(children) < 2 or len(children) % 2 != 0:
            raise MathXMLValidationError("OMATP must contain attribute/value pairs.")
        if any(_local_name(children[index]) != "OMS" for index in range(0, len(children), 2)):
            raise MathXMLValidationError("Each OMATP attribute key must be OMS.")
    elif local_name == "OMR":
        _require_no_children(local_name, children)
        _require_attributes(element, local_name, "href")
    else:
        raise MathXMLValidationError(f"Unsupported OpenMath element `{local_name}`.")

    if local_name not in {"OMI", "OMB", "OMSTR"} and (element.text or "").strip():
        raise MathXMLValidationError(f"OpenMath element `{local_name}` has unexpected text.")


def _validate_omb_base64(value: str) -> None:
    compact = _BASE64_IGNORABLE_RE.sub("", value)
    if _BASE64_RE.fullmatch(compact) is None:
        raise MathXMLValidationError("OMB contains malformed base64 data.")
    try:
        decoded = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MathXMLValidationError("OMB contains malformed base64 data.") from exc
    if base64.b64encode(decoded).decode("ascii") != compact:
        raise MathXMLValidationError("OMB contains non-canonical base64 padding bits.")


def _validate_omf_lexical_form(element: ET.Element) -> None:
    decimal = element.get("dec")
    if decimal is not None:
        if _OMF_DECIMAL_RE.fullmatch(decimal) is None:
            raise MathXMLValidationError(f"OMF contains invalid decimal float `{decimal}`.")
        return

    hexadecimal = element.get("hex")
    if hexadecimal is None or _OMF_HEX_RE.fullmatch(hexadecimal) is None:
        raise MathXMLValidationError(
            f"OMF contains invalid 64-bit hexadecimal float `{hexadecimal or ''}`."
        )


def _validate_pals_symbol_bases(root: ET.Element) -> None:
    parents = _openmath_parents(root)
    for element in root.iter(f"{{{OPENMATH_NAMESPACE}}}OMS"):
        if element.get("cd") != "pals1":
            continue
        symbol = _operator_symbol(element, parents=parents)
        if symbol is not None and symbol[0] == PALS_OPENMATH_CDBASE:
            continue
        resolved = symbol[0] if symbol is not None else OPENMATH_STANDARD_CDBASE
        raise MathXMLValidationError(
            "A `pals1` OMS must resolve `cdbase` to "
            f"`{PALS_OPENMATH_CDBASE}`; resolved `{resolved}`."
        )


def _validate_ids_and_local_references(root: ET.Element) -> None:
    ids: set[str] = set()
    for element in root.iter():
        for key in ("id", _XML_ID):
            element_id = element.get(key)
            if element_id is None:
                continue
            if element_id in ids:
                raise MathXMLValidationError(f"Duplicate XML id `{element_id}`.")
            ids.add(element_id)

    missing: set[str] = set()
    for element in root.iter():
        for attribute, value in element.attrib.items():
            if _local_attribute_name(attribute) not in _LOCAL_REFERENCE_ATTRIBUTES:
                continue
            for token in value.split():
                if token.startswith("#") and token[1:] not in ids:
                    missing.add(token)
    if missing:
        refs = ", ".join(sorted(missing))
        raise MathXMLValidationError(f"Unresolved local XML reference(s): {refs}.")


def _alpha_normalize_openmath_tree(root: ET.Element) -> None:
    counter = [1]
    _alpha_normalize_element(root, environment={}, counter=counter)


def _alpha_normalize_element(
    element: ET.Element,
    *,
    environment: dict[str, str],
    counter: list[int],
) -> None:
    local_name = _local_name(element)
    if local_name == "OMV":
        name = element.get("name")
        if name is not None and name in environment:
            element.set("name", environment[name])
        return

    if local_name != "OMBIND":
        for child in element:
            _alpha_normalize_element(child, environment=environment, counter=counter)
        return

    binder, variables, body = list(element)
    _alpha_normalize_element(binder, environment=environment, counter=counter)
    body_environment = dict(environment)
    declared_here: set[str] = set()
    for declaration in variables:
        variable = _normalize_bound_declaration(
            declaration,
            environment=body_environment,
            counter=counter,
        )
        original_name = variable[0]
        if original_name in declared_here:
            raise MathXMLValidationError(
                f"OMBVAR declares bound variable `{original_name}` more than once."
            )
        declared_here.add(original_name)
        body_environment[original_name] = variable[1]
    _alpha_normalize_element(body, environment=body_environment, counter=counter)


def _normalize_bound_declaration(
    declaration: ET.Element,
    *,
    environment: dict[str, str],
    counter: list[int],
) -> tuple[str, str]:
    local_name = _local_name(declaration)
    if local_name == "OMV":
        original_name = declaration.get("name")
        if original_name is None:
            raise MathXMLValidationError("Bound OMV is missing `name`.")
        canonical_name = f"v{counter[0]}"
        counter[0] += 1
        declaration.set("name", canonical_name)
        return original_name, canonical_name

    if local_name != "OMATTR":
        raise MathXMLValidationError("Bound variable declaration must end in OMV.")
    attributes, attributed_variable = list(declaration)
    _alpha_normalize_element(attributes, environment=environment, counter=counter)
    return _normalize_bound_declaration(
        attributed_variable,
        environment=environment,
        counter=counter,
    )


def _is_bound_variable_declaration(element: ET.Element) -> bool:
    local_name = _local_name(element)
    if local_name == "OMV":
        return True
    if local_name != "OMATTR" or len(element) != 2:
        return False
    return _is_bound_variable_declaration(element[1])


def _remove_ignorable_whitespace(element: ET.Element) -> None:
    if element.text is not None and not element.text.strip():
        element.text = None
    if _local_name(element) == "OMI" and element.text is not None:
        element.text = "".join(element.text.split())
    for child in element:
        _remove_ignorable_whitespace(child)
        if child.tail is not None and not child.tail.strip():
            child.tail = None


def _is_emptyset_only(
    expression: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> bool:
    symbols = [
        symbol
        for element in expression.iter()
        if _local_name(element) == "OMS"
        if (symbol := _operator_symbol(element, parents=parents)) is not None
    ]
    emptyset = (OPENMATH_STANDARD_CDBASE, "set1", "emptyset")
    has_emptyset = emptyset in symbols
    has_values = any(
        _local_name(element) in {"OMB", "OMF", "OMI", "OMSTR", "OMV"}
        for element in expression.iter()
    )
    nonlogical_symbols = [symbol for symbol in symbols if symbol[1] not in {"logic1", "quant1"}]
    return (
        has_emptyset
        and not has_values
        and bool(nonlogical_symbols)
        and all(symbol == emptyset for symbol in nonlogical_symbols)
    )


def _is_proposition(
    expression: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> bool:
    local_name = _local_name(expression)
    if local_name == "OMATTR":
        return _is_proposition(list(expression)[1], parents=parents)
    if local_name == "OMS":
        symbol = _operator_symbol(expression, parents=parents)
        spec = _SUPPORTED_SYMBOLS.get(symbol) if symbol is not None else None
        return bool(spec is not None and spec.role == "constant" and spec.returns_proposition)
    if local_name == "OMBIND":
        binder, _variables, body = list(expression)
        symbol = _operator_symbol(binder, parents=parents)
        spec = _SUPPORTED_SYMBOLS.get(symbol) if symbol is not None else None
        return bool(
            spec is not None
            and spec.role == "binder"
            and spec.returns_proposition
            and _is_proposition(body, parents=parents)
        )
    if local_name != "OMA":
        return False

    operator, *arguments = list(expression)
    symbol = _operator_symbol(operator, parents=parents)
    if symbol is None:
        return False
    spec = _SUPPORTED_SYMBOLS.get(symbol)
    if spec is None or spec.role != "application" or not spec.returns_proposition:
        return False
    if not spec.proposition_arguments:
        return True
    return all(_is_proposition(argument, parents=parents) for argument in arguments)


def _operator_symbol(
    element: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> _SymbolIdentity | None:
    local_name = _local_name(element)
    if local_name == "OMS":
        cd = element.get("cd")
        name = element.get("name")
        if cd is None or name is None:
            return None
        return (_resolved_cdbase(element, parents=parents), cd, name)
    if local_name == "OMATTR":
        return _operator_symbol(list(element)[1], parents=parents)
    return None


def _resolved_cdbase(
    element: ET.Element,
    *,
    parents: dict[ET.Element, ET.Element],
) -> str:
    current: ET.Element | None = element
    while current is not None:
        if "cdbase" in current.attrib:
            return (current.get("cdbase") or "").strip()
        current = parents.get(current)
    return OPENMATH_STANDARD_CDBASE


def _openmath_parents(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def _strict_xml_payload(output: str) -> str:
    stripped = output.strip()
    if not stripped:
        raise MathXMLValidationError("The model returned an empty response.")
    if not stripped.startswith("```"):
        return stripped

    lines = stripped.splitlines()
    if len(lines) < 3 or lines[0].strip().lower() not in {"```", "```xml"}:
        raise MathXMLValidationError("The model returned an unsupported fenced response.")
    if lines[-1].strip() != "```":
        raise MathXMLValidationError("The model returned an unterminated XML fence.")
    return "\n".join(lines[1:-1]).strip()


def _openmath_prompt(
    statement: str,
    *,
    previous_xml: str | None,
    validation_error: str | None,
) -> str:
    repair_context = ""
    if previous_xml is not None and validation_error is not None:
        repair_hint = _validation_repair_hint(validation_error)
        repair_context = f"""
The previous candidate failed validation. Repair that candidate; do not replace the theorem
with an easier or unrelated expression.

Previous invalid XML:
```xml
{previous_xml}
```

Exact validation error:
{validation_error}
{repair_hint}
"""

    return f"""Convert the mathematical statement below to one OpenMath 2.0 XML object.
Return only a single OMOBJ XML document, optionally in one ```xml fence. Do not return prose,
JSON, MathML, OMDoc, or OMSTR. Do not use a seed, retrieved example, or deterministic fallback.

Requirements:
- The root is OMOBJ with xmlns=\"{OPENMATH_NAMESPACE}\" and version=\"2.0\".
- Encode the proposition semantically with OpenMath constructors and content-dictionary symbols.
- Preserve the theorem's abstraction level. A proof-method instruction such as epsilon-delta,
  induction, contradiction, or a named theorem controls the later proof strategy; it is not part
  of the theorem proposition. Do not expand a named property into its defining quantifiers merely
  because the user asks to prove it by that method. In particular, a request to prove continuity
  by epsilon-delta must still be encoded with `pals1:continuous_on`.
- Prefer standard content dictionaries. The validated core profile covers quant1, logic1,
  relation1, arith1, alg1, set1, setname1, and fns1. Use a `pals1` symbol only when no
  standard symbol fits, and never invent a new symbol name in these dictionaries.
- A standard OMS with no inherited or explicit `cdbase` resolves to
  `{OPENMATH_STANDARD_CDBASE}`. Preserve that OpenMath default by omitting `cdbase` on standard
  symbols unless an explicit standard base is required.
- Every `pals1` OMS must carry `cdbase="{PALS_OPENMATH_CDBASE}"` on that OMS. A missing or
  different base identifies another dictionary and is invalid. Do not put the PALS base on a
  shared ancestor because standard symbols would inherit the wrong identity.
- Preserve distinct free variables. Never merge variables merely because their names or roles
  look similar.
- Use OMBIND and OMBVAR for bound variables. A deterministic alpha-normalizer will rename only
  those bound variables after validation.
- The result must contain a predicate/proposition. Do not emit placeholders, emptyset as a proxy,
  or a term with no predicate. Variables from the statement must be represented with OMV.
- Do not invent a simpler fallback proposition if the statement is ambiguous or unsupported.
  In that case, fail by returning no XML rather than asserting a different claim.

Short XML grammar:
- OMOBJ contains exactly one OpenMath object.
- OMA contains an operator followed by at least one argument.
- OMBIND contains exactly: binder, OMBVAR, body.
- OMATTR contains exactly: OMATP, attributed object.
- OMS requires cd/name; OMV requires name.

Canonical symbol vocabulary and arity:
- `quant1:forall` and `quant1:exists` are OMBIND binders; `fns1:lambda` is also a binder.
- `logic1:not` is unary; `logic1:implies` and `logic1:equivalent` are binary; the other
  supported logical connectives take at least two proposition arguments.
- `relation1:eq`, `neq`, `lt`, `leq`, `gt`, `geq`, and `approx` are binary predicates.
- `arith1:abs` and `unary_minus` are unary; `divide`, `minus`, `power`, `root`, `sum`, and
  `product` are binary; `plus`, `times`, `gcd`, and `lcm` take at least two arguments.
- Set predicates (`set1:in`, `notin`, `subset`, `notsubset`, `prsubset`, `notprsubset`) and
  constructors (`map`, `setdiff`, `suchthat`) are binary. `set1:size` is unary.
- Arithmetic power is always `arith1:power(base, exponent)`.
- `pals1:continuous_on(domain, function)` at cdbase `{PALS_OPENMATH_CDBASE}` is the continuity
  predicate.
- Its function argument must be an OMV function variable or an OMBIND whose binder is
  `fns1:lambda` and whose body is a term, not a predicate. When continuity is asserted for an
  explicit expression, encode it as
  `pals1:continuous_on(setname1:R, fns1:lambda(variable, expression))`; never put the raw
  expression in either argument position.
- Do not universally quantify a point variable outside `continuous_on` when the continuity domain
  already expresses that point restriction. Quantify only parameters that occur in a
  `continuous_on` domain or function expression.
- When a theorem explicitly says that a function is real-valued, encode
  `set1:subset(set1:map(function, setname1:R), setname1:R)` as a proposition in its assumptions.
  When coefficients are explicitly real, encode each membership with
  `set1:in(coefficient, setname1:R)`.
- All remaining `pals1` symbols below use cdbase `{PALS_OPENMATH_CDBASE}`.
- `pals1:compact(set)` is the compactness predicate.
- `pals1:rank(map)` and `pals1:nullity(map)` are numeric terms.
- `pals1:dimension(space)` is a numeric term.
- `pals1:domain(map)` returns the domain space.
- `pals1:finite_dimensional(space)` is a predicate.
- `pals1:linear_map(map)` is a predicate.
- The image of a set under a function is always `set1:map(function, set)`. Do not use
  `fns1:image` for a set image.
- Build equations between terms with `relation1:eq(left, right)`.

Positive example 1, forall a in Z, a + 0 = a:
<OMOBJ xmlns=\"{OPENMATH_NAMESPACE}\" version=\"2.0\"><OMBIND><OMS cd=\"quant1\"
name=\"forall\"/><OMBVAR><OMV name=\"a\"/></OMBVAR><OMA><OMS cd=\"logic1\"
name=\"implies\"/><OMA><OMS cd=\"set1\" name=\"in\"/><OMV name=\"a\"/><OMS
cd=\"setname1\" name=\"Z\"/></OMA><OMA><OMS cd=\"relation1\" name=\"eq\"/><OMA><OMS
cd=\"arith1\" name=\"plus\"/><OMV name=\"a\"/><OMI>0</OMI></OMA><OMV
name=\"a\"/></OMA></OMA></OMBIND></OMOBJ>

Positive example 2, x is a member of S:
<OMOBJ xmlns=\"{OPENMATH_NAMESPACE}\" version=\"2.0\"><OMA><OMS cd=\"set1\"
name=\"in\"/><OMV name=\"x\"/><OMV name=\"S\"/></OMA></OMOBJ>

Canonical continuity shape example, the expression x + 1 on the real domain:
<OMOBJ xmlns=\"{OPENMATH_NAMESPACE}\" version=\"2.0\"><OMA><OMS
cdbase=\"{PALS_OPENMATH_CDBASE}\" cd=\"pals1\" name=\"continuous_on\"/><OMS
cd=\"setname1\" name=\"R\"/><OMBIND><OMS cd=\"fns1\"
name=\"lambda\"/><OMBVAR><OMV name=\"x\"/></OMBVAR><OMA><OMS cd=\"arith1\"
name=\"plus\"/><OMV name=\"x\"/><OMI>1</OMI></OMA></OMBIND></OMA></OMOBJ>
{repair_context}
Original statement:
{statement}
"""


def _validation_repair_hint(validation_error: str) -> str:
    if "Leading universal variable(s)" in validation_error:
        return """
Error-specific repair hint:
Remove redundant outer point quantifiers introduced from the proof method. Express the set of
points only as the first argument of `pals1:continuous_on`, and keep theorem parameters only when
they occur in the continuity domain or function expression.
"""
    if (
        "omits operator(s) explicitly named" in validation_error
        or "omits explicit statement exponent" in validation_error
        or "logical polarity does not match" in validation_error
    ):
        return """
Error-specific repair hint:
Re-read the original theorem and preserve its explicitly named function operator, power exponent,
and positive/negative continuity polarity. Do not substitute a nearby function family or reverse
the proposition.
"""
    if (
        "Proof-method instructions such as epsilon-delta" in validation_error
        or "epsilon-delta proof method" in validation_error
    ):
        return f"""
Error-specific repair hint:
Encode the theorem-level continuity claim with
`pals1:continuous_on(domain, function)` and set
`cdbase="{PALS_OPENMATH_CDBASE}"` directly on that OMS. The epsilon-delta phrase is a proof-method
requirement for the later Draft/Sketch/Prove stages, so do not expand it into quantifiers here.
"""
    if "A `pals1` OMS must resolve `cdbase`" in validation_error:
        return f"""
Error-specific repair hint:
Set `cdbase=\"{PALS_OPENMATH_CDBASE}\"` directly on every OMS whose `cd` is `pals1`.
Do not set that base on standard OpenMath symbols or on a shared ancestor.
"""
    if "`pals1:continuous_on`" in validation_error:
        return f"""
Error-specific repair hint:
Use exactly `pals1:continuous_on(domain, function)` with
`cdbase=\"{PALS_OPENMATH_CDBASE}\"` directly on that OMS. If the statement gives an explicit
expression, make the function argument an `fns1:lambda` OMBIND over that full term expression.
The lambda body must not be an equality or another predicate.
"""
    if "distinct variables" in validation_error or "omits variables" in validation_error:
        return """
Error-specific repair hint:
Preserve every distinct variable from the original statement as a distinct OpenMath variable
identity, and reference each one in the encoded proposition. Do not add an unused OMBVAR merely
to satisfy the count.
"""
    if "supported OpenMath symbol profile" in validation_error:
        return """
Error-specific repair hint:
Replace the unsupported symbol with the standard profile symbol that has the intended meaning.
Do not invent a `pals1`, logic, relation, arithmetic, function, or set symbol name.
"""
    if "OpenMath role" in validation_error:
        return """
Error-specific repair hint:
Use application-role symbols only as OMA heads, binder-role symbols only as OMBIND binders, and
constant-role symbols as values rather than compound-object heads.
"""
    if "does not encode a predicate/proposition" not in validation_error:
        return ""
    return f"""
Error-specific repair hint:
The candidate is a term, not a proposition. Wrap the complete term in a predicate that is
faithful to the original statement. For example, only when the statement asks for continuity,
encode `pals1:continuous_on(domain, function)` with exactly that CD/name and put an explicit
term inside an `fns1:lambda` function argument. For other statements, select their actual
predicate instead.
If a familiar symbol has a wrong or unknown CD, use the canonical CD: `arith1:power` for power;
`pals1:continuous_on`, `pals1:compact`, `pals1:rank`, `pals1:nullity`, `pals1:dimension`,
`pals1:domain`, `pals1:finite_dimensional`, and `pals1:linear_map` for the listed PALS vocabulary.
Every listed `pals1` OMS must set `cdbase="{PALS_OPENMATH_CDBASE}"` directly.
"""


def _require_attributes(element: ET.Element, local_name: str, *names: str) -> None:
    missing = [name for name in names if not (element.get(name) or "").strip()]
    if missing:
        joined = ", ".join(f"`{name}`" for name in missing)
        raise MathXMLValidationError(f"{local_name} is missing required attribute(s): {joined}.")


def _require_no_children(local_name: str, children: list[ET.Element]) -> None:
    if children:
        raise MathXMLValidationError(f"{local_name} must not contain child elements.")


def _require_child_count(
    local_name: str,
    children: list[ET.Element],
    *,
    exact: int | None = None,
    minimum: int | None = None,
) -> None:
    if exact is not None and len(children) != exact:
        raise MathXMLValidationError(f"{local_name} must contain exactly {exact} child element(s).")
    if minimum is not None and len(children) < minimum:
        raise MathXMLValidationError(
            f"{local_name} must contain at least {minimum} child element(s)."
        )


def _split_tag(tag: str) -> tuple[str, str]:
    if tag.startswith("{") and "}" in tag:
        namespace, local_name = tag[1:].split("}", 1)
        return namespace, local_name
    return "", tag


def _local_name(element: ET.Element) -> str:
    return _split_tag(element.tag)[1]


def _local_attribute_name(attribute: str) -> str:
    return _split_tag(attribute)[1]


def _has_ancestor(
    element: ET.Element,
    parents: dict[ET.Element, ET.Element],
    ancestor_tag: str,
) -> bool:
    parent = parents.get(element)
    while parent is not None:
        if parent.tag == ancestor_tag:
            return True
        parent = parents.get(parent)
    return False
