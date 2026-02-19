# Setup Guide: Local + AKS + App Insights Validation

This guide documents the exact workflow used to stand up and validate the LangGraph tracing demo.

## 1) Prerequisites

- Python 3.11+ (`python3`)
- Azure CLI (`az`) authenticated to subscription:
  - `<subscription-id>`
- `kubectl`
- Access to resource group:
  - `<resource-group-name>`

## 2) Local Environment Setup

```bash
cp .env.example .env
python3 -m venv .venv
source .venv/bin/activate
set -a && source .env && set +a
python3 -m pip install -e .[dev]
```

### Keys/Secrets Placement

- Local runtime secrets: `.env`
- AKS runtime secrets: `k8s/secret.yaml` or `kubectl create secret ...`
- CI/CD secrets: GitHub repository secrets

## 3) Install `langchain-azure-ai[opentelemetry]` from Branch

```bash
source .venv/bin/activate
python3 -m pip install --force-reinstall --no-deps \
  "langchain-azure-ai[opentelemetry] @ git+https://github.com/nagkumar91/langchain-azure.git@copilot/implement-compatibility-improvements#subdirectory=libs/azure-ai"
```

> Note: this is a temporary branch install for compatibility work; once that PR is merged/released, switch back to:
> `python3 -m pip install -U "langchain-azure-ai[opentelemetry]"`

Verification command:

```bash
source .venv/bin/activate
python3 - <<'PY'
import importlib.metadata as m
d = m.distribution("langchain-azure-ai")
print(d.read_text("direct_url.json"))
PY
```

Expected:
- URL points to `nagkumar91/langchain-azure.git`
- Requested revision is `copilot/implement-compatibility-improvements`
- Commit SHA matches the expected branch head

## 4) Local Validation

```bash
source .venv/bin/activate
set -a && source .env && set +a
python3 -m compileall app
python3 -m pytest
```

Local smoke invoke example:

```bash
curl -s http://localhost:8080/invoke \
  -H 'content-type: application/json' \
  -H 'traceparent: 00-11111111111111111111111111111111-2222222222222222-01' \
  -d '{
    "input": {"messages":[{"role":"user","content":"Plan a 2-day Seattle itinerary under $120 with rain backup."}]},
    "constraints":{"budget_usd":120,"days":2,"location":"Seattle","dates":["2026-05-20","2026-05-21"]},
    "options":{"record_content":false,"force_goto_path":true}
  }'
```

## 5) Azure Resource Provisioning (Performed)

Resources created in `<resource-group-name>`:
- AKS: `<aks-name>`
- ACR: `<acr-name>`
- Managed Identity: `<managed-identity-name>`
- Federated Credential: `<federated-credential-name>`

Representative commands:

```bash
az account set --subscription <subscription-id>
az acr create -g <resource-group-name> -n <acr-name> --sku Standard --location <azure-region>
az aks create -g <resource-group-name> -n <aks-name> \
  --location <azure-region> \
  --node-count 1 \
  --node-vm-size Standard_D2s_v5 \
  --enable-managed-identity \
  --enable-oidc-issuer \
  --enable-workload-identity \
  --attach-acr <acr-name>
```

Workload identity setup:

```bash
az identity create -g <resource-group-name> -n <managed-identity-name> --location <azure-region>
az identity federated-credential create \
  -g <resource-group-name> \
  --identity-name <managed-identity-name> \
  -n <federated-credential-name> \
  --issuer "<AKS_OIDC_ISSUER_URL>" \
  --subject "system:serviceaccount:agent-tracing-demo:workflow-agent-sa" \
  --audiences api://AzureADTokenExchange
```

## 6) Manifest Wiring (Performed)

Updated with real values:
- `k8s/configmap.yaml`
  - `AZURE_OPENAI_ENDPOINT=https://<your-azure-openai-resource>.cognitiveservices.azure.com`
  - `AZURE_OPENAI_API_VERSION=<api-version>`
- `k8s/deployment.yaml`
  - image `<acr-name>.azurecr.io/langgraph-workflow-agent:<tag>`
  - label `azure.workload.identity/use: "true"`
- `k8s/serviceaccount.yaml`
  - `azure.workload.identity/client-id` set to managed identity client ID

## 7) Build and Deploy to AKS

Because local Docker daemon may not be available, build in ACR:

```bash
az acr build -r <acr-name> -t langgraph-workflow-agent:<tag> .
az aks get-credentials -g <resource-group-name> -n <aks-name> --overwrite-existing
kubectl apply -k k8s
```

Apply runtime secrets from local environment values:

