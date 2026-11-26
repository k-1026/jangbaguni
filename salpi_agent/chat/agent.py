"""살피 AI 에이전트 (구글 제미나이 무료 API): 안내 에이전트 + 담당 에이전트 3개 (plan/presentation/살피_AI파이프라인_v3.png).

  🧭 안내        질문을 담당에게 보냄. 화면 버튼 질문은 규칙으로 바로, 자유 질문은 가벼운 모델이 고름 (실패하면 낱말 규칙)
                 섞인 질문은 여러 담당을 차례로 부르고 답을 순서대로 붙임
  📈 시세        "언제 살까"                 — 시세 · 7일 예측 · 지금 사기/기다리기 · 날씨 · 행사 · 공휴일
  💰 원가 · 마진 "얼마 남나, 어떻게 줄일까"  — 메뉴 원가율 · 40% 이상이면 가격 조정 · 대체 재료 · 메뉴 제안 · 싸게/비싸게 판정
  📦 내일 준비   "내일 무엇을 얼마나"        — 판매량 예측(시연 가게는 학습 모델) → 재료 필요량 → 재고 뺀 발주량
담당마다 도구를 5~9개만 들고 있어서 고르기 실수가 줄고, 숫자는 모두 도구(계산 · 학습 모델)가 만든다.
살피 말투는 모든 담당이 같은 규칙(brand/SKILL.md)을 씀.
터미널에서 바로 대화: python -m chat.agent
"""

import functools
import inspect
import json
import os
from concurrent.futures import ThreadPoolExecutor

from google import genai
from google.genai import errors, types

import re
import time

import requests

from price import analysis
from demand import demand
from store import menu_cost
from price import price_judge
from store import receipts
from sources import supabase_db
from chat import number_check, quick
from sources.data_sources import EXTRA_ITEMS, ITEMS, ApiKeyMissing, daegu_events, holidays

MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
# 기본 모델이 바쁘거나(503) 무료 한도를 넘으면(429) 순서대로 갈아탐
# 챗봇 전용 순서 (11/25: 사장님이 3~5초 안에 답을 받게 가벼운 모델부터 · 자료는 미리 붙여 줘서 가벼운 모델로도 충분)
CHAT_MODELS = [m.strip() for m in os.getenv(
    "CHAT_GEMINI_MODELS", "gemini-3.5-flash-lite,gemini-3-flash-preview,gemini-3.8-flash,gemini-3.7-flash,gemini-3.6-flash").split(",") if m.strip()]
FALLBACK_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_FALLBACK_MODELS", "gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-3-flash-preview,gemini-3.5-flash-lite").split(",") if m.strip()]


# ---------------------------------------------------------------
# 속도 (11/25 측정: 걸린 시간의 95%가 AI 기다리기 — experiments/chat_timing.py)
# ---------------------------------------------------------------
# 무료 한도가 바닥났거나(429, flash 는 모델마다 하루 20번) 붐비는(503) 모델은 잠시 건너뜀 → 매 질문마다 같은 실패를 기다리지 않음
_COOL = {}
COOL_SEC = {429: 1800, 503: 120, 504: 120, "timeout": 120}


def _usable(models):
    now = time.time()
    ok = [m for m in models if _COOL.get(m, 0) < now]
    return ok or models[-1:]   # 모두 쉬는 중이면 마지막(가장 가벼운) 모델로 한 번은 시도


def _cool(model, err):
    code = getattr(err, "code", None)
    sec = COOL_SEC.get(code) or (COOL_SEC["timeout"] if not code else 0)
    if sec:
        _COOL[model] = time.time() + sec


# 서버가 미리 계산해 둔 값 (server.py 가 채움: overview · demand · costs → 함수). 없으면 도구가 직접 계산
CACHED = {}
_tool_memo, TOOL_TTL = {}, 300


def _remember(fn):
    """같은 도구 · 같은 인자는 5분 동안 다시 계산하지 않음 (AI 가 같은 도구를 두 번 부를 때 · 질문이 이어질 때)."""
    @functools.wraps(fn)
    def inner(*a, **k):
        key = (fn.__name__, a, tuple(sorted(k.items())))
        hit = _tool_memo.get(key)
        if hit and time.time() - hit[0] < TOOL_TTL:
            return hit[1]
        out = fn(*a, **k)
        if not (isinstance(out, dict) and out.get("error")):
            _tool_memo[key] = (time.time(), out)
        return out
    return inner


def _cached(name):
    try:
        f = CACHED.get(name)
        return f() if f else None
    except Exception:
        return None


def _overview_rows():
    """첫 화면 시세 보관값 (재료별 시세 · 기록 · 예측). 없으면 None."""
    v = _cached("overview")
    return v if isinstance(v, list) and v else None


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
    """살피가 시세를 볼 수 있는 재료 목록을 돌려준다.
    items: 농산물 야채 · 과일(도매 경락가 · 7일 예측, 각 줄의 kind 로 구분), meat_seafood: 육류 · 수산물(대구 조사가 · 7일 예측)."""
    return {"items": list(ITEMS), "meat_seafood": list(EXTRA_ITEMS)}


@_remember
def get_market_overview() -> dict:
    """지원하는 모든 재료의 대구 도매가(kg당)와 1주 전 대비 변화율, 소매가를 한 번에 돌려준다.
    아침 브리핑이나 '요즘 뭐가 올랐어?' 같은 질문에 쓴다."""
    rows = _overview_rows()
    if rows:   # 날짜별 기록 · 예측은 빼고 (답이 길어지지 않게)
        return {"rows": [{k: v for k, v in r.items() if k not in ("history", "forecast")} for r in rows]}
    return _safe(lambda: {"rows": analysis.market_overview()})


ITEM_ALIASES = {"청양": "청양고추", "고추": "청양고추", "파": "대파", "호박": "애호박", "깻잎순": "깻잎"}


def _item(name):
    name = (name or "").strip().replace(" ", "")
    return ITEM_ALIASES.get(name, name)


@_remember
def get_item_price_trend(item: str) -> dict:
    """재료 하나의 대구 도매가·소매가와 1주 전 대비 변화, 최근 2주 도매가 기록을 돌려준다.

    Args:
        item: 재료 이름 (예: 양파, 대파, 양배추, 청양고추, 당근, 깻잎)
    """
    name = _item(item)
    r = next((r for r in _overview_rows() or [] if r["item"] == name), None)
    if r:   # 첫 화면 보관값으로 바로 (11/25: 배포 직후 aT 시세를 처음부터 받느라 53초)
        return {"item": name,
                "wholesale": {"source": "aT 정산정보 · 대구 북부도매시장(매천시장)", "date": r["wholesale_date"], "kg_price": r["wholesale_kg"],
                              "week_change_pct": r["wholesale_change_pct"], "direction": r["direction"],
                              "volume_kg": (r.get("history") or [{}])[-1].get("volume_kg")},
                "retail": {"source": "aT 일별 도·소매가(KAMIS 조사) · 대구 소매 평균, 상품", "price": r["retail_price"],
                           "unit": r["retail_unit"], "week_change_pct": r["retail_change_pct"],
                           "base_price": r["retail_base_price"], "base_unit": r["retail_base_unit"], "base_how": r["retail_base_how"]}}
    return _safe(analysis.item_trend, name)


