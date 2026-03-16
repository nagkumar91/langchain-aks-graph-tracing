from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from opentelemetry import trace

TRACER = trace.get_tracer(__name__)

# --- Deterministic weather data for popular destinations ---
WEATHER_TABLE: dict[str, dict[str, dict[str, Any]]] = {
    "paris": {
        "2026-06-10": {"condition": "sunny", "high_f": 75, "low_f": 59},
        "2026-06-11": {"condition": "partly_cloudy", "high_f": 73, "low_f": 57},
        "2026-06-12": {"condition": "sunny", "high_f": 77, "low_f": 60},
    },
    "tokyo": {
        "2026-04-05": {"condition": "sunny", "high_f": 65, "low_f": 50},
        "2026-04-06": {"condition": "rain", "high_f": 60, "low_f": 48},
        "2026-04-07": {"condition": "cloudy", "high_f": 63, "low_f": 49},
    },
    "cancun": {
        "2026-03-15": {"condition": "sunny", "high_f": 86, "low_f": 72},
        "2026-03-16": {"condition": "sunny", "high_f": 88, "low_f": 73},
        "2026-03-17": {"condition": "partly_cloudy", "high_f": 85, "low_f": 71},
    },
    "bali": {
        "2026-07-01": {"condition": "sunny", "high_f": 84, "low_f": 74},
        "2026-07-02": {"condition": "sunny", "high_f": 85, "low_f": 73},
        "2026-07-03": {"condition": "partly_cloudy", "high_f": 83, "low_f": 74},
    },
    "new york": {
        "2026-05-20": {"condition": "sunny", "high_f": 74, "low_f": 62},
        "2026-05-21": {"condition": "cloudy", "high_f": 70, "low_f": 61},
        "2026-05-22": {"condition": "sunny", "high_f": 76, "low_f": 63},
    },
    "barcelona": {
        "2026-09-10": {"condition": "sunny", "high_f": 79, "low_f": 66},
        "2026-09-11": {"condition": "sunny", "high_f": 80, "low_f": 67},
        "2026-09-12": {"condition": "partly_cloudy", "high_f": 77, "low_f": 64},
    },
}

# --- Deterministic flight pricing ---
FLIGHT_TABLE: dict[str, dict[str, dict[str, Any]]] = {
    "paris": {
        "economy": {"price_usd": 650, "airline": "Air France", "duration_hr": 8.5},
        "business": {"price_usd": 2800, "airline": "Air France", "duration_hr": 8.5},
        "budget": {"price_usd": 420, "airline": "Norse Atlantic", "duration_hr": 9.5},
    },
    "tokyo": {
        "economy": {"price_usd": 900, "airline": "ANA", "duration_hr": 13.0},
        "business": {"price_usd": 4500, "airline": "ANA", "duration_hr": 13.0},
        "budget": {"price_usd": 680, "airline": "Zipair", "duration_hr": 14.5},
    },
    "cancun": {
        "economy": {"price_usd": 350, "airline": "United", "duration_hr": 4.5},
        "business": {"price_usd": 1200, "airline": "United", "duration_hr": 4.5},
        "budget": {"price_usd": 220, "airline": "Spirit", "duration_hr": 5.0},
    },
    "bali": {
        "economy": {"price_usd": 1100, "airline": "Singapore Airlines", "duration_hr": 20.0},
        "business": {"price_usd": 5200, "airline": "Singapore Airlines", "duration_hr": 20.0},
        "budget": {"price_usd": 780, "airline": "AirAsia", "duration_hr": 22.0},
    },
    "new york": {
        "economy": {"price_usd": 280, "airline": "JetBlue", "duration_hr": 5.5},
        "business": {"price_usd": 950, "airline": "Delta", "duration_hr": 5.5},
        "budget": {"price_usd": 150, "airline": "Spirit", "duration_hr": 6.0},
    },
    "barcelona": {
        "economy": {"price_usd": 580, "airline": "Iberia", "duration_hr": 9.0},
        "business": {"price_usd": 2400, "airline": "Iberia", "duration_hr": 9.0},
        "budget": {"price_usd": 390, "airline": "LEVEL", "duration_hr": 10.0},
    },
}

