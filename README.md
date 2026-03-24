# LangGraph Workflow Agent (AKS + GPT-4.1 + GenAI Tracing)

A containerized FastAPI service with a custom LangGraph workflow (`goto` replan path), **LLM-driven tool-calling** (`bind_tools`), deterministic retriever, GPT-4.1 Azure OpenAI, and full OpenTelemetry GenAI tracing to Application Insights via `configure_azure_monitor()`.

For full step-by-step commands, see **[SETUP_GUIDE.md](./SETUP_GUIDE.md)**.

## Architecture

### Graph Nodes
```
user_proxy → orchestrator → retrieve_context → draft_plan → run_tools → evaluate_constraints → finalize
                                                                ↑              │ (goto)
                                                                └── replan ←───┘
```

### LLM Tool-Calling
The `run_tools` node uses `llm.bind_tools([get_weather, estimate_cost])` so the LLM receives tool schemas and decides which tools to call. This produces `gen_ai.tool.definitions` on chat spans in App Insights.

### Custom Metadata Headers
Pass any `metadata-*` HTTP header on `/invoke` — they're injected as `gen_ai.custom.*` span attributes and appear as `customDimensions` in Azure Monitor.

### Telemetry Stack
- `configure_azure_monitor()` — handles FastAPI HTTP spans, trace export, and LiveMetrics
- `AzureAIOpenTelemetryTracer` (from `langchain-azure-ai`) — GenAI spans for agent nodes, LLM calls, tool calls, retriever

## Trace Semantics

One `/invoke` produces these span types in App Insights:

| Span | Type | Key Attributes |
|------|------|----------------|
| `invoke_agent langgraph-workflow-agent` | dependency | `gen_ai.agent.name`, `gen_ai.custom.*` metadata |
| `invoke_agent {node}` | dependency | Per-node: user_proxy, orchestrator, retrieve_context, etc. |
| `chat gpt-4.1-*` | dependency | `gen_ai.tool.definitions`, `gen_ai.input.messages`, `gen_ai.output.messages` |
| `execute_tool get_weather` | dependency | `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result` |
| `execute_tool estimate_cost` | dependency | `gen_ai.tool.call.arguments`, `gen_ai.tool.call.result` |

## Repo Layout

- `app/server.py` — FastAPI endpoints, metadata header extraction, traceparent propagation
- `app/graph.py` — LangGraph workflow with `bind_tools()` and `goto` routing
- `app/tools.py` — Deterministic tools (`@tool` decorated for LLM tool-calling)
- `app/model.py` — Azure OpenAI GPT-4.1 deployment config
- `app/retriever.py` — Offline keyword retriever with corpus
- `app/telemetry.py` — `configure_azure_monitor()` + `AzureAIOpenTelemetryTracer` callback setup
- `data/corpus.jsonl` — Travel knowledge base
- `k8s/` — AKS manifests
- `tests/` — Smoke/unit tests

## Environment Variables

```bash
cp .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | ✅ | Azure OpenAI resource endpoint |
| `AZURE_OPENAI_CHAT_DEPLOYMENT` | ✅ | GPT-4.1 deployment name |
| `AZURE_OPENAI_API_KEY` | ✅* | API key (*or use managed identity) |
| `APPLICATION_INSIGHTS_CONNECTION_STRING` | ✅ | App Insights connection string |
| `OTEL_SERVICE_NAME` | | Default: `langgraph-workflow-agent` |
| `OTEL_TRACES_SAMPLER` | | Default: `parentbased_trace_id_ratio` (use `always_on` for demos) |
| `OTEL_TRACES_SAMPLER_ARG` | | Default: `1.0` (set to `0.1` for 10% sampling in prod) |
| `DEMO_FORCE_GOTO` | | Set `true` to force the replan path |

## Local Run

```bash
python3 -m venv .venv
source .venv/bin/activate
set -a && source .env && set +a
python3 -m pip install -e .[dev]
python3 -m pytest
export OTEL_TRACES_SAMPLER=always_on  # 100% sampling for demos
uvicorn app.server:app --host 0.0.0.0 --port 8080
```

## Example Curl

```bash
curl -X POST http://localhost:8080/invoke \
  -H "Content-Type: application/json" \
  -H "traceparent: 00-aaaabbbbccccddddeeee111122223333-ff00ff00ff00ff00-01" \
  -H "metadata-client-region: us-west-2" \
  -H "metadata-session-id: sess-abc-123" \
  -H "metadata-experiment-id: exp-42" \
  -d '{
    "input": {"messages": [{"role":"user","content":"Plan a 2-day Seattle trip on a tight budget."}]},
    "constraints": {"budget_usd":100,"days":2,"location":"Seattle","dates":["2026-05-20","2026-05-21"]},
    "options": {"record_content":true,"force_goto_path":true}
  }'
```

## KQL Query (App Insights → Logs)

```kql
union dependencies, requests
| where operation_Id == '<trace-id-from-response>'
| project TimeGenerated, itemType, name, duration,
          customDimensions["gen_ai.operation.name"],
          customDimensions["gen_ai.agent.name"],
          customDimensions["gen_ai.tool.definitions"],
          customDimensions["gen_ai.custom.metadata_client_region"]
| order by TimeGenerated asc
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/invoke` | Plan a trip (main endpoint) |
| GET | `/healthz` | Health check |
| GET | `/readyz` | Readiness check |
| GET | `/version` | Build info |
| GET | `/debug/telemetry` | Telemetry config |
