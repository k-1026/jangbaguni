"""살피 AI 에이전트 (구글 제미나이 무료 API).

제미나이는 아래 도구 함수를 불러 숫자를 받고, 살피 말투로 설명만 한다.
터미널에서 바로 대화: python agent.py
"""

import os
from pathlib import Path

from google import genai
from google.genai import errors, types

import re

import requests

import analysis
import demand
import menu_cost
import receipts
import supabase_db
from data_sources import ITEMS, ApiKeyMissing, daegu_events, holidays

ROOT = Path(__file__).resolve().parent
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
# 기본 모델이 바쁘거나(503) 무료 한도를 넘으면(429) 순서대로 갈아탐
FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_FALLBACK_MODELS", "gemini-3-flash-preview,gemini-flash-latest,gemini-3.5-flash-lite").split(",") if m.strip()]


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


ITEM_ALIASES = {"청양": "청양고추", "고추": "청양고추", "파": "대파", "호박": "애호박", "깻잎순": "깻잎"}


def _item(name):
    name = (name or "").strip().replace(" ", "")
    return ITEM_ALIASES.get(name, name)


def get_item_price_trend(item: str) -> dict:
    """재료 하나의 대구 도매가·소매가와 1주 전 대비 변화, 최근 2주 도매가 기록을 돌려준다.

    Args:
        item: 재료 이름 (예: 양파, 대파, 양배추, 청양고추, 당근, 깻잎)
    """
    return _safe(analysis.item_trend, _item(item))


def forecast_item_price(item: str) -> dict:
    """재료 하나의 다음 7일 도매가 방향(오를/내릴/비슷)과 예상 범위, 요인별 이유를 돌려준다.
    요인: 최근 시세 흐름, 반입량, 대구 날씨, 다가오는 공휴일, 대구 행사.

    Args:
        item: 재료 이름 (예: 양파, 대파, 양배추, 청양고추, 당근, 깻잎)
    """
    return _safe(analysis.forecast_item, _item(item))


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


def recommend_buy_now() -> dict:
    """지금 사면 이득인 재료를 나눠서 돌려준다.
    buy_now_before_rise: 다음 7일 오를 가능성이 있어 미리 사면 좋은 재료,
    cheap_now: 지난주보다 많이 내려 지금 싼 재료, wait: 내릴 가능성이 있어 기다리면 좋은 재료,
    as_usual: 평소대로 사면 되는 재료. 각 재료에 식봄 검색 링크(foodspring_url)가 붙어 있다."""
    return _safe(analysis.buy_now_recommendations)


def list_standard_menus() -> dict:
    """원가를 바로 계산할 수 있는 표준 레시피 메뉴 목록과 각 메뉴의 1인분 재료."""
    return {"menus": {m: [f"{n} {a:g}{u}" for n, a, u in r] for m, r in menu_cost.STANDARD_RECIPES.items()}}


def calc_menu_margin(menu: str, sale_price: int, ingredients: str = "") -> dict:
    """메뉴 1인분 재료비, 원가율(재료비÷판매가), 재료비 뺀 남는 돈, 판단을 계산한다.
    채소는 오늘 대구 시세, 나머지는 참고 단가를 쓴다.

    Args:
        menu: 메뉴 이름 (예: 제육볶음)
        sale_price: 1인분 판매가(원). 사장님이 말한 값만 넣는다.
        ingredients: 표준 레시피가 없거나 사장님이 직접 재료를 알려 준 경우만,
            "돼지고기 앞다리 150g, 양파 100g, 두부 0.5모, 계란 1개" 형식. 아니면 빈 문자열.
    """
    parsed = [{"name": m.group(1).strip(), "amount": m.group(2), "unit": m.group(3)}
              for m in re.finditer(r"([^,\d]+?)\s*([\d.]+)\s*(kg|g|모|개)", ingredients or "")]
    for p in parsed:   # kg는 g로 맞춤
        if p["unit"] == "kg":
            p["amount"], p["unit"] = float(p["amount"]) * 1000, "g"
    return _safe(menu_cost.menu_cost, menu, sale_price, parsed or None)


