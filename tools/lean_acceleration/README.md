# Measured Lake environment reuse

The private mTLS verifier can opt in with
`PALS_LEAN_REUSE_LAKE_ENVIRONMENT=true` (default `false`). Startup must first
attest the trusted workspace's read-only boundary. The cache stores one reviewed
Lake environment delta in process memory, keyed by executable/config bytes,
resolved dependency topology and platform. It is cleared on process restart;
local callers may also call `LakeEnvironmentCache.clear()`. Every source,
including an identical source or a changed instantiation, still receives fresh
sandboxed Lean compilation. No compiler process is kept alive.

Each child receives a fresh HOME/TMPDIR. Lake's exact default HOME-based config
path is rebound to that HOME; other scratch-dependent values and unknown keys
disable reuse. Darwin's known runtime text-encoding key is dropped only on
Darwin. Setup failure or unsupported topology records `fallback` and executes
the original command within the same overall deadline. Proof-job source hashes,
semantic review, admission and API verification ownership are unchanged.

Recipe admission uses a separate uncached verifier because its receipt binds
the literal `lake env lean --threads=1 Main.lean` command. Any custom server
composition using a cached proof verifier must also supply a contract-compatible
uncached `admission_verifier`.

Production logs stage/duration/cache status only, without source or environment
values. The cache key is setup identity, **not** a proof, dependency-artifact or
catalog admission certificate. It cannot make mutable/untrusted workspaces
safe. Installed Mathlib modules retain their deployment trust boundary.

Run from the agent repository using its installed Python dependencies:

```sh
python -m tools.lean_acceleration.benchmark \
  --project-dir /absolute/trusted/lean-workspace \
  --lean-binary /absolute/pinned-toolchain/bin/lean \
  --lake-binary /absolute/pinned-toolchain/bin/lake \
  --repeats 5 --output /tmp/lean-environment-benchmark.json
```

The same four substantive proof bodies cover group-homomorphism injectivity from
its kernel, an epsilon proof of sequence-limit addition, coprime product
divisibility, and the kernel of a sum of linear maps with disjoint ranges.
Every sample invokes a fresh bounded Lean compiler. Broad and explicit import
variants compile independently; they are benchmark inputs, not an automatic
import transformation or theorem-equivalence claim.

The four modes measure broad imports, explicit imports, a new setup cache for
each compile, and a prepared process-local setup cache. Warmup is recorded
separately. Cold refers only to the process-local cache; OS filesystem caches
are uncontrolled. The report includes raw stage events, per-case and pooled
p50/p95, actual setup hits, invalid-source rejection under concurrency, and a
cache-clear lifecycle check. Baseline `compile` includes the Lake wrapper; cached
`compile` executes Lean directly. `environment_identity` is nested inside
`environment_prepare`, so stage timings must not be added together.
Nearest-rank p95 needs more samples before any
production tail-latency claim. Child RSS is the cumulative process maximum,
not per-mode memory or a concurrent process-tree peak.

No DB, provider, retrieval metrics, semantic review, catalog admission, compiled
proof-artifact reuse, browser result, or deployment is established by this tool.
Those stages are explicitly marked unmeasured. Existing installed Mathlib
artifacts are loaded afresh by Lean; no arbitrary compiled artifact is ingested.

Real integration tests use explicit environment variables:

```sh
PALS_ACCELERATION_REAL_PROJECT=/absolute/trusted/lean-workspace \
PALS_ACCELERATION_REAL_LEAN=/absolute/pinned-toolchain/bin/lean \
PALS_ACCELERATION_REAL_LAKE=/absolute/pinned-toolchain/bin/lake \
python -m pytest tests/integration/test_lean_acceleration_real.py
```
