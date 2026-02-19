# Custom LangGraph Workflow Agent (AKS + GPT-4.1 + GenAI Tracing)

This repo hosts a containerized FastAPI service with a custom LangGraph workflow (`goto` replan path), deterministic tools/retriever, GPT-4.1 Azure OpenAI calls, and OpenTelemetry GenAI tracing to Application Insights.

For full step-by-step commands, use **[SETUP_GUIDE.md](./SETUP_GUIDE.md)**.

## What Was Completed

### Application
- Implemented explicit LangGraph nodes and edges: `user_proxy`, `orchestrator`, `retrieve_context`, `draft_plan`, `run_tools`, `evaluate_constraints`, `replan`, `finalize`.
- Implemented `Command(goto="replan", update=...)` branch logic with `goto_triggered` telemetry event.
- Added deterministic offline tools (`get_weather`, `estimate_cost`) and offline retriever corpus.
- Added `/invoke`, `/healthz`, `/readyz`, `/version`, `/debug/telemetry`.
- Added trace context extraction (`traceparent`/`tracestate`) and parent-child correlation.

### Dependency and Local Validation
- Local environment runs with `python3` + virtualenv.
- Installed `langchain-azure-ai[opentelemetry]` from branch:
  - repo: `<your-langchain-azure-fork-url>`
  - ref: `<your-feature-branch>`
  - commit: `<commit-sha>`
- Local validation passed:
  - `python3 -m compileall app`
  - `python3 -m pytest` (`5 passed`, `1 skipped`)
  - local `/invoke` smoke with traceparent correlation

### Azure and AKS Provisioning
- Resource group used: `<resource-group-name>`
- App Insights resource:
  - `/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/microsoft.insights/components/<app-insights-name>`
- Created:
  - AKS: `<aks-name>` (OIDC + workload identity enabled)
  - ACR: `<acr-name>`
  - Managed identity: `<managed-identity-name>`
  - Federated credential: `<federated-credential-name>`
- Deployed app to namespace `agent-tracing-demo` with 2 replicas and successful rollout.

### Trace Validation
- Queried App Insights and confirmed full trace tree for deployed AKS invocation.
- Verified spans include:
  - `invoke_agent` (request root)
  - `gen_ai.chat` spans
  - tool spans (`gen_ai.operation.name=execute_tool`)
  - retriever spans
  - `goto_triggered` event

## Repo Layout

- `app/server.py` - API + request tracing context extraction
- `app/graph.py` - workflow graph, `goto` routing, node-level span attributes/events
- `app/model.py` - Azure OpenAI GPT-4.1 deployment config
- `app/tools.py` - deterministic tools
- `app/retriever.py` - deterministic retriever
- `app/telemetry.py` - OTel + callback tracer setup
- `k8s/` - AKS manifests (namespace/service/deployment/ingress/hpa/pdb/config/secret)
- `tests/` - smoke/unit tests and optional trace query test

## Environment and Secrets

Create local env file:

```bash
cp .env.example .env
```

Where to add keys:
- Local: `.env`
- AKS runtime: `k8s/secret.yaml` (or external secret manager)
- CI/CD: GitHub repository secrets

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

## AKS Deployment Template Values

Before deployment, set these values for your environment:
- Image: `<acr-name>.azurecr.io/langgraph-workflow-agent:<tag>`
- AOAI endpoint: `https://<your-azure-openai-resource>.cognitiveservices.azure.com`
- API version: `<azure-openai-api-version>`
- Workload identity client ID in `k8s/serviceaccount.yaml`

Never commit real secrets or tenant-specific key material.

## Trace Semantics Expected

One `/invoke` should show:
- root request span (`invoke_agent`)
- child `gen_ai.chat` spans for `draft_plan`, `replan`, `finalize`
- tool execution spans
- retriever span with query/result attributes
- custom attributes/events (`app.node_name`, `app.route_decision`, `biz.request_id`, `goto_triggered`)

## Notes

- `OTEL_RECORD_CONTENT=false` is the default.
- Sampler setting uses `parentbased_trace_id_ratio`.
- See **[SETUP_GUIDE.md](./SETUP_GUIDE.md)** for complete reproducible commands and verification queries.

## FAQ (for users and AI agents)

### 1) How do I confirm the service is actually using GPT-4.1?
Check App Insights dependency spans for `gen_ai.response.model` and your configured deployment in `AZURE_OPENAI_CHAT_DEPLOYMENT`.

### 2) Why do I see both `gen_ai.chat` and `chat gpt-4.1-*` spans?
`gen_ai.chat` is the app-level semantic span; `chat gpt-4.1-*` is provider/client-level detail span from the SDK callbacks.

### 3) How do I force the `goto` path for demos?
Set `options.force_goto_path=true` in `/invoke` or set `DEMO_FORCE_GOTO=true` for environment-level forcing.

### 4) Why do traces look flat sometimes?
This usually happens when work is executed outside the graph run context. Keep nested LLM/tool/retriever calls inside graph nodes.

### 5) Why are traces missing entirely?
Common causes: missing `APPLICATION_INSIGHTS_CONNECTION_STRING`, blocked egress, or misconfigured sampler.

### 6) How do I keep telemetry safe?
Keep `OTEL_RECORD_CONTENT=false` in shared/prod environments; only enable content capture for controlled debugging.

### 7) What should I preserve if another AI updates this repo?
Do not remove node-level span attributes/events (`app.node_name`, `app.route_decision`, `biz.request_id`, `goto_triggered`) or deterministic tool/retriever behavior.

### 8) How do I rotate config without rebuilding image?
Update ConfigMap/Secret values and redeploy/restart pods; image rebuild is not required for env-only changes.
