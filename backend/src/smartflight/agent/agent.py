from langgraph.graph import START, END, StateGraph
from smartflight.agent.state import AgentState
from smartflight.agent.guardrail import intent_guardrail_node
from smartflight.agent.extract_query import extract_query_node
from smartflight.agent.extract_preference import extract_preference_node
from smartflight.agent.search_flights import search_flights_node
from smartflight.agent.filter_flights import filter_flights_node



# Conditional Edge
def route_after_guardrail(state: AgentState) -> str:
    """If the intent is irrelevant, terminate directly; if it is relevant, proceed to the distribution node."""
    if state.get("error_message"):
        return "end"
    return "dispatch_extractions"

# Join Node
def join_extractions(state: AgentState) -> dict:
    """
    This is an empty node, used only to wait for `extract_query` and `extract_preference` to complete in parallel.
    LangGraph will summarize the state updates from the previous Superstep at this node.
    Returning an empty dictionary indicates that no state is modified.
    """
    return {}


# Conditional Edge
def route_after_extraction(state: AgentState) -> str:
    if state.get("error_message"):
        return "end"
    return "search_flights"

builder = StateGraph(AgentState)

builder.add_node("intent_guardrail", intent_guardrail_node)
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
    }
)

# Fan-out
builder.add_edge(START, "extract_query")
builder.add_edge(START, "extract_preference")

# Fan-in
builder.add_edge("extract_query", "join_extractions")
builder.add_edge("extract_preference", "join_extractions")

builder.add_conditional_edges(
    "join_extractions",
    route_after_extraction,
    {
        "end": END,
        "search_flights": "search_flights",
    }
)

builder.add_edge("search_flights", "filter_flights")
builder.add_edge("filter_flights", END)

graph = builder.compile()



'''
# 测试
if __name__ == "__main__":
    test_input = {
        "user_input": "我想从北京出发去东京，下个月出发，一周后返回，预算30000元以内",
        "flight_query": None,
        "flight_preference": None,
        "error_message": None,
    }

    result = graph.invoke(test_input)

    result_logger.info("=== flight_query ===")
    for k, v in result["flight_query"].items():
        result_logger.info("  %s: %s", k, v)

    result_logger.info("\n=== flight_preference ===")
    for k, v in result["flight_preference"].items():
        result_logger.info("  %s: %s", k, v)

    if result["error_message"]:
        result_logger.warning("\n=== error ===\n  %s", result["error_message"])

    result_logger.info("\n=== flight_choices ===")

    flight_choices = result.get("flight_choices") or []

    if not flight_choices:
        result_logger.info("  (no results)")
    else:
        for i, choice in enumerate(flight_choices[:10], 1):
            # ===== 基本信息 =====
            header = (
                f"\n--- Option {i} ---\n"
                f"  trip: {choice['trip']}\n"
                f"  route: {choice['from_airport']} -> {choice['to_airport']}\n"
                f"  departure_date: {choice['departure_date']}"
            )

            if choice["return_date"]:
                header += f"\n  return_date: {choice['return_date']}"

            result_logger.info(header)

            # ===== Outbound =====
            outbound_info = (
                "\n  [Outbound]\n"
                f"    airlines: {choice['airlines']}\n"
                f"    price: {choice['price']}\n"
                f"    duration: {choice['duration']} min\n"
                f"    direct: {choice['is_direct']}"
            )
            result_logger.info(outbound_info)

            for j, f in enumerate(choice["flights"], 1):
                result_logger.info(
                    "    Leg %d:\n"
                    "      %s -> %s\n"
                    "      depart: %s %s\n"
                    "      arrive: %s %s\n"
                    "      duration: %s min\n"
                    "      flight_no: %s",
                    j,
                    f.from_airport.code,
                    f.to_airport.code,
                    f.departure.date,
                    f.departure.time,
                    f.arrival.date,
                    f.arrival.time,
                    f.duration,
                    f.flight_number,
                )

            # ===== Inbound =====
            if choice["trip"] == "round_trip":
                inbound_info = (
                    "\n  [Inbound]\n"
                    f"    airlines: {choice['airlines_2']}\n"
                    f"    price: {choice['price_2']}\n"
                    f"    duration: {choice['duration_2']} min\n"
                    f"    direct: {choice['is_direct_2']}"
                )
                result_logger.info(inbound_info)

                for j, f in enumerate(choice["flights_2"] or [], 1):
                    result_logger.info(
                        "    Leg %d:\n"
                        "      %s -> %s\n"
                        "      depart: %s %s\n"
                        "      arrive: %s %s\n"
                        "      duration: %s min\n"
                        "      flight_no: %s",
                        j,
                        f.from_airport.code,
                        f.to_airport.code,
                        f.departure.date,
                        f.departure.time,
                        f.arrival.date,
                        f.arrival.time,
                        f.duration,
                        f.flight_number,
                    )
'''