# --- Deterministic hotel pricing ---
HOTEL_TABLE: dict[str, dict[str, dict[str, Any]]] = {
    "paris": {
        "budget": {"name": "Hotel Ibis Montmartre", "price_per_night": 95, "rating": 3.5},
        "mid": {"name": "Hotel Le Marais", "price_per_night": 195, "rating": 4.0},
        "luxury": {"name": "Le Bristol Paris", "price_per_night": 650, "rating": 4.8},
    },
    "tokyo": {
        "budget": {"name": "Sakura Hotel Jimbocho", "price_per_night": 65, "rating": 3.5},
        "mid": {"name": "Shinjuku Granbell Hotel", "price_per_night": 150, "rating": 4.0},
        "luxury": {"name": "Park Hyatt Tokyo", "price_per_night": 500, "rating": 4.9},
    },
    "cancun": {
        "budget": {"name": "Hostel Natura Cancun", "price_per_night": 45, "rating": 3.5},
        "mid": {"name": "Hyatt Zilara Cancun", "price_per_night": 250, "rating": 4.2},
        "luxury": {"name": "Ritz-Carlton Cancun", "price_per_night": 550, "rating": 4.8},
    },
    "bali": {
        "budget": {"name": "Puri Garden Hotel Ubud", "price_per_night": 35, "rating": 3.8},
        "mid": {"name": "Alila Seminyak", "price_per_night": 160, "rating": 4.3},
        "luxury": {"name": "Four Seasons Bali", "price_per_night": 480, "rating": 4.9},
    },
    "new york": {
        "budget": {"name": "Pod 51 Hotel", "price_per_night": 120, "rating": 3.6},
        "mid": {"name": "The Marcel at Gramercy", "price_per_night": 250, "rating": 4.1},
        "luxury": {"name": "The Plaza Hotel", "price_per_night": 750, "rating": 4.8},
    },
    "barcelona": {
        "budget": {"name": "Generator Barcelona", "price_per_night": 55, "rating": 3.5},
        "mid": {"name": "Hotel 1898 La Rambla", "price_per_night": 180, "rating": 4.2},
        "luxury": {"name": "Hotel Arts Barcelona", "price_per_night": 420, "rating": 4.7},
    },
}

# --- Per-item cost lookup for itinerary costing ---
ACTIVITY_BASE_COST: dict[str, float] = {
    "flight": 0.0,  # handled separately
    "hotel": 0.0,  # handled separately
    "sightseeing": 45.0,
    "adventure": 120.0,
    "cultural": 35.0,
    "dining": 60.0,
    "relaxation": 80.0,
    "shopping": 50.0,
    "transport": 25.0,
    "budget": 30.0,
}


def search_flights(
    destination: str, travelers: int, travel_class: str,
) -> dict[str, Any]:
    norm = destination.strip().lower()
    dest_flights = FLIGHT_TABLE.get(norm, FLIGHT_TABLE.get("new york", {}))
    tier = travel_class.strip().lower()
    if tier not in dest_flights:
        tier = "economy"
    flight = dest_flights[tier]
    total = flight["price_usd"] * travelers
    return {
        "destination": destination,
        "travelers": travelers,
        "travel_class": tier,
        "airline": flight["airline"],
        "price_per_person": flight["price_usd"],
        "total_price_usd": total,
        "duration_hr": flight["duration_hr"],
        "method": "deterministic-v1",
    }


