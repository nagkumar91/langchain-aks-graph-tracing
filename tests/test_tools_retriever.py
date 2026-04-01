from app.retriever import OfflineRetriever
from app.tools import estimate_trip_cost, get_destination_weather, search_flights, search_hotels


def test_get_weather_is_deterministic() -> None:
    result = get_destination_weather.invoke({"destination": "Paris", "dates": ["2026-06-10", "2026-06-11"]})
    assert result["destination"] == "Paris"
    assert result["daily"][0]["condition"] == "sunny"
    assert "deterministic" in result["summary"].lower()


def test_search_flights_returns_pricing() -> None:
    result = search_flights.invoke({"destination": "Paris", "travelers": 2, "travel_class": "economy"})
    assert result["airline"] == "Air France"
    assert result["total_price_usd"] == 1300
    assert result["method"] == "deterministic-v1"


def test_search_hotels_returns_info() -> None:
    result = search_hotels.invoke({"destination": "Tokyo", "nights": 3, "travelers": 2, "tier": "budget"})
    assert result["hotel_name"] == "Sakura Hotel Jimbocho"
    assert result["total_price_usd"] == 195  # 65 * 3 nights * 1 room
    assert result["rooms"] == 1


def test_estimate_trip_cost_marks_budget_status() -> None:
    import json
    plan = {
        "itinerary": [
            {"activity": "Eiffel Tower", "type": "sightseeing", "budget_friendly": False},
            {"activity": "Louvre Museum", "type": "cultural", "budget_friendly": True},
        ]
    }
    result = estimate_trip_cost.invoke({
        "plan": json.dumps(plan),
        "days": 3,
        "budget_usd": 500.0,
        "travelers": 2,
        "destination": "Paris",
    })
    assert result["estimate_usd"] > 0
    assert result["within_budget"] is False  # flights+hotel+activities > $500


def test_offline_retriever_returns_ranked_docs() -> None:
    retriever = OfflineRetriever()
    docs = retriever.search("paris culture museum romantic", top_k=2)
    assert len(docs) == 2
    assert docs[0]["score"] >= docs[1]["score"]
