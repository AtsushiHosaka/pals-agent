"""Explicit, fail-closed input for one checked synthetic-geometry family.

This parser does not transcribe images or infer mathematical premises. The
``user_structured`` form is a caller-supplied mathematical interpretation, not
an assertion an LLM may manufacture to bypass semantic review. Existing OCR
snapshots and exact confirmation turns are retained for downstream review.
Display coordinates and figure metadata are never Lean hypotheses.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any

import rfc8785

from pals_agent.chat_images import valid_chat_turn
from pals_agent.material_context import (
    MaterialContext,
    latest_confirmed_proposition,
    proposition_question,
)

SCHEMA_VERSION = "pals.synthetic-geometry-input.v1"
FAMILY = "isosceles-midpoint-perpendicular-v1"
_ROLES = ("A", "B", "C", "M")
_ID = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z", re.ASCII)
_MAX_INPUT_BYTES = 512_000
_REQUIRED = {
    "schema_version", "family", "original_text", "proposition", "source_kind",
    "objects", "hypotheses", "conclusion",
}
_OPTIONAL = {
    "figures", "display_coordinates", "ambiguities", "material_context", "project_id",
    "material_citations", "context_turns", "language",
}


class GeometryInputError(ValueError):
    """The explicit model is malformed or outside this supported family."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GeometryInputError(message)


def _text(value: Any, maximum: int) -> bool:
    return (
        isinstance(value, str) and bool(value.strip()) and len(value) <= maximum
        and not any(ord(char) < 32 and char not in "\n\r\t" for char in value)
        and not any("\ud800" <= char <= "\udfff" for char in value)
    )


def _valid_source_turn(value: Any) -> bool:
    """Adapt the shared metadata validator to this parser's fail-closed boundary."""
    try:
        return valid_chat_turn(value)
    except (TypeError, ValueError, KeyError, OverflowError, RecursionError):
        return False


def _identifier(value: Any) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _claim(value: Any, *, proposition: str, expected: tuple[str, tuple[str, ...]]) -> None:
    _require(
        isinstance(value, dict)
        and set(value) == {"id", "predicate", "objects", "source_span"},
        "claim fields are invalid",
    )
    _require(_identifier(value["id"]), "claim identity is invalid")
    predicate, objects = expected
    _require(
        value["predicate"] == predicate and value["objects"] == list(objects),
        "claim does not match the supported family and object roles",
    )
    span = value["source_span"]
    _require(
        isinstance(span, dict) and set(span) == {"start", "end", "excerpt"},
        "claim requires an exact proposition span",
    )
    _require(
        type(span["start"]) is int and type(span["end"]) is int
        and 0 <= span["start"] < span["end"] <= len(proposition)
        and _text(span["excerpt"], 1600)
        and proposition[span["start"]:span["end"]] == span["excerpt"],
        "claim source span does not bind the exact proposition",
    )