def search_hotels(
    destination: str, nights: int, travelers: int, tier: str,
) -> dict[str, Any]:
    norm = destination.strip().lower()
    dest_hotels = HOTEL_TABLE.get(norm, HOTEL_TABLE.get("new york", {}))
    hotel_tier = tier.strip().lower()
    if hotel_tier not in dest_hotels:
        hotel_tier = "mid"
    hotel = dest_hotels[hotel_tier]
    rooms = max(1, (travelers + 1) // 2)
    total = hotel["price_per_night"] * nights * rooms
    return {
        "destination": destination,
        "hotel_name": hotel["name"],
        "tier": hotel_tier,
        "rating": hotel["rating"],
        "price_per_night": hotel["price_per_night"],
        "nights": nights,
        "rooms": rooms,
        "total_price_usd": total,
        "method": "deterministic-v1",
    }


def get_destination_weather(
    destination: str, dates: list[str],
) -> dict[str, Any]:
    norm = destination.strip().lower()
    table = WEATHER_TABLE.get(norm, {})
    daily = []
    for day in dates:
        weather = table.get(day, {"condition": "sunny", "high_f": 75, "low_f": 60})
        daily.append({"date": day, **weather})
    condition_counts: dict[str, int] = {}
    for entry in daily:
        condition_counts[entry["condition"]] = condition_counts.get(entry["condition"], 0) + 1
    dominant = max(condition_counts, key=condition_counts.get) if condition_counts else "sunny"
    return {
        "destination": destination,
        "dates": dates,
        "daily": daily,
        "summary": f"Mostly {dominant} with deterministic forecast.",
    }


def estimate_trip_cost(
    plan: dict[str, Any], days: int, budget_usd: float,
    travelers: int, destination: str,
) -> dict[str, Any]:
    itinerary = plan.get("itinerary", [])
    line_items: list[dict[str, Any]] = []
    total = 0.0

    # Flight cost
    norm = destination.strip().lower()
    flight_info = FLIGHT_TABLE.get(norm, {}).get("economy", {"price_usd": 500})
    flight_cost = float(flight_info["price_usd"] * travelers)
    total += flight_cost
    line_items.append({"name": "round_trip_flights", "kind": "flight", "cost": round(flight_cost, 2)})

    # Hotel cost
    hotel_info = HOTEL_TABLE.get(norm, {}).get("mid", {"price_per_night": 150})
    rooms = max(1, (travelers + 1) // 2)
    hotel_cost = float(hotel_info["price_per_night"] * days * rooms)
    total += hotel_cost
    line_items.append({"name": "accommodation", "kind": "hotel", "cost": round(hotel_cost, 2)})

    # Activity costs from itinerary
    for item in itinerary:
        kind = str(item.get("type", "sightseeing")).lower()
        base = ACTIVITY_BASE_COST.get(kind, 50.0)
        multiplier = 0.7 if item.get("budget_friendly", False) else 1.0
        cost = base * multiplier * travelers
        total += cost
        line_items.append({
            "name": item.get("activity", "activity"),
            "kind": kind,
            "cost": round(cost, 2),
        })

    return {
        "estimate_usd": round(total, 2),
        "within_budget": total <= budget_usd,
        "line_items": line_items,
        "method": "deterministic-v1",
    }


SEARCH_FLIGHTS_TOOL = StructuredTool.from_function(
    func=search_flights,
    name="search_flights",
    description="Deterministic flight search for destination and travel class.",
)
SEARCH_HOTELS_TOOL = StructuredTool.from_function(
    func=search_hotels,
    name="search_hotels",
    description="Deterministic hotel search by destination and tier.",
)
GET_WEATHER_TOOL = StructuredTool.from_function(
    func=get_destination_weather,
    name="get_destination_weather",
    description="Deterministic weather forecast for travel destination.",
)
ESTIMATE_COST_TOOL = StructuredTool.from_function(
    func=estimate_trip_cost,
    name="estimate_trip_cost",
    description="Deterministic total trip cost estimator including flights, hotels, and activities.",
)

TOOLS = {
    SEARCH_FLIGHTS_TOOL.name: SEARCH_FLIGHTS_TOOL,
    SEARCH_HOTELS_TOOL.name: SEARCH_HOTELS_TOOL,
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
