from smartflight.agent.state import AgentState
from typing import List, Optional
from openai import OpenAI
from pydantic import BaseModel
import os

import logging
logger = logging.getLogger(__name__)


# 结构化LLM输出的提取结果
class FlightPreferenceExtraction(BaseModel):
    """LLM 提取用户偏好的结构化模型"""
    direct_only: Optional[bool]              # 是否明确要求直飞
    preferred_airlines: Optional[List[str]]  # 航司二字码列表
    max_price: Optional[float]               # 价格上限 SGD
    min_price: Optional[float]               # 价格下限 SGD
    max_duration: Optional[int]              # 时长上限（分钟）
    min_duration: Optional[int]              # 时长下限（分钟）


def extract_preference_node(state: AgentState) -> AgentState:
    client = OpenAI() if os.environ.get("OPENAI_API_KEY") else None
    if not client:
        raise ValueError("OPENAI_API_KEY not set")
        
    user_input = state["user_input"]

    system_prompt = """
You are a flight preference extraction assistant. Extract the user's soft preferences from their natural language input.
All fields are optional — only populate a field if the user explicitly or implicitly expresses that preference.

Extraction rules:
1. direct_only:
   - true if the user wants non-stop/direct flights only (e.g. "direct", "non-stop", "不转机", "直飞")
   - false if the user explicitly says they don't mind connecting flights
   - null if not mentioned at all

2. preferred_airlines:
   - Extract as a list of IATA 2-letter airline codes (e.g. "CA" for Air China, "MU" for China Eastern, "SQ" for Singapore Airlines)
   - null if no airline preference is mentioned

3. max_price / min_price:
   - Extract price constraints in SGD
   - If user says "under $500", set max_price=500.0, min_price=null
   - If user says "around $300", set min_price=270.0, max_price=330.0 (±10%)
   - null if not mentioned

4. max_duration / min_duration:
   - Extract flight duration constraints in MINUTES
   - If user says "less than 3 hours", set max_duration=180, min_duration=null
   - null if not mentioned
""".strip()
    
    logger.debug("[LLM] system_prompt:\n%s", system_prompt)
    logger.debug("[LLM] user_input: %s", user_input)

    response = client.beta.chat.completions.parse(
        model="gpt-5-mini", # gpt-4o-mini is too dumb
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ],
        response_format=FlightPreferenceExtraction,
    )

    extraction: FlightPreferenceExtraction = response.choices[0].message.parsed

    flight_preference = {
        "direct_only": extraction.direct_only,
        "preferred_airlines": extraction.preferred_airlines,
        "max_price": extraction.max_price,
        "min_price": extraction.min_price,
        "max_duration": extraction.max_duration,
        "min_duration": extraction.min_duration,
    }

    return {
        **state,
        "flight_preference": flight_preference,
    }