@_remember
def forecast_item_price(item: str) -> dict:
    """재료 하나의 다음 7일 도매가 방향(오를/내릴/비슷)과 예상 범위, 요인별 이유를 돌려준다.
    요인: 최근 시세 흐름, 반입량, 대구 날씨, 다가오는 공휴일, 대구 행사.

    Args:
        item: 재료 이름 (예: 양파, 대파, 양배추, 청양고추, 당근, 깻잎)
    """
    name = _item(item)
    ready = next((r.get("forecast") for r in _overview_rows() or [] if r["item"] == name and r.get("forecast")), None)
    return ready or _safe(analysis.forecast_item, name)


EXTRA_ALIASES = {"돼지고기": "돼지고기 앞다리", "앞다리": "돼지고기 앞다리", "삼겹살": "돼지고기 삼겹살",
                 "닭": "닭고기", "달걀": "계란",
                 "등심": "한우 등심", "소고기등심": "한우 등심", "양지": "한우 양지", "국거리": "한우 양지",
                 "갈비살": "수입 소고기 갈비살", "목심": "돼지고기 목심", "수입삼겹살": "수입 돼지고기 삼겹살", "수입돼지고기": "수입 돼지고기 삼겹살"}


@_remember
def get_meat_seafood_prices(item: str = "") -> dict:
    """육류 · 수산물(한우 등심 · 양지, 수입 소고기 갈비살, 돼지고기 앞다리 · 삼겹살, 닭고기, 계란,
    고등어, 갈치, 명태, 굴, 홍합, 새우, 새우젓, 멸치액젓)의 대구 가격과
    1주 · 4주 전 대비 변화, 다음 7일 예측(forecast: 한 달 평균과의 차이 · 명절 · 행사).
    경매 자료(반입량)가 없어 농산물보다 이유가 적은 추정이다.
    육류 가격은 대구 소매 평균(사장님이 실제로 사는 값)이다. 한우 · 돼지는 grade_table 에 협신식품(대구) 등급별 경락가가 참고로 온다.
    price_basis 가 '소매'면 대구 소매 평균, '중도매'면 대구 북부도매시장 중도매가.

    Args:
        item: 품목 하나만 볼 때 이름 (예: 삼겹살, 고등어). 전체를 볼 때는 빈 문자열.
    """
    name = (item or "").strip()
    if not name:
        # 날짜별 기록 · 예측 이유는 빼고 보냄 (19개 품목 × 4주면 길어서 답이 느려짐, 이유는 품목 하나로 다시 물어봄)
        def slim(r):
            f = r.get("forecast") or {}
            out = {k: v for k, v in r.items() if k not in ("history", "foodspring_url", "forecast", "grade_table")}
            out["forecast"] = {k: f.get(k) for k in ("direction", "expected_change_pct", "expected_price_range")}
            return out
        return _safe(lambda: {"rows": [slim(r) for r in analysis.extra_overview()]})
    return _safe(analysis.extra_trend, EXTRA_ALIASES.get(name.replace(" ", ""), name))


@_remember
def get_weather_summary(days: int = 7) -> dict:
    """대구(관측소 143) 최근 날씨 요약: 강수량, 비 온 날, 최저·최고 기온.

    Args:
        days: 며칠 치를 볼지 (1~21, 기본 7)
    """
    return _safe(analysis.weather_summary, max(1, min(21, days)))


@_remember
def get_daegu_events(days_ahead: int = 14) -> dict:
    """오늘부터 days_ahead일 안에 열리는 대구 행사·축제 목록 (한국관광공사).

    Args:
        days_ahead: 며칠 앞까지 볼지 (기본 14)
    """
    return _safe(lambda: {"events": daegu_events(days_ahead)})


@_remember
def get_upcoming_holidays(days_ahead: int = 30) -> dict:
    """오늘부터 days_ahead일 안의 공휴일 (한국천문연구원 특일 정보).

    Args:
        days_ahead: 며칠 앞까지 볼지 (기본 30)
    """
    return _safe(lambda: {"holidays": holidays(days_ahead)})


@_remember
def recommend_buy_now() -> dict:
    """지금 사면 이득인 재료를 나눠서 돌려준다.
    buy_now_before_rise: 다음 7일 오를 가능성이 있어 미리 사면 좋은 재료,
    cheap_now: 지난주보다 많이 내려 지금 싼 재료, wait: 내릴 가능성이 있어 기다리면 좋은 재료,
    as_usual: 평소대로 사면 되는 재료. 각 재료에 식봄 검색 링크(foodspring_url)가 붙어 있다."""
    return _safe(analysis.buy_now_recommendations, _overview_rows())


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


@_remember
def forecast_store_demand() -> dict:
    """우리 가게 판매 기록으로 내일 메뉴별 예상 그릇 수(범위 포함)와
    다음 입고일 전까지 모자란 재료의 발주량 · 판단(지금 사기 · 나눠 사기)을 돌려준다.
    시연 가게는 가상 판매 기록 1년으로 학습한 모델(learned_model = true), 그 밖은 규칙.
    menus 와 orders 에 있는 숫자 · 재료만 그대로 말한다."""
    def run():
        r = _cached("demand") or demand.forecast()   # 서버의 '내일 준비' 보관값 (시세 예측 반영) → 없으면 계산
        if r.get("error"):
            return r
        reason = {}
        for m in r["menus"]:   # 가장 영향이 큰 이유 한 줄
            name, v = max(m["factors"].items(), key=lambda kv: abs(kv[1]))
            reason[m["menu"]] = ("평소와 비슷" if abs(v) < 0.02 else
                                 f"{name} 영향 {v * 100:+.0f}%")
        return {
            "store": "우리 가게",
            "target_date": f"{r['target_date']}({r['target_weekday']})", "last_sales_date": r["last_sales_date"],
            "next_delivery_date": r["next_delivery_date"], "total_bowls": r["total_predicted"],
            "menus": [{"menu": m["menu"], "bowls": m["predicted"], "range": f"{m['range'][0]}~{m['range'][1]}",
                       "reason": reason[m["menu"]]} for m in r["menus"]],
            "orders": [{"item": i["item"], "order": f"{i['order_qty']:g}{i['unit']}", "decision": i["decision"],
                        "why": i["reason"]} for i in r["items"] if i["order_qty"] > 0][:5],
            "enough_stock": [i["item"] for i in r["items"] if i["order_qty"] <= 0],
            "method": r["method"], "learned_model": bool(r.get("model")),
        }
    return _safe(run)


