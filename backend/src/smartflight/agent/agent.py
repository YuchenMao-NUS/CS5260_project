from langgraph.graph import START, END, StateGraph
from smartflight.agent.state import AgentState
from smartflight.agent.guardrail import intent_guardrail_node
from smartflight.agent.extract_query import extract_query_node
from smartflight.agent.extract_preference import extract_preference_node
from smartflight.agent.search_flights import search_flights_node
from smartflight.agent.filter_flights import filter_flights_node

import logging
# 普通日志（带时间等）
logging.basicConfig(
    level=logging.INFO,  # 改成 DEBUG 可以看更详细日志
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Conditional Edge
def route_after_guardrail(state: AgentState) -> str:
    """If the intent is irrelevant, terminate directly; if it is relevant, proceed to the distribution node."""
    if state.get("error_message"):
        return "end"
    return "dispatch_extractions"

def dispatch_extractions(state: AgentState) -> dict:
    return {}

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
    }
)

# Fan-out
builder.add_edge("dispatch_extractions", "extract_query")
builder.add_edge("dispatch_extractions", "extract_preference")

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




# 测试
if __name__ == "__main__":
    test_input = {
        "user_input": "我想从北京出发去东京，下个月出发, 一周后返回 ,预算30000元以内",
        "flight_query": None,
        "flight_preference": None,
        "error_message": None,
    }

    result = graph.invoke(test_input)
