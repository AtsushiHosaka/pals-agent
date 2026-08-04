import json
from typing import Any

from pals_agent.artifacts import S3ArtifactStore


class RecordingS3Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)


def test_pae_016_s3_checkpoint_uses_create_only_attempt_key() -> None:
    client = RecordingS3Client()
    store = S3ArtifactStore(client=client, bucket="proof-artifacts")
    metadata = {
        "checkpoint_schema_version": 1,
        "run_id": "proof-run-1",
        "attempt": {"attempt": 3},
    }

    store.save_checkpoint(run_id="proof-run-1", attempt=3, metadata=metadata)

    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["Bucket"] == "proof-artifacts"
    assert call["Key"] == "proof-jobs/proof-run-1/attempts/0003.json"
    assert call["IfNoneMatch"] == "*"
    assert json.loads(call["Body"].decode("utf-8")) == metadata
