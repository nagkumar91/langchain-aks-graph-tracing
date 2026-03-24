from __future__ import annotations

import json
import os
from typing import Any, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from app.retriever import OfflineRetriever
from app.tools import TOOL_LIST, TOOLS_BY_NAME


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


def _fallback_plan(state: WorkflowState, *, budget_mode: bool) -> dict[str, Any]:
    constraints = state.get("constraints", {})
    docs = state.get("context_docs", [])
    days = max(int(constraints.get("days", 2)), 1)
    itinerary = []
    for index in range(days):
        doc = docs[index % len(docs)] if docs else {}
        if budget_mode:
            kind = "budget"
        else:
            kind = "outdoor" if index % 2 == 0 else "indoor"
        itinerary.append(
            {
                "day": index + 1,
                "activity": doc.get("title", f"Day {index + 1} activity"),
                "type": kind,
                "budget_friendly": budget_mode,
                "notes": doc.get("text", "Deterministic fallback plan item."),
            }
        )
    return {
        "itinerary": itinerary,
        "summary": "Budget-optimized plan." if budget_mode else "Initial deterministic plan.",
    }


def _invoke_chat(
    llm: Any,
    system_prompt: str,
    payload: dict[str, Any],
    config: RunnableConfig,
) -> str:
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=json.dumps(payload, ensure_ascii=True)),
    ]
    response = llm.invoke(messages, config=config)
    return _as_text(response)


def _invoke_with_tools(
    llm_with_tools: Any,
    system_prompt: str,
    user_content: str,
    config: RunnableConfig,
) -> dict[str, Any]:
    """Call the LLM with bound tools. Execute any tool_calls the model makes
    and feed results back, collecting all tool outputs."""
    messages: list[Any] = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_content),
    ]
    collected: dict[str, Any] = {}

    for _ in range(5):  # max iterations to prevent infinite loops
        response: AIMessage = llm_with_tools.invoke(messages, config=config)
        messages.append(response)

        if not response.tool_calls:
            break

        for tc in response.tool_calls:
            tool_fn = TOOLS_BY_NAME.get(tc["name"])
            if tool_fn is None:
                result = {"error": f"Unknown tool: {tc['name']}"}
            else:
                result = tool_fn.invoke(tc["args"])
            collected[tc["name"]] = result
            messages.append(
                ToolMessage(content=json.dumps(result, default=str), tool_call_id=tc["id"])
            )

    return collected


def build_graph(
    *,
    llm: Any,
    retriever: OfflineRetriever,
) -> Any:
    # LLM with tools bound — produces gen_ai.tool.definitions on chat spans
    llm_with_tools = llm.bind_tools(TOOL_LIST)

    builder = StateGraph(WorkflowState)

    def user_proxy(state: WorkflowState) -> WorkflowState:
        metadata = dict(state.get("metadata", {}))
        metadata.setdefault("replan_count", 0)
        state_thread = state.get("thread", {})
        state_thread.setdefault("messages", [])
        return {"metadata": metadata, "thread": state_thread}

    def orchestrator(state: WorkflowState) -> WorkflowState:
        return {"route": "normal"}

    def retrieve_context(state: WorkflowState) -> WorkflowState:
        constraints = state.get("constraints", {})
        query = (
            f"{_latest_user_message(state)} "
            f"location={constraints.get('location', '')} "
            f"budget={constraints.get('budget_usd', '')} "
            f"days={constraints.get('days', '')}"
        ).strip()
        docs = retriever.search(query)
        return {"context_docs": docs}

    def draft_plan(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
        payload = {
            "constraints": state.get("constraints", {}),
            "context_docs": state.get("context_docs", []),
            "instruction": (
                "Return JSON with keys itinerary (list) and summary (string). "
                "Each itinerary item should include day, activity, type, budget_friendly."
            ),
        }
        response_text = _invoke_chat(
            llm,
            "NODE:draft_plan. Build an initial plan using retrieved context only.",
            payload,
            config,
        )
        parsed = _extract_json(response_text)
        plan = parsed if parsed.get("itinerary") else _fallback_plan(state, budget_mode=False)
        return {"draft_plan": plan}

    def run_tools(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
        """Use LLM tool-calling: the model receives tool definitions, decides
        which tools to call, and the results are fed back automatically."""
        constraints = state.get("constraints", {})
        plan = state.get("draft_plan", {})
        prompt = (
            "You are a travel planning assistant with access to tools. "
            "Use the get_weather tool to check weather for the destination, "
            "and the estimate_cost tool to estimate the trip cost. "
            "You MUST call both tools."
        )
        user_msg = json.dumps({
            "location": constraints.get("location", "Seattle"),
            "dates": constraints.get("dates", []),
            "plan": plan,
            "days": int(constraints.get("days", 2)),
            "budget_usd": float(constraints.get("budget_usd", 500)),
        })

        collected = _invoke_with_tools(llm_with_tools, prompt, user_msg, config)

        # Ensure we have both outputs even if the LLM skipped a tool
        weather = collected.get("get_weather", {"summary": "No weather data."})
        cost = collected.get("estimate_cost", {"estimate_usd": 0, "within_budget": True})
        return {"tool_outputs": {"weather": weather, "cost": cost}}

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
            metadata["replan_count"] = replan_count + 1
            metadata["replan_reason"] = reason
            return Command(
                goto="replan",
                update={
                    "route": "replan",
                    "metadata": metadata,
                },
            )
        route_value = "replan_then_finalize" if replan_count > 0 else "normal_finalize"
        metadata["replan_reason"] = "within_budget" if cost <= budget else "max_replans_reached"
        return {
            "route": route_value,
            "metadata": metadata,
        }

    def replan(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
        payload = {
            "constraints": state.get("constraints", {}),
            "previous_plan": state.get("draft_plan", {}),
            "tool_outputs": state.get("tool_outputs", {}),
            "instruction": (
                "Return JSON with itinerary and summary. "
                "Must reduce estimated spend and prefer budget-friendly activities."
            ),
        }
        response_text = _invoke_chat(
            llm,
            "NODE:replan. Rewrite the plan to satisfy budget constraints.",
            payload,
            config,
        )
        parsed = _extract_json(response_text)
        plan = parsed if parsed.get("itinerary") else _fallback_plan(state, budget_mode=True)
        return {"draft_plan": plan}

    def finalize(state: WorkflowState, config: RunnableConfig) -> WorkflowState:
        payload = {
            "plan": state.get("draft_plan", {}),
            "tool_outputs": state.get("tool_outputs", {}),
            "route": state.get("route", "normal"),
            "instruction": "Produce final plain-text answer and short rationale.",
        }
        response_text = _invoke_chat(
            llm,
            "NODE:finalize. Return concise final user-facing answer.",
            payload,
            config,
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
