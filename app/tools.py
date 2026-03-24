from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool, tool

WEATHER_TABLE = {
    "seattle": {
        "2026-05-20": {"condition": "rain", "high_f": 57, "low_f": 48},
        "2026-05-21": {"condition": "cloudy", "high_f": 60, "low_f": 49},
        "2026-05-22": {"condition": "sunny", "high_f": 67, "low_f": 51},
    },
    "new york": {
        "2026-05-20": {"condition": "sunny", "high_f": 74, "low_f": 62},
        "2026-05-21": {"condition": "cloudy", "high_f": 70, "low_f": 61},
    },
}

ACTIVITY_BASE_COST = {
    "outdoor": 140.0,
    "indoor": 95.0,
    "budget": 65.0,
    "backup": 80.0,
}


@tool
def get_weather(location: str, dates: list[str]) -> dict[str, Any]:
    """Get weather forecast for a location and list of dates. Returns daily conditions, highs, lows, and a summary."""
    normalized_location = location.strip().lower()
    table = WEATHER_TABLE.get(normalized_location, {})
    daily = []
    for day in dates:
        weather = table.get(day, {"condition": "cloudy", "high_f": 63, "low_f": 50})
        daily.append({"date": day, **weather})
    condition_counts: dict[str, int] = {}
    for entry in daily:
        condition_counts[entry["condition"]] = condition_counts.get(entry["condition"], 0) + 1
    dominant = max(condition_counts, key=condition_counts.get) if condition_counts else "cloudy"
    return {
        "location": location,
        "dates": dates,
        "daily": daily,
        "summary": f"Mostly {dominant} with deterministic forecast.",
    }


@tool
def estimate_cost(plan_json: str, days: int, budget_usd: float) -> dict[str, Any]:
    """Estimate the total cost of a travel plan. Pass the plan as a JSON string with an 'itinerary' list. Returns estimate_usd, within_budget, and line_items."""
    try:
        plan = json.loads(plan_json) if isinstance(plan_json, str) else plan_json
    except (json.JSONDecodeError, TypeError):
        plan = {}
    itinerary = plan.get("itinerary", [])
    if not itinerary:
        estimated = float(days) * 120.0
        return {
            "estimate_usd": round(estimated, 2),
            "within_budget": estimated <= budget_usd,
            "line_items": [{"name": "default_plan", "cost": estimated}],
            "method": "deterministic-v1",
        }

    line_items = []
    total = 0.0
    for item in itinerary:
        kind = str(item.get("type", "indoor")).lower()
        base = ACTIVITY_BASE_COST.get(kind, 110.0)
        multiplier = 1.0 if item.get("budget_friendly", False) else 1.2
        cost = base * multiplier
        total += cost
        line_items.append(
            {
                "name": item.get("activity", "activity"),
                "kind": kind,
                "cost": round(cost, 2),
            }
        )
    return {
        "estimate_usd": round(total, 2),
        "within_budget": total <= budget_usd,
        "line_items": line_items,
        "method": "deterministic-v1",
    }


TOOL_LIST = [get_weather, estimate_cost]
TOOLS_BY_NAME = {t.name: t for t in TOOL_LIST}
