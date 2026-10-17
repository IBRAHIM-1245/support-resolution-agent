#!/bin/bash
# Starts n8n inside this GitHub Codespace.

# Public URL of port 5678 (needed for webhooks behind the Codespaces proxy)
export WEBHOOK_URL="https://${CODESPACE_NAME}-5678.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}/"
export N8N_PROXY_HOPS=1

# n8n file nodes may ONLY read/write inside our data folder (safety)
export N8N_RESTRICT_FILE_ACCESS_TO="/workspaces/support-resolution-agent/data"

export GENERIC_TIMEZONE="Asia/Kolkata"

n8n start