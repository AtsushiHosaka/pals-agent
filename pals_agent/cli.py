from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pals_agent.api_client import PalsApiClient
from pals_agent.benchmarks import BENCHMARK_PROBLEMS
from pals_agent.draft_catalog import SeedDraftCatalog
from pals_agent.evaluation import (
    JsonlEvaluationStore,
    compare_evaluation_runs,
    evaluate_artifact,
    migrate_evaluation_history,
    summarize_evaluation_runs,
)
from pals_agent.factory import (
    build_draft_embedding_model,
    build_pipeline,
    build_proof_explainer,
    build_proof_output_reviewer,
    build_proof_request_processor,
    build_proof_semantic_reviewer,
    build_recipe_attempt_planner,
    build_semantic_stage_judge,
    build_statement_openmath_structurer,
)
from pals_agent.models import ProofRunResult
from pals_agent.proof_flow_image import (
    SubprocessDocker,
    build_worker_image,
    probe_base_image_elementtree,
)
from pals_agent.proof_flow_seed import (
    CanonicalizerChildProperty,
    ProofDraftSeedBuilder,
    SeedBuildArtifact,
    SeedEmbeddingFingerprint,
)
from pals_agent.settings import AgentSettings
from pals_agent.worker import SqsProofWorker, worker_queue_url

