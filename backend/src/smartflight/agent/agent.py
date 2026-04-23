from langgraph.graph import START, END, StateGraph
from smartflight.agent.state import AgentState
from smartflight.agent.guardrail import intent_guardrail_node
from smartflight.agent.extract_query import extract_query_node
from smartflight.agent.extract_preference import extract_preference_node
from smartflight.agent.search_flights import search_flights_node
from smartflight.agent.filter_flights import filter_flights_node
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

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
    Wait for `extract_query` and `extract_preference` to finish, then
    append a single history record for this turn.

    This avoids history write conflicts inside parallel branches.
    """
    history = list(state.get("history") or [])

    history.append(
        {
            "user_input": state.get("user_input"),
            "flight_query": state.get("flight_query"),
            "flight_preference": state.get("flight_preference"),
        }
    )

    # Keep only the most recent turns to avoid unbounded growth
    max_turns = 5
    history = history[-max_turns:]

    return {
        "history": history,
    }


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

# Initialize memory manager
memory = MemorySaver(
    serde=JsonPlusSerializer()
)
# Inject memory into the compiled graph
graph = builder.compile(checkpointer=memory)



# 测试
if __name__ == "__main__":
    # 定义 thread_id 以启用记忆功能
    thread_config = {"configurable": {"thread_id": "multi_turn_test_session"}}

    def run_test_turn(turn_name: str, user_input: str):
        print(f"\n{'='*15} {turn_name} {'='*15}")
        print(f"用户输入: {user_input}")
        
        current_input = {
            "user_input": user_input,
            "user_context": {"location": "Singapore"} 
        }

        # 运行 Agent，状态将自动在 checkpoint 中持久化
        result_state = graph.invoke(current_input, thread_config)

        # 打印状态更新详情
        if result_state.get("error_message"):
            print(f"[系统拦截/报错]: {result_state['error_message']}")

        else:
            print("[Agent 内部状态合并结果]:")
            query = result_state.get("flight_query", {})
            pref = result_state.get("flight_preference", {})
            
            # 展示硬性查询参数 (Query)
            print(f"[Query]出发地: {query.get('from_airport')}")
            print(f"Query]目的地: {query.get('to_airports')}")
            print(f"Query]时间: {query.get('departure_date')}")
            
            # 展示软性偏好参数 (Preference)
            print(f"[Pref]航司: {pref.get('preferred_airlines')}")
            print(f"[Pref]价格上限: {pref.get('max_price')} SGD")


    # 第一轮：干扰测试
    run_test_turn("第一轮: 无关意图", "我想学做红烧肉。")

    # 第二轮：核心意图（补充目的地）
    run_test_turn("第二轮: 提供目的地", "好吧，我是想买去东京的机票。")

    # 第三轮：补充时间
    run_test_turn("第三轮: 补充时间", "我想下周五出发。")

    # 第四轮：补充偏好航司（测试偏好合并）
    # 预期：此时状态应包含 东京 + 下周五 + 新航(SQ)
    run_test_turn("第四轮: 偏好航司", "我比较喜欢坐新加坡航空。")

    # 第五轮：补充价格限制（测试偏好增量合并）
    # 预期：此时状态应包含 东京 + 下周五 + 新航(SQ) + 800元上限
    run_test_turn("第五轮: 价格上限", "最大价格不要超过800新币。")
