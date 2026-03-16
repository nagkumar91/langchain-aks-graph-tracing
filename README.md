# Zava Travel Agent (LangGraph + AKS + GPT-4.1 + GenAI Tracing)

**Zava** is an AI-powered travel agent built as a containerized FastAPI service. It uses a custom LangGraph workflow with `goto` replan path, deterministic travel tools (flight search, hotel search, weather, trip cost estimation), an offline travel knowledge retriever, GPT-4.1 Azure OpenAI calls, and OpenTelemetry GenAI tracing to Application Insights.

For full step-by-step commands, use **[SETUP_GUIDE.md](./SETUP_GUIDE.md)**.

## What Zava Does

Zava plans complete trips for travelers by:
1. Understanding travel constraints (budget, destination, dates, travelers, travel style)
2. Retrieving relevant destination knowledge from its corpus
3. Drafting an initial travel plan with flights, hotels, and daily activities
4. Running tools to get weather forecasts, flight pricing, hotel availability, and cost estimates
5. Evaluating budget constraints and replanning if needed (using LangGraph `goto`)
6. Producing a final, friendly travel plan summary

## Architecture

### Graph Nodes
- `user_proxy` → `orchestrator` → `retrieve_context` → `draft_plan` → `run_tools` → `evaluate_constraints` → `replan` (optional) → `finalize`

### Tools
- **search_flights** - Deterministic flight search across 12 destinations with economy/business/budget classes
- **search_hotels** - Deterministic hotel search with budget/mid/luxury tiers
- **get_destination_weather** - Weather forecasts for travel destinations
- **estimate_trip_cost** - Full trip cost estimation (flights + hotels + activities)

### Destinations Supported
Paris, Tokyo, Cancun, Bali, New York, Barcelona, London, Seattle, Rome, Dubai, Sydney, Bangkok

## Repo Layout

- `app/server.py` - FastAPI endpoints + request tracing context extraction
- `app/graph.py` - LangGraph workflow with travel agent nodes and `goto` routing
- `app/model.py` - Azure OpenAI GPT-4.1 deployment config
- `app/tools.py` - Deterministic travel tools (flights, hotels, weather, cost)
- `app/retriever.py` - Offline travel knowledge retriever
- `app/schemas.py` - Pydantic request/response models with travel constraints
- `app/telemetry.py` - OTel + callback tracer setup
- `data/corpus.jsonl` - Travel destination knowledge base
- `k8s/` - AKS manifests
- `tests/` - Smoke/unit tests

## API Endpoints

- `POST /invoke` - Plan a trip (main endpoint)
- `GET /healthz` - Health check
- `GET /readyz` - Readiness check
- `GET /version` - Build info
- `GET /debug/telemetry` - Telemetry config

### Example `/invoke` Request

```json
{
  "input": {
    "messages": [{"role": "user", "content": "Plan a 5-day trip to Paris for 2 people"}]
  },
  "constraints": {
    "budget_usd": 3000,
    "days": 5,
    "destination": "Paris",
    "travelers": 2,
    "travel_style": "mid",
    "dates": ["2026-06-10", "2026-06-11", "2026-06-12", "2026-06-13", "2026-06-14"]
  },
  "options": {"record_content": false, "force_goto_path": false}
}
```

## Environment and Secrets

```bash
cp .env.example .env
```

Required variables:
- `AZURE_OPENAI_ENDPOINT`
- `AZURE_OPENAI_CHAT_DEPLOYMENT`
- `APPLICATION_INSIGHTS_CONNECTION_STRING`

## Local Run (Quick)

```bash
python3 -m venv .venv
source .venv/bin/activate
set -a && source .env && set +a
python3 -m pip install -e .[dev]
python3 -m pytest
uvicorn app.server:app --host 0.0.0.0 --port 8080
```

## Trace Semantics Expected

One `/invoke` should show:
- root request span (`invoke_agent`)
- child `gen_ai.chat` spans for `draft_plan`, `replan`, `finalize`
- tool execution spans (`search_flights`, `search_hotels`, `get_destination_weather`, `estimate_trip_cost`)
- retriever span with query/result attributes
- custom attributes/events (`app.node_name`, `app.route_decision`, `biz.request_id`, `goto_triggered`)

## Notes

- `OTEL_RECORD_CONTENT=false` is the default.
- Sampler setting uses `parentbased_trace_id_ratio`.
- Set `options.force_goto_path=true` or `DEMO_FORCE_GOTO=true` to force the replan path for demos.
