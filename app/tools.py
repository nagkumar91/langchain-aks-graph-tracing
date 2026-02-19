from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from opentelemetry import trace

TRACER = trace.get_tracer(__name__)

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


def get_weather(location: str, dates: list[str]) -> dict[str, Any]:
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


def estimate_cost(plan: dict[str, Any], days: int, budget_usd: float) -> dict[str, Any]:
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


GET_WEATHER_TOOL = StructuredTool.from_function(
    func=get_weather,
    name="get_weather",
    description="Deterministic weather tool for location and date range.",
)
ESTIMATE_COST_TOOL = StructuredTool.from_function(
    func=estimate_cost,
    name="estimate_cost",
    description="Deterministic budget estimator for itinerary plans.",
)

TOOLS = {
    GET_WEATHER_TOOL.name: GET_WEATHER_TOOL,
    ESTIMATE_COST_TOOL.name: ESTIMATE_COST_TOOL,
}


def execute_tool(
    tool_name: str,
    args: dict[str, Any],
    *,
    record_content: bool = False,
) -> dict[str, Any]:
    tool = TOOLS[tool_name]
    with TRACER.start_as_current_span(f"tool.{tool_name}") as span:
        span.set_attribute("gen_ai.operation.name", "execute_tool")
        span.set_attribute("gen_ai.tool.name", tool_name)
        if record_content:
            span.set_attribute("gen_ai.tool.call.arguments", json.dumps(args, sort_keys=True))
        result = tool.invoke(args)
        if record_content:
            span.set_attribute("gen_ai.tool.result", json.dumps(result, sort_keys=True))
        return result