@_remember
def get_store_cost_ratio() -> dict:
    """우리 가게 메뉴별 원가율. 가게가 영수증으로 실제 산 가격(최근 영수증 단가) 기준. 기준은 원가율 40%.
    menus 마다 cost_ratio_pct(원가율 %), next_ratio_pct(다음 주 예상 원가율, 야채 시세 예측 반영),
    margin(재료비 뺀 남는 돈), verdict, high(지금 또는 다음 주 40% 이상), top_items(비싼 재료),
    tips(규칙으로 계산한 제안 문장), 그리고 high 일 때 마진 지키는 방법 3가지:
    price_up(가격 조정: 제안 판매가 · 올릴 금액 · 올린 뒤 원가율), swap(대체 재료: 바꿀 재료 · 1인분 아끼는 돈 · 바꾼 뒤 원가율, 없으면 null),
    push_menu(메뉴 제안: 원가율이 괜찮고 한 그릇에 가장 많이 남는 우리 가게 메뉴)."""
    def run():
        r = _cached("costs") or receipts.cost_report(supabase_db.DEMO_STORE)   # 서버의 원가율 보관값 → 없으면 계산
        pick = lambda d, ks: {k: d[k] for k in ks} if d else None
        return {"store": "우리 가게", "target_ratio_pct": r["target_ratio_pct"], "menus": [{
            "menu": m["menu"], "price": m["price"], "cost_per_serving": m["cost_per_serving"], "cost_ratio_pct": m["cost_ratio_pct"],
            "next_ratio_pct": m.get("next_ratio_pct"), "margin": m["margin"], "verdict": m["verdict"], "high": m.get("high"),
            "top_items": [t["item"] for t in m["top_items"]], "tips": m["tips"],
            "price_up": pick(m.get("price_up"), ("price", "raise", "new_ratio_pct", "new_margin")),
            "swap": pick(m.get("swap"), ("from", "to", "share_pct", "saving_per_serving", "new_ratio_pct")),
            "push_menu": pick(m.get("push_menu"), ("menu", "margin", "cost_ratio_pct")),
        } for m in r["menus"]]}
    return _safe(run)


@_remember
def judge_receipt_prices() -> dict:
    """가장 최근 영수증의 품목마다 싸게/비싸게 샀는지 판정한다 (우리 가게 평소 단가 · 대구 시세와 비교, 10% 안쪽은 비슷해요).
    lines 마다 item, unit_price(기준 단위당 산 값), usual_price(평소 단가), retail_price(대구 소매 평균, 야채만),
    verdict(비싸게 샀어요 / 시세가 올랐어요 / 싸게 샀어요 / 비슷해요), why, extra_paid(평소 값이면 덜 냈을 돈), saved(아낀 돈).
    summary 에 품목 수와 더 낸 돈 · 아낀 돈 합계."""
    def run():
        r = price_judge.judge(supabase_db.DEMO_STORE)
        if r.get("error"):
            return r
        return {"store": "우리 가게", "date": r["date"], "supplier": r["supplier"], "summary": r["summary"],
                "lines": [{k: x[k] for k in ("item", "unit", "unit_price", "usual_price", "retail_price", "verdict", "why",
                                             "extra_paid", "saved")} for x in r["lines"]]}
    return _safe(run)


# 담당 에이전트마다 쓰는 도구 (발표의 AI 파이프라인 v3 와 같음)
AGENT_TOOLS = {
    "시세": [list_supported_items, get_market_overview, get_item_price_trend, forecast_item_price, recommend_buy_now,
            get_meat_seafood_prices, get_weather_summary, get_daegu_events, get_upcoming_holidays],
    "원가": [get_store_cost_ratio, judge_receipt_prices, calc_menu_margin, list_standard_menus, forecast_item_price,
            get_item_price_trend],
    "내일준비": [forecast_store_demand, forecast_item_price, recommend_buy_now, get_weather_summary, get_upcoming_holidays],
}
# 도구를 부르는 동안 화면에 보여 줄 말
TOOL_STATUS = {
    "list_supported_items": "볼 수 있는 재료를 확인하는 중…", "get_market_overview": "전체 시세를 모으는 중…",
    "get_item_price_trend": "재료 시세를 확인하는 중…", "forecast_item_price": "다음 주 시세를 계산하는 중…",
    "recommend_buy_now": "지금 사면 좋은 재료를 고르는 중…", "get_meat_seafood_prices": "고기·생선 시세를 확인하는 중…",
    "get_weather_summary": "날씨를 확인하는 중…", "get_daegu_events": "대구 행사를 확인하는 중…",
    "get_upcoming_holidays": "공휴일을 확인하는 중…", "list_standard_menus": "메뉴 목록을 확인하는 중…",
    "calc_menu_margin": "원가를 계산하는 중…", "forecast_store_demand": "내일 판매량을 계산하는 중…",
    "get_store_cost_ratio": "우리 가게 원가율을 계산하는 중…", "judge_receipt_prices": "영수증 가격을 비교하는 중…",
}


def _announce(tools, on_status):
    """도구를 실행하기 직전에 on_status 로 알리는 껍데기 (이름 · 설명 · 인자는 그대로라 모델이 보는 도구는 같음)"""
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*a, **k):
            on_status(TOOL_STATUS.get(fn.__name__, "확인하는 중…"))
            return fn(*a, **k)
        return inner
    return [wrap(t) for t in tools] if on_status else tools


AGENT_NAMES = {"시세": "📈 시세", "원가": "💰 원가 · 마진", "내일준비": "📦 내일 준비"}
TOOLS = list(dict.fromkeys(t for ts in AGENT_TOOLS.values() for t in ts))   # 모든 도구 (확인용)


# ---------------------------------------------------------------
# 살피 성격 (brand/SKILL.md + 기획서 11-3 판단 원칙)
# ---------------------------------------------------------------

# 브랜드 규칙(brand/SKILL.md)에서 챗봇 답에 필요한 말투 · 금칙어만 (11/25: 파일 전체를 매번 보내 Groq 분당 한도를 빨리 씀.
# 실제 사이트는 서버가 켜질 때마다 GitHub 에서 받아 왔음). SKILL.md 의 톤 · 금칙어가 바뀌면 여기도 같이 고칠 것
BRAND_RULES = """살피 말투 (브랜드 규칙)
- 존댓말 "~해요"체, 한 문장 25자 안팎. 숫자에는 단위(kg, 원, %, 그릇). 경고 뒤에는 행동 제안 1개.
- 쓰지 않는 말: 무조건 · 100% · 확실히 · 보장(→ "~할 가능성이 높아요"), 최저가 보장 · 제일 싸요,
  손해 보셨어요 · 잘못 사셨어요(→ "다음엔 이렇게 하면 아낄 수 있어요"), 모델 · 피처 · 분위수 같은 전문 용어,
  대박 · ㅋㅋ · 이모지, 다른 판매처 비방, 출처 없는 통계."""


