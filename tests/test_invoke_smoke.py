import json

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.server import create_app


class StubLLM:
    def invoke(self, messages, config=None):  # noqa: ANN001
        system = messages[0].content
        if "NODE:draft_plan" in system:
            return AIMessage(
                content=json.dumps(
                    {
                        "itinerary": [
                            {
                                "day": 1,
                                "activity": "Waterfront Walk",
                                "type": "outdoor",
                                "budget_friendly": False,
                            },
                            {
                                "day": 2,
                                "activity": "Museum Day",
                                "type": "indoor",
                                "budget_friendly": False,
                            },
                        ],
                        "summary": "Initial draft plan",
                    }
                )
            )
        if "NODE:replan" in system:
            return AIMessage(
                content=json.dumps(
                    {
                        "itinerary": [
                            {
                                "day": 1,
                                "activity": "Discovery Park",
                                "type": "budget",
                                "budget_friendly": True,
                            },
                            {
                                "day": 2,
                                "activity": "Food Hall + Museum Pass",
                                "type": "budget",
                                "budget_friendly": True,
                            },
                        ],
                        "summary": "Budget-friendly replan",
                    }
                )
            )
        return AIMessage(content="Here is your finalized itinerary and rationale.")


def _payload(force_goto: bool = False) -> dict:
    return {
        "input": {
            "messages": [
                {"role": "user", "content": "Plan a 2-day Seattle itinerary with rain backup."}
            ]
        },
        "constraints": {
            "budget_usd": 120.0,
            "days": 2,
            "location": "Seattle",
            "dates": ["2026-05-20", "2026-05-21"],
        },
        "options": {"record_content": False, "force_goto_path": force_goto},
    }


def test_invoke_smoke_with_goto() -> None:
    client = TestClient(create_app(llm=StubLLM()))
    response = client.post("/invoke", json=_payload(force_goto=True))
    assert response.status_code == 200
    body = response.json()
    assert body["output"]["messages"][0]["role"] == "assistant"
    assert body["output"]["debug"]["route_taken"] == "replan_then_finalize"
    assert body["output"]["plan"]["itinerary"][0]["budget_friendly"] is True


def test_invoke_honors_traceparent() -> None:
    client = TestClient(create_app(llm=StubLLM()))
    incoming_trace_id = "11111111111111111111111111111111"
    traceparent = f"00-{incoming_trace_id}-2222222222222222-01"
    response = client.post(
        "/invoke",
        json=_payload(force_goto=False),
        headers={"traceparent": traceparent},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["telemetry"]["trace_id"] == incoming_trace_id
