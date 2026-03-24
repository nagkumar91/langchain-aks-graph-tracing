from app.retriever import OfflineRetriever
from app.tools import estimate_cost, get_weather


def test_get_weather_is_deterministic() -> None:
    result = get_weather.invoke({"location": "Seattle", "dates": ["2026-05-20", "2026-05-21"]})
    assert result["location"] == "Seattle"
    assert result["daily"][0]["condition"] == "rain"
    assert "deterministic" in result["summary"].lower()


def test_estimate_cost_marks_budget_status() -> None:
    plan = {
        "itinerary": [
            {"activity": "Pike Place", "type": "outdoor", "budget_friendly": False},
            {"activity": "Museum Day", "type": "indoor", "budget_friendly": True},
        ]
    }
    import json
    result = estimate_cost.invoke({"plan_json": json.dumps(plan), "days": 2, "budget_usd": 200.0})
    assert result["estimate_usd"] > 0
    assert result["within_budget"] is False


def test_offline_retriever_returns_ranked_docs() -> None:
    retriever = OfflineRetriever()
    docs = retriever.search("seattle budget rainy backup options", top_k=2)
    assert len(docs) == 2
    assert docs[0]["score"] >= docs[1]["score"]