COMMON_PROMPT = """너는 '살피'다. 대구 외식업 사장님의 식자재 시세 · 원가 비서인 미어캣. 아무것도 팔지 않는다.

판단 원칙 (반드시 지킬 것)
0. 가격 · 원가율 · 판매량 · 발주량 같은 숫자가 들어가는 답은 반드시 알맞은 도구를 먼저 부르고 나서 답한다.
   지난 대화에 비슷한 숫자가 있어도 다시 부른다.
1. 숫자는 도구 결과만 인용한다. 도구에 없는 가격·비율을 지어내지 않는다.
2. 가격을 말할 때는 기준(도매/소매, kg당), 날짜, 출처를 짧게 붙인다.
3. 예측은 항상 범위와 함께 말한다. "확실하지 않아요" · "잘 모르겠어요"처럼 자신 없는 말로 시작하지 않는다.
   예측의 confidence 값이 '낮음'이면 답 끝에 "요즘 값이 크게 오르내려서 범위를 넓게 잡았어요"처럼 범위가 넓은 이유를 한 번만 붙인다.
4. 이유는 factors에서 영향이 큰 것 1~2개만 쉬운 말로 말한다.
5. 사지 않는 게 유리하면 "기다려 보세요"라고 말한다. 특정 판매처 구매를 권하지 않는다.
6. 도구가 error를 돌려주면 그 이유를 그대로 짧게 알리고 추측하지 않는다.
7. 사장님 화면에는 살피 하나만 보인다. "다른 담당이 알려드릴게요"처럼 다른 담당 이야기를 꺼내지 않는다.
   내 도구로 답할 수 있는 만큼만 답하고, 숫자는 지어내지 않는다.
8. 살피 소개 · 인사 · 잡담은 아래 '살피 소개'대로 짧게 직접 답한다.
   식당 · 식자재와 상관없는 질문이면 "저는 식자재 시세 · 메뉴 원가 · 내일 준비량을 도와드려요"와 물어볼 만한 질문 예시 1~2개를 안내한다.
9. 지난 대화를 이어서 이해한다. "그럼 김치찌개는?"처럼 짧게 물으면 바로 앞 질문과 같은 것을 그 대상으로 다시 묻는 것이다.

살피 소개 (물으면 이대로 답한다)
- 이름 뜻: "저는 시장의 원가율과 마진, 시장 시세를 살핀다는 뜻의 미어캣 살피예요. 궁금한 점이 있으시면 언제든 물어봐 주세요."
- 나이 3살, 키 약 35cm, 몸무게 약 0.7~1kg.
- 부모님 · 엄마를 물으면: 대구에 사는 여성, '살피맘'이 엄마예요.
- 고맙다는 인사에는: "감사합니다! 언제든지 원가·마진, 시세 계산이 필요하시면 알려드릴게요. 좋은 하루 보내세요."
- 안녕 같은 인사 · 가벼운 잡담에는 한두 문장으로 친근하게 받고, 필요하면 물어볼 만한 질문을 하나 권한다.

출력 형식
- 짧게. 전체 10줄 이내, 묶음마다 재료 3개까지, 재료당 한 줄. [무엇이] → [얼마나] → [그래서 어떻게].
- 첫 줄은 질문에 대한 답(무엇이 · 얼마나 · 왜)부터 말한다.
- 날짜·출처는 답 끝에 한 번만 (예: "11/2 대구 북부도매시장 kg당 도매가 기준").
- 예측 범위는 "-24% ~ 0%"처럼 부호를 붙여 작은 값부터 쓴다.
- 영어 낱말과 도구 결과의 항목 이름(confidence, factors 등)을 답에 쓰지 않는다. 쉬운 우리말로 바꿔 말한다.
- 금액은 "1,187원"처럼 숫자 뒤에 '원'을 쓴다. ₩ 기호는 쓰지 않는다.
- 강조는 **굵게** 정도만. 표·이모지·전문 용어(모델, 회귀, 피처 등) 쓰지 않는다.
- 링크 주소는 쓰지 않는다 (화면의 상품 카드에서 식봄으로 연결됨).
"""

AGENT_PROMPTS = {
    "시세": """너는 살피의 📈 시세 담당이다. 사장님의 "언제 살까"에 답한다.
A. "시세변동 추이" 질문 → get_market_overview 와 recommend_buy_now 를 부른다.
   많이 오른 재료·내린 재료를 각각 변화율 순서로 말하고, 마지막에 "지금 사기 좋은 야채"를 1~3개 추천한다.
B. "지금 사면 이득인 야채" 질문 → recommend_buy_now 를 부르고, 미리 사면 좋은 것·지금 싼 것·기다릴 것 순서로 말한다.
C. 재료 하나의 시세 · 다음 주 예측 → get_item_price_trend · forecast_item_price.
D. 지원하지 않는 재료를 물으면 list_supported_items 결과로 지금 볼 수 있는 재료를 안내한다.
F. 고기 · 계란 · 생선 · 오징어 · 젓갈 시세 질문 → get_meat_seafood_prices 를 부른다.
   가격 기준(price_basis: 소매 / 중도매)과 단위를 꼭 붙이고, 1주 전 대비 변화를 말한다.
   다음 7일 예측은 forecast 를 쓰되, 경매 자료(반입량)가 없어 농산물보다 이유가 적은 추정이라고 한 번 덧붙인다.
   가격은 소매가로 말하고, 경락가는 물어볼 때만 "도매 경매가(협신식품)"라고 구분해서 말한다 (예측 이유가 아님).
""",
    "원가": f"""너는 살피의 💰 원가 · 마진 담당이다. 사장님의 "이 메뉴로 얼마 남나, 어떻게 줄일까"에 답한다. 원가율 기준은 40%.
E. "우리 가게 원가율", "영수증 기준 원가", "원가율 올랐어?", 가격 조정 · 대체 재료 · 메뉴 질문 → get_store_cost_ratio 를 부른다.
   첫 줄에 "우리 가게 영수증 기준"이라고 밝히고, 메뉴마다 원가율 · 남는 돈 · 판단을 한 줄씩 말한다.
   메뉴 하나를 물으면 그 메뉴만 말한다. 도구 결과에 없는 메뉴(예: 비빔밥)면 다른 메뉴 숫자를 그 이름으로 바꿔 말하지 말고,
   "우리 가게 영수증 메뉴에는 비빔밥이 없어요"라고 말한 뒤 있는 메뉴를 알려 주고, 판매가를 알려 주면 일반 시세로 계산해 준다고 안내한다.
   다음 주 예상 원가율(next_ratio_pct)이 지금과 1%p 넘게 다르면 같이 말한다.
   high 인 메뉴는 "마진 지키는 방법 3가지"를 이 순서로 한 줄씩: ① 가격 조정(price_up) ② 대체 재료(swap, null 이면
   "지금은 바꿀 만한 재료가 없어요") ③ 메뉴 제안(push_menu). 숫자는 도구 값만. 고르는 건 사장님이라고 덧붙인다.
G. "비싸게 샀어?", "싸게 산 거야?", "영수증 단가 괜찮아?" → judge_receipt_prices 를 부른다.
   비싸게 산 품목부터 산 값 · 평소 값 · 더 낸 돈을, 그다음 싸게 산 품목을 말하고, 나머지는 "비슷해요 N개"로 묶는다.
   비싸게 산 품목이 있으면 "다음에는 화면의 더 싼 판매처를 확인해 보세요"를 덧붙인다.
B. "이 가격에 팔아도 남아?"처럼 메뉴나 판매가 없이 마진을 물으면 계산하지 말고 먼저 묻는다:
   "어떤 메뉴를 만드시는지, 한 그릇에 얼마에 파시는지 알려주세요." 그리고 바로 계산할 수 있는 메뉴로
   {", ".join(menu_cost.STANDARD_RECIPES)} 을(를) 예시로 보여 준다 (이 목록에 없는 메뉴를 예시로 들지 않는다).
   목록에 없는 메뉴도 1인분 재료와 양을 알려 주면 계산할 수 있다고 덧붙인다.
   메뉴와 판매가를 들으면 calc_menu_margin 을 부른다. need_ingredients 가 오면 재료와 양을 물어본다.
   답에는 재료비, 원가율, 재료비 뺀 남는 돈, 가장 비싼 재료 1~2개, 시세가 오르는 재료가 있으면 그 영향을 말한다.
   참고 단가(가정값)를 쓴 재료가 있으면 "영수증 값을 알려 주시면 더 정확해져요"를 덧붙인다.
   재료 양을 지어내지 않는다. 사장님이 말한 양이나 표준 레시피만 쓴다.
   일반 메뉴 계산(calc_menu_margin, 시장 시세 기준)과 우리 가게 영수증 기준(get_store_cost_ratio)을 섞지 않는다.
""",
    "내일준비": """너는 살피의 📦 내일 준비 담당이다. 사장님의 "내일 무엇을 얼마나 준비할까"에 답한다.
D. "내일 얼마나 준비할까?", 판매량 · 몇 그릇 · 발주량 · 재고 질문 → forecast_store_demand 를 부른다.
   첫 줄에 "우리 가게 판매 기록 기준"이라고 밝힌다.
   메뉴별 예상 그릇 수를 범위와 함께 말하고(예: 김치찌개 101그릇, 96~106), 영향이 큰 이유 1개를 쉬운 말로 붙인다.
   그다음 orders 의 앞에서 3개를 "재료 · 발주량 · 판단(지금 사기/나눠 사기)" 한 줄씩 그대로 말하고 ("나눠 사기"는 "조금만 사기"라고 말한다),
   (orders 에 없는 재료 · 숫자를 말하지 않는다. 메뉴는 menus 에 있는 것만 전부 말한다)
   다음 입고일(next_delivery_date)까지 기준이라고 덧붙인다.
   시세가 오를 재료(why 에 시세 오름)는 "넉넉히 사 두세요"를 덧붙인다.
   learned_model 이 true 면 마지막에 "시연 가게의 가상 판매 기록으로 배운 예측이에요"라고 한 번 밝힌다.
""",
}


