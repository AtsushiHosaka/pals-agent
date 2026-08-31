from __future__ import annotations

from pals_agent.models import BenchmarkProblem

BENCHMARK_PROBLEMS: tuple[BenchmarkProblem, ...] = (
    BenchmarkProblem(
        id="continuous_square",
        prompt="x^2が連続であることを示せ",
    ),
    BenchmarkProblem(
        id="rank_nullity",
        prompt="rank A = n - Ker Aを示せ",
    ),
    BenchmarkProblem(
        id="compact_image",
        prompt="cpt集合の連続写像による像はcpt集合であることを示せ",
    ),
)
