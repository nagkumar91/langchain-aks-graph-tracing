from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command
from opentelemetry import trace

from app.retriever import OfflineRetriever
from app.tools import execute_tool

TRACER = trace.get_tracer(__name__)


class WorkflowState(TypedDict, total=False):
    thread: dict[str, list[dict[str, str]]]
    constraints: dict[str, Any]
    context_docs: list[dict[str, Any]]
    draft_plan: dict[str, Any]
    tool_outputs: dict[str, Any]
    route: str
    final_answer: str
    metadata: dict[str, Any]


def _as_text(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        return " ".join(str(item) for item in content)
    return str(content)


def _extract_json(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or start >= end:
        return {}
    snippet = text[start : end + 1]
    try:
        parsed = json.loads(snippet)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _latest_user_message(state: WorkflowState) -> str:
    messages = state.get("thread", {}).get("messages", [])
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content", "")
    return ""


def _annotate_span(state: WorkflowState, node_name: str, route_decision: str | None = None) -> None:
    span = trace.get_current_span()
    if not span:
        return
    metadata = state.get("metadata", {})
    span.set_attribute("app.node_name", node_name)
    if route_decision:
        span.set_attribute("app.route_decision", route_decision)
    request_id = metadata.get("request_id")
    if request_id:
        span.set_attribute("biz.request_id", request_id)
    user_id = metadata.get("user_id")
    if user_id:
        span.set_attribute("app.user_id", user_id)
        span.set_attribute("enduser.id", user_id)


def _fallback_plan(state: WorkflowState, *, budget_mode: bool) -> dict[str, Any]:
    constraints = state.get("constraints", {})
    docs = state.get("context_docs", [])
    days = max(int(constraints.get("days", 5)), 1)
    destination = constraints.get("destination", "Paris")
    itinerary = []
    for index in range(days):
        doc = docs[index % len(docs)] if docs else {}
        if budget_mode:
            kind = "budget"
        else:
            kind = "sightseeing" if index % 2 == 0 else "cultural"
        itinerary.append(
            {
                "day": index + 1,
                "activity": doc.get("title", f"Day {index + 1} in {destination}"),
                "type": kind,
                "budget_friendly": budget_mode,
                "notes": doc.get("text", "Zava recommended activity."),
            }
        )
    return {
        "destination": destination,
        "itinerary": itinerary,
        "summary": "Budget-optimized travel plan by Zava." if budget_mode else f"Your {destination} travel plan by Zava.",
    }


def _invoke_chat(
    llm: Any,
    node_name: str,
    system_prompt: str,
    payload: dict[str, Any],
    callbacks_factory: Callable[[bool], list[Any]],
    record_content: bool,
    metadata: dict[str, Any],
) -> str:
    callbacks = callbacks_factory(record_content)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=json.dumps(payload, ensure_ascii=True)),
    ]
    with TRACER.start_as_current_span("gen_ai.chat") as span:
        span.set_attribute("gen_ai.operation.name", "chat")
        span.set_attribute("gen_ai.provider.name", "azure_openai")
        span.set_attribute("app.node_name", node_name)
        request_id = metadata.get("request_id")
        if request_id:
            span.set_attribute("biz.request_id", request_id)
        if record_content:
            span.set_attribute("gen_ai.request.payload", json.dumps(payload, sort_keys=True))
        invoke_kwargs = {"config": {"callbacks": callbacks}} if callbacks else {}
        response = llm.invoke(messages, **invoke_kwargs)
        text = _as_text(response)
        if record_content:
            span.set_attribute("gen_ai.response.payload", text)
        return text


