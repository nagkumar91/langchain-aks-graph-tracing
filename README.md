# Zava Travel Agent (LangGraph + AKS + Azure AI Foundry + GenAI Tracing)

**Zava** is an AI-powered travel agent built as a containerized FastAPI service. It uses a custom LangGraph workflow with `goto` replan path, **LLM-driven tool-calling** (`bind_tools`), an offline travel knowledge retriever, GPT-4.1 via Azure OpenAI, and full OpenTelemetry GenAI tracing to Application Insights via `configure_azure_monitor()`.

Zava can be registered as a **custom agent in Azure AI Foundry** via the AI Gateway, enabling centralized governance, telemetry, and rate limiting.

For full step-by-step commands, see **[SETUP_GUIDE.md](./SETUP_GUIDE.md)**.

## What Zava Does

Zava plans complete trips for travelers by:
1. Understanding travel constraints (budget, destination, dates, travelers, travel style)
2. Retrieving relevant destination knowledge from its corpus
3. Drafting an initial travel plan via LLM
4. Using LLM tool-calling (`bind_tools`) to search flights, hotels, weather, and estimate costs
5. Evaluating budget constraints and replanning if needed (LangGraph `goto`)
6. Producing a final, friendly travel plan summary

## Architecture

### Graph Nodes
```
user_proxy → orchestrator → retrieve_context → draft_plan → run_tools → evaluate_constraints → finalize
                                                                ↑              │ (goto)
                                                                └── replan ←───┘
```

### LLM Tool-Calling
The `run_tools` node uses `llm.bind_tools([search_flights, search_hotels, get_destination_weather, estimate_trip_cost])`. The LLM receives tool schemas, decides which tools to call, and tool results are fed back. This produces `gen_ai.tool.definitions` on chat spans in App Insights.

### Custom Metadata Headers
Pass any `metadata-*` HTTP header on `/invoke` — they're injected as `gen_ai.custom.*` span attributes and appear as `customDimensions` in Azure Monitor.

### Telemetry Stack
- `configure_azure_monitor()` — handles trace export, LiveMetrics, and FastAPI auto-instrumentation
- `AzureAIOpenTelemetryTracer` (from `langchain-azure-ai`) — GenAI spans for agent nodes, LLM calls, tool calls

### Destinations Supported
Paris, Tokyo, Cancun, Bali, New York, Barcelona, London, Seattle, Rome, Dubai, Sydney, Bangkok

## Repo Layout

| File | Description |
|------|-------------|
| `app/server.py` | FastAPI endpoints, metadata header extraction |
| `app/graph.py` | LangGraph workflow with `bind_tools()` and `goto` routing |
| `app/tools.py` | `@tool` decorated tools for LLM tool-calling |
| `app/model.py` | Azure OpenAI GPT-4.1 deployment config |
| `app/retriever.py` | Offline keyword retriever with corpus |
| `app/schemas.py` | Pydantic request/response models |
| `app/telemetry.py` | `configure_azure_monitor()` + callback tracer setup |
| `data/corpus.jsonl` | Travel destination knowledge base |
| `k8s/` | AKS manifests (deployment, service, configmap, etc.) |
| `tests/` | Smoke/unit tests |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/invoke` | Plan a trip (main endpoint) |
| GET | `/healthz` | Health check |
| GET | `/readyz` | Readiness check |
| GET | `/version` | Build info |
| GET | `/debug/telemetry` | Telemetry config |

### Example `/invoke` Request

```bash
curl -X POST https://<gateway-or-host>/invoke \
  -H "Content-Type: application/json" \
  -H "traceparent: 00-aaaabbbbccccddddeeee111122223333-ff00ff00ff00ff00-01" \
  -H "metadata-trip-type: romantic" \
  -H "metadata-client-region: eu-west-1" \
  -d '{
    "input": {"messages": [{"role":"user","content":"Plan a 4-day romantic Paris getaway for 2"}]},
    "constraints": {"budget_usd":4000,"days":4,"destination":"Paris","travelers":2,"travel_style":"luxury","dates":["2026-06-10","2026-06-11","2026-06-12","2026-06-13"]},
    "options": {"record_content":true,"force_goto_path":false}
  }'
