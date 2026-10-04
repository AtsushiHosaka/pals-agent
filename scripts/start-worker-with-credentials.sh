#!/bin/sh
set -eu

# This serving entry is selected only for the production worker service.
if [ "${PALS_ENV:-${PALS_ENVIRONMENT:-local}}" != "prod" ]; then
  printf 'Worker AWS credential boundary requires the production environment.\n' >&2
  exit 2
fi
export PALS_ENV=prod

if [ "${PALS_PROOF_CAPABILITY:-}" != "natural-only" ] || \
   [ "${PALS_TOKEN_ACCOUNTING_ENABLED:-}" != "true" ]; then
  printf 'Worker production boundary requires natural-only capability and token accounting.\n' >&2
  exit 2
fi

# AgentSettings passes these overrides directly to boto3. Reject them before any
# worker import; the SDK's ignore-configured-endpoints flag cannot override them.
if [ -n "${PALS_LOCALSTACK_ENDPOINT_URL:-}" ] || [ -n "${PALS_AWS_ENDPOINT_URL:-}" ]; then
  printf 'Worker AWS credential boundary requires the production AWS endpoint.\n' >&2
  exit 2
fi

# CredentialProcess is behind environment/configuration providers in the SDK
# chain. Remove every ambient credential source before the worker imports boto3.
unset AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN AWS_SECURITY_TOKEN
unset AWS_ACCESS_KEY AWS_SECRET_KEY AWS_CREDENTIAL_EXPIRATION AWS_DATA_PATH AWS_CREDENTIAL_FILE
unset AWS_WEB_IDENTITY_TOKEN_FILE AWS_ROLE_ARN AWS_ROLE_SESSION_NAME
unset AWS_CONTAINER_CREDENTIALS_RELATIVE_URI AWS_CONTAINER_CREDENTIALS_FULL_URI
unset AWS_CONTAINER_AUTHORIZATION_TOKEN AWS_CONTAINER_AUTHORIZATION_TOKEN_FILE
unset AWS_ENDPOINT_URL AWS_ENDPOINT_URL_S3 AWS_ENDPOINT_URL_SQS AWS_ENDPOINT_URL_STS
export AWS_PROFILE=pals-worker-runtime AWS_DEFAULT_PROFILE=pals-worker-runtime
export PALS_AWS_REGION=ap-northeast-1 AWS_REGION=ap-northeast-1 AWS_DEFAULT_REGION=ap-northeast-1
export AWS_CONFIG_FILE=/app/scripts/aws-worker-profile.conf
export AWS_SHARED_CREDENTIALS_FILE=/dev/null BOTO_CONFIG=/dev/null
export AWS_EC2_METADATA_DISABLED=true AWS_SDK_LOAD_CONFIG=1
export AWS_IGNORE_CONFIGURED_ENDPOINT_URLS=true

/usr/local/bin/python -I -m pals_agent.aws_worker_credentials --check /run/credentials/worker

exec /usr/local/bin/pals-agent worker "$@"