_SOURCE_COMMIT = re.compile(r"[0-9a-f]{40}")
_DEFAULT_AGENT_SOURCE_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pals-agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    benchmark_parser = subparsers.add_parser("benchmark", help="Run the built-in benchmark set.")
    benchmark_parser.add_argument(
        "--output",
        type=Path,
        default=Path(".pals-agent-artifacts/benchmark-results.json"),
    )
    worker_parser = subparsers.add_parser("worker", help="Continuously process SQS proof jobs.")
    worker_parser.add_argument("--ready-file", type=Path)
    worker_once_parser = subparsers.add_parser("worker-once", help="Process at most one SQS task.")
    for lane_parser in (worker_parser, worker_once_parser):
        lane_parser.add_argument("--lane", choices=("all", "proof", "assessment"), default="all")
    pfi_seed_parser = subparsers.add_parser(
        "build-pfi-seed",
        help="Build the atomic PFI signed-worker seed input.",
    )
    pfi_seed_parser.add_argument("--output", type=Path, required=True)
    pfi_seed_parser.add_argument("--source-commit", required=True)
    pfi_image_parser = subparsers.add_parser(
        "build-pfi-worker-image",
        help="Build and verify the PFI signed worker image from an atomic seed.",
    )
    pfi_image_parser.add_argument("--source-commit", required=True)
    pfi_image_parser.add_argument("--tag", default="pals-agent-worker")
    pfi_image_parser.add_argument(
        "--repository-root",
        type=Path,
        default=Path.cwd().parent,
    )
    pfi_image_parser.add_argument(
        "--context",
        type=Path,
        default=_DEFAULT_AGENT_SOURCE_ROOT,
        help="Agent Docker build context; the generated seed is placed under build/.",
    )
    openmath_parser = subparsers.add_parser(
        "openmath-structure",
        help="Structure a natural-language statement as validated canonical OpenMath XML.",
    )
    openmath_parser.add_argument("statement")
    evaluation_parser = subparsers.add_parser(
        "evaluate-artifact",
        help="Score one persisted proof artifact and append a versioned history record.",
    )
    evaluation_parser.add_argument("artifact", type=Path)
    evaluation_parser.add_argument("--suite-revision", required=True)
    evaluation_parser.add_argument("--run-id", required=True)
    evaluation_parser.add_argument("--case-id")
    evaluation_parser.add_argument("--explanation", type=Path)
    evaluation_parser.add_argument("--clarifications", type=Path)
    evaluation_parser.add_argument(
        "--expect-clarification",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Evaluation-only expectation for a clarification payload.",
    )
    evaluation_parser.add_argument(
        "--semantic-judge",
        action="store_true",
        help="Add optional live semantic stage scores without replacing deterministic metrics.",
    )
    evaluation_parser.add_argument(
        "--expected-evidence",
        type=Path,
        help="Evaluation-only expected evidence; never passed to proof generation.",
    )
    evaluation_parser.add_argument(
        "--rubric",
        type=Path,
        help="Evaluation-only semantic rubric; never passed to proof generation.",
    )
    evaluation_parser.add_argument(
        "--history",
        type=Path,
        default=Path(".pals-agent-artifacts/evaluations/history.jsonl"),
    )
    history_parser = subparsers.add_parser(
        "evaluation-history",
        help="Summarize durable evaluation history without rerunning an LLM.",
    )
    history_parser.add_argument(
        "--history",
        type=Path,
        default=Path(".pals-agent-artifacts/evaluations/history.jsonl"),
    )
    history_parser.add_argument("--run-id")
    migration_parser = subparsers.add_parser(
        "evaluation-history-migrate",
        help="Explicitly migrate a digest-pinned evaluation history snapshot.",
    )
    migration_parser.add_argument(
        "--migration",
        required=True,
        choices=("semantic-comments-v2",),
    )
    migration_parser.add_argument("--history", type=Path, required=True)
    migration_parser.add_argument("--expected-sha256", required=True)
    comparison_parser = subparsers.add_parser(
        "evaluation-compare",
        help="Compare state-level metrics for two persisted evaluation runs.",
    )
    comparison_parser.add_argument(
        "--history",
        type=Path,
        default=Path(".pals-agent-artifacts/evaluations/history.jsonl"),
    )
    comparison_parser.add_argument("--baseline-run", required=True)
    comparison_parser.add_argument("--candidate-run", required=True)

    args = parser.parse_args(argv)
    ready_file = args.ready_file if args.command == "worker" else None
    if ready_file is not None:
        ready_file.unlink(missing_ok=True)

    if args.command == "evaluation-history-migrate":
        report = migrate_evaluation_history(
            path=args.history,
            migration=args.migration,
            expected_sha256=args.expected_sha256,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0

    settings = AgentSettings.from_env()

    if args.command in {"build-pfi-seed", "build-pfi-worker-image"}:
        source_root = _DEFAULT_AGENT_SOURCE_ROOT
        if args.command == "build-pfi-worker-image":
            _require_worker_context_matches_source(
                context=args.context,
                source_root=source_root,
            )
        _require_exact_source_checkout(
            source_root=source_root,
            source_commit=args.source_commit,
        )
        docker = SubprocessDocker()
        docker_cwd = args.context if args.command == "build-pfi-worker-image" else source_root
        canonicalizer_property = probe_base_image_elementtree(docker, cwd=docker_cwd)
        output = (
            args.output
            if args.command == "build-pfi-seed"
            else args.context / "build" / "proof-flow-index"
        )
        pfi_artifact = _build_pfi_seed(
            settings=settings,
            output=output,
            source_commit=args.source_commit,
            canonicalizer_property=canonicalizer_property,
        )
        if args.command == "build-pfi-worker-image":
            build_worker_image(
                docker,
                artifact=pfi_artifact,
                context=args.context,
                image_tag=args.tag,
                canonicalizer_property=canonicalizer_property,
            )
        print(
            json.dumps(
                {
                    "schema_version": "pals.pfi-seed-build-result.v1",
                    "seed_count": pfi_artifact.seed_count,
                    "seed_manifest_sha256": pfi_artifact.seed_manifest_sha256,
                    **(
                        {"worker_image": args.tag}
                        if args.command == "build-pfi-worker-image"
                        else {}
                    ),
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0

    if args.command == "evaluate-artifact":
        if not args.semantic_judge and (
            args.expected_evidence is not None or args.rubric is not None
        ):
            raise ValueError("--expected-evidence and --rubric require --semantic-judge")
        artifact = _read_json_mapping(args.artifact)
        explanation = (
            _explanation_content(_read_json_mapping(args.explanation))
            if args.explanation is not None
            else None
        )
        clarifications = (
            _clarification_contents(_read_json_value(args.clarifications))
            if args.clarifications is not None
            else None
        )
        run = evaluate_artifact(
            artifact,
            suite_revision=args.suite_revision,
            run_id=args.run_id,
            case_id=args.case_id,
            model=_artifact_model(artifact, fallback=settings.openai_model),
            model_metadata=_artifact_model_metadata(artifact),
            explanation=explanation,
            clarifications=clarifications,
            expect_clarification=args.expect_clarification,
        )
        if args.semantic_judge:
            judge = build_semantic_stage_judge(settings)
            run = judge.evaluate_or_mark_unavailable(
                artifact_metadata=artifact,
                evaluation_run=run,
                explanation=explanation,
                clarifications=clarifications,
                expect_clarification=args.expect_clarification,
                expected_evidence=(
                    _read_json_mapping(args.expected_evidence)
                    if args.expected_evidence is not None
                    else None
                ),
                rubric=(_read_json_mapping(args.rubric) if args.rubric is not None else None),
            )
        store = JsonlEvaluationStore(args.history)
        store.append(run)
        print(
            json.dumps(
                {
                    "evaluation": run.to_dict(),
                    "history": str(args.history),
                    "run_summary": summarize_evaluation_runs(
                        tuple(item for item in store.load_history() if item.run_id == run.run_id)
                    ),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "evaluation-history":
        history = JsonlEvaluationStore(args.history).load_history()
        selected = (
            tuple(run for run in history if run.run_id == args.run_id) if args.run_id else history
        )
        print(
            json.dumps(
                {
                    "history": str(args.history),
                    "summary": summarize_evaluation_runs(selected),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "evaluation-compare":
        history = JsonlEvaluationStore(args.history).load_history()
        baseline = tuple(run for run in history if run.run_id == args.baseline_run)
        candidate = tuple(run for run in history if run.run_id == args.candidate_run)
        if not baseline:
            raise ValueError(f"Baseline run not found: {args.baseline_run}")
        if not candidate:
            raise ValueError(f"Candidate run not found: {args.candidate_run}")
        print(
            json.dumps(
                {
                    "history": str(args.history),
                    "comparison": compare_evaluation_runs(baseline, candidate),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "benchmark":
        pipeline = build_pipeline(settings)
        results = [
            pipeline.run_problem(
                problem=problem,
            )
            for problem in BENCHMARK_PROBLEMS
        ]
        benchmark_payload = [_result_payload(result) for result in results]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(benchmark_payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(json.dumps(benchmark_payload, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if all(result.model_attempt_success for result in results) else 1

    if args.command == "openmath-structure":
        structurer = build_statement_openmath_structurer(settings)
        openmath_xml = structurer.structure(args.statement)
        print(
            json.dumps(
                {"statement": args.statement, "openmath_xml": openmath_xml},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    if args.command in {"worker", "worker-once"}:
        worker_queue_url(settings, args.lane)
        if not settings.worker_shared_secret:
            raise RuntimeError("PALS_WORKER_SHARED_SECRET is required for worker commands.")
        api_client = PalsApiClient(
            base_url=settings.api_base_url,
            worker_secret=settings.worker_shared_secret,
        )
        draining = False

        def request_drain(signum: int, frame: object) -> None:
            nonlocal draining
            # Only set an atomic Python flag in the signal handler. The worker
            # finishes its current receipt using the ordinary claim/ack path.
            draining = True

        formal_enabled = (
            args.lane != "assessment"
            and getattr(settings, "proof_capability", "full") == "full"
        )
        worker = SqsProofWorker(
            settings=settings,
            api_client=api_client,
            pipeline=None,
            explainer=build_proof_explainer(settings) if formal_enabled else None,
            output_reviewer=build_proof_output_reviewer(settings) if formal_enabled else None,
            proof_reviewer=build_proof_semantic_reviewer(settings) if formal_enabled else None,
            pipeline_factory=(lambda: build_pipeline(settings)) if formal_enabled else None,
            recipe_attempt_planner=(
                build_recipe_attempt_planner(settings) if formal_enabled else None
            ),
            proof_request_processor=(
                build_proof_request_processor(settings, api_client)
                if args.lane != "proof" else None
            ),
            stop_requested=lambda: draining,
            lane=args.lane,
        )
        if args.command == "worker":
            if ready_file is not None:
                ready_file.write_text(str(os.getpid()), encoding="ascii")
            previous_handlers = {}
            try:
                for signum in (signal.SIGTERM, signal.SIGINT):
                    previous_handlers[signum] = signal.signal(signum, request_drain)
                worker.run_forever()
            finally:
                for signum, previous in previous_handlers.items():
                    signal.signal(signum, previous)
                if ready_file is not None:
                    ready_file.unlink(missing_ok=True)
            return 0
        processed = worker.run_once()
        print(json.dumps({"processed": processed}, sort_keys=True))
        return 0

    raise AssertionError(f"Unhandled command: {args.command}")


def _require_exact_source_checkout(*, source_root: Path, source_commit: str) -> None:
    """Fail closed unless the claimed Agent source tree is clean and exact."""
    if not _SOURCE_COMMIT.fullmatch(source_commit):
        raise RuntimeError("PFI Agent source commit is invalid")
    if not source_root.is_dir() or source_root.is_symlink():
        raise RuntimeError("PFI Agent source checkout is invalid")

    status = _run_git(source_root, "status", "--porcelain=v1", "--untracked-files=all")
    if status.returncode != 0:
        raise RuntimeError("PFI Agent source checkout cannot be inspected")
    if status.stdout:
        raise RuntimeError("PFI Agent source checkout is not clean")

    revision = _run_git(source_root, "rev-parse", "--verify", "HEAD")
    if revision.returncode != 0:
        raise RuntimeError("PFI Agent source checkout cannot be inspected")
    if revision.stdout.strip() != source_commit:
        raise RuntimeError("PFI Agent source commit does not match the checkout")


def _require_worker_context_matches_source(*, context: Path, source_root: Path) -> None:
    try:
        context_root = context.resolve(strict=True)
        checked_source_root = source_root.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("PFI worker image build context is invalid") from exc
    if context_root != checked_source_root:
        raise RuntimeError("PFI worker image context does not match the Agent source")


def _run_git(source_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ("git", "-C", str(source_root), *arguments),
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("PFI Agent source checkout cannot be inspected") from exc


def _build_pfi_seed(
    *,
    settings: AgentSettings,
    output: Path,
    source_commit: str,
    canonicalizer_property: CanonicalizerChildProperty,
) -> SeedBuildArtifact:
    embedding_model = build_draft_embedding_model(settings)
    return ProofDraftSeedBuilder(
        embedding_model=embedding_model,
        fingerprint=SeedEmbeddingFingerprint(
            provider=settings.draft_embedding_provider,
            model=settings.draft_embedding_model,
            endpoint=embedding_model.endpoint_identity,
            deployment=embedding_model.deployment_identity,
            revision=embedding_model.revision,
            dimension=embedding_model.dimension,
            canonicalizer_version="openmath-cdbase-alpha-c14n-v4",
        ),
        canonicalizer_property=canonicalizer_property,
    ).build(
        drafts=SeedDraftCatalog().all_drafts(),
        destination=output,
        source_commit=source_commit,
    )


def _result_payload(result: ProofRunResult) -> dict[str, Any]:
    return {
        "problem_id": result.problem_id,
        "prompt": result.prompt,
        "state": result.state,
        "model": result.generated.model,
        "model_attempt_success": result.model_attempt_success,
        "artifact_uri": result.artifact.uri,
        "lean_artifact_uri": result.artifact.lean_uri,
        "model_attempt": {
            "verification": (
                asdict(result.model_attempt_verification)
                if result.model_attempt_verification is not None
                else None
            ),
        },
        "verification": asdict(result.verification),
    }


def _read_json_mapping(path: Path) -> dict[str, Any]:
    value = _read_json_value(path)
    if not isinstance(value, dict):
        raise ValueError(f"JSON input must contain an object: {path}")
    return value


def _read_json_value(path: Path) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"JSON input does not exist: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"JSON input is invalid: {path}: {exc}") from exc
    return value


def _explanation_content(payload: dict[str, Any]) -> dict[str, Any]:
    content = payload.get("content")
    if content is None:
        return payload
    if not isinstance(content, dict):
        raise ValueError("Explanation record content must be an object")
    return content


def _clarification_contents(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and "items" in payload:
        raw_items = payload["items"]
    elif isinstance(payload, list):
        raw_items = payload
    elif isinstance(payload, dict):
        raw_items = [payload]
    else:
        raise ValueError("Clarification JSON must contain an object or array")
    if not isinstance(raw_items, list):
        raise ValueError("Clarification items must be an array")

    contents: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise ValueError("Each clarification must be an object")
        content = item.get("content")
        if isinstance(content, dict):
            contents.append(content)
        else:
            contents.append(item)
    return contents


def _artifact_model(artifact: dict[str, Any], *, fallback: str) -> str:
    for key in ("generated", "model_attempt"):
        candidate = artifact.get(key)
        if isinstance(candidate, dict):
            model = candidate.get("model")
            if isinstance(model, str) and model.strip():
                return model.strip()
    return fallback


def _artifact_model_metadata(artifact: dict[str, Any]) -> dict[str, Any]:
    generated = artifact.get("generated")
    if not isinstance(generated, dict):
        generated = artifact.get("model_attempt")
    if not isinstance(generated, dict):
        return {}
    return {
        key: generated[key]
        for key in ("provider", "model", "elapsed_ms")
        if isinstance(generated.get(key), (str, int, float, bool))
    }


if __name__ == "__main__":
    raise SystemExit(main())