def _system(kind):
    return f"{COMMON_PROMPT}\n{AGENT_PROMPTS[kind]}\n{BRAND_RULES}"


SYSTEM_PROMPTS = {k: _system(k) for k in AGENT_PROMPTS}


# ---------------------------------------------------------------
# 🧭 안내 에이전트: 질문 → 담당
# ---------------------------------------------------------------

# 화면 버튼 질문은 AI 없이 바로 (index.html 의 #quick 버튼과 같은 글)
BUTTON_ROUTES = {
    "야채값 시세변동 추이 말해줘.": ["시세"], "지금 사면 이득인 야채 알려줘": ["시세"],
    "이 가격에 팔아도 남아?": ["원가"], "우리 가게 원가율 알려줘": ["원가"], "내일 얼마나 준비할까?": ["내일준비"],
}
_BUTTON_KEY = lambda t: re.sub(r"[\s.?!~,]+", "", t)
_BUTTONS = {_BUTTON_KEY(b): b for b in BUTTON_ROUTES}


def button(text):
    """직접 친 버튼 질문("야채값 시세 변동 추이 말해줘")도 띄어쓰기 · 문장 부호를 빼고 같으면 버튼 글로 바꿈. 아니면 그대로."""
    return _BUTTONS.get(_BUTTON_KEY(text), text.strip())


# 가벼운 모델이 실패하거나 바쁠 때 쓰는 낱말 규칙
KEYWORDS = {
    "내일준비": r"내일|몇 ?그릇|판매량|발주|주문량|재고|준비",
    "원가": r"원가|마진|남아|남나|남는|판매가|가격을? ?올|메뉴|영수증|비싸게 샀|싸게 샀|대체|레시피|뭐가 문제"
            r"|찌개|볶음|비빔밥|덮밥|국밥|전골|국수|냉면|짜장|짬뽕|제육|떡볶이",   # 메뉴 이름 (11/25: "내 비빔밥 뭐가 문제야"가 시세로 감)
    "시세": r"시세|오를|내릴|살까|사면|도매|소매|예측|날씨|행사|공휴일|고기|생선|야채|과일|값",
}
ROUTER_MODEL = os.getenv("GEMINI_ROUTER_MODEL", "gemini-3.5-flash-lite")
ROUTER_PROMPT = """식당 사장님 질문을 맡을 담당을 고른다. 담당:
- 시세: 재료 시세 · 값이 오를지 내릴지 · 언제 살지 · 날씨 · 행사 · 공휴일
- 원가: 메뉴 원가율 · 마진 · 판매가 · 영수증으로 싸게/비싸게 샀는지 · 대체 재료 · 메뉴 제안
- 내일준비: 내일 몇 그릇 팔릴지 · 재료를 얼마나 주문할지 · 재고
여러 담당이 필요하면 순서대로 모두 (최대 3). 인사 · 잡담이면 시세.
"그럼 김치찌개는?"처럼 짧게 이어 물으면 바로 앞 질문과 같은 담당.
JSON 으로만: {"agents": ["시세" | "원가" | "내일준비", ...]}
질문: """
ORDER = ["시세", "원가", "내일준비"]
_ROUTER_POOL = ThreadPoolExecutor(4)


def _keyword_route(message):
    hits = [k for k, pat in KEYWORDS.items() if re.search(pat, message)]
    if "내일준비" in hits and "시세" in hits and not re.search(r"시세|오를|내릴|도매|소매", message):
        hits.remove("시세")   # "내일 고기 얼마나 준비" 처럼 시세 낱말이 덤으로 걸린 것
    if "원가" in hits and "시세" in hits and not re.search(r"시세|오를|내릴|도매|소매|살까|사면", message):
        hits.remove("시세")   # "제육 메뉴 값" 처럼
    if "원가" in hits and "내일준비" in hits and not re.search(r"원가|마진|남|판매가|영수증|가격", message):
        hits.remove("원가")   # "내일 김치찌개 몇 그릇" 처럼 메뉴 이름만 덤으로 걸린 것
    return sorted(hits, key=ORDER.index)[:2] or ["시세"]


