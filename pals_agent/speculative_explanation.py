"""Start the explanation model call while the independent semantic review is still running.

The proof is already Lean-verified when it reaches ``semantic_review``. The explanation call needs
only the learner's statement, that Lean source and the output language, none of which the review
can change, so the two calls do not depend on each other. What does depend on the review is
everything durable: the API accepts the explanation claim only for a ``verified`` job, and the
job becomes ``verified`` only when the review is approved and settled.

So this module runs the model call and nothing else, and its result has no effect until the
caller adopts it after the claim is held:

* nothing is written to the API, so a rejected, failed or stale review leaves no explanation row;
* usage is held back (``hold_usage``) and forwarded only on adoption, so rejected work is not
  billed even if explanation calls are metered later;
* the explanation review, the claim, its lease and the final write are unchanged;
* an exception from the call is re-raised on adoption, so the outcome is the one a direct call
  would have had.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from collections.abc import Callable
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextvars import copy_context
from dataclasses import dataclass, field
from typing import Any

from pals_agent.explanations import ExplanationDeadlineExceeded, ProofExplanation
from pals_agent.runtime_latency import latency_label
from pals_agent.usage import forward_usage, hold_usage, reporter_active

logger = logging.getLogger(__name__)


@dataclass
class SpeculativeExplanation:
    """One in-flight first explanation call for a fixed (statement, Lean source, language)."""

    theorem_statement: str
    lean_code: str
    language: str
    _future: Future[ProofExplanation] = field(default_factory=Future, repr=False)
    _usage: list[dict[str, Any]] = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _closed: bool = False
    _forwarded: bool = False

    @classmethod
    def start(
        cls,
        *,
        explain: Callable[..., ProofExplanation],
        theorem_statement: str,
        lean_code: str,
        language: str,
        deadline: float,
        timeout_seconds: float,
    ) -> SpeculativeExplanation:
        """Call ``explain`` on a daemon thread that shares this context's tracing."""
        speculative = cls(theorem_statement, lean_code, language)

        def run() -> None:
            try:
                with hold_usage() as records, latency_label("explain"):
                    try:
                        explanation = explain(
                            theorem_statement=theorem_statement,
                            lean_code=lean_code,
                            verified=True,
                            language=language,
                            deadline=deadline,
                            timeout_seconds=timeout_seconds,
                        )
                    finally:
                        speculative._usage = list(records)
            except BaseException as exc:  # noqa: BLE001 -- re-raised unchanged on adoption.
                speculative._future.set_exception(exc)
            else:
                speculative._future.set_result(explanation)

        thread = threading.Thread(
            target=copy_context().run, args=(run,), name="pals-speculative-explanation",
            daemon=True,
        )
        thread.start()
        return speculative

    def adopt(
        self,
        *,
        theorem_statement: str,
        lean_code: str,
        language: str,
        wait_seconds: float,
    ) -> ProofExplanation | None:
        """The pre-generated first candidate, once; ``None`` when it does not apply.

        It applies only to exactly the inputs it was started with, and only once. A call that is
        still running when ``wait_seconds`` ends counts as a missed deadline, as a direct call
        would have. The held usage is forwarded to the active reporter before returning.
        """
        with self._lock:
            if self._closed:
                return None
            self._closed = True
        if (theorem_statement, lean_code, language) != (
            self.theorem_statement, self.lean_code, self.language,
        ):
            return None
        try:
            explanation = self._future.result(timeout=max(0.0, wait_seconds))
        except FutureTimeoutError:
            raise ExplanationDeadlineExceeded(
                "explanation generation deadline exceeded"
            ) from None
        except BaseException:
            # A direct call that raised would also have used (and reported) its tokens.
            self._forward_if_reportable()
            raise
        self._forward_if_reportable()
        return explanation

    def _forward_if_reportable(self) -> None:
        """Forward the held usage only when a reporter is active. ``take_usage_once`` marks it
        handed out, so taking it with nobody to report to would lose it for good; left alone, a
        later settle (``t2_lane.settle_unadopted``) still reports it."""
        if reporter_active():
            forward_usage(self.take_usage_once())

    def take_usage_once(self) -> list[dict[str, Any]]:
        """The call's usage, handed out exactly once: adopt, settle and discard accounting all
        take it here, so no order of them reports it twice (later takers get an empty list)."""
        with self._lock:
            if self._forwarded:
                return []
            self._forwarded = True
            return [dict(record) for record in self._usage]

    def held_usage(self) -> list[dict[str, Any]]:
        """Usage of the call so far (only complete once it has finished), for cost accounting."""
        return [dict(record) for record in self._usage]

    def done(self) -> bool:
        return self._future.done()

    def wait(self, timeout: float | None = None) -> None:
        """Block until the call ended (result or error); used to account for discarded work."""
        with contextlib.suppress(BaseException):  # only waiting, never raising
            self._future.exception(timeout=timeout)

    def discard(self) -> None:
        """Drop the result. The call may still finish; nothing it produced is used or reported."""
        with self._lock:
            self._closed = True
        # Retrieve any exception so an unobserved failure is not reported at garbage collection.
        self._future.add_done_callback(lambda done: done.exception())