@dataclass(frozen=True, slots=True)
class GeometryProblem:
    """Immutable snapshot; accessors return copies, not the accepted input object."""

    _encoded: str
    _roles: tuple[tuple[str, str], ...]
    ready: bool
    _clarification_encoded: str | None

    @classmethod
    def parse(cls, payload: Any) -> GeometryProblem:
        _require(isinstance(payload, dict), "geometry input must be an object")
        _require(
            _REQUIRED <= set(payload) <= _REQUIRED | _OPTIONAL,
            "geometry input fields are invalid",
        )
        try:
            encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False, sort_keys=True)
            size = len(encoded.encode("utf-8"))
        except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
            raise GeometryInputError("geometry input must be bounded JSON") from exc
        _require(size <= _MAX_INPUT_BYTES, "geometry input exceeds the byte bound")
        try:
            data = json.loads(encoded)
        except (ValueError, RecursionError) as exc:
            raise GeometryInputError("geometry input must be bounded JSON") from exc
        _require(data["schema_version"] == SCHEMA_VERSION, "unsupported geometry schema")
        _require(data["family"] == FAMILY, "unsupported geometry family")
        _require(_text(data["original_text"], 20_000), "original problem text is required")
        _require(
            _text(data["proposition"], 1600)
            and len(data["proposition"].encode("utf-8")) <= 1600,
            "exact proposition must contain at most 1600 UTF-8 bytes",
        )
        _require(data["source_kind"] in ("user_structured", "ocr"), "invalid source kind")
        proposition = data["proposition"]
        objects = data["objects"]
        _require(isinstance(objects, list) and len(objects) == 4, "four point objects are required")
        roles: dict[str, str] = {}
        labels: set[str] = set()
        for point in objects:
            _require(
                isinstance(point, dict) and set(point) == {"id", "kind", "label", "role"},
                "point object fields are invalid",
            )
            _require(
                _identifier(point["id"]) and point["kind"] == "point"
                and _text(point["label"], 32) and point["label"] == point["label"].strip()
                and point["role"] in _ROLES,
                "point object is invalid",
            )
            _require(
                point["role"] not in roles and point["id"] not in roles.values()
                and point["label"] not in labels,
                "point roles, identities and labels must be distinct",
            )
            roles[point["role"]] = point["id"]
            labels.add(point["label"])
        a, b, c, m = (roles[role] for role in _ROLES)
        expected = {
            "non_collinear": (a, b, c),
            "equal_distance": (a, b, a, c),
            "midpoint": (m, b, c),
        }
        hypotheses = data["hypotheses"]
        _require(
            isinstance(hypotheses, list) and len(hypotheses) == len(expected),
            "all three explicit hypotheses are required",
        )
        seen: set[str] = set()
        claim_ids: set[str] = set()
        for hypothesis in hypotheses:
            _require(isinstance(hypothesis, dict), "hypothesis must be an object")
            predicate = hypothesis.get("predicate")
            _require(
                isinstance(predicate, str) and predicate in expected and predicate not in seen,
                "hypotheses are duplicated or unsupported",
            )
            _claim(hypothesis, proposition=proposition, expected=(predicate, expected[predicate]))
            _require(hypothesis["id"] not in claim_ids, "claim identities must be distinct")
            seen.add(predicate)
            claim_ids.add(hypothesis["id"])
        _claim(
            data["conclusion"], proposition=proposition,
            expected=("perpendicular", (a, m, b, c)),
        )
        _require(data["conclusion"]["id"] not in claim_ids, "claim identities must be distinct")
        figures = data.get("figures", [])
        _require(
            _valid_source_turn({
                "question_id": "geometry-source-figures", "question": "Original figures",
                "answer": "Retained as input evidence", "attachments": figures,
            }),
            "figure references must be existing valid chat attachment metadata",
        )
        _require(
            len({figure["id"] for figure in figures}) == len(figures),
            "figure identities must be distinct",
        )
        coordinates = data.get("display_coordinates", {})
        _require(isinstance(coordinates, dict), "display coordinates must be an object")
        for point_id, coordinate in coordinates.items():
            _require(point_id in roles.values(), "display coordinate has an unknown object")
            _require(
                isinstance(coordinate, list) and len(coordinate) == 2
                and all(
                    type(number) in (int, float) and abs(number) <= 10_000
                    and math.isfinite(number) for number in coordinate
                ),
                "display coordinates must be bounded finite pairs",
            )
        ambiguities = data.get("ambiguities", [])
        _require(
            isinstance(ambiguities, list) and len(ambiguities) <= 12
            and all(_text(ambiguity, 500) for ambiguity in ambiguities),
            "ambiguity list is invalid",
        )
        language = data.get("language", "en")
        _require(language in ("en", "ja", "zh-Hans", "zh-Hant"), "unsupported language")
        turns = data.get("context_turns", [])
        _require(
            isinstance(turns, list) and len(turns) <= 24
            and all(_valid_source_turn(turn) for turn in turns),
            "confirmation turns are invalid",
        )
        # Retain full metadata snapshots, not caller-controlled file paths or URLs.
        material = data.get("material_context")
        citations = data.get("material_citations", [])
        _require(isinstance(citations, list), "material citations must be a list")
        if material is not None:
            try:
                context = MaterialContext.parse(material, project_id=data.get("project_id"))
                context.validate_citations(citations)
            except ValueError as exc:
                raise GeometryInputError("material provenance is invalid") from exc
        else:
            _require(
                not citations and data.get("project_id") is None, "material provenance missing",
            )
        clarification = None
        if data["source_kind"] == "user_structured":
            _require(
                proposition == data["original_text"], "user proposition must preserve exact text",
            )
        else:
            _require(
                material is not None and bool(citations),
                "OCR requires selected material citations",
            )
            if latest_confirmed_proposition(turns, language) != proposition:
                clarification = proposition_question(proposition, language)
        if ambiguities:
            clarification = {
                "text": "Please clarify the mathematical interpretation before proving:\n"
                + "\n".join(ambiguities),
                "options": [],
            }
        return cls(
            encoded,
            tuple((role, roles[role]) for role in _ROLES),
            clarification is None,
            json.dumps(clarification, ensure_ascii=False) if clarification is not None else None,
        )

    @property
    def role_ids(self) -> dict[str, str]:
        return dict(self._roles)

    @property
    def statement(self) -> str:
        return str(self.to_data()["proposition"])

    @property
    def original_text(self) -> str:
        return str(self.to_data()["original_text"])

    @property
    def clarification(self) -> dict[str, Any] | None:
        return json.loads(self._clarification_encoded) if self._clarification_encoded else None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(rfc8785.dumps(self.to_data())).hexdigest()

    def to_data(self) -> dict[str, Any]:
        return json.loads(self._encoded)  # type: ignore[no-any-return]
