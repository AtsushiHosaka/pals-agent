import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

import pals_agent.cli as cli
from pals_agent.cli import main
from pals_agent.proof_flow_seed import CanonicalizerChildProperty, SeedBuildArtifact
from pals_agent.semantic_evaluation import SemanticStageJudge


class _FailingSemanticClient:
    def generate(self, *, model: str, prompt: str) -> str:
        del model, prompt
        raise RuntimeError("private semantic judge transport detail")


def test_build_pfi_worker_image_cli_generates_then_verifies_the_image(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    context = tmp_path / "agent"
    context.mkdir()
    property = CanonicalizerChildProperty(
        source_path="/usr/local/lib/python3.12/xml/etree/ElementTree.py",
        source_sha256="a" * 64,
    )
    artifact = SeedBuildArtifact(
        root=context / "build/proof-flow-index",
        seed_file=context / "build/proof-flow-index/rootfs/opt/pals/draft-seed.json",
        seed_manifest_file=context / "build/proof-flow-index/metadata/seed-manifest.json",
        fingerprint_file=context / "build/proof-flow-index/metadata/fingerprint.json",
        build_provenance_file=context
        / "build/proof-flow-index/metadata/build-provenance.json",
        oci_labels_file=context / "build/proof-flow-index/metadata/oci-labels.json",
        seed_manifest_sha256="sha256:" + "b" * 64,
        seed_count=31,
    )
    calls: dict[str, Any] = {}
    docker = object()

    monkeypatch.setattr(cli, "_DEFAULT_AGENT_SOURCE_ROOT", context)
    monkeypatch.setattr(cli, "SubprocessDocker", lambda: docker)
    monkeypatch.setattr(
        cli,
        "_require_exact_source_checkout",
        lambda **kwargs: _record_source_checkout(calls, kwargs),
    )
    monkeypatch.setattr(
        cli,
        "probe_base_image_elementtree",
        lambda actual_docker, *, cwd: _record_probe(calls, actual_docker, cwd, property),
    )
    monkeypatch.setattr(
        cli,
        "_build_pfi_seed",
        lambda **kwargs: _record_seed_build(calls, kwargs, artifact),
    )
    monkeypatch.setattr(
        cli,
        "build_worker_image",
        lambda actual_docker, **kwargs: _record_image_build(calls, actual_docker, kwargs),
    )

    assert (
        main(
            [
                "build-pfi-worker-image",
                "--source-commit",
                "1" * 40,
                "--tag",
                "pals-agent-worker:test",
                "--context",
                str(context),
            ]
        )
        == 0
    )

    assert calls["source_checkout"] == {
        "source_root": context,
        "source_commit": "1" * 40,
    }
    assert calls["probe"] == (docker, context)
    assert calls["seed"]["output"] == context / "build/proof-flow-index"
    assert calls["image"] == (
        docker,
        {
            "artifact": artifact,
            "context": context,
            "image_tag": "pals-agent-worker:test",
            "canonicalizer_property": property,
        },
    )
    assert json.loads(capsys.readouterr().out) == {
        "schema_version": "pals.pfi-seed-build-result.v1",
        "seed_count": 31,
        "seed_manifest_sha256": "sha256:" + "b" * 64,
        "worker_image": "pals-agent-worker:test",
    }


def test_build_pfi_seed_cli_uses_the_explicit_agent_source_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "agent-source"
    unrelated_cwd = tmp_path / "unrelated-checkout"
    source_root.mkdir()
    unrelated_cwd.mkdir()
    output = tmp_path / "seed-output"
    property = CanonicalizerChildProperty(
        source_path="/usr/local/lib/python3.12/xml/etree/ElementTree.py",
        source_sha256="a" * 64,
    )
    artifact = SeedBuildArtifact(
        root=output,
        seed_file=output / "rootfs/opt/pals/draft-seed.json",
        seed_manifest_file=output / "metadata/seed-manifest.json",
        fingerprint_file=output / "metadata/fingerprint.json",
        build_provenance_file=output / "metadata/build-provenance.json",
        oci_labels_file=output / "metadata/oci-labels.json",
        seed_manifest_sha256="sha256:" + "b" * 64,
        seed_count=31,
    )
    calls: dict[str, Any] = {}
    docker = object()
    monkeypatch.chdir(unrelated_cwd)
    monkeypatch.setattr(cli, "_DEFAULT_AGENT_SOURCE_ROOT", source_root)
    monkeypatch.setattr(cli, "SubprocessDocker", lambda: docker)
    monkeypatch.setattr(
        cli,
        "_require_exact_source_checkout",
        lambda **kwargs: _record_source_checkout(calls, kwargs),
    )
    monkeypatch.setattr(
        cli,
        "probe_base_image_elementtree",
        lambda actual_docker, *, cwd: _record_probe(calls, actual_docker, cwd, property),
    )
    monkeypatch.setattr(
        cli,
        "_build_pfi_seed",
        lambda **kwargs: _record_seed_build(calls, kwargs, artifact),
    )

    assert (
        main(
            [
                "build-pfi-seed",
                "--output",
                str(output),
                "--source-commit",
                "1" * 40,
            ]
        )
        == 0
    )

    assert calls["source_checkout"] == {
        "source_root": source_root,
        "source_commit": "1" * 40,
    }
    assert calls["probe"] == (docker, source_root)


def _record_probe(
    calls: dict[str, Any],
    docker: object,
    cwd: Path,
    property: CanonicalizerChildProperty,
) -> CanonicalizerChildProperty:
    calls["probe"] = (docker, cwd)
    return property


def _record_source_checkout(calls: dict[str, Any], kwargs: dict[str, Any]) -> None:
    calls["source_checkout"] = kwargs


def _record_seed_build(
    calls: dict[str, Any],
    kwargs: dict[str, Any],
    artifact: SeedBuildArtifact,
) -> SeedBuildArtifact:
    calls["seed"] = kwargs
    return artifact


def _record_image_build(
    calls: dict[str, Any],
    docker: object,
    kwargs: dict[str, Any],
) -> None:
    calls["image"] = (docker, kwargs)


@pytest.mark.parametrize(
    ("status", "revision", "expected_message"),
    [
        (
            subprocess.CompletedProcess((), 0, stdout=" M pals_agent/cli.py\n", stderr=""),
            None,
            "PFI Agent source checkout is not clean",
        ),
        (
            subprocess.CompletedProcess((), 0, stdout="", stderr=""),
            subprocess.CompletedProcess((), 0, stdout="2" * 40 + "\n", stderr=""),
            "PFI Agent source commit does not match the checkout",
        ),
    ],
)
def test_pfi_source_checkout_rejects_dirty_or_mismatched_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: subprocess.CompletedProcess[str],
    revision: subprocess.CompletedProcess[str] | None,
    expected_message: str,
) -> None:
    results = iter(
        (status,) if revision is None else (status, revision)
    )
    monkeypatch.setattr(cli, "_run_git", lambda _root, *_args: next(results))

    with pytest.raises(RuntimeError, match=expected_message):
        cli._require_exact_source_checkout(
            source_root=tmp_path,
            source_commit="1" * 40,
        )


