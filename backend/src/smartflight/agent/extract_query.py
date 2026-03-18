from smartflight.agent.state import AgentState
from typing import List, Literal, Optional
from openai import OpenAI
from pydantic import BaseModel
from datetime import datetime, timedelta
import os


# 结构化LLM输出的提取结果
class FlightQueryExtraction(BaseModel):
    """LLM 提取结果的结构化模型"""
    has_origin: bool                                    # 用户是否提供了出发地
    trip: Optional[Literal["one_way", "round_trip"]]    # 单程 / 往返
    from_airport: Optional[str]                         # 出发地 IATA 码
    to_airports: Optional[List[str]]                    # 目的地 IATA 码列表
    departure_date: Optional[str]                       # 出发日期 YYYY-MM-DD
    return_date: Optional[str]                          # 返回日期 YYYY-MM-DD
    seat_classes: Optional[
        List[Literal["business", "economy", "first", "premium-economy"]]
    ]
    passengers: Optional[int]



def extract_query_node(state: AgentState) -> AgentState:
    client = OpenAI() if os.environ.get("OPENAI_API_KEY") else None
    if not client:
        raise ValueError("OPENAI_API_KEY not set")
        
    # 使用datetime获取当前时间
    today = datetime.now().strftime("%Y-%m-%d")
    user_input = state["user_input"]

    system_prompt = f"""
You are a flight search assistant. Extract structured flight search parameters from the user's natural language input.
Today's date is {today}.

Extraction rules:
1. has_origin: Set to false if no departure city/airport is mentioned. In that case, leave all other fields null.
2. from_airport / to_airports: MUST use 3-letter IATA codes (e.g. PEK, SHA, SIN, NRT).
3. trip: Infer from context. Keywords like "round trip", "return", "来回" → round_trip; otherwise → one_way.
4. departure_date: If not mentioned, use today ({today}). Format: YYYY-MM-DD.
5. return_date: Only set for round_trip. If not mentioned, default to departure_date + 7 days.
6. seat_classes: If not specified, return all four: ["business", "economy", "first", "premium-economy"].
7. passengers: If not specified, default to 1.
8. to_airports: If no destination is mentioned, recommend 5 suitable destinations (as IATA codes) based on the origin.
""".strip()

    response = client.beta.chat.completions.parse(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        response_format=FlightQueryExtraction,
    )

    extraction: FlightQueryExtraction = response.choices[0].message.parsed

    # 缺少出发地：写入错误，终止本轮
    if not extraction.has_origin:
        return {
            **state,
            "flight_query": None,
            "error_message": "The origin could not be identified. Please reenter your search terms.",
        }

    # 填充默认值
    departure_date = extraction.departure_date or today

    if extraction.trip == "round_trip" and not extraction.return_date:
        return_date = (
            datetime.strptime(departure_date, "%Y-%m-%d") + timedelta(days=7)
        ).strftime("%Y-%m-%d")
    else:
        return_date = extraction.return_date  # one_way 时为 None

    seat_classes = extraction.seat_classes or [
        "business", "economy", "first", "premium-economy"
    ]

    flight_query = {
        "trip": extraction.trip,
        "from_airport": extraction.from_airport,
        "to_airports": extraction.to_airports or [],
        "departure_date": departure_date,
        "return_date": return_date,
        "seat_classes": seat_classes,
        "passengers": extraction.passengers or 1,
    }

    return {
        **state,
        "flight_query": flight_query,
        "error_message": None,
    }