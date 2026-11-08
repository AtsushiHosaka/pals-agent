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
disable reuse. Behind the Elan proxies Lake also reports
`LEAN_RECURSION_COUNT`; only the one-hop value `1` is accepted, so a hit's `lean`
proxy sees the same count (`2`) as `lake env lean`. Darwin's known runtime
text-encoding key is dropped only on Darwin. Setup failure or unsupported topology records `fallback` and executes
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

With Elan the key digests the proxy, not the toolchain behind it. The toolchain
is bound by the `lean-toolchain` bytes, `ELAN_HOME` and the attested read-only
root, and the entry never outlives the process.

## Startup warm-up and failure backoff

With the flag on, the verifier resolves Lake's environment once during startup, after the
boundary attestation and before the ready marker (`LeanVerifier.warm_lake_environment`). No source
is compiled and no scratch directory outlives the call. The log line
`lean_environment_reuse status=<miss|hit|fallback>` reports the result: `miss` is the expected
value of a fresh process, and `fallback` (logged at warning level) means requests will keep running
the original `lake env lean` command because the reviewed vocabulary or topology check rejected the
setup. Startup does not fail on a fallback.

A rejected preparation (`ValueError`: unreviewed key, Lake output on stderr, non-zero exit) is
remembered for 60 s per setup key. Before, every request paid for a doomed `lake env` preparation and
then for the original command, which cost about 1.8 s more than leaving the flag off. Timeouts and
OS errors are not remembered. The backoff stores no result, and `clear()` resets it.

Reuse covers every Lean launch of a verification, not only the compile: the trusted audit that
follows an accepted compile runs `lake env lean --run` as well, so a hit removes two `lake env`
launches per accepted proof (three when the source contains an `example`).

## Production Elan path

Production resolves `lean` and `lake` to the `/opt/elan/bin` proxies. The
benchmark below takes native toolchain binaries (it derives `ELAN_HOME` from
their location), so its results do not exercise this path.

Measured in the arm64 verifier image with the production container limits, a
64 MiB request tmpfs and Lean 4.32.0-rc1 behind Elan 4.2.3. Fresh process per
arm, order rotated each round, 6 rounds, five sources per round (the four corpus
cases with explicit imports and one with `import Mathlib`). Another benchmark
shared the Docker daemon, so read the paired differences rather than the
absolute values.

| Source | Reuse off | Reuse on, before Elan fix | Reuse on, after fix |
| --- | --- | --- | --- |
| group-kernel-injectivity | 2059 ms | 3907 ms | 885 ms |
| coprime-product-divisibility | 2289 ms | 4250 ms | 1137 ms |
| linear-kernel-sum | 2612 ms | 4337 ms | 1381 ms |
| sequence-limit-addition | 2731 ms | 4578 ms | 1540 ms |
| group-kernel-injectivity, `import Mathlib` | 6721 ms | 7788 ms | 5296 ms |

Each cell is the median `verify` wall time of 6 samples, all hits in the last
column. Paired by round and source, the fix saves a median 1179 ms against reuse
off (faster in 29 of 30 pairs) and 2940 ms against the unfixed flag (30 of 30).
Before the fix the flag only added cost, because every request failed the
key check and then ran the original command. The first request of a process
(`miss`) took a median 2635 ms against 2121 ms with reuse off. On a hit,
`environment_identity` took about 20 ms.

The largest single-process RSS stays near 1050 MiB (one explicit-import source,
3 samples), because that is Lean itself. A hit does remove a process: `lake env`
spawns Lean and waits, holding about 823 MiB RSS during the compile, of which
67 MiB is anonymous and 756 MiB file-backed. File-backed pages may be shared
with Lean, so only the anonymous part is a firm per-request saving; total
container memory was not measured. Elan's proxy hop is lost in the noise of a 25-30 ms
`lean --version`, so calling native binaries would not gain measurable time.

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

Set `PALS_ACCELERATION_REAL_ELAN_HOME=/absolute/elan-home` as well to run the
production proxy path; without it that test is skipped.
