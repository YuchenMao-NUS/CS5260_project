from typing import TypedDict, Optional, List, Literal


class FlightQuery(TypedDict):
    trip: Literal["one_way", "round_trip"]
    from_airport: str                    # IATA 三字码
    to_airports: List[str]               # IATA 三字码列表（可能是推荐的5个）
    departure_date: str                  # YYYY-MM-DD
    return_date: Optional[str]           # YYYY-MM-DD，仅往返有效
    seat_classes: List[Literal["business", "economy", "first", "premium-economy"]]
    passengers: int


class FlightPreference(TypedDict):
    direct_only: Optional[bool]               # True=只要直飞，False=无所谓，None=未提及
    preferred_airlines: Optional[List[str]]   # 航司 IATA 二字码列表，如 ["CA", "MU"]
    max_price: Optional[float]                # 价格上限（SGD）
    min_price: Optional[float]                # 价格下限（SDG）
    max_duration: Optional[int]               # 飞行时长上限（分钟）
    min_duration: Optional[int]               # 飞行时长下限（分钟）


class AgentState(TypedDict):
    user_input: str                                # 用户原始输入
    flight_query: Optional[FlightQuery]            # 提取出的检索条件
    flight_preference: Optional[FlightPreference]  # 提取出的用户偏好
    error_message: Optional[str]                   # 节点错误信息（缺少出发地）