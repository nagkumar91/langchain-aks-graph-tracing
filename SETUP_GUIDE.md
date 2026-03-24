# Setup Guide: Local + AKS + App Insights Validation

## 1) Prerequisites

- Python 3.11+ (`python3`)
- Azure CLI (`az`) authenticated
- `kubectl` (for AKS deployment)
- Azure OpenAI resource with GPT-4.1 deployment
- App Insights resource

## 2) Local Environment Setup

```bash
cp .env.example .env
# Fill in: AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_CHAT_DEPLOYMENT,
#          AZURE_OPENAI_API_KEY, APPLICATION_INSIGHTS_CONNECTION_STRING

python3 -m venv .venv
source .venv/bin/activate
set -a && source .env && set +a
python3 -m pip install -e .[dev]
```

### Dependency: langchain-azure-ai

Installed from `langchain-ai/langchain-azure` main branch:

```bash
pip install "langchain-azure-ai[opentelemetry] @ git+https://github.com/langchain-ai/langchain-azure.git@main#subdirectory=libs/azure-ai"
```

## 3) Local Validation

```bash
source .venv/bin/activate
set -a && source .env && set +a
python3 -m compileall app
python3 -m pytest
```

## 4) Run the Server

```bash
# Use always_on sampler for demos (100% sampling):
export OTEL_TRACES_SAMPLER=always_on
uvicorn app.server:app --host 0.0.0.0 --port 8080
```

## 5) Invoke with Trace Headers

```bash
curl -X POST http://localhost:8080/invoke \
  -H "Content-Type: application/json" \
  -H "traceparent: 00-aaaabbbbccccddddeeee111122223333-ff00ff00ff00ff00-01" \
  -H "metadata-client-region: us-west-2" \
  -H "metadata-session-id: sess-abc-123" \
  -H "metadata-experiment-id: exp-42" \
  -d '{
    "input": {"messages":[{"role":"user","content":"Plan a 2-day Seattle itinerary under $100 with rain backup."}]},
    "constraints":{"budget_usd":100,"days":2,"location":"Seattle","dates":["2026-05-20","2026-05-21"]},
    "options":{"record_content":true,"force_goto_path":true}
  }'
```

Expected:
- HTTP 200
- `output.debug.route_taken = replan_then_finalize` (goto path)
- `telemetry.trace_id` matches the traceparent header
- Custom `metadata-*` headers flow as `gen_ai.custom.*` span attributes

## 6) Telemetry Architecture

```
configure_azure_monitor()
  └─ TracerProvider + BatchSpanProcessor → App Insights
  └─ FastAPI auto-instrumentation (HTTP server spans)
  └─ LiveMetrics / QuickPulse

AzureAIOpenTelemetryTracer (LangChain callback)
  └─ invoke_agent spans (per LangGraph node)
  └─ chat spans (with gen_ai.tool.definitions from bind_tools)
  └─ execute_tool spans (tool call arguments + results)
```

Key: `configure_azure_monitor()` runs first and sets up the global `TracerProvider`.
The `AzureAIOpenTelemetryTracer` detects the existing provider and piggybacks on it
(no duplicate provider — see PR langchain-ai/langchain-azure#398).

## 7) Query Traces in App Insights

### Via Azure Portal
Go to App Insights → Logs, run:

```kql
union dependencies, requests
| where timestamp > ago(30m)
| where customDimensions["gen_ai.operation.name"] == "invoke_agent"
| project TimeGenerated, name, duration,
          customDimensions["gen_ai.agent.name"],
          customDimensions["gen_ai.tool.definitions"],
          customDimensions["gen_ai.custom.metadata_client_region"]
| order by TimeGenerated desc
| take 20
```

### Via az CLI

```bash
az rest --method post \
  --url "https://api.applicationinsights.io/v1/apps/<APP_ID>/query" \
  --headers "Content-Type=application/json" \
  --body '{"query": "union dependencies, requests | where operation_Id == '"'"'<TRACE_ID>'"'"' | project timestamp, itemType, name, duration, customDimensions | order by timestamp asc"}'
```

### Trace Shape (Observed)

```
invoke_agent langgraph-workflow-agent  (root, ~25s)
├─ invoke_agent user_proxy
├─ invoke_agent orchestrator
├─ invoke_agent retrieve_context
├─ invoke_agent draft_plan
│  └─ chat gpt-4.1-2025-04-14         (draft LLM call)
├─ invoke_agent run_tools              📋 gen_ai.tool.definitions
│  ├─ chat gpt-4.1-2025-04-14         (LLM decides tool calls)
│  ├─ execute_tool get_weather
│  ├─ execute_tool estimate_cost
│  └─ chat gpt-4.1-2025-04-14         (LLM receives tool results)
├─ invoke_agent evaluate_constraints   → goto replan
├─ invoke_agent replan
│  └─ chat gpt-4.1-2025-04-14
├─ invoke_agent run_tools              📋 gen_ai.tool.definitions (2nd pass)
│  ├─ chat gpt-4.1-2025-04-14
│  ├─ execute_tool get_weather
│  ├─ execute_tool estimate_cost
│  └─ chat gpt-4.1-2025-04-14
├─ invoke_agent evaluate_constraints
└─ invoke_agent finalize
   └─ chat gpt-4.1-2025-04-14
```

## 8) AKS Deployment

```bash
# Build and push to ACR
az acr build -r <acr-name> -t langgraph-workflow-agent:<tag> .
az aks get-credentials -g <resource-group> -n <aks-name> --overwrite-existing

# Apply secrets
set -a && source .env && set +a
kubectl -n agent-tracing-demo create secret generic workflow-agent-secrets \
  --from-literal=APPLICATION_INSIGHTS_CONNECTION_STRING="$APPLICATION_INSIGHTS_CONNECTION_STRING" \
  --from-literal=AZURE_OPENAI_API_KEY="${AZURE_OPENAI_API_KEY:-}" \
  --dry-run=client -o yaml | kubectl apply -f -

# Deploy
kubectl apply -k k8s
kubectl -n agent-tracing-demo rollout status deployment/workflow-agent --timeout=600s
```

## 9) Notes

- Set `OTEL_TRACES_SAMPLER=always_on` for demos; use `parentbased_trace_id_ratio` with `0.1` in prod.
- `configure_azure_monitor()` auto-instruments FastAPI — no manual HTTP span creation needed.
- Custom `metadata-*` headers are mapped to `gen_ai.custom.*` keys in LangChain metadata, which the tracer sets as span attributes.
- The `langchain-azure-ai` tracer's `_configure_azure_monitor()` detects the existing provider and skips duplicate setup.
