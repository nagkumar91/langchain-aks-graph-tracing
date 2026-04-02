# Setup Guide: Local → AKS → AI Foundry Registration

## 1) Prerequisites

- Python 3.11+, Azure CLI (`az`), `kubectl`, Docker
- MCP tools are included — no extra setup needed (runs as subprocess via stdio)
- Azure subscription with:
  - Azure OpenAI resource (or APIM gateway to one) with GPT-4.1 deployment
  - App Insights resource
  - ACR (Azure Container Registry)
  - AI Foundry project with **AI Gateway enabled**

## 2) Local Environment Setup

```bash
cp .env.example .env
# Fill in AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_CHAT_DEPLOYMENT,
#         AZURE_OPENAI_API_KEY, APPLICATION_INSIGHTS_CONNECTION_STRING
#
# Content recording (ensures tool args/results are NOT redacted in traces):
#   OTEL_RECORD_CONTENT=true
#   AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=true

python3 -m venv .venv
source .venv/bin/activate
set -a && source .env && set +a
python3 -m pip install -e .[dev]
python3 -m pytest
```

## 3) Run Locally

```bash
export OTEL_TRACES_SAMPLER=always_on  # 100% sampling for demos
export OTEL_RECORD_CONTENT=true
export AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=true
uvicorn app.server:app --host 0.0.0.0 --port 8080
```

Test:
```bash
curl -X POST http://localhost:8080/invoke \
  -H "Content-Type: application/json" \
  -H "metadata-trip-type: romantic" \
  -d '{"input":{"messages":[{"role":"user","content":"Plan a 3-day Paris trip for 2"}]},"constraints":{"budget_usd":3000,"days":3,"destination":"Paris","travelers":2,"travel_style":"mid","dates":["2026-06-10","2026-06-11","2026-06-12"]},"options":{"record_content":true,"force_goto_path":false}}'
```

## 4) Build and Deploy to AKS

### Build the container image

```bash
# Local build (for docker push)
docker build --platform linux/amd64 -t <ACR>.azurecr.io/zava-travel-agent:v1 .
az acr login -n <ACR>
docker push <ACR>.azurecr.io/zava-travel-agent:v1

# Or ACR build (requires git in image — see Dockerfile)
az acr build -r <ACR> -t zava-travel-agent:v1 .
```

### Create AKS cluster (if needed)

```bash
az aks create -g <RG> -n <AKS_NAME> \
  --location <REGION> --node-count 1 --node-vm-size Standard_B2s \
  --enable-managed-identity --enable-oidc-issuer --enable-workload-identity
```

### Deploy

```bash
az aks get-credentials -g <RG> -n <AKS_NAME> --overwrite-existing
kubectl create namespace agent-tracing-demo

# ACR pull secret (if no role assignment)
az acr credential show -n <ACR>
kubectl -n agent-tracing-demo create secret docker-registry acr-secret \
  --docker-server=<ACR>.azurecr.io \
  --docker-username=<ACR_USER> --docker-password=<ACR_PASSWORD>

# App secrets
kubectl -n agent-tracing-demo create secret generic zava-travel-agent-secrets \
  --from-literal=APPLICATION_INSIGHTS_CONNECTION_STRING="<CONN_STRING>" \
  --from-literal=AZURE_OPENAI_API_KEY="<API_KEY>"

# Update k8s/deployment.yaml with your image, then:
kubectl apply -k k8s
kubectl -n agent-tracing-demo rollout status deployment/zava-travel-agent
```

### Expose with HTTPS (required for Foundry registration)

```bash
# Generate self-signed cert
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /tmp/zava-tls.key -out /tmp/zava-tls.crt \
  -subj "/CN=<EXTERNAL_IP>" -addext "subjectAltName=IP:<EXTERNAL_IP>"

# Create configmap and update deployment to use TLS
kubectl -n agent-tracing-demo create configmap zava-tls-files \
  --from-file=tls.crt=/tmp/zava-tls.crt --from-file=tls.key=/tmp/zava-tls.key

# Expose via LoadBalancer on port 443
kubectl -n agent-tracing-demo apply -f - <<EOF
apiVersion: v1
kind: Service
metadata:
  name: zava-travel-agent
  namespace: agent-tracing-demo
spec:
  type: LoadBalancer
  selector:
    app: zava-travel-agent
  ports:
    - port: 443
      targetPort: 8443
EOF
```

Verify: `curl -sk https://<EXTERNAL_IP>/readyz`

## 5) Register in Azure AI Foundry