```

## Azure AI Foundry Registration

Zava can be registered as a custom agent in Azure AI Foundry, routing all traffic through the AI Gateway for governance and observability.

### Prerequisites
- An Azure AI Foundry project with **AI Gateway enabled**
- An APIM instance linked as the AI Gateway
- The agent deployed to AKS with an HTTPS endpoint (self-signed cert is OK)

### Register via CLI

```bash
# 1. Create the agent API in APIM with isAgent=true
az rest --method put \
  --url "https://management.azure.com/subscriptions/<SUB_ID>/resourceGroups/<RG>/providers/Microsoft.ApiManagement/service/<APIM_NAME>/apis/<AGENT_ID>?api-version=2025-03-01-preview" \
  --body '{
    "properties": {
      "displayName": "Zava Travel Agent",
      "path": "<AGENT_ID>",
      "protocols": ["https"],
      "serviceUrl": "https://<AKS_EXTERNAL_IP>",
      "subscriptionRequired": false,
      "isAgent": true,
      "agent": {
        "id": "<AGENT_ID>",
        "title": "Zava Travel Agent",
        "description": "AI-powered travel planning agent with LangGraph, LLM tool-calling, and OTel tracing.",
        "providerName": "zava"
      }
    }
  }'

# 2. Create a backend with TLS validation disabled (for self-signed certs)
az rest --method put \
  --url "https://management.azure.com/subscriptions/<SUB_ID>/resourceGroups/<RG>/providers/Microsoft.ApiManagement/service/<APIM_NAME>/backends/<AGENT_ID>-backend?api-version=2025-03-01-preview" \
  --body '{
    "properties": {
      "url": "https://<AKS_EXTERNAL_IP>",
      "protocol": "http",
      "tls": {"validateCertificateChain": false, "validateCertificateName": false}
    }
  }'

# 3. Set the API policy to use the backend and extend timeout
az rest --method put \
  --url "https://management.azure.com/subscriptions/<SUB_ID>/resourceGroups/<RG>/providers/Microsoft.ApiManagement/service/<APIM_NAME>/apis/<AGENT_ID>/policies/policy?api-version=2025-03-01-preview" \
  --body '{
    "properties": {
      "format": "xml",
      "value": "<policies><inbound><base /><set-backend-service backend-id=\"<AGENT_ID>-backend\" /></inbound><backend><forward-request timeout=\"120\" /></backend><outbound><base /></outbound><on-error><base /></on-error></policies>"
    }
  }'

# 4. Add the /invoke operation
az rest --method put \
  --url "https://management.azure.com/subscriptions/<SUB_ID>/resourceGroups/<RG>/providers/Microsoft.ApiManagement/service/<APIM_NAME>/apis/<AGENT_ID>/operations/invoke?api-version=2025-03-01-preview" \
  --body '{"properties": {"displayName": "Invoke Agent", "method": "POST", "urlTemplate": "/invoke"}}'
```

### Register via Portal

1. Go to **Azure AI Foundry** → your project → **Operate** → **Overview**
2. Click **Register asset**
3. Fill in:
   - **Agent URL**: `https://<AKS_EXTERNAL_IP>/invoke`
   - **Protocol**: `General HTTP, Including REST`
   - **OpenTelemetry agent ID**: `zava-travel-agent` (matches `OTEL_SERVICE_NAME`)
   - **Admin portal URL**: link to your AKS cluster in Azure Portal
   - **Project**: your Foundry project
   - **Agent name**: `Zava Travel Agent`

### Invoke via AI Gateway

Once registered, all traffic goes through the APIM gateway with unified tracing:

```bash
curl -X POST https://<APIM_NAME>.azure-api.net/zava-travel-agent/invoke \
  -H "Content-Type: application/json" \
  -H "traceparent: 00-$(openssl rand -hex 16)-$(openssl rand -hex 8)-01" \
  -H "metadata-trip-type: romantic" \
  -H "metadata-client-region: eu-west-1" \
  -H "metadata-source: ai-foundry-gateway" \
  -d '{
    "input": {
      "messages": [{"role": "user", "content": "Plan a 4-day romantic Paris getaway for 2. Eiffel Tower, Seine cruise, fine dining."}]
    },
    "constraints": {
      "budget_usd": 4000,
      "days": 4,
      "destination": "Paris",
      "travelers": 2,
      "travel_style": "luxury",
      "dates": ["2026-06-10", "2026-06-11", "2026-06-12", "2026-06-13"]
    },
    "options": {"record_content": true, "force_goto_path": false}
  }'
```