```bash
set -a && source .env && set +a
kubectl -n agent-tracing-demo create secret generic workflow-agent-secrets \
  --from-literal=APPLICATION_INSIGHTS_CONNECTION_STRING="$APPLICATION_INSIGHTS_CONNECTION_STRING" \
  --from-literal=AZURE_OPENAI_API_KEY="${AZURE_OPENAI_API_KEY:-}" \
  --dry-run=client -o yaml | kubectl apply -f -
```

Rollout checks:

```bash
kubectl -n agent-tracing-demo rollout status deployment/workflow-agent --timeout=600s
kubectl -n agent-tracing-demo get pods -o wide
kubectl -n agent-tracing-demo get svc workflow-agent -o wide
```

If pods are pending due to capacity, scale AKS node count:

```bash
az aks scale -g <resource-group-name> -n <aks-name> --node-count 2
```

## 8) AKS Smoke Test + Trace Correlation

Port-forward and invoke with explicit traceparent:

```bash
kubectl -n agent-tracing-demo port-forward svc/workflow-agent 18080:80
```

In another shell:

```bash
curl -s http://127.0.0.1:18080/invoke \
  -H 'content-type: application/json' \
  -H 'traceparent: 00-44444444444444444444444444444444-5555555555555555-01' \
  -d '{
    "input": {"messages":[{"role":"user","content":"Plan a 2-day Seattle itinerary under $120 with rain backup."}]},
    "constraints":{"budget_usd":120,"days":2,"location":"Seattle","dates":["2026-05-20","2026-05-21"]},
    "options":{"record_content":false,"force_goto_path":true}
  }'
```

Expected response checks:
- HTTP 200
- `output.debug.route_taken = replan_then_finalize`
- `telemetry.trace_id = 44444444444444444444444444444444`

## 9) App Insights Trace Query

Resource ID:

`/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/microsoft.insights/components/<app-insights-name>`

Example query:

```bash
az monitor app-insights query \
  --ids "/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/microsoft.insights/components/<app-insights-name>" \
  --analytics-query "search \"44444444444444444444444444444444\" | project itemType, operation_Name, operation_Id, operation_ParentId, message, customDimensions | take 30" \
  --offset 2h
```

Latest-run query (pulls the newest `invoke_agent` trace automatically):

```bash
az monitor app-insights query \
  --ids "/subscriptions/<subscription-id>/resourceGroups/<resource-group>/providers/microsoft.insights/components/<app-insights-name>" \
  --analytics-query "let latestTraceId = toscalar(requests | where operation_Name == 'invoke_agent' | top 1 by timestamp desc | project operation_Id); search * | where operation_Id == latestTraceId | project timestamp, itemType, operation_Name, operation_ParentId, message, customDimensions | order by timestamp asc | take 50" \
  --offset 2h
```

### Trace Shape (Observed from Current Query, Redacted)

The current live query shows this hierarchy pattern:

1. `request` → `invoke_agent` (root span)
2. `dependency` → `gen_ai.retriever` with:
   - `retriever.query`
   - `retriever.top_k`
   - `retriever.result_count`
3. `trace` event → `retriever_results`
4. `dependency` → `gen_ai.chat` (`app.node_name=draft_plan`)
5. `dependency` → `tool.get_weather` (`gen_ai.operation.name=execute_tool`)
6. `dependency` → `tool.estimate_cost` (`gen_ai.operation.name=execute_tool`)
7. `trace` event → `goto_triggered` (`from=evaluate_constraints`, `to=replan`)
8. `dependency` → `gen_ai.chat` (`app.node_name=replan`)
9. `dependency` → `gen_ai.chat` (`app.node_name=finalize`)

Representative redacted row snippets:

```text
request    invoke_agent      parent=<incoming-parent-span-id>
dependency gen_ai.retriever  parent=<workflow-span-id>
trace      retriever_results parent=<retriever-span-id>
dependency gen_ai.chat       customDimensions.app.node_name=draft_plan
dependency tool.get_weather  customDimensions.gen_ai.operation.name=execute_tool
trace      goto_triggered    customDimensions.reason=force_goto
dependency gen_ai.chat       customDimensions.app.node_name=replan
dependency gen_ai.chat       customDimensions.app.node_name=finalize
```

Expected records:
- `request` with `operation_Name=invoke_agent`
- `dependency` for `gen_ai.chat`, `tool.get_weather`, `tool.estimate_cost`, `gen_ai.retriever`
- `trace` message `goto_triggered`

## 10) Known Operational Notes

- Conditional access can block some Graph-backed `az` operations; re-login may be required:
  - `az login --tenant <tenant-id> --scope https://graph.microsoft.com//.default`
- Keep `OTEL_RECORD_CONTENT=false` by default.
- Replace ingress host/TLS in `k8s/ingress.yaml` before exposing public endpoint.