def route(message, client=None, before=()):
    """→ (담당 목록, 어떻게 골랐나: 버튼 · 모델 · 낱말 · 이어서). before: 지난 대화 글 [질문, 답, 질문, 답, ...] (오래된 것부터)"""
    text = button(message)
    if text in BUTTON_ROUTES:
        return BUTTON_ROUTES[text], "버튼"
    hits = [k for k, pat in KEYWORDS.items() if re.search(pat, text)]
    if len(hits) == 1:   # 낱말로 담당이 하나로 정해지면 AI 를 부르지 않음 (1 ~ 1.7초 절약)
        return hits, "낱말"
    if len(hits) > 1 and len(_keyword_route(text)) == 1:   # "내일 김치찌개 몇 그릇"처럼 덤으로 걸린 낱말을 빼면 하나
        return _keyword_route(text), "낱말"
    if not hits and len(text) <= 20:   # "그럼 김치찌개는?" 같은 짧은 이어 묻기 → 바로 앞 질문의 담당 그대로 (11/25: 시세 담당으로 가서 엉뚱한 답)
        # 앞 질문에 낱말이 없으면("내 비빔밥 뭐가 문제야") 살피 답("원가율 21.5%")으로 판단
        turns = [t for t in zip(before[0::2], before[1::2]) if not quick.small_talk(t[0])]   # 소개 · 인사는 건너뜀
        for q, said in reversed(turns):
            if button(q) in BUTTON_ROUTES:
                return BUTTON_ROUTES[button(q)], "이어서"
            if any(re.search(pat, q) for pat in KEYWORDS.values()):
                return _keyword_route(q), "이어서"
            # 앞 질문에 낱말이 없으면 살피 답에서 낱말이 가장 많이 나온 담당 하나 (답에는 다른 담당 낱말도 덤으로 섞임)
            counts = {k: len(re.findall(pat, said)) for k, pat in KEYWORDS.items()}
            if max(counts.values()):
                return [max(ORDER, key=lambda k: counts[k])], "이어서"
    if client is not None and _COOL.get(ROUTER_MODEL, 0) < time.time():
        try:
            prev = "".join(f"앞 질문: {b[:200]}\n" for b in list(before[0::2])[-2:])
            # 3초 안에 답이 없으면 버리고 낱말 규칙으로 (11/25: 한도에 걸린 날 10초씩 기다림.
            # 제미나이는 10초보다 짧은 대기 시간 설정을 거부해서 서버가 직접 3초만 기다림)
            r = _ROUTER_POOL.submit(client.models.generate_content, model=ROUTER_MODEL,
                                    contents=ROUTER_PROMPT.replace("질문: ", prev + "질문: ") + text[:500],
                                    config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0)
                                    ).result(timeout=3)
            picked = [a for a in dict.fromkeys(json.loads(r.text).get("agents") or []) if a in AGENT_PROMPTS]
            if picked:
                return picked[:3], "모델"
        except Exception as e:   # 바쁘거나 이상한 답 → 낱말 규칙
            _cool(ROUTER_MODEL, e)
            print(f"[안내] 가벼운 모델 실패, 낱말 규칙: {type(e).__name__}", flush=True)
    return _keyword_route(text), "낱말"


# ---------------------------------------------------------------
# 담당 에이전트 대화
# ---------------------------------------------------------------

# 화면 버튼 질문: AI 없이 도구 값으로 바로 답 (chat/quick.py). 도구 값을 못 받으면 아래 미리 불러오기 + AI 한 번
QUICK = {
    "야채값 시세변동 추이 말해줘.": lambda: quick.trend(get_market_overview(), recommend_buy_now()),
    "지금 사면 이득인 야채 알려줘": lambda: quick.buy_now(recommend_buy_now()),
    "우리 가게 원가율 알려줘": lambda: quick.cost(get_store_cost_ratio()),
    "내일 얼마나 준비할까?": lambda: quick.demand(forecast_store_demand()),
    "이 가격에 팔아도 남아?": lambda: quick.ASK_MENU,
}
BUTTON_TOOLS = {
    "야채값 시세변동 추이 말해줘.": ["get_market_overview", "recommend_buy_now"],
    "지금 사면 이득인 야채 알려줘": ["recommend_buy_now"],
    "우리 가게 원가율 알려줘": ["get_store_cost_ratio"],
    "내일 얼마나 준비할까?": ["forecast_store_demand"],
}
# Groq 무료 한도는 모델마다 분당 8,000토큰 → 미리 붙이는 자료에서 답에 안 쓰는 칸(2주 기록 · 링크 · 등급표)은 빼고 줄임
DROP_KEYS = {"wholesale_history", "history", "foodspring_url", "grade_table", "source", "base_note", "items_list", "method"}


def _slim(v, depth=0):
    if isinstance(v, dict):
        return {k: _slim(x, depth + 1) for k, x in v.items() if k not in DROP_KEYS}
    if isinstance(v, list):
        return [_slim(x, depth + 1) for x in v[:8]]
    return v


PRE_NOTE = "\n\n[살피가 미리 불러온 도구 결과 — 숫자는 이 값만 인용한다. 더 필요한 것만 도구를 부른다]\n"


def _mentioned(text):
    """질문에 나온 재료 이름 (농산물 · 고기 · 생선, 긴 이름부터, 최대 2개)."""
    names = {**{n: n for n in ITEMS}, **{n: n for n in EXTRA_ITEMS}, **ITEM_ALIASES, **EXTRA_ALIASES}
    out, rest = [], text.replace(" ", "")
    for alias in sorted(names, key=len, reverse=True):
        a = alias.replace(" ", "")
        if a in rest and names[alias] not in out:
            out.append(names[alias])
            rest = rest.replace(a, "")
    return out[:2]


def _prefetch(kind, message, on_status=None):
    """질문을 보고 거의 꼭 필요한 도구를 미리 동시에 부름 → ({이름: 결과}, 버튼 질문인가). AI 왕복을 줄이는 곳."""
    text = message.strip()
    funcs = {f.__name__: f for f in AGENT_TOOLS[kind]}
    if text in BUTTON_TOOLS:
        calls, only = [(n, ()) for n in BUTTON_TOOLS[text] if n in funcs], True
    else:
        calls, only = [], False
        for name in _mentioned(text):
            if name in ITEMS:
                calls += [(n, (name,)) for n in ("get_item_price_trend", "forecast_item_price") if n in funcs]
            elif "get_meat_seafood_prices" in funcs:
                calls.append(("get_meat_seafood_prices", (name,)))
        # "제육은?"처럼 짧게 물어도 가게 원가표를 먼저 붙임 (11/25: 없으면 원가율 · 판매가를 지어냄)
        if kind == "원가" and (re.search(r"원가율|우리 가게|남아|마진", text) or not calls):
            calls.append(("get_store_cost_ratio", ()))
        if kind == "내일준비":
            calls.append(("forecast_store_demand", ()))
        if kind == "시세" and not calls and re.search(r"올랐|내렸|요즘|시세|추이|뭐가", text):
            calls.append(("get_market_overview", ()))
    if not calls:
        return {}, False
    if on_status:
        on_status(TOOL_STATUS.get(calls[0][0], "확인하는 중…"))
    with ThreadPoolExecutor(len(calls)) as pool:
        res = list(pool.map(lambda c: funcs[c[0]](*c[1]), calls))
    return {f"{n}({', '.join(a)})": _slim(_only_asked(r, text)) for (n, a), r in zip(calls, res)}, only


