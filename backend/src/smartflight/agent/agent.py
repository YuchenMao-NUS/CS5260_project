from langgraph.graph import END, StateGraph
from smartflight.agent.extract_query import extract_query_node
from smartflight.agent.extract_preference import extract_preference_node
from smartflight.agent.state import AgentState
from smartflight.agent.search_flights import search_flights_node
from smartflight.agent.filter_flights import filter_flights_node

# 条件路由
def route_after_extraction(state: AgentState) -> str:
    """有错误（缺出发地）则终止，否则继续提取偏好"""
    if state.get("error_message"):
        return "end"
    return "extract_preference"

# 第三节点：根据 flight_query 调用外部 API 检索机票
# def search_flights_node(state: AgentState) -> AgentState:
#     return state

# 第四节点：根据 flight_preference 对检索结果筛选排序
# def filter_flights_node(state: AgentState) -> AgentState:
#     return state

# TODO
# 第五节点：将最终结果以网页等形式展示给用户（待实现）
def display_flights_node(state: AgentState) -> AgentState:
    # state["flight_choices"]
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
    }
)

builder.add_edge("extract_preference", "search_flights")
builder.add_edge("search_flights", "filter_flights")
builder.add_edge("filter_flights", "display_flights")
builder.add_edge("display_flights", END)

graph = builder.compile()


# 测试
if __name__ == "__main__":
    test_input = {
        "user_input": "我想从北京出发去东京，下个月出发，一周后返回，预算30000元以内",
        "flight_query": None,
        "flight_preference": None,
        "error_message": None,
    }

    result = graph.invoke(test_input)

    # result_logger.info("=== flight_query ===")
    # for k, v in result["flight_query"].items():
    #     result_logger.info("  %s: %s", k, v)

    # result_logger.info("\n=== flight_preference ===")
    # for k, v in result["flight_preference"].items():
    #     result_logger.info("  %s: %s", k, v)

    # if result["error_message"]:
    #     result_logger.warning("\n=== error ===\n  %s", result["error_message"])

    # result_logger.info("\n=== flight_choices ===")

    # flight_choices = result.get("flight_choices") or []

    # if not flight_choices:
    #     result_logger.info("  (no results)")
    # else:
    #     for i, choice in enumerate(flight_choices[:10], 1):
    #         # ===== 基本信息 =====
    #         header = (
    #             f"\n--- Option {i} ---\n"
    #             f"  trip: {choice['trip']}\n"
    #             f"  route: {choice['from_airport']} -> {choice['to_airport']}\n"
    #             f"  departure_date: {choice['departure_date']}"
    #         )

    #         if choice["return_date"]:
    #             header += f"\n  return_date: {choice['return_date']}"

    #         result_logger.info(header)

    #         # ===== Outbound =====
    #         outbound_info = (
    #             "\n  [Outbound]\n"
    #             f"    airlines: {choice['airlines']}\n"
    #             f"    price: {choice['price']}\n"
    #             f"    duration: {choice['duration']} min\n"
    #             f"    direct: {choice['is_direct']}"
    #         )
    #         result_logger.info(outbound_info)

    #         for j, f in enumerate(choice["flights"], 1):
    #             result_logger.info(
    #                 "    Leg %d:\n"
    #                 "      %s -> %s\n"
    #                 "      depart: %s %s\n"
    #                 "      arrive: %s %s\n"
    #                 "      duration: %s min\n"
    #                 "      flight_no: %s",
    #                 j,
    #                 f.from_airport.code,
    #                 f.to_airport.code,
    #                 f.departure.date,
    #                 f.departure.time,
    #                 f.arrival.date,
    #                 f.arrival.time,
    #                 f.duration,
    #                 f.flight_number,
    #             )

    #         # ===== Inbound =====
    #         if choice["trip"] == "round_trip":
    #             inbound_info = (
    #                 "\n  [Inbound]\n"
    #                 f"    airlines: {choice['airlines_2']}\n"
    #                 f"    price: {choice['price_2']}\n"
    #                 f"    duration: {choice['duration_2']} min\n"
    #                 f"    direct: {choice['is_direct_2']}"
    #             )
    #             result_logger.info(inbound_info)

    #             for j, f in enumerate(choice["flights_2"] or [], 1):
    #                 result_logger.info(
    #                     "    Leg %d:\n"
    #                     "      %s -> %s\n"
    #                     "      depart: %s %s\n"
    #                     "      arrive: %s %s\n"
    #                     "      duration: %s min\n"
    #                     "      flight_no: %s",
    #                     j,
    #                     f.from_airport.code,
    #                     f.to_airport.code,
    #                     f.departure.date,
    #                     f.departure.time,
    #                     f.arrival.date,
    #                     f.arrival.time,
    #                     f.duration,
    #                     f.flight_number,
    #                 )