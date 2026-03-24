import json

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from app.server import create_app


class StubLLM:
    """Stub that supports bind_tools() and returns appropriate responses."""

    def __init__(self):
        self._tools = None

    def bind_tools(self, tools):
        bound = StubLLM()
        bound._tools = tools
        return bound

    def invoke(self, messages, config=None, **kwargs):  # noqa: ANN001
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
        # For run_tools node: if tools are bound, simulate tool_calls then
        # return a final message after tool results are fed back.
        if self._tools and "MUST call" in system:
            has_tool_results = any(
                getattr(m, "type", None) == "tool"
                for m in messages
            )
            if not has_tool_results:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "call_flights_1",
                            "name": "search_flights",
                            "args": {"destination": "Paris", "travelers": 2, "travel_class": "economy"},
                        },
                        {
                            "id": "call_hotels_1",
                            "name": "search_hotels",
                            "args": {"destination": "Paris", "nights": 3, "travelers": 2, "tier": "mid"},
                        },
                        {
                            "id": "call_weather_1",
                            "name": "get_destination_weather",
                            "args": {"destination": "Paris", "dates": ["2026-06-10", "2026-06-11", "2026-06-12"]},
                        },
                        {
                            "id": "call_cost_1",
                            "name": "estimate_trip_cost",
                            "args": {
                                "plan": "{}",
                                "days": 3,
                                "budget_usd": 800.0,
                                "travelers": 2,
                                "destination": "Paris",
                            },
                        },
                    ],
                )
            return AIMessage(content="Tools executed successfully.")
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