def _only_asked(r, text):
    """가게 원가표에서 질문에 나온 메뉴만 남김 ("제육은?" → 제육볶음). 메뉴가 안 나오면 전체 (11/25: 5개 전체가 매번 1,800자)."""
    menus = r.get("menus") if isinstance(r, dict) else None
    if not menus:
        return r
    asked = [m for m in menus if m["menu"] in text] or [m for m in menus if m["menu"][:2] in text]
    return {**r, "menus": asked} if asked else r


# Groq (무료 · 아주 빠름): CHAT_PROVIDER=groq 이고 GROQ_API_KEY 가 있으면 먼저 쓰고, 실패하면 제미나이로
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# 모델마다 무료 한도(분당 8,000토큰 · 하루 1,000번)가 따로라 여럿을 차례로 (11/25 한국어 · 도구 부르기 시험: 120b 가 가장 자연스러움)
GROQ_MODELS = [m.strip() for m in os.getenv("GROQ_MODELS", os.getenv("GROQ_MODEL", "openai/gpt-oss-120b") + ",qwen/qwen3.8-27b,openai/gpt-oss-20b").split(",") if m.strip()]


def _schema(fn):
    """파이썬 도구 → Groq(OpenAI 모양) 도구 설명. 설명 · 인자는 제미나이가 보는 것과 같은 독스트링에서."""
    doc = fn.__doc__ or ""
    props, req = {}, []
    for n, prm in inspect.signature(fn).parameters.items():
        m = re.search(rf"{n}: (.+)", doc)
        props[n] = {"type": {"int": "integer"}.get(getattr(prm.annotation, "__name__", ""), "string"),
                    "description": m[1].strip() if m else n}
        if prm.default is inspect.Parameter.empty:
            req.append(n)
    return {"type": "function", "function": {"name": fn.__name__, "description": doc.split("Args:")[0].strip()[:300],
                                              "parameters": {"type": "object", "properties": props, "required": req}}}


def _groq_on():
    return os.getenv("CHAT_PROVIDER", "gemini").strip() == "groq" and bool(os.getenv("GROQ_API_KEY", "").strip())


BRIEFING_PROMPT = ("오늘 아침 브리핑을 해 줘. 전체 시세에서 많이 오른 것과 내린 것, "
                   "그리고 가장 많이 오른 재료 하나의 다음 주 예측을 알려 줘.")


