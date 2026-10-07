"""Content-free usage reporting scoped to the current generation claim.

A metering failure is visible but never changes proof generation or quota.
"""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)
_reporter: ContextVar[Callable[[dict[str, Any]], None] | None] = ContextVar(
    "pals_usage_reporter", default=None
)
# Exact model identities only; never infer prices for unknown dated releases.
# Official pricing provenance: docs/billing-model-price-snapshots-2026-09-29.md.
PRICE_SNAPSHOTS = {
    "text-embedding-3-small": "openai-text-embedding-3-small-standard-2026-09-30",
    # v1 usage does not carry cache-write counts. These snapshots explicitly
    # estimate all input at the cache-write upper bound, not a claimed invoice.
    "gpt-6-luna": "openai-gpt-6-luna-standard-upper-bound-2026-09-30",
    "gpt-6.1-sol": "openai-gpt-6.1-sol-standard-upper-bound-2026-10-07",
    "gpt-5.6-terra": "openai-gpt-5.6-terra-standard-upper-bound-2026-09-30",
    "gpt-5.4-mini": "openai-gpt-5.4-mini-2026-09-29",
    "gpt-5.4-mini-2026-03-17": "openai-gpt-5.4-mini-2026-09-29",
    "gpt-5.4-nano": "openai-gpt-5.4-nano-2026-09-29",
    "gpt-5.4-nano-2026-03-17": "openai-gpt-5.4-nano-2026-09-29",
}


@contextmanager
def usage_scope(reporter: Callable[[dict[str, Any]], None]) -> Iterator[None]:
    token = _reporter.set(reporter)
    try:
        yield
    finally:
        _reporter.reset(token)


def report_usage(call_id: str, model: str, usage: Any) -> None:
    reporter = _reporter.get()
    if reporter is None:
        return
    try:
        if not isinstance(usage, dict):
            raise ValueError
        input_tokens = usage["input_tokens"]
        output_tokens = usage["output_tokens"]
        cached = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
        reasoning = usage.get("output_tokens_details", {}).get("reasoning_tokens", 0)
        if (
            any(
                type(v) is not int or not 0 <= v <= 9007199254740991
                for v in (input_tokens, output_tokens, cached, reasoning)
            )
            or cached > input_tokens
            or reasoning > output_tokens
        ):
            raise ValueError
        snapshot = PRICE_SNAPSHOTS.get(model)
        if snapshot is None:
            raise ValueError
        reporter(
            dict(
                schema_version="pals.proof-job-usage.v1",
                call_id=call_id,
                provider="openai",
                model=model,
                input_tokens=input_tokens,
                cached_input_tokens=cached,
                output_tokens=output_tokens,
                reasoning_output_tokens=reasoning,
                price_snapshot_id=snapshot,
            )
        )
    except Exception as exc:
        logger.warning("Provider usage recording failed (%s)", type(exc).__name__)
