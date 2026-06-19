# pals-agent

Public OSS LangGraph agent toolkit for PALS.

`pals-agent` contains the proof-generation agent, tool interfaces, and Lean
verification runtime used by PALS. The repository is designed to work without
private PALS infrastructure: private API clients, deployment configuration, and
production prompts must live outside this public boundary.

## Scope

- LangGraph proof-generation workflow
- Lean compile tool interface
- Lean verifier runtime and diagnostics parser
- Provider adapters for local and hosted LLMs
- Evaluation fixtures that are safe to publish

## Repository Boundaries

This repository must not contain:

- API keys or provider credentials
- private PALS API endpoints
- AWS account IDs or production configuration
- private prompts or private datasets
- files under `.claude/`, `.codex/`, or `.env.*`

Lean verification code lives here because it is a first-class agent tool. In
production, the verifier can still run as a separate process or sidecar
container even though it shares this repository.

## License

Apache License 2.0.
