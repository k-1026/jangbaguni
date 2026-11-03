"""살피 AI 에이전트 (구글 제미나이 무료 API).

제미나이는 아래 도구 함수를 불러 숫자를 받고, 살피 말투로 설명만 한다.
터미널에서 바로 대화: python agent.py
"""

import os
from pathlib import Path

from google import genai
from google.genai import types

import analysis
from data_sources import ITEMS, ApiKeyMissing, daegu_events, holidays

ROOT = Path(__file__).resolve().parent
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")


# ---------------------------------------------------------------
# 제미나이가 부를 수 있는 도구 (설명 문장이 그대로 도구 설명이 됨)
# ---------------------------------------------------------------

def _safe(fn, *args):
    try:
        return fn(*args)
    except ApiKeyMissing as e:
        return {"error": str(e)}
    except Exception as e:  # API 장애는 에이전트가 "지금은 못 불러와요"라고 말하게 함
        return {"error": f"데이터를 불러오지 못했어요: {type(e).__name__}"}


def list_supported_items() -> dict:
    """살피가 시세를 볼 수 있는 재료 목록을 돌려준다."""
    return {"items": list(ITEMS)}


def get_market_overview() -> dict:
    """지원하는 모든 재료의 대구 도매가(kg당)와 1주 전 대비 변화율, 소매가를 한 번에 돌려준다.
    아침 브리핑이나 '요즘 뭐가 올랐어?' 같은 질문에 쓴다."""
    return _safe(lambda: {"rows": analysis.market_overview()})


def get_item_price_trend(item: str) -> dict:
    """재료 하나의 대구 도매가·소매가와 1주 전 대비 변화, 최근 2주 도매가 기록을 돌려준다.

    Args:
        item: 재료 이름 (예: 양파, 대파, 양배추, 청양고추, 당근, 깻잎)
    """
    return _safe(analysis.item_trend, item)


def forecast_item_price(item: str) -> dict:
    """재료 하나의 다음 7일 도매가 방향(오를/내릴/비슷)과 예상 범위, 요인별 이유를 돌려준다.
    요인: 최근 시세 흐름, 반입량, 대구 날씨, 다가오는 공휴일, 대구 행사.

    Args:
        item: 재료 이름 (예: 양파, 대파, 양배추, 청양고추, 당근, 깻잎)
    """
    return _safe(analysis.forecast_item, item)


def get_weather_summary(days: int = 7) -> dict:
    """대구(관측소 143) 최근 날씨 요약: 강수량, 비 온 날, 최저·최고 기온.

    Args:
        days: 며칠 치를 볼지 (1~21, 기본 7)
    """
    return _safe(analysis.weather_summary, max(1, min(21, days)))


def get_daegu_events(days_ahead: int = 14) -> dict:
    """오늘부터 days_ahead일 안에 열리는 대구 행사·축제 목록 (한국관광공사).

    Args:
        days_ahead: 며칠 앞까지 볼지 (기본 14)
    """
    return _safe(lambda: {"events": daegu_events(days_ahead)})


def get_upcoming_holidays(days_ahead: int = 30) -> dict:
    """오늘부터 days_ahead일 안의 공휴일 (한국천문연구원 특일 정보).

    Args:
        days_ahead: 며칠 앞까지 볼지 (기본 30)
    """
    return _safe(lambda: {"holidays": holidays(days_ahead)})


TOOLS = [list_supported_items, get_market_overview, get_item_price_trend, forecast_item_price,
         get_weather_summary, get_daegu_events, get_upcoming_holidays]


# ---------------------------------------------------------------
# 살피 성격 (brand/SKILL.md + 기획서 11-3 판단 원칙)
# ---------------------------------------------------------------

def _brand_skill():
    path = ROOT.parent / "brand" / "SKILL.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


SYSTEM_PROMPT = f"""너는 '살피'다. 대구 외식업 사장님의 식자재 시세 비서인 미어캣. 아무것도 팔지 않는다.

판단 원칙 (반드시 지킬 것)
1. 숫자는 도구 결과만 인용한다. 도구에 없는 가격·비율을 지어내지 않는다.
2. 가격을 말할 때는 기준(도매/소매, kg당), 날짜, 출처를 짧게 붙인다.
3. 예측은 항상 범위와 함께 말하고, confidence가 '낮음'이면 "확실하지 않아요"를 먼저 말한다.
4. 이유는 factors에서 영향이 큰 것 1~2개만 쉬운 말로 말한다.
5. 사지 않는 게 유리하면 "기다려 보세요"라고 말한다. 특정 판매처 구매를 권하지 않는다.
6. 지원하지 않는 재료를 물으면 list_supported_items 결과로 지금 볼 수 있는 재료를 안내한다.
7. 도구가 error를 돌려주면 그 이유를 그대로 짧게 알리고 추측하지 않는다.

출력 형식
- 한 문단 2~4문장, 또는 재료가 여러 개면 재료당 한 줄. [무엇이] → [얼마나] → [그래서 어떻게].
- 표·이모지·전문 용어(모델, 회귀, 피처 등) 쓰지 않는다.

아래는 살피 브랜드 규칙이다. 말투와 금칙어를 따른다.
{_brand_skill()}
"""


BRIEFING_PROMPT = ("오늘 아침 브리핑을 해 줘. 전체 시세에서 많이 오른 것과 내린 것, "
                   "그리고 가장 많이 오른 재료 하나의 다음 주 예측을 알려 줘.")


class SalpiAgent:
    def __init__(self, api_key=None, model=MODEL):
        key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            raise ApiKeyMissing(".env 의 GEMINI_API_KEY 가 비어 있어요 (aistudio.google.com 에서 무료 발급)")
        self.client = genai.Client(api_key=key)
        self.chat = self.client.chats.create(
            model=model,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=TOOLS,
                temperature=0.3,
            ),
        )

    def ask(self, message: str) -> str:
        return self.chat.send_message(message).text or "답을 만들지 못했어요. 다시 물어봐 주세요."

    def morning_briefing(self) -> str:
        return self.ask(BRIEFING_PROMPT)


if __name__ == "__main__":
    agent = SalpiAgent()
    print("살피: 사장님, 궁금한 재료를 물어보세요. (끝내려면 엔터만)")
    while True:
        q = input("사장님: ").strip()
        if not q:
            break
        print("살피:", agent.ask(q))
