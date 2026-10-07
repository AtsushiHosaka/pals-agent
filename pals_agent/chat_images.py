"""Claim-bound inline visual inputs, with immutable source and derivative identities."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any
from uuid import UUID

_SHA = re.compile(r"^[0-9a-f]{64}$")
_images: ContextVar[tuple[str, ...]] = ContextVar("chat_images", default=())
MAX_DERIVATIVE_BYTES = 4_000_000


def validate_image_data_url(value: Any) -> bytes:
    prefixes = ("data:image/png;base64,", "data:image/jpeg;base64,")
    if not isinstance(value, str) or not any(value.startswith(prefix) for prefix in prefixes):
        raise ValueError("invalid chat image data URL")
    prefix = next(prefix for prefix in prefixes if value.startswith(prefix))
    encoded = value[len(prefix) :]
    if len(encoded) > 4 * ((MAX_DERIVATIVE_BYTES + 2) // 3):
        raise ValueError("chat image derivative too large")
    pixels = base64.b64decode(encoded, validate=True)
    signature = b"\x89PNG\r\n\x1a\n" if "png" in prefix else b"\xff\xd8\xff"
    if not pixels.startswith(signature) or not 8 < len(pixels) <= MAX_DERIVATIVE_BYTES:
        raise ValueError("invalid chat image derivative")
    return pixels


def parse_chat_images(payload: Any, attachment_ids: Any) -> list[dict[str, Any]]:
    if (
        not isinstance(payload, dict)
        or set(payload) != {"attachments"}
        or not isinstance(payload["attachments"], list)
        or not isinstance(attachment_ids, list)
        or not 1 <= len(attachment_ids) <= 330
        or len(set(attachment_ids)) != len(attachment_ids)
        or [image.get("id") for image in payload["attachments"] if isinstance(image, dict)]
        != attachment_ids
    ):
        raise ValueError("invalid chat attachment binding")
    total_bytes = 0
    total_ocr_bytes = 0
    for item in payload["attachments"]:
        if set(item) != {
            "id",
            "filename",
            "media_type",
            "size_bytes",
            "content_sha256",
            "image_sha256",
            "image_data_url",
            "ocr_text",
        }:
            raise ValueError("invalid chat attachment fields")
        if str(UUID(item["id"])) != item["id"]:
            raise ValueError("invalid chat attachment identity")
        if (
            item["media_type"] not in {"image/png", "image/jpeg"}
            or type(item["size_bytes"]) is not int
            or not 1 <= item["size_bytes"] <= 50_000_000
            or not isinstance(item["filename"], str)
            or not isinstance(item["ocr_text"], str)
            or len(item["ocr_text"]) > 20000
            or any(
                not isinstance(item[key], str) or not _SHA.fullmatch(item[key])
                for key in ("content_sha256", "image_sha256")
            )
        ):
            raise ValueError("invalid chat attachment metadata")
        pixels = validate_image_data_url(item["image_data_url"])
        total_bytes += len(pixels)
        total_ocr_bytes += len(item["ocr_text"].encode("utf-8"))
        if total_bytes > 20_000_000 or total_ocr_bytes > 65536:
            raise ValueError("chat visual context exceeds limits")
        if hashlib.sha256(pixels).hexdigest() != item["image_sha256"]:
            raise ValueError("chat attachment hash mismatch")
    return payload["attachments"]


def valid_chat_turn(turn: Any) -> bool:
    if (
        not isinstance(turn, dict)
        or set(turn) not in (
            {"question_id", "question", "answer"},
            {"question_id", "question", "answer", "attachments"},
        )
        or any(
            not isinstance(turn[key], str) or not turn[key].strip()
            for key in ("question_id", "question")
        )
        or not isinstance(turn["answer"], str)
    ):
        return False
    attachments = turn.get("attachments", [])
    if not isinstance(attachments, list) or len(attachments) > 5:
        return False
    if not turn["answer"].strip() and not attachments:
        return False
    for item in attachments:
        if (
            not isinstance(item, dict)
            or set(item) != {
                "id", "filename", "media_type", "size_bytes", "content_sha256", "image_sha256"
            }
            or not isinstance(item["id"], str)
            or not isinstance(item["filename"], str)
            or item["media_type"] not in {"image/png", "image/jpeg"}
            or type(item["size_bytes"]) is not int
            or not 1 <= item["size_bytes"] <= 50_000_000
            or any(
                not isinstance(item[key], str) or not _SHA.fullmatch(item[key])
                for key in ("content_sha256", "image_sha256")
            )
        ):
            return False
        try:
            if str(UUID(item["id"])) != item["id"]:
                return False
        except ValueError:
            return False
    return True


def chat_input_data(request: dict[str, Any]) -> dict[str, Any]:
    return {
        "statement": request["statement"],
        "context": request["context_turns"],
        "history": request.get("chat_history", []),
        "images": [
            {
                "attachment_id": item["id"],
                "source_sha256": item["content_sha256"],
                "image_sha256": item["image_sha256"],
                "ocr_text": item["ocr_text"],
            }
            for item in request.get("chat_images", [])
        ],
    }


def chat_input_sha256(request: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            chat_input_data(request), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def current_chat_images() -> tuple[str, ...]:
    return _images.get()


def chat_attachment_ids(request: dict[str, Any]) -> list[str]:
    identifiers = request.get("attachment_ids", [])
    history = request.get("chat_history", [])
    if not isinstance(identifiers, list) or not isinstance(history, list):
        raise ValueError("invalid chat attachment manifest")
    result = list(identifiers)
    turns = request.get("context_turns", [])
    if not isinstance(turns, list):
        raise ValueError("invalid chat clarification manifest")
    for turn in turns:
        if not isinstance(turn, dict):
            raise ValueError("invalid chat clarification manifest")
        attachments = turn.get("attachments", [])
        if not isinstance(attachments, list):
            raise ValueError("invalid chat clarification manifest")
        for item in attachments:
            if not isinstance(item, dict) or "id" not in item:
                raise ValueError("invalid chat clarification manifest")
            if item["id"] not in result:
                result.append(item["id"])
    for message in history:
        if not isinstance(message, dict) or not isinstance(message.get("attachment_ids"), list):
            raise ValueError("invalid chat history attachment manifest")
        for identifier in message["attachment_ids"]:
            if identifier not in result:
                result.append(identifier)
    if len(result) > 330 or len(set(result)) != len(result):
        raise ValueError("invalid chat attachment count")
    for identifier in result:
        if not isinstance(identifier, str) or str(UUID(identifier)) != identifier:
            raise ValueError("invalid chat attachment identity")
    return result


@contextmanager
def chat_image_scope(images: tuple[str, ...]) -> Iterator[None]:
    token = _images.set(images)
    try:
        yield
    finally:
        _images.reset(token)