> Reference: [Register a custom agent](https://learn.microsoft.com/en-us/azure/foundry/control-plane/register-custom-agent)

### Prerequisites
1. **Enable AI Gateway** in Foundry Admin → AI Gateway tab → Enable for your project
2. Note your APIM gateway name (e.g., `nitya-3p-agents-gateway`)

### Register via CLI

```bash
SUB_ID="<subscription-id>"
RG="<resource-group>"
APIM="<apim-gateway-name>"
AGENT_ID="zava-travel-agent"
BACKEND_IP="<AKS_EXTERNAL_IP>"

# Step 1: Register the agent API
az rest --method put \
  --url "https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.ApiManagement/service/$APIM/apis/$AGENT_ID?api-version=2025-03-01-preview" \
  --body "{
    \"properties\": {
      \"displayName\": \"Zava Travel Agent\",
      \"path\": \"$AGENT_ID\",
      \"protocols\": [\"https\"],
      \"serviceUrl\": \"https://$BACKEND_IP\",
      \"subscriptionRequired\": false,
      \"isAgent\": true,
      \"agent\": {
        \"id\": \"$AGENT_ID\",
        \"title\": \"Zava Travel Agent\",
        \"description\": \"AI travel agent with LangGraph, tool-calling, and OTel tracing\",
        \"providerName\": \"zava\"
      }
    }
  }"

# Step 2: Create backend (skip TLS validation for self-signed certs)
az rest --method put \
  --url "https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.ApiManagement/service/$APIM/backends/$AGENT_ID-backend?api-version=2025-03-01-preview" \
  --body "{
    \"properties\": {
      \"url\": \"https://$BACKEND_IP\",
      \"protocol\": \"http\",
      \"tls\": {\"validateCertificateChain\": false, \"validateCertificateName\": false}
    }
  }"

# Step 3: Set policy (backend routing + 120s timeout for LLM calls)
az rest --method put \
  --url "https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.ApiManagement/service/$APIM/apis/$AGENT_ID/policies/policy?api-version=2025-03-01-preview" \
  --body "{
    \"properties\": {
      \"format\": \"xml\",
      \"value\": \"<policies><inbound><base /><set-backend-service backend-id=\\\"$AGENT_ID-backend\\\" /></inbound><backend><forward-request timeout=\\\"120\\\" /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>\"
    }
  }"

# Step 4: Add the /invoke operation
az rest --method put \
  --url "https://management.azure.com/subscriptions/$SUB_ID/resourceGroups/$RG/providers/Microsoft.ApiManagement/service/$APIM/apis/$AGENT_ID/operations/invoke?api-version=2025-03-01-preview" \
  --body '{"properties": {"displayName": "Invoke", "method": "POST", "urlTemplate": "/invoke"}}'
```

### Register via Portal

1. Go to **Foundry** → your project → **Operate** → **Overview**
2. Click **Register asset**
3. Fill in:
   - **Agent URL**: `https://<AKS_EXTERNAL_IP>/invoke`
   - **Protocol**: General HTTP, Including REST
   - **OpenTelemetry agent ID**: `zava-travel-agent`
   - **Project**: your Foundry project
   - **Agent name**: `Zava Travel Agent`

### Send traffic via AI Gateway

```bash
curl -X POST https://<APIM>.azure-api.net/zava-travel-agent/invoke \
  -H "Content-Type: application/json" \
  -H "metadata-trip-type: luxury" \
  -H "metadata-client-region: eu-west-1" \
  -d '{"input":{"messages":[{"role":"user","content":"Plan a 4-day Paris getaway for 2"}]},"constraints":{"budget_usd":4000,"days":4,"destination":"Paris","travelers":2,"travel_style":"luxury","dates":["2026-06-10","2026-06-11","2026-06-12","2026-06-13"]},"options":{"record_content":true,"force_goto_path":false}}'
```

## 6) Verify Traces in App Insights

```bash
# Via az CLI (use the App Insights Application ID)
az rest --method post \
  --url "https://api.applicationinsights.io/v1/apps/<APP_ID>/query" \
  --headers "Content-Type=application/json" \
  --body '{"query": "dependencies | where timestamp > ago(30m) | where customDimensions[\"gen_ai.agent.name\"] == \"zava-travel-agent\" | project timestamp, name, duration, customDimensions | order by timestamp desc | take 20"}'
```

### Expected Trace Shape (~20-28 spans per request)

```
invoke_agent zava-travel-agent              (root, ~25-50s)
├─ invoke_agent user_proxy
├─ invoke_agent orchestrator
├─ invoke_agent retrieve_context
├─ invoke_agent research_destination        🌐 MCP tools (travel advisory + local phrases)
│  ├─ app.mcp.get_travel_advisory           visa, safety, currency info
│  └─ app.mcp.get_local_phrases             local language phrases
├─ invoke_agent draft_plan                  (enriched with MCP research data)
│  └─ chat gpt-4.1-2025-04-14              (draft LLM call)
├─ invoke_agent run_tools                   📋 gen_ai.tool.definitions
│  ├─ chat gpt-4.1-2025-04-14              (LLM selects tools)
│  ├─ execute_tool search_flights
│  ├─ execute_tool search_hotels
│  ├─ execute_tool get_destination_weather
│  ├─ execute_tool estimate_trip_cost
│  └─ chat gpt-4.1-2025-04-14              (LLM receives results)
├─ invoke_agent evaluate_constraints        → goto replan (if over budget)
├─ invoke_agent replan
│  └─ chat gpt-4.1-2025-04-14
├─ invoke_agent run_tools                   📋 (2nd pass)
│  └─ ...
├─ invoke_agent evaluate_constraints
└─ invoke_agent finalize
   └─ chat gpt-4.1-2025-04-14
```

## 7) Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| 502 on Foundry registration | AI Gateway not enabled on APIM | Enable in Foundry Admin → AI Gateway |
| 502 on `isAgent: true` API creation | APIM doesn't support agent APIs | Enable AI Gateway first |
| 500 on POST through APIM | APIM can't validate self-signed cert | Create backend with `validateCertificateChain: false` |
| Timeout on invoke through APIM | Default 30s timeout too short for LLM | Set `forward-request timeout="120"` in policy |
| No traces in App Insights | 10% sampling drops traces | Set `OTEL_TRACES_SAMPLER=always_on` |
| Tool args show `[redacted]` | Content recording disabled | Set `OTEL_RECORD_CONTENT=true` and `AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=true` |
| MCP tools fail silently | Subprocess spawn error | Check `python -m app.mcp_server` runs standalone; check Python path |
| `MCP_SIMULATE_FAILURE=true` | Intentional failure demo | Unset to restore normal operation |
| Image pull fails on AKS | ACR role assignment missing | Use `imagePullSecrets` with ACR admin credentials |
