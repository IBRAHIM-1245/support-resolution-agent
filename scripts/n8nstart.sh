#!/bin/bash
# Starts n8n inside this GitHub Codespace, with Langfuse tracing.

# Public URL of port 5678 (needed for webhooks behind the Codespaces proxy)
export WEBHOOK_URL="https://${CODESPACE_NAME}-5678.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}/"
export N8N_PROXY_HOPS=1

# n8n file nodes may ONLY read/write inside our data folder (safety)
export N8N_RESTRICT_FILE_ACCESS_TO="/workspaces/support-resolution-agent/data"
export GENERIC_TIMEZONE="Asia/Kolkata"

# Load secret keys from .env (this file is never committed)
set -a
source .env
set +a

# Langfuse tracing through n8n's built-in OpenTelemetry
export N8N_OTEL_ENABLED=true
export N8N_OTEL_EXPORTER_OTLP_ENDPOINT="https://cloud.langfuse.com/api/public/otel"
AUTH=$(printf "%s:%s" "$LANGFUSE_PUBLIC_KEY" "$LANGFUSE_SECRET_KEY" | base64 -w0)
export N8N_OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic ${AUTH},x-langfuse-ingestion-version=4"
export N8N_OTEL_EXPORTER_SERVICE_NAME="shaikmart-support-agent"

n8n start