def build_graph(
    *,
    llm: Any,
    retriever: OfflineRetriever,
    callbacks_factory: Callable[[bool], list[Any]],
) -> Any:
    builder = StateGraph(WorkflowState)

    def user_proxy(state: WorkflowState) -> WorkflowState:
        _annotate_span(state, "user_proxy")
        metadata = dict(state.get("metadata", {}))
        metadata.setdefault("replan_count", 0)
        state_thread = state.get("thread", {})
        state_thread.setdefault("messages", [])
        return {"metadata": metadata, "thread": state_thread}

    def orchestrator(state: WorkflowState) -> WorkflowState:
        _annotate_span(state, "orchestrator", route_decision="retrieve_context")
        return {"route": "normal"}

    def retrieve_context(state: WorkflowState) -> WorkflowState:
        _annotate_span(state, "retrieve_context")
        constraints = state.get("constraints", {})
        query = (
            f"{_latest_user_message(state)} "
            f"destination={constraints.get('destination', '')} "
            f"budget={constraints.get('budget_usd', '')} "
            f"days={constraints.get('days', '')} "
            f"style={constraints.get('travel_style', '')}"
        ).strip()
        docs = retriever.search(query)
        return {"context_docs": docs}

    def draft_plan(state: WorkflowState) -> WorkflowState:
        _annotate_span(state, "draft_plan")
        metadata = state.get("metadata", {})
        record_content = bool(metadata.get("record_content", False))
        payload = {
            "constraints": state.get("constraints", {}),
            "context_docs": state.get("context_docs", []),
            "instruction": (
                "You are Zava, an expert travel agent. "
                "Return JSON with keys: destination (string), itinerary (list), and summary (string). "
                "Each itinerary item should include day, activity, type "
                "(sightseeing/cultural/adventure/dining/relaxation/shopping), and budget_friendly (bool). "
                "Consider the traveler's budget, travel style, and destination weather."
            ),
        }
        response_text = _invoke_chat(
            llm,
            "draft_plan",
            "NODE:draft_plan. You are Zava Travel Agent. Build an initial travel plan using destination info and retrieved context.",
            payload,
            callbacks_factory,
            record_content,
            metadata,
        )
        parsed = _extract_json(response_text)
        plan = parsed if parsed.get("itinerary") else _fallback_plan(state, budget_mode=False)
        return {"draft_plan": plan}

    def run_tools(state: WorkflowState) -> WorkflowState:
        _annotate_span(state, "run_tools")
        constraints = state.get("constraints", {})
        metadata = state.get("metadata", {})
        record_content = bool(metadata.get("record_content", False))
        destination = constraints.get("destination", "Paris")
        travelers = int(constraints.get("travelers", 2))
        days = int(constraints.get("days", 5))
        travel_style = constraints.get("travel_style", "mid")

        flights = execute_tool(
            "search_flights",
            {
                "destination": destination,
                "travelers": travelers,
                "travel_class": "budget" if travel_style == "budget" else "economy",
            },
            record_content=record_content,
        )
        hotels = execute_tool(
            "search_hotels",
            {
                "destination": destination,
                "nights": days,
                "travelers": travelers,
                "tier": travel_style,
            },
            record_content=record_content,
        )
        weather = execute_tool(
            "get_destination_weather",
            {
                "destination": destination,
                "dates": constraints.get("dates", []),
            },
            record_content=record_content,
        )
        cost = execute_tool(
            "estimate_trip_cost",
            {
                "plan": state.get("draft_plan", {}),
                "days": days,
                "budget_usd": float(constraints.get("budget_usd", 2000)),
                "travelers": travelers,
                "destination": destination,
            },
            record_content=record_content,
        )
        return {"tool_outputs": {"flights": flights, "hotels": hotels, "weather": weather, "cost": cost}}

    def evaluate_constraints(state: WorkflowState) -> WorkflowState | Command:
        metadata = dict(state.get("metadata", {}))
        cost = float(state.get("tool_outputs", {}).get("cost", {}).get("estimate_usd", 0))
        budget = float(state.get("constraints", {}).get("budget_usd", 0))
        replan_count = int(metadata.get("replan_count", 0))
        forced = bool(metadata.get("force_goto_path", False)) or os.getenv(
            "DEMO_FORCE_GOTO", "false"
        ).lower() in {"1", "true", "yes", "on"}
        if (forced or cost > budget) and replan_count < 1:
            reason = "force_goto" if forced else "budget_exceeded"
            _annotate_span(state, "evaluate_constraints", route_decision="goto_replan")
            span = trace.get_current_span()
            span.add_event(
                "goto_triggered",
                {"from": "evaluate_constraints", "to": "replan", "reason": reason},
            )
            metadata["replan_count"] = replan_count + 1
            metadata["replan_reason"] = reason
            return Command(
                goto="replan",
                update={
                    "route": "replan",
                    "metadata": metadata,
                },
            )
        route_decision = "finalize_budget_ok" if cost <= budget else "finalize_max_replans"
        route_value = "replan_then_finalize" if replan_count > 0 else "normal_finalize"
        _annotate_span(state, "evaluate_constraints", route_decision=route_decision)
        metadata["replan_reason"] = "within_budget" if cost <= budget else "max_replans_reached"
        return {
            "route": route_value,
            "metadata": metadata,
        }

    def replan(state: WorkflowState) -> WorkflowState:
        _annotate_span(state, "replan", route_decision="run_tools")
        metadata = state.get("metadata", {})
        record_content = bool(metadata.get("record_content", False))
        payload = {
            "constraints": state.get("constraints", {}),
            "previous_plan": state.get("draft_plan", {}),
            "tool_outputs": state.get("tool_outputs", {}),
            "instruction": (
                "You are Zava Travel Agent. The previous plan exceeded the traveler's budget. "
                "Return JSON with destination, itinerary, and summary. "
                "Switch to budget flights, budget hotels, and budget-friendly activities. "
                "Reduce estimated spend while keeping the trip enjoyable."
            ),
        }
        response_text = _invoke_chat(
            llm,
            "replan",
            "NODE:replan. You are Zava Travel Agent. Rewrite the travel plan to fit the budget.",
            payload,
            callbacks_factory,
            record_content,
            metadata,
        )
        parsed = _extract_json(response_text)
        plan = parsed if parsed.get("itinerary") else _fallback_plan(state, budget_mode=True)
        return {"draft_plan": plan}

    def finalize(state: WorkflowState) -> WorkflowState:
        _annotate_span(state, "finalize")
        metadata = state.get("metadata", {})
        record_content = bool(metadata.get("record_content", False))
        payload = {
            "plan": state.get("draft_plan", {}),
            "tool_outputs": state.get("tool_outputs", {}),
            "route": state.get("route", "normal"),
            "instruction": (
                "You are Zava Travel Agent. Produce the final travel plan summary for the traveler. "
                "Include flight info, hotel recommendation, daily itinerary highlights, "
                "total estimated cost, and weather outlook. Be friendly and enthusiastic."
            ),
        }
        response_text = _invoke_chat(
            llm,
            "finalize",
            "NODE:finalize. You are Zava Travel Agent. Return the final user-facing travel plan.",
            payload,
            callbacks_factory,
            record_content,
            metadata,
        )
        return {"final_answer": response_text.strip()}

    builder.add_node("user_proxy", user_proxy)
    builder.add_node("orchestrator", orchestrator)
    builder.add_node("retrieve_context", retrieve_context)
    builder.add_node("draft_plan", draft_plan)
    builder.add_node("run_tools", run_tools)
    builder.add_node("evaluate_constraints", evaluate_constraints)
    builder.add_node("replan", replan)
    builder.add_node("finalize", finalize)

    builder.add_edge(START, "user_proxy")
    builder.add_edge("user_proxy", "orchestrator")
    builder.add_edge("orchestrator", "retrieve_context")
    builder.add_edge("retrieve_context", "draft_plan")
    builder.add_edge("draft_plan", "run_tools")
    builder.add_edge("run_tools", "evaluate_constraints")
    builder.add_edge("evaluate_constraints", "finalize")
    builder.add_edge("replan", "run_tools")
    builder.add_edge("finalize", END)

    return builder.compile()