def forecast_store_demand() -> dict:
    """시연용 가게('살피 시연 한식당')의 판매 기록으로 내일 메뉴별 예상 그릇 수(범위 포함)와
    다음 입고일 전까지 모자란 재료의 발주량 · 판단(지금 사기 · 나눠 사기)을 돌려준다.
    menus 와 orders 에 있는 숫자 · 재료만 그대로 말한다."""
    def run():
        r = demand.forecast()
        if r.get("error"):
            return r
        reason = {}
        for m in r["menus"]:   # 가장 영향이 큰 이유 한 줄
            name, v = max(m["factors"].items(), key=lambda kv: abs(kv[1]))
            reason[m["menu"]] = ("평소와 비슷" if abs(v) < 0.02 else
                                 f"{name} 영향 {v * 100:+.0f}%")
        return {
            "store": r["store"]["name"] + (" (시연용)" if r["store"]["is_demo"] else ""),
            "target_date": f"{r['target_date']}({r['target_weekday']})", "last_sales_date": r["last_sales_date"],
            "next_delivery_date": r["next_delivery_date"], "total_bowls": r["total_predicted"],
            "menus": [{"menu": m["menu"], "bowls": m["predicted"], "range": f"{m['range'][0]}~{m['range'][1]}",
                       "reason": reason[m["menu"]]} for m in r["menus"]],
            "orders": [{"item": i["item"], "order": f"{i['order_qty']:g}{i['unit']}", "decision": i["decision"],
                        "why": i["reason"]} for i in r["items"] if i["order_qty"] > 0][:5],
            "enough_stock": [i["item"] for i in r["items"] if i["order_qty"] <= 0],
        }
    return _safe(run)


def get_store_cost_ratio() -> dict:
    """시연용 가게('살피 시연 한식당') 메뉴별 원가율. 가게가 영수증으로 실제 산 가격(최근 영수증 단가) 기준.
    menus 마다 cost_ratio_pct(원가율 %), margin(재료비 뺀 남는 돈), verdict, top_items(비싼 재료),
    riser(영수증 기준 가장 많이 오른 재료), tips(규칙으로 계산한 판매가 조정 · 대체 재료 제안)가 있다."""
    def run():
        r = receipts.cost_report(supabase_db.DEMO_STORE)
        return {"store": "살피 시연 한식당 (시연용)", "target_ratio_pct": r["target_ratio_pct"], "menus": [{
            "menu": m["menu"], "price": m["price"], "cost_per_serving": m["cost_per_serving"], "cost_ratio_pct": m["cost_ratio_pct"],
            "margin": m["margin"], "verdict": m["verdict"], "top_items": [t["item"] for t in m["top_items"]], "tips": m["tips"],
        } for m in r["menus"]]}
    return _safe(run)


TOOLS = [list_supported_items, get_market_overview, get_item_price_trend, forecast_item_price,
         recommend_buy_now, list_standard_menus, calc_menu_margin, forecast_store_demand, get_store_cost_ratio,
         get_weather_summary, get_daegu_events, get_upcoming_holidays]


# ---------------------------------------------------------------
# 살피 성격 (brand/SKILL.md + 기획서 11-3 판단 원칙)
# ---------------------------------------------------------------

SKILL_URL = "https://raw.githubusercontent.com/k-1026/jangbaguni/main/brand/SKILL.md"


def _brand_skill():
    # 내 컴퓨터는 저장소의 brand/SKILL.md, Vercel은 salpi_agent 폴더만 올라가므로 GitHub에서 읽어 옴
    path = ROOT.parent / "brand" / "SKILL.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    try:
        return requests.get(SKILL_URL, timeout=10).text
    except requests.RequestException:
        return ""


