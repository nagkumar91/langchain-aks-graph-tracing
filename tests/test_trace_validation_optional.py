import json
import os
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.server import create_app


class MinimalStubLLM:
    def invoke(self, messages, config=None):  # noqa: ANN001
        system = messages[0].content
        if "NODE:finalize" in system:
            return AIMessage(content="final response")
        return AIMessage(content=json.dumps({"itinerary": [], "summary": "ok"}))


@pytest.mark.skipif(
    os.getenv("RUN_TRACE_VALIDATION", "").lower() not in {"1", "true", "yes"},
    reason="Set RUN_TRACE_VALIDATION=true to run App Insights trace query validation.",
)
def test_trace_id_queryable_in_app_insights() -> None:
    from azure.identity import DefaultAzureCredential
    from azure.monitor.query import LogsQueryClient, LogsQueryStatus

    workspace_id = os.environ["TRACE_VALIDATION_WORKSPACE_ID"]
    app = create_app(llm=MinimalStubLLM())
    client = TestClient(app)
    trace_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    traceparent = f"00-{trace_id}-bbbbbbbbbbbbbbbb-01"

    response = client.post(
        "/invoke",
        json={
            "input": {"messages": [{"role": "user", "content": "trace validation"}]},
            "constraints": {"budget_usd": 5000, "days": 3, "destination": "Paris", "travelers": 2, "travel_style": "mid", "dates": []},
            "options": {"record_content": False, "force_goto_path": False},
        },
        headers={"traceparent": traceparent},
    )
    assert response.status_code == 200
    assert response.json()["telemetry"]["trace_id"] == trace_id

    time.sleep(int(os.getenv("TRACE_VALIDATION_WAIT_SECONDS", "20")))
    logs_client = LogsQueryClient(DefaultAzureCredential())
    query = (
        "union isfuzzy=true AppRequests, AppDependencies, AppTraces "
        f"| where OperationId == '{trace_id}' "
        "| project OperationName, Name, TimeGenerated "
        "| take 20"
    )
    result = logs_client.query_workspace(
        workspace_id=workspace_id,
        query=query,
        timespan=timedelta(minutes=int(os.getenv("TRACE_VALIDATION_LOOKBACK_MINUTES", "30"))),
    )
    assert result.status == LogsQueryStatus.SUCCESS
    rows = result.tables[0].rows if result.tables else []
    assert rows
