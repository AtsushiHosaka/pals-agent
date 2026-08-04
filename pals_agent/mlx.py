from __future__ import annotations

import subprocess
from dataclasses import dataclass


class MlxError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MlxGenerateClient:
    binary: str = "mlx_lm.generate"
    timeout_seconds: float = 180.0
    max_tokens: int = 2048
    temperature: float = 0.0

    def generate(self, *, model: str, prompt: str) -> str:
        command = [
            self.binary,
            "--model",
            model,
            "--prompt",
            "-",
            "--max-tokens",
            str(self.max_tokens),
            "--temp",
            str(self.temperature),
            "--verbose",
            "False",
        ]
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise MlxError(f"MLX generate binary was not found: {self.binary}") from exc
        except subprocess.TimeoutExpired as exc:
            raise MlxError(
                f"MLX generation timed out after {self.timeout_seconds:.1f}s."
            ) from exc

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise MlxError(
                f"MLX generation failed with status {completed.returncode}: {detail}"
            )

        generated = completed.stdout.strip()
        if not generated:
            raise MlxError("MLX response did not contain text.")
        return generated