SYSTEM_PROMPT = f"""너는 '살피'다. 대구 외식업 사장님의 식자재 시세 비서인 미어캣. 아무것도 팔지 않는다.

판단 원칙 (반드시 지킬 것)
0. 가격 · 원가율 · 판매량 · 발주량 같은 숫자가 들어가는 답은 반드시 알맞은 도구를 먼저 부르고 나서 답한다.
   지난 대화에 비슷한 숫자가 있어도 다시 부른다.
1. 숫자는 도구 결과만 인용한다. 도구에 없는 가격·비율을 지어내지 않는다.
2. 가격을 말할 때는 기준(도매/소매, kg당), 날짜, 출처를 짧게 붙인다.
3. 예측은 항상 범위와 함께 말하고, confidence가 '낮음'이면 "확실하지 않아요"를 먼저 말한다.
4. 이유는 factors에서 영향이 큰 것 1~2개만 쉬운 말로 말한다.
5. 사지 않는 게 유리하면 "기다려 보세요"라고 말한다. 특정 판매처 구매를 권하지 않는다.
6. 지원하지 않는 재료를 물으면 list_supported_items 결과로 지금 볼 수 있는 재료를 안내한다.
7. 도구가 error를 돌려주면 그 이유를 그대로 짧게 알리고 추측하지 않는다.

자주 오는 질문 처리
A. "시세변동 추이" 질문 → get_market_overview 와 recommend_buy_now 를 부른다.
   많이 오른 재료·내린 재료를 각각 변화율 순서로 말하고, 마지막에 "지금 사기 좋은 야채"를 1~3개 추천한다.
B. "이 가격에 팔아도 남아?"처럼 메뉴나 판매가 없이 마진을 물으면 계산하지 말고 먼저 묻는다:
   "어떤 메뉴를 만드시는지, 한 그릇에 얼마에 파시는지 알려주세요." 그리고 바로 계산할 수 있는 메뉴로
   {", ".join(menu_cost.STANDARD_RECIPES)} 을(를) 예시로 보여 준다 (이 목록에 없는 메뉴를 예시로 들지 않는다).
   목록에 없는 메뉴도 1인분 재료와 양을 알려 주면 계산할 수 있다고 덧붙인다.
   메뉴와 판매가를 들으면 calc_menu_margin 을 부른다. need_ingredients 가 오면 재료와 양을 물어본다.
   답에는 재료비, 원가율, 재료비 뺀 남는 돈, 가장 비싼 재료 1~2개, 시세가 오르는 재료가 있으면 그 영향을 말한다.
   참고 단가(시연용 가정값)를 쓴 재료가 있으면 "영수증 값을 알려 주시면 더 정확해져요"를 덧붙인다.
   재료 양을 지어내지 않는다. 사장님이 말한 양이나 표준 레시피만 쓴다.
C. "지금 사면 이득인 야채" 질문 → recommend_buy_now 를 부르고, 미리 사면 좋은 것·지금 싼 것·기다릴 것 순서로 말한다.
E. "우리 가게 원가율", "영수증 기준 원가", "원가율 올랐어?", 가격 조정 · 대체 재료 질문 → get_store_cost_ratio 를 부른다.
   첫 줄에 "시연용 가게 영수증 기준"이라고 밝히고, 메뉴마다 원가율 · 남는 돈 · 판단을 한 줄씩 말한다.
   tips 가 있으면 그대로 1~2개 전한다 (판매가 숫자는 tips 에 있는 값만). 대체 재료는 "검토해 보세요"로만 말한다.
   일반 메뉴 계산(calc_menu_margin, 시장 시세 기준)과 섞지 않는다.
D. "내일 얼마나 준비할까?", 판매량 · 몇 그릇 · 발주량 질문 → forecast_store_demand 를 부른다.
   첫 줄에 "시연용 가게(살피 시연 한식당) 판매 기록 기준"이라고 밝힌다.
   메뉴별 예상 그릇 수를 범위와 함께 말하고(예: 김치찌개 101그릇, 96~106), 영향이 큰 이유 1개를 쉬운 말로 붙인다.
   그다음 orders 의 앞에서 3개를 "재료 · 발주량 · 판단(지금 사기/나눠 사기)" 한 줄씩 그대로 말하고,
   (orders 에 없는 재료 · 숫자를 말하지 않는다. 메뉴는 menus 에 있는 것만 전부 말한다)
   다음 입고일(next_delivery_date)까지 기준이라고 덧붙인다. 우리 가게 판매량을 넣으면 그 가게 기준으로 바뀐다고 안내한다.

출력 형식
- 짧게. 전체 10줄 이내, 묶음마다 재료 3개까지, 재료당 한 줄. [무엇이] → [얼마나] → [그래서 어떻게].
- "확실하지 않아요"는 답 맨 앞에 한 번만. 줄마다 반복하지 않는다.
- 날짜·출처는 답 끝에 한 번만 (예: "11/2 대구 북부도매시장 kg당 도매가 기준").
- 예측 범위는 "-24% ~ 0%"처럼 부호를 붙여 작은 값부터 쓴다.
- 강조는 **굵게** 정도만. 표·이모지·전문 용어(모델, 회귀, 피처 등) 쓰지 않는다.
- 링크 주소는 쓰지 않는다 (화면의 상품 카드에서 식봄으로 연결됨).

아래는 살피 브랜드 규칙이다. 말투와 금칙어를 따른다.
{_brand_skill()}
"""


