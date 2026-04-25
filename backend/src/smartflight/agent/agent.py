import logging

from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.graph import END, START, StateGraph

from smartflight.agent.extract_preference import extract_preference_node
from smartflight.agent.extract_query import extract_query_node
from smartflight.agent.filter_flights import filter_flights_node
from smartflight.agent.guardrail import intent_guardrail_node
from smartflight.agent.search_flights import search_flights_node
from smartflight.agent.state import AgentState

logger = logging.getLogger(__name__)


def route_after_guardrail(state: AgentState) -> str:
    """If the intent is irrelevant, terminate; otherwise continue extraction."""
    if state.get("error_message"):
        return "end"
    return "dispatch_extractions"


def dispatch_extractions(state: AgentState) -> dict:
    return {}


def join_extractions(state: AgentState) -> dict:
    """
    Wait for `extract_query` and `extract_preference` to finish, then
    append a single history record for this turn.

    This avoids history write conflicts inside parallel branches.
    """
    history = list(state.get("history") or [])
    history.append(
        {
            "user_input": state.get("user_input"),
            "flight_query": state.get("flight_query"),
            "clarification": state.get("clarification"),
            "flight_preference": state.get("flight_preference"),
        }
    )

    max_turns = 5
    return {"history": history[-max_turns:]}


def route_after_extraction(state: AgentState) -> str:
    if state.get("error_message"):
        return "end"
    clarification = state.get("clarification") or {}
    if clarification and not clarification.get("can_search", True):
        return "end"
    return "search_flights"


builder = StateGraph(AgentState)
builder.add_node("intent_guardrail", intent_guardrail_node)
builder.add_node("dispatch_extractions", dispatch_extractions)
builder.add_node("extract_query", extract_query_node)
builder.add_node("extract_preference", extract_preference_node)
builder.add_node("join_extractions", join_extractions)
builder.add_node("search_flights", search_flights_node)
builder.add_node("filter_flights", filter_flights_node)

builder.add_edge(START, "intent_guardrail")
builder.add_conditional_edges(
    "intent_guardrail",
    route_after_guardrail,
    {
        "end": END,
        "dispatch_extractions": "dispatch_extractions",
    },
)

builder.add_edge("dispatch_extractions", "extract_query")
builder.add_edge("dispatch_extractions", "extract_preference")
builder.add_edge("extract_query", "join_extractions")
builder.add_edge("extract_preference", "join_extractions")
builder.add_conditional_edges(
    "join_extractions",
    route_after_extraction,
    {
        "end": END,
        "search_flights": "search_flights",
    },
)

builder.add_edge("search_flights", "filter_flights")
builder.add_edge("filter_flights", END)

memory = MemorySaver(serde=JsonPlusSerializer())
graph = builder.compile(checkpointer=memory)


if __name__ == "__main__":
    thread_config = {"configurable": {"thread_id": "multi_turn_test_session"}}

    def run_test_turn(turn_name: str, user_input: str):
        print(f"\n{'=' * 15} {turn_name} {'=' * 15}")
        print(f"User input: {user_input}")

        current_input = {
            "user_input": user_input,
            "user_context": {"location": "Singapore"},
        }
        result_state = graph.invoke(current_input, thread_config)

        if result_state.get("error_message"):
            print(f"[System blocked/error]: {result_state['error_message']}")
            return

        print("[Agent merged state]:")
        query = result_state.get("flight_query", {})
        pref = result_state.get("flight_preference", {})
        print(f"[Query] origin: {query.get('from_airport')}")
        print(f"[Query] destinations: {query.get('to_airports')}")
        print(f"[Query] departure: {query.get('departure_date')}")
        print(f"[Pref] airlines: {pref.get('preferred_airlines')}")
        print(f"[Pref] max_price: {pref.get('max_price')} SGD")

    run_test_turn("turn 1: unrelated intent", "I want to learn cooking.")
    run_test_turn("turn 2: destination", "Actually, I want a flight to Tokyo.")
    run_test_turn("turn 3: date", "I want to depart next Friday.")
    run_test_turn("turn 4: airline preference", "I prefer Singapore Airlines.")
    run_test_turn("turn 5: price limit", "Keep the maximum price under 800 SGD.")