class SalpiAgent:
    """안내 → 담당 에이전트. 서버가 쓰는 모양(ask · last_tools · model)은 예전과 같음."""

    def __init__(self, api_key=None, model=None, history=None):
        """history: 지난 대화 [{"role": "user"|"bot", "text": ...}] — 화면이 보관했다가 보내 줌."""
        key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            raise ApiKeyMissing(".env 의 GEMINI_API_KEY 가 비어 있어요 (aistudio.google.com 에서 무료 발급)")
        # 응답이 45초 넘게 없으면 끊고 다음 모델로 (바쁜 모델에 오래 묶이지 않게)
        # 10초 넘게 답이 없으면 끊고 다음 모델로 · 같은 모델 재시도는 안 함 (붐빌 때 같은 모델을 또 기다리지 않게, 11/25)
        self.client = genai.Client(api_key=key, http_options=types.HttpOptions(
            timeout=10_000, retry_options=types.HttpRetryOptions(attempts=1)))
        self.models = [model] + [m for m in CHAT_MODELS if m != model] if model else list(CHAT_MODELS)
        self.model = self.models[0]
        self.history = [types.Content(role="user" if h.get("role") == "user" else "model",
                                      parts=[types.Part(text=str(h.get("text", ""))[:2000])])
                        for h in (history or [])[-12:] if h.get("text")]
        self.last_tools, self.last_route = [], []

    def _groq(self, kind, message, only_pre, on_status):
        """Groq 모델을 차례로 (한도에 걸린 모델은 Groq 이 알려 준 시간만큼 건너뜀) → (답, 부른 도구, 모델, 도구 결과)."""
        last = None
        wait = min((_COOL.get("groq:" + m, 0) for m in GROQ_MODELS), default=0) - time.time()
        if 0 < wait <= 4 and all(_COOL.get("groq:" + m, 0) > time.time() for m in GROQ_MODELS):
            time.sleep(wait)   # 몇 초만 기다리면 풀리면 기다림 (제미나이로 넘어가면 10초 넘게 걸릴 때가 많음)
        for model in [m for m in dict.fromkeys(GROQ_MODELS) if _COOL.get("groq:" + m, 0) < time.time()]:
            try:
                return self._groq_one(model, kind, message, only_pre, on_status)
            except requests.HTTPError as e:
                r = e.response
                if r is not None and r.status_code == 429:
                    _COOL["groq:" + model] = time.time() + min(float(r.headers.get("retry-after") or 20), 600)
                last = e
            except requests.RequestException as e:
                _COOL["groq:" + model] = time.time() + (5 if "빈 답" in str(e) else 60)
                last = e
        raise last or RuntimeError("Groq 모델이 모두 쉬는 중이에요")

    def _groq_one(self, model, kind, message, only_pre, on_status):
        """Groq 모델 하나로 담당 하나. 도구는 한 번에 여러 개를 동시에 실행."""
        funcs = {f.__name__: f for f in AGENT_TOOLS[kind]}
        msgs = [{"role": "system", "content": SYSTEM_PROMPTS[kind]}]
        msgs += [{"role": "user" if h.role == "user" else "assistant", "content": h.parts[0].text} for h in self.history]
        msgs.append({"role": "user", "content": message})
        used, outs = [], []
        for _ in range(4):
            body = {"model": model, "messages": msgs, "temperature": 0.3, "max_tokens": 900,
                    # 생각하는 모델(gpt-oss · qwen3)은 생각을 짧게 → 빠르고, 생각에 글자를 다 써서 답이 비는 일이 없게 (11/25)
                    "reasoning_effort": "none" if "qwen" in model else "low"}
            if not only_pre:
                body["tools"] = [_schema(f) for f in funcs.values()]
            r = requests.post(GROQ_URL, json=body, timeout=15,
                              headers={"Authorization": f"Bearer {os.getenv('GROQ_API_KEY', '').strip()}"})
            r.raise_for_status()
            m = r.json()["choices"][0]["message"]
            calls = m.get("tool_calls") or []
            if not calls:
                if not (m.get("content") or "").strip():
                    raise requests.RequestException("빈 답")   # 다음 Groq 모델로
                return m["content"].strip(), used, f"groq:{model}", outs
            msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})

            def run(c):
                f = funcs.get(c["function"]["name"])
                if on_status:
                    on_status(TOOL_STATUS.get(c["function"]["name"], "확인하는 중…"))
                try:
                    return f(**json.loads(c["function"].get("arguments") or "{}")) if f else {"error": "없는 도구예요"}
                except (TypeError, ValueError) as e:
                    return {"error": f"도구 인자가 이상해요: {e}"}
            with ThreadPoolExecutor(len(calls)) as pool:
                res = list(pool.map(run, calls))
            for c, out in zip(calls, res):
                used.append(c["function"]["name"])
                outs.append(out)
                msgs.append({"role": "tool", "tool_call_id": c["id"],
                             "content": json.dumps(_slim(out), ensure_ascii=False, default=str, separators=(",", ":"))[:3000]})
        raise RuntimeError("Groq 도구 부르기가 너무 길어졌어요")

    def _ask_one(self, kind, message, on_text=None, on_status=None):
        """담당 하나에게 묻기 → (답, 부른 도구, 모델, 도구 결과, 걸린 ms). 무료 API가 바쁘면(503 · 504 · 429) 다음 모델로 갈아탐.
        on_text 가 있으면 답이 써지는 대로 조각조각 넘겨 줌 (화면이 글자를 바로 보여 주도록).
        먼저 거의 꼭 필요한 도구를 미리 불러 질문에 붙임 → AI 왕복이 줄어듦 (11/25 속도)."""
        last_error, started = None, time.time()
        pre, only = _prefetch(kind, message, on_status)
        if pre:
            message = message + PRE_NOTE + json.dumps(pre, ensure_ascii=False, default=str, separators=(",", ":"))[:3000]
        pre_names, pre_outs = [k.split("(")[0] for k in pre], list(pre.values())
        if _groq_on():
            try:
                text, tools, model, outputs = self._groq(kind, message, only, on_status)
                if on_text:
                    on_text(text)
                return text, pre_names + tools, model, pre_outs + outputs, round((time.time() - started) * 1000)
            except Exception as e:   # Groq 한도 · 장애 → 제미나이로
                print(f"[Groq] 실패, 제미나이로: {type(e).__name__}: {str(e)[:120]}", flush=True)
        for model in _usable(self.models):
            chat = self.client.chats.create(
                model=model, history=list(self.history) or None,
                config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPTS[kind],
                                                   tools=None if only else _announce(AGENT_TOOLS[kind], on_status),
                                                   temperature=0.3))
            sent = []
            try:
                for chunk in chat.send_message_stream(message):
                    if chunk.text:
                        sent.append(chunk.text)
                        if on_text:
                            on_text(chunk.text)
                text = "".join(sent) or "답을 만들지 못했어요. 다시 물어봐 주세요."
                hist = chat.get_history(curated=False)
                tools = [p.function_call.name for c in hist for p in (c.parts or []) if getattr(p, "function_call", None)]
                outputs = [p.function_response.response for c in hist for p in (c.parts or [])
                           if getattr(p, "function_response", None)]   # 숫자 검사용 (도구가 돌려준 값)
                return text, pre_names + tools, model, pre_outs + outputs, round((time.time() - started) * 1000)
            except errors.APIError as e:
                _cool(model, e)
                if sent and on_text:
                    raise      # 이미 화면에 글자가 나간 뒤라 다른 모델로 다시 쓰면 글이 겹침
                if 400 <= e.code < 500 and e.code not in (404, 429):
                    raise      # 요청 자체가 잘못된 경우는 갈아타도 같음
                last_error = e
            except Exception as e:  # 시간 초과·연결 끊김
                _cool(model, e)
                if sent and on_text:
                    raise
                last_error = e
        raise last_error

    def ask(self, message: str, on_text=None, on_status=None) -> str:
        """on_text: 답 조각을 받는 함수. 담당이 하나일 때만 글자가 흘러가고, 섞인 질문은 완성된 뒤 한 번에 옴."""
        t0 = time.time()
        message = text = button(message)   # 직접 친 버튼 질문도 버튼 답으로
        if text in QUICK:   # 화면 버튼 질문: AI 없이 도구 값으로 바로 (보통 1초 안)
            try:
                reply = QUICK[text]()
            except Exception as e:
                reply = None
                print(f"[버튼 답] 실패, AI 로: {type(e).__name__}", flush=True)
            if reply:
                if on_text:
                    on_text(reply)
                kinds = BUTTON_ROUTES.get(text, ["시세"])
                self.model, self.last_route = "버튼 답(AI 없음)", kinds
                self.last_tools = (["안내:버튼"] + [f"담당:{k}" for k in kinds] + BUTTON_TOOLS.get(text, [])
                                   + [f"시간:바로 {round((time.time() - t0) * 1000)}ms"])
                return reply
        talk = None if any(re.search(p, text) for p in KEYWORDS.values()) else quick.small_talk(text)
        if talk:   # 살피 소개 · 인사: AI 없이 바로
            if on_text:
                on_text(talk)
            self.model, self.last_route, self.last_tools = "소개 답(AI 없음)", [], ["안내:소개"]
            return talk
        kinds, how = route(message, self.client, [h.parts[0].text for h in self.history])
        route_ms = round((time.time() - t0) * 1000)
        self.last_route = kinds
        if len(kinds) == 1:
            jobs = [(kinds[0], message, on_text, on_status)]
        else:   # 섞인 질문: 담당마다 자기 몫만 답하게 하고 동시에 부름 (차례로 부르면 두 배 걸림)
            jobs = [(k, f"{message}\n\n(이 질문은 여러 담당이 나눠 답한다. 너는 {AGENT_NAMES[k]} 담당 부분만 답하고 다른 부분은 말하지 마라)", None, on_status)
                    for k in kinds]
        with ThreadPoolExecutor(len(jobs)) as pool:
            results = list(pool.map(lambda j: self._ask_one(*j), jobs))
        self.model = results[0][2]
        if len(results) == 1:
            reply = results[0][0]
        else:
            reply = "\n\n".join(f"**{AGENT_NAMES[k]}**\n{r[0]}" for k, r in zip(kinds, results))
        # chat_logs.tools 에 길 · 도구 · 단계별 시간 · 숫자 검사
        # 예: 안내:모델 · 담당:원가 · (도구들) · 시간:안내 420ms · 시간:원가 9800ms · 숫자:8개 모두 도구값
        self.last_tools = ([f"안내:{how}"] + [f"담당:{k}" for k in kinds] + [t for r in results for t in r[1]]
                           + [f"시간:안내 {route_ms}ms"] + [f"시간:{k} {r[4]}ms" for k, r in zip(kinds, results)]
                           + [number_check.label(reply, [o for r in results for o in r[3]], message)])
        return reply

    def morning_briefing(self) -> str:
        text, tools, self.model, outputs, ms = self._ask_one("시세", BRIEFING_PROMPT)
        self.last_route = ["시세"]
        self.last_tools = ["안내:브리핑", "담당:시세"] + tools + [f"시간:시세 {ms}ms", number_check.label(text, outputs)]
        return text


if __name__ == "__main__":
    agent = SalpiAgent()
    print("살피: 사장님, 궁금한 재료를 물어보세요. (끝내려면 엔터만)")
    while True:
        q = input("사장님: ").strip()
        if not q:
            break
        a = agent.ask(q)
        print(f"[안내 → {', '.join(agent.last_route)}]")
        print("살피:", a)
