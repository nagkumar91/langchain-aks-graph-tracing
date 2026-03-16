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
                        "destination": "Paris",
                        "itinerary": [
                            {
                                "day": 1,
                                "activity": "Eiffel Tower & Seine Cruise",
                                "type": "sightseeing",
                                "budget_friendly": False,
                            },
                            {
                                "day": 2,
                                "activity": "Louvre Museum & Montmartre",
                                "type": "cultural",
                                "budget_friendly": False,
                            },
                            {
                                "day": 3,
                                "activity": "Versailles Day Trip",
                                "type": "sightseeing",
                                "budget_friendly": False,
                            },
                        ],
                        "summary": "A 3-day Parisian adventure by Zava",
                    }
                )
            )
        if "NODE:replan" in system:
            return AIMessage(
                content=json.dumps(
                    {
                        "destination": "Paris",
                        "itinerary": [
                            {
                                "day": 1,
                                "activity": "Free Walking Tour & Picnic",
                                "type": "budget",
                                "budget_friendly": True,
                            },
                            {
                                "day": 2,
                                "activity": "Musée d'Orsay Free Day & Parks",
                                "type": "budget",
                                "budget_friendly": True,
                            },
                            {
                                "day": 3,
                                "activity": "Marché aux Puces & Street Food",
                                "type": "budget",
                                "budget_friendly": True,
                            },
                        ],
                        "summary": "Budget-friendly Paris replan by Zava",
                    }
                )
            )
        return AIMessage(content="Here is your Zava travel plan for Paris! Bon voyage!")


def _payload(force_goto: bool = False) -> dict:
    return {
        "input": {
            "messages": [
                {"role": "user", "content": "Plan a 3-day trip to Paris for 2 travelers."}
            ]
        },
        "constraints": {
            "budget_usd": 800.0,
            "days": 3,
            "destination": "Paris",
            "travelers": 2,
            "travel_style": "mid",
            "dates": ["2026-06-10", "2026-06-11", "2026-06-12"],
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


def test_invoke_returns_flight_and_hotel_debug() -> None:
    client = TestClient(create_app(llm=StubLLM()))
    response = client.post("/invoke", json=_payload(force_goto=False))
    assert response.status_code == 200
    body = response.json()
    debug = body["output"]["debug"]
    assert "Air France" in debug["flight_summary"]
    assert "Hotel Le Marais" in debug["hotel_summary"]
    assert debug["cost_estimate_usd"] > 0
