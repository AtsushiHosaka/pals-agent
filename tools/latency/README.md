# Latency probes

- `http_helper_overhead.py`: cost of the worker's fresh-process HTTP helper per call.
- `poll_lag.py`: time from a Lean verification settling to the worker noticing it. Runs the
  worker's real `_wait_for_candidate_reconciliation` and HTTP transport against a local stub API
  (no Lean, DB, model or TLS), so it isolates the polling schedule and the per-call process cost.
  `python -m tools.latency.poll_lag --trials 20 --min-seconds 2 --max-seconds 6`