def test_pfi_source_checkout_accepts_only_the_exact_clean_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, ...]] = []
    results = iter(
        (
            subprocess.CompletedProcess((), 0, stdout="", stderr=""),
            subprocess.CompletedProcess((), 0, stdout="1" * 40 + "\n", stderr=""),
        )
    )

    def run_git(_root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        calls.append(arguments)
        return next(results)

    monkeypatch.setattr(cli, "_run_git", run_git)

    cli._require_exact_source_checkout(
        source_root=tmp_path,
        source_commit="1" * 40,
    )

    assert calls == [
        ("status", "--porcelain=v1", "--untracked-files=all"),
        ("rev-parse", "--verify", "HEAD"),
    ]


def test_pfi_worker_image_rejects_a_different_docker_context_before_docker_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "agent-source"
    context = tmp_path / "different-context"
    source_root.mkdir()
    context.mkdir()
    monkeypatch.setattr(cli, "_DEFAULT_AGENT_SOURCE_ROOT", source_root)
    monkeypatch.setattr(
        cli,
        "SubprocessDocker",
        lambda: pytest.fail("Docker must not start before source/context validation"),
    )

    with pytest.raises(RuntimeError, match="context does not match"):
        main(
            [
                "build-pfi-worker-image",
                "--source-commit",
                "1" * 40,
                "--context",
                str(context),
            ]
        )


def test_evaluate_artifact_cli_appends_history_and_reports_run_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_path = tmp_path / "result.json"
    history_path = tmp_path / "history.jsonl"
    artifact_path.write_text(
        json.dumps(
            {
                "problem_id": "add-zero",
                "generated": {
                    "model": "gpt-test",
                    "provider": "openai",
                    "lean_code": "example : True := by\n  trivial",
                },
                "verification": {"success": True, "diagnostics": []},
            }
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "evaluate-artifact",
            str(artifact_path),
            "--suite-revision",
            "suite-v1",
            "--run-id",
            "experiment-1",
            "--history",
            str(history_path),
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["evaluation"]["case_id"] == "add-zero"
    assert output["evaluation"]["model"] == "gpt-test"
    assert output["run_summary"]["run_count"] == 1
    assert history_path.read_text(encoding="utf-8").count("\n") == 1


def test_evaluation_history_cli_filters_by_experiment_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    artifact_path = tmp_path / "result.json"
    history_path = tmp_path / "history.jsonl"
    artifact_path.write_text("{}", encoding="utf-8")
    for run_id in ("experiment-1", "experiment-2"):
        assert (
            main(
                [
                    "evaluate-artifact",
                    str(artifact_path),
                    "--suite-revision",
                    "suite-v1",
                    "--run-id",
                    run_id,
                    "--case-id",
                    "case-1",
                    "--history",
                    str(history_path),
                ]
            )
            == 0
        )
        capsys.readouterr()

    assert (
        main(
            [
                "evaluation-history",
                "--history",
                str(history_path),
                "--run-id",
                "experiment-2",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["summary"]["run_count"] == 1
    assert output["summary"]["cases"] == ["case-1"]


def test_evaluate_artifact_cli_includes_explanation_and_clarification_flow(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    lean_code = "example : True := by\n  trivial"
    artifact_path = tmp_path / "result.json"
    explanation_path = tmp_path / "explanation.json"
    clarifications_path = tmp_path / "clarifications.json"
    history_path = tmp_path / "history.jsonl"
    artifact_path.write_text(
        json.dumps(
            {
                "generated": {"model": "gpt-test", "lean_code": lean_code},
                "verification": {"success": True},
            }
        ),
        encoding="utf-8",
    )
    explanation_path.write_text(
        json.dumps(
            {
                "content": {
                    "overview": "証明の概要",
                    "sections": [
                        {
                            "id": "close-goal",
                            "title": "ゴールを閉じる",
                            "summary": "trivial で True を示します。",
                            "references": [
                                {
                                    "start_line": 2,
                                    "end_line": 2,
                                    "excerpt": "  trivial",
                                }
                            ],
                        }
                    ],
                    "conclusion": "True が示されました。",
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    clarifications_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "state": "completed",
                        "content": {
                            "section_id": "close-goal",
                            "question": "trivial とは？",
                            "answer": (
                                "現在のゴールは True なので、trivial は標準コンストラクタを"
                                "適用し、未解決ゴールを残さずに証明を完了します。"
                            ),
                            "key_points": [
                                "現在のゴールは True です。",
                                "標準コンストラクタで閉じます。",
                            ],
                            "references": [
                                {
                                    "start_line": 2,
                                    "end_line": 2,
                                    "excerpt": "  trivial",
                                }
                            ],
                        },
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "evaluate-artifact",
            str(artifact_path),
            "--suite-revision",
            "explanation-v1",
            "--run-id",
            "flow-1",
            "--case-id",
            "true-proof",
            "--explanation",
            str(explanation_path),
            "--clarifications",
            str(clarifications_path),
            "--expect-clarification",
            "--history",
            str(history_path),
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    explanation_stage = next(
        stage
        for stage in output["evaluation"]["stages"]
        if stage["stage"] == "explanation"
    )
    metrics = {metric["name"]: metric["value"] for metric in explanation_stage["metrics"]}
    assert explanation_stage["status"] == "passed"
    assert metrics["clarification_count"] == 1
    assert metrics["clarification_section_overlap"] is True


def test_evaluate_artifact_cli_preserves_deterministic_history_when_semantic_judge_fails(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_path = tmp_path / "result.json"
    history_path = tmp_path / "history.jsonl"
    artifact_path.write_text(
        json.dumps(
            {
                "problem_id": "semantic-transport-failure",
                "retrieval": {
                    "candidate_draft_id": "draft-1",
                    "exact_equivalence": False,
                    "scores": {"final": 0.91},
                },
                "generated": {"model": "gpt-test", "lean_code": ""},
                "verification": {"success": False, "diagnostics": []},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "pals_agent.cli.build_semantic_stage_judge",
        lambda settings: SemanticStageJudge(
            client=_FailingSemanticClient(),
            model=settings.openai_model,
            provider="openai",
            model_revision="judge-revision",
        ),
    )

    exit_code = main(
        [
            "evaluate-artifact",
            str(artifact_path),
            "--suite-revision",
            "semantic-v1",
            "--run-id",
            "semantic-failure-1",
            "--semantic-judge",
            "--history",
            str(history_path),
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    retrieval = next(
        stage
        for stage in output["evaluation"]["stages"]
        if stage["stage"] == "retrieval"
    )
    metrics = {metric["name"]: metric for metric in retrieval["metrics"]}
    assert metrics["candidate_present"]["value"] is True
    assert metrics["semantic_quality"]["status"] == "not_evaluated"
    assert metrics["semantic_quality"]["value"] is None
    assert "private semantic judge transport detail" not in history_path.read_text(
        encoding="utf-8"
    )


def test_evaluation_compare_cli_reports_baseline_to_candidate_delta(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    history_path = tmp_path / "history.jsonl"
    failed_path = tmp_path / "failed.json"
    passed_path = tmp_path / "passed.json"
    failed_path.write_text(
        json.dumps({"verification": {"success": False}, "generated": {"lean_code": ""}}),
        encoding="utf-8",
    )
    passed_path.write_text(
        json.dumps(
            {
                "verification": {"success": True},
                "generated": {"lean_code": "example : True := by\n  trivial"},
            }
        ),
        encoding="utf-8",
    )
    for run_id, artifact_path in (("baseline", failed_path), ("candidate", passed_path)):
        assert main(
            [
                "evaluate-artifact",
                str(artifact_path),
                "--suite-revision",
                "suite-v1",
                "--run-id",
                run_id,
                "--case-id",
                "true-proof",
                "--history",
                str(history_path),
            ]
        ) == 0
        capsys.readouterr()

    assert main(
        [
            "evaluation-compare",
            "--history",
            str(history_path),
            "--baseline-run",
            "baseline",
            "--candidate-run",
            "candidate",
        ]
    ) == 0

    output = json.loads(capsys.readouterr().out)
    end_to_end = output["comparison"]["stages"]["end_to_end"]
    assert end_to_end["pass_rate_delta"] == 1.0