The `traceparent` header creates a unified trace across APIM → Agent. All 30+ spans (gateway HTTP + agent workflow + LLM calls + tool executions) appear under a single trace ID in App Insights.

**More examples:**

```bash
# Tokyo budget solo adventure (force replan)
curl -X POST https://<APIM_NAME>.azure-api.net/zava-travel-agent/invoke \
  -H "Content-Type: application/json" \
  -H "traceparent: 00-$(openssl rand -hex 16)-$(openssl rand -hex 8)-01" \
  -H "metadata-trip-type: adventure" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "Plan a 5-day solo Tokyo adventure. Temples, street food, Akihabara."}]},
    "constraints": {"budget_usd": 1500, "days": 5, "destination": "Tokyo", "travelers": 1, "travel_style": "budget", "dates": ["2026-04-05", "2026-04-06", "2026-04-07", "2026-04-08", "2026-04-09"]},
    "options": {"record_content": true, "force_goto_path": true}
  }'

# London family weekend
curl -X POST https://<APIM_NAME>.azure-api.net/zava-travel-agent/invoke \
  -H "Content-Type: application/json" \
  -H "traceparent: 00-$(openssl rand -hex 16)-$(openssl rand -hex 8)-01" \
  -H "metadata-trip-type: family" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "Plan a 2-day London weekend for a family of 4. British Museum, Tower of London, afternoon tea."}]},
    "constraints": {"budget_usd": 1800, "days": 2, "destination": "London", "travelers": 4, "travel_style": "mid", "dates": ["2026-06-15", "2026-06-16"]},
    "options": {"record_content": true, "force_goto_path": false}
  }'

# Dubai luxury escape
curl -X POST https://<APIM_NAME>.azure-api.net/zava-travel-agent/invoke \
  -H "Content-Type: application/json" \
  -H "traceparent: 00-$(openssl rand -hex 16)-$(openssl rand -hex 8)-01" \
  -H "metadata-trip-type: luxury" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "Plan a 3-day Dubai luxury trip. Burj Khalifa, desert safari, shopping."}]},
    "constraints": {"budget_usd": 5000, "days": 3, "destination": "Dubai", "travelers": 2, "travel_style": "luxury", "dates": ["2026-11-10", "2026-11-11", "2026-11-12"]},
    "options": {"record_content": true, "force_goto_path": false}
  }'
```
```

## Trace Semantics

One `/invoke` produces ~20-28 spans in App Insights:

| Span | Key Attributes |
|------|----------------|
| `invoke_agent zava-travel-agent` | `gen_ai.agent.name`, `gen_ai.custom.*` metadata |
| `invoke_agent {node}` | Per-node spans for each graph node |
| `chat gpt-4.1-*` | `gen_ai.tool.definitions`, `gen_ai.input/output.messages` |
| `execute_tool search_flights` | `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result` |
| `execute_tool search_hotels` | Hotel search results |
| `execute_tool get_destination_weather` | Weather forecast |
| `execute_tool estimate_trip_cost` | Cost breakdown |

### KQL Query

```kql
union dependencies, requests
| where timestamp > ago(30m)
| where customDimensions["gen_ai.agent.name"] == "zava-travel-agent"
| project TimeGenerated, name, duration,
          customDimensions["gen_ai.operation.name"],
          customDimensions["gen_ai.tool.definitions"],
          customDimensions["gen_ai.custom.metadata_trip_type"]
| order by TimeGenerated desc
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | ✅ | Azure OpenAI or APIM gateway endpoint |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | ✅ | GPT-4.1 deployment name |
| `AZURE_OPENAI_API_KEY` | ✅* | API key or APIM subscription key |
| `APPLICATION_INSIGHTS_CONNECTION_STRING` | ✅ | App Insights connection string |
| `OTEL_SERVICE_NAME` | | Default: `zava-travel-agent` |
| `OTEL_TRACES_SAMPLER` | | Use `always_on` for demos |
| `DEMO_FORCE_GOTO` | | Set `true` to force replan path |

## Local Run

```bash
python3 -m venv .venv && source .venv/bin/activate
set -a && source .env && set +a
python3 -m pip install -e .[dev]
python3 -m pytest
export OTEL_TRACES_SAMPLER=always_on
uvicorn app.server:app --host 0.0.0.0 --port 8080
```