BRIEFING_PROMPT = ("오늘 아침 브리핑을 해 줘. 전체 시세에서 많이 오른 것과 내린 것, "
                   "그리고 가장 많이 오른 재료 하나의 다음 주 예측을 알려 줘.")


class SalpiAgent:
    def __init__(self, api_key=None, model=MODEL, history=None):
        """history: 지난 대화 [{"role": "user"|"bot", "text": ...}] — 화면이 보관했다가 보내 줌."""
        key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            raise ApiKeyMissing(".env 의 GEMINI_API_KEY 가 비어 있어요 (aistudio.google.com 에서 무료 발급)")
        # 응답이 45초 넘게 없으면 끊고 다음 모델로 (바쁜 모델에 오래 묶이지 않게)
        self.client = genai.Client(api_key=key, http_options=types.HttpOptions(
            timeout=45_000, retry_options=types.HttpRetryOptions(attempts=2)))
        self.models = [model] + [m for m in FALLBACK_MODELS if m != model]
        past = [types.Content(role="user" if h.get("role") == "user" else "model",
                              parts=[types.Part(text=str(h.get("text", ""))[:2000])])
                for h in (history or [])[-12:] if h.get("text")]
        self._start(self.models[0], history=past or None)

    def _start(self, model, history):
        self.model = model
        self.chat = self.client.chats.create(
            model=model,
            config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT, tools=TOOLS, temperature=0.3),
            history=history,
        )

    def ask(self, message: str) -> str:
        # 무료 API는 몰리면 503·504(바쁨), 한도를 넘으면 429를 돌려줌
        # → (SDK가 한 번 더 시도한 뒤) 다음 모델로 갈아타서 대화를 이어 감
        last_error = None
        for model in self.models[self.models.index(self.model):]:
            if model != self.model:
                self._start(model, history=self.chat.get_history())
            try:
                return self.chat.send_message(message).text or "답을 만들지 못했어요. 다시 물어봐 주세요."
            except errors.APIError as e:
                if 400 <= e.code < 500 and e.code not in (404, 429):
                    raise      # 요청 자체가 잘못된 경우는 갈아타도 같음
                last_error = e
            except Exception as e:  # 시간 초과·연결 끊김
                last_error = e
        raise last_error

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
