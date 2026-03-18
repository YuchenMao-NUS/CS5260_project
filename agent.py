from langgraph.graph import END, StateGraph
from nodes.extract_query import extract_query_node
from nodes.extract_preference import extract_preference_node
from state import AgentState

# 条件路由
def route_after_extraction(state: AgentState) -> str:
    """有错误（缺出发地）则终止，否则继续提取偏好"""
    if state.get("error_message"):
        return "end"
    return "extract_preference"

# TODO
# 第三节点：根据 flight_query 调用外部 API 检索机票（待实现）
def search_flights_node(state: AgentState) -> AgentState:
    return state

# 第四节点：根据 flight_preference 对检索结果筛选排序（待实现）
def filter_flights_node(state: AgentState) -> AgentState:
    return state

# 第五节点：将最终结果以网页等形式展示给用户（待实现）
def display_flights_node(state: AgentState) -> AgentState:
    return state



builder = StateGraph(AgentState)

builder.add_node("extract_query", extract_query_node)
builder.add_node("extract_preference", extract_preference_node)
# TODO
builder.add_node("search_flights", search_flights_node)
builder.add_node("filter_flights", filter_flights_node)
builder.add_node("display_flights", display_flights_node)

builder.set_entry_point("extract_query")

# extract_query 完成后走条件边
builder.add_conditional_edges(
    "extract_query",
    route_after_extraction,
    {
        "end": END,
        "extract_preference": "extract_preference",
    },
)

builder.add_edge("extract_preference", "search_flights")
builder.add_edge("search_flights", "filter_flights")
builder.add_edge("filter_flights", "display_flights")
builder.add_edge("display_flights", END)

graph = builder.compile()


# 测试
if __name__ == "__main__":
    test_input = {
        "user_input": "我想从北京出发去东京，下周五出发，希望直飞，预算2000元以内",
        "flight_query": None,
        "flight_preference": None,
        "error_message": None,
    }

    result = graph.invoke(test_input)

    print("=== flight_query ===")
    for k, v in result["flight_query"].items():
        print(f"  {k}: {v}")

    print("\n=== flight_preference ===")
    for k, v in result["flight_preference"].items():
        print(f"  {k}: {v}")

    if result["error_message"]:
        print(f"\n=== error ===\n  {result['error_message']}")