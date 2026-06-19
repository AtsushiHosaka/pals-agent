FROM python:3.12-slim

WORKDIR /app
COPY pals_agent /app/pals_agent

CMD ["python", "-m", "pals_agent.lean_verifier.server"]

