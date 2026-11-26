"""살피 웹 서버: 시세 대시보드 화면 + 데이터 API + 살피 AI 채팅.

실행: python server.py → http://localhost:8000
"""

import os
import base64
import hashlib
import json
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
import time
from contextlib import asynccontextmanager
from pathlib import Path

from datetime import date

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from price import analysis
from account import auth
from chat import chat_log
from price import cheaper as cheaper_sellers
from demand import demand
from price import forecast_log
from price import forecast_model
from price import seller_links
from sources import foodspring
from account import app_push
from account import trial
from account import store_costs
from account import kakao_alert
from sources import mart_price
from store import menus
from store import sales
from store import cost_alert
from price import price_judge
from account import subscription
from store import inventory
from store import receipts
from sources import supabase_db
from chat import agent as chat_agent
from chat.agent import BUTTON_ROUTES, SalpiAgent, button
from sources.data_sources import ITEMS, ApiError, ApiKeyMissing, event_detail, foodspring_url, holidays, month_events, weather_forecast

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"         # 데스크톱 화면
MOBILE = ROOT / "mobile"   # 모바일 앱 화면 (MVVM)



@asynccontextmanager
async def lifespan(_app):
    """서버가 켜지면 뒤에서 시세를 미리 받아 둠 (첫 화면이 빨리 뜨게)."""
    def warm():
        try:
            shared("overview", _overview)
            _daily("forecast")
        except Exception:
            pass   # 키가 없거나 API 장애면 화면에서 안내
        for name in ("demand", "costs"):   # 챗봇 버튼 · 도구가 바로 답하도록 내일 준비 · 원가율도 미리 (11/25 속도)
            try:
                chat_agent.CACHED[name]()
            except Exception:
                pass
    threading.Thread(target=warm, daemon=True).start()
    yield


app = FastAPI(title="살피", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB), name="static")
app.mount("/mobile", StaticFiles(directory=MOBILE), name="mobile")   # 모바일 화면 파일 (주소는 /m/)
app.mount("/receipts_demo", StaticFiles(directory=ROOT / "store" / "receipts_demo"), name="receipts_demo")   # 시연용 가상 영수증

# ---------------------------------------------------------------
# 계산 결과 1시간 보관 (같은 화면을 여러 명이 열어도 다시 계산하지 않음)
# ---------------------------------------------------------------
_memo, _memo_lock, _key_locks = {}, threading.Lock(), {}


def memo(key, fn, ttl=3600):
    with _memo_lock:
        lock = _key_locks.setdefault(key, threading.Lock())
    with lock:   # 같은 계산을 여러 요청이 동시에 시작하지 않게 (공공데이터포털 429 방지) — 나중 요청은 결과를 기다림
        hit = _memo.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        value = fn()
        _memo[key] = (time.time(), value)
        return value


# ---------------------------------------------------------------
# 서버가 새로 켜져도 빠르게: 계산 결과를 Supabase 보관함(models/cache/)에도 둠
# Vercel 은 한동안 요청이 없으면 서버를 끄고, 다시 켜면 메모리가 비어 첫 화면이 공공 API 를 처음부터 부름 (11/18 재 보니 46초)
# → 보관함의 마지막 결과를 바로 보여 주고(약 0.3초), ttl 이 지났으면 뒤에서 새로 계산해 바꿔 둠 (다음 요청부터 새 값)
# keep 시간보다 오래된 보관값은 쓰지 않고 그 자리에서 계산 (예: 며칠 꺼져 있던 뒤)
# ---------------------------------------------------------------
CACHE_BUCKET = "models"
_refreshing = set()


def _save_shared(key, ts, value):
    try:
        supabase_db.upload(CACHE_BUCKET, f"cache/{key}.json",
                           json.dumps({"saved_at": ts, "value": value}, ensure_ascii=False).encode("utf-8"), "application/json")
    except Exception as e:   # 보관 실패해도 화면은 그대로
        print(f"[빠른 보관] {key} 저장 실패: {e}", flush=True)


def _refresh(key, fn):
    with _memo_lock:
        if key in _refreshing:
            return
        _refreshing.add(key)

    def run():
        try:
            value = fn()
            ts = time.time()
            _memo[key] = (ts, value)
            _save_shared(key, ts, value)
        except Exception as e:
            print(f"[빠른 보관] {key} 새로 계산 실패: {e}", flush=True)
        finally:
            _refreshing.discard(key)
    threading.Thread(target=run, daemon=True).start()


def shared(key, fn, ttl=3600, keep=24 * 3600):
    """memo + 보관함. 메모리에 있으면 그대로, 없으면 보관함 → 그것도 없거나 너무 오래됐으면 계산."""
    hit = _memo.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    if not hit:
        try:
            raw = supabase_db.download(CACHE_BUCKET, f"cache/{key}.json")
            blob = json.loads(raw) if raw else None
        except Exception:
            blob = None
        if blob and time.time() - blob["saved_at"] < keep:
            _memo[key] = hit = (blob["saved_at"], blob["value"])
            if time.time() - hit[0] < ttl:
                return hit[1]
    if hit:   # 오래됐지만 보여 줄 수 있음 → 지금 값을 주고 뒤에서 새로
        _refresh(key, fn)
        return hit[1]

    def compute():
        value = fn()
        threading.Thread(target=_save_shared, args=(key, time.time(), value), daemon=True).start()
        return value
    return memo(key, compute, ttl)


def _peek_shared(key):
    """보관값이 있으면 꺼내기만 함 (메모리 → 보관함). 없으면 None — 계산은 하지 않음 (다른 계산이 기다리지 않게)."""
    hit = _memo.get(key)
    if hit:
        return hit[1]
    try:
        raw = supabase_db.download(CACHE_BUCKET, f"cache/{key}.json")
        blob = json.loads(raw) if raw else None
    except Exception:
        return None
    if not blob:
        return None
    _memo.setdefault(key, (blob["saved_at"], blob["value"]))
    return blob["value"]


# 우리 가게 자료(영수증 · 메뉴 · 판매 · 재고)로 계산한 보관값 — 자료가 바뀌면 _store_changed 가 메모리 · 보관함에서 같이 지움
STORE_KEYS = ("costs_report", "receipts_recent", "my_items", "receipts_all")


def _demand_key():
    return f"demand_{forecast_log.today().isoformat()}"   # 날이 바뀌면 '내일'이 바뀌므로 날짜를 이름에


def _overview():
    """첫 화면에 필요한 것 전부 (재료별 시세 · 날짜별 기록 · 예측) — 화면은 이 한 번으로 모든 대시보드를 그림."""
    rows = analysis.market_overview()
    for r in rows:
        d = analysis.item_detail(r["item"])
        r["history"], r["forecast"] = d["history"], d["forecast"]
    return rows


def _guard(fn):
    try:
        return fn()
    except (ApiKeyMissing, ApiError) as e:
        raise HTTPException(503, f"{e}. 잠시 뒤 새로고침해 주세요.")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


# 키 확인용: 값은 절대 보내지 않고 "넣었는지"만 알려 줌 (Vercel 환경 변수 확인)
KEY_NAMES = ["AT_SALE_API_KEY", "AT_PERDAY_API_KEY", "AT_REALTIME_API_KEY", "KMA_ASOS_API_KEY", "KASI_SPCDE_API_KEY",
             "KTO_TOUR_API_KEY", "KAMIS_CERT_KEY", "KAMIS_CERT_ID", "GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_SECRET_KEY",
             "KCA_PRICE_API_KEY", "KMA_VILAGE_API_KEY", "KMA_MID_API_KEY", "KOSIS_API_KEY", "MOIS_RESTAURANT_API_KEY",
             "KAKAO_REST_API_KEY", "KAKAO_CLIENT_SECRET", "VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY", "FCM_SERVICE_ACCOUNT",
             "TOSS_CLIENT_KEY", "TOSS_SECRET_KEY"]


# 설치형 앱(PWA): 앱 정보 · 백그라운드 작업 파일은 사이트 맨 위 주소에 있어야 앱 전체를 맡을 수 있음
# 모바일 앱 화면 (MVVM, mobile/) — 데스크톱 화면(/)과 파일을 따로 둬서 서로 건드리지 않음
@app.get("/m")
@app.get("/m/")
def mobile_app():
    return FileResponse(MOBILE / "index.html", headers={"Cache-Control": "no-cache"})


# 안드로이드 앱(android/, TWA)이 주소창 없이 열리려면 "이 사이트는 이 앱 것" 확인 파일이 필요
# ANDROID_SHA256 = 앱 서명 지문(SHA-256, 콜론 포함). 여러 개면 쉼표로 (디버그 · 출시 열쇠). 없으면 빈 목록 → 앱은 주소창이 보인 채로 열림
@app.get("/.well-known/assetlinks.json")
def assetlinks():
    prints = [x.strip().upper() for x in os.getenv("ANDROID_SHA256", "").split(",") if x.strip()]
    return [{"relation": ["delegate_permission/common.handle_all_urls"],
             "target": {"namespace": "android_app", "package_name": os.getenv("ANDROID_PACKAGE", "com.salpi.app"),
                        "sha256_cert_fingerprints": prints}}] if prints else []


@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(WEB / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    return FileResponse(WEB / "sw.js", media_type="text/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/api/health")
def health(fcm: int = 0):
    out = {"keys": {k: bool(os.getenv(k, "").strip()) for k in KEY_NAMES}}
    if fcm:   # /api/health?fcm=1 — 안드로이드 앱 알림 열쇠로 Google 인증이 실제로 되는지 (열쇠 값은 보내지 않음)
        try:
            app_push.fcm._access_token()
            out["fcm"] = {"ok": True, "project": app_push.fcm._account()["project_id"]}
        except Exception as e:
            out["fcm"] = {"ok": False, "error": str(e)[:200]}
    return out


@app.get("/api/overview")
def overview():
    out = _guard(lambda: {"items": shared("overview", _overview)})
    _daily("forecast")
    return out


@app.get("/api/item/{name}")
def item(name: str):
    if name not in ITEMS:
        raise HTTPException(404, f"'{name}'은(는) 아직 지원하지 않아요")
    return _guard(lambda: memo(f"item:{name}", lambda: analysis.item_detail(name)))


@app.get("/api/meat-seafood")
def meat_seafood():
    """육류 · 수산물 대구 가격과 1주 · 4주 변화 (aT 일별 도·소매가, 예측 없음)."""
    out = _guard(lambda: shared("meat_seafood", lambda: {"items": analysis.extra_overview()}))
    _daily("forecast")
    return out


@app.get("/api/products")
def products():
    """식봄 실제 상품 · 가격 (재료마다 4개). 살피 시세 정보는 화면에서 /api/overview 와 합침."""
    out = memo("products", lambda: {"items": foodspring.all_products(4)})
    _daily("shop")
    return out


# ---------------------------------------------------------------
# 예측 기록 · 채점 · 식봄 판매가 기록 (Supabase forecast_log · price_snapshots), 하루 한 번
# 그날 처음 대시보드를 계산할 때 뒤에서 저장 → 따로 예약 실행을 걸지 않아도 쌓임
# (아무도 안 들어온 날은 빠짐. 꼭 매일 남기려면 POST /api/jobs/daily 를 예약 실행으로 부르면 됨)
# ---------------------------------------------------------------
_daily_done, _daily_lock = {}, threading.Lock()


def _run_forecast_job():
    veg = memo("overview", _overview)
    extra = memo("meat_seafood", lambda: {"items": analysis.extra_overview()})["items"]
    return {"recorded": forecast_log.record(veg, extra), "scored": forecast_log.score(veg, extra)}


def _run_shop_job():
    return {"shop_rows": forecast_log.snapshot_shop(memo("products", lambda: {"items": foodspring.all_products(4)})["items"])}


def _daily(job):
    """job 을 오늘 아직 안 했으면 뒤에서 한 번 실행 (실패해도 화면에는 영향 없음, 다음 요청 때 다시)."""
    day = forecast_log.today()
    with _daily_lock:
        if _daily_done.get(job) == day:
            return
        _daily_done[job] = day

    def run():
        try:
            print(f"[하루 기록] {job}", (_run_forecast_job if job == "forecast" else _run_shop_job)(), flush=True)
        except Exception as e:   # Supabase 키가 없거나 표가 아직 없으면 오늘은 건너뜀
            with _daily_lock:
                _daily_done.pop(job, None)
            print(f"[하루 기록] {job} 실패: {e}", flush=True)
    threading.Thread(target=run, daemon=True).start()


@app.post("/api/jobs/daily")
def daily_jobs():
    """예약 실행용: 예측 저장 · 채점 · 식봄 판매가 저장을 바로 실행하고 결과 수를 돌려줌.
    새벽 학습(learner.py)이 끝난 뒤 불리므로, 새 모델을 바로 읽고 예측을 다시 계산한 뒤 저장."""
    forecast_model.reset()
    with _memo_lock:
        _memo.pop("overview", None)

    def run():
        # 새 모델로 첫 화면 시세를 다시 계산해 보관함에도 둠 → 아침에 처음 여는 사람도 기다리지 않음
        for key, fn in (("overview", _overview), ("meat_seafood", lambda: {"items": analysis.extra_overview()})):
            ts, value = time.time(), fn()
            _memo[key] = (ts, value)
            _save_shared(key, ts, value)
        return {**_run_forecast_job(), **_run_shop_job()}
    return _guard(run)


@app.get("/api/model")
def model_status(days: int = 14):
    """AI 예측 모델: 종류별 지금 모델(버전 · 지표 3개 · 화면 사용 여부)과 최근 매일 학습 기록 (AI 진단 · 실험 · 교체)."""
    def build():
        now = {k: {"version": m.blob["version"], "trained_at": m.blob["trained_at"], "features": m.features,
                   "metrics": m.blob["metrics"], "formula_metrics": m.blob["formula_metrics"], "test_period": m.blob["test_period"]}
               for k, m in forecast_model.models().items()}
        return {"on_screen": now, "history": forecast_model.history()[: max(1, min(days, 60)) * 2]}
    return _guard(lambda: memo(f"model:{days}", build, ttl=600))


@app.get("/api/forecast-score")
def forecast_score(weeks: int = 4):
    """최근 weeks주 실제 화면 예측의 채점 결과 (종류별 · 품목별 방향 적중 · 범위 적중 · 정반대)."""
    weeks = max(1, min(weeks, 26))
    return _guard(lambda: memo(f"forecast_score:{weeks}", lambda: forecast_log.scorecard(weeks), ttl=1800))


@app.get("/api/event/{content_id}")
def event(content_id: str):
    """행사 하나 자세히 (관광공사). 번호는 숫자만 받음."""
    if not content_id.isdigit():
        raise HTTPException(400, "행사 번호가 올바르지 않아요")
    return _guard(lambda: memo(f"event:{content_id}", lambda: event_detail(content_id), ttl=6 * 3600))


@app.get("/api/mart")
def mart():
    """대형마트 판매가 (한국소비자원 참가격, 음식 재료만). 2주마다 조사돼서 6시간 보관."""
    return _guard(lambda: shared("mart2", mart_price.mart_prices, ttl=6 * 3600, keep=3 * 24 * 3600))


@app.get("/api/buy-links")
def buy_links(item: str = ""):
    """사러 가기 판매처 6곳 주소: 재료가 있으면 상품 목록(검색 결과), 없으면 첫 화면.
    쿠팡 파트너스 키가 있으면 쿠팡은 제휴 주소 + ad_note(대가성 안내 문구), 없으면 ad_note = null. 1시간 보관."""
    item = item.strip()[:30]
    fs = foodspring_url(item) if item in ITEMS else None
    return memo(f"buy_links:{item}", lambda: seller_links.links(item or None, fs), ttl=3600)


@app.get("/api/cheaper")
def cheaper(item: str, paid: float | None = None):
    """더 싼 판매처: 산 값(최근 영수증 · 없으면 대구 소매 평균)보다 기준 단위당 싼 식봄 상품, 싼 순서.
    paid 를 주면 그 값과 비교 (예: /api/cheaper?item=양파&paid=2300). 10분 보관."""
    return _guard(lambda: memo(f"cheaper:{item}:{paid}",
                               lambda: cheaper_sellers.cheaper(item, paid, supabase_db.DEMO_STORE), ttl=600))


@app.get("/api/price-judge")
def price_judge_api(purchase_id: int | None = None):
    """싸게/비싸게 판정: 영수증 품목마다 산 값을 우리 가게 평소 단가 · 대구 시세와 비교 (없으면 가장 최근 영수증)."""
    try:
        return _guard(lambda: price_judge.judge(supabase_db.DEMO_STORE, purchase_id))
    except ValueError as e:
        raise HTTPException(404, str(e))


def _forecast_or_empty():
    """예보가 안 와도 지난 날씨 · 공휴일 · 행사는 보여 주도록 빈 목록으로."""
    try:
        return weather_forecast(7)
    except (ApiKeyMissing, ApiError):
        return []


@app.get("/api/context")
def context():
    return _guard(lambda: memo("context", lambda: {
        "weather": analysis.weather_summary(7), "weather_forecast": _forecast_or_empty(),
        "holidays": holidays(30), "events": month_events()}))


# ---------------------------------------------------------------
# 우리 가게 내일 준비: 판매 기록(Supabase)으로 메뉴별 그릇 수 · 재료 필요량 · 발주 추천
# 지금은 시연용 가게 한 곳 (로그인이 없어서)
# ---------------------------------------------------------------


def _price_outlook():
    """대시보드 시세 예측이 이미 계산돼 있으면(메모리 · 보관함) 그대로 씀 (없으면 demand 가 필요한 재료만 계산)."""
    rows = _peek_shared("overview")
    return {r["item"]: (r.get("forecast") or {}).get("expected_change_pct") for r in rows} if rows else None


def _forecasts():
    """원가율 계산용: 재료 → 시세 예측 (첫 화면 시세 보관값). 없으면 {} → 원가율이 재료마다 직접 계산."""
    rows = _peek_shared("overview") or []
    return {r["item"]: r.get("forecast") for r in rows if r.get("forecast")}


# 챗봇 도구가 화면과 같은 보관값을 씀 → 처음 부르는 도구도 다시 계산하지 않음 (11/25: 7 ~ 9초 → 보관값이면 1초 안)
chat_agent.CACHED.update({
    "overview": lambda: shared("overview", _overview),
    "demand": lambda: shared(_demand_key(), lambda: demand.forecast(price_outlook=_price_outlook()), ttl=600) if _price_outlook() else None,
    "costs": lambda: shared("costs_report", lambda: receipts.cost_report(supabase_db.DEMO_STORE, _forecasts()), 600),
})


def _sales_user(authorization, check=True):
    """판매율 분석: 로그인 표 → 계정 (다 썼으면 check=True 일 때 402). 표가 없거나 만료면 None = 횟수 없이 보여 줌
    (표 없이 부르는 모바일 시연 화면과 같게 · 로그인이 끝난 화면이 오류로 깨지지 않게)."""
    token = _bearer(authorization)
    if not token:
        return None
    try:
        return trial.check(token, "sales") if check else auth.user_of(token)
    except auth.AuthError as e:
        if e.status == 401:
            return None
        raise HTTPException(e.status, str(e))
    except (ApiKeyMissing, ApiError):
        return None


@app.get("/api/demand")
def demand_forecast(target: str | None = None, authorization: str | None = Header(None)):
    """내일 예상 판매 (판매율 분석). 로그인 표를 같이 보내고 무료 5회(판매 올린 날짜 수)를 다 썼으면 402.
    보는 것은 횟수를 세지 않음 (세는 곳은 PUT /api/sales). 표 없이 부르는 곳(모바일 시연 화면)은 지금처럼."""
    user = _sales_user(authorization)
    try:
        day = date.fromisoformat(target) if target else None
    except ValueError:
        raise HTTPException(400, "날짜는 2026-11-05 형식으로 보내 주세요")
    # 대시보드 시세가 아직 준비 전이면 기다리지 않고 시세 없이 계산 (1분 뒤 다시 계산할 때 시세 반영)
    outlook = _price_outlook()
    if day is None and outlook:   # 보통의 경우(내일 · 시세 있음): 보관함에도 둠 → 새로 켜진 서버도 바로 (9초 → 0.5초)
        out = _guard(lambda: shared(_demand_key(), lambda: demand.forecast(price_outlook=outlook), ttl=600))
    else:
        key = f"demand:{day}:{'price' if outlook else 'noprice'}"
        out = _guard(lambda: memo(key, lambda: demand.forecast(target=day, price_outlook=outlook or {}), ttl=600 if outlook else 60))
    return {**out, "trial": trial._state(user, "sales")} if user else out


class SalesIn(BaseModel):
    date: str | None = None
    items: list[dict] = []   # [{"menu_id": 3, "hall": 25, "delivery": 8}] — 빈칸(null)은 안 바꿈


@app.get("/api/sales")
def sales_day(date: str | None = None):
    """판매 기록 확인: 그날(기본 오늘) 메뉴별 홀 · 배달 그릇 수 · 합계 · 매출 · 마지막으로 넣은 날."""
    return _receipt_guard(lambda: sales.day(supabase_db.DEMO_STORE, date))


class HoursIn(BaseModel):
    open: str = ""
    close: str = ""


@app.put("/api/sales/hours")
def sales_hours(body: HoursIn):
    """영업시간 저장 (마감이 자정을 넘기면 새벽 판매도 전날 영업일로). → {open_time, close_time, today}"""
    return _receipt_guard(lambda: sales.set_hours(supabase_db.DEMO_STORE, body.open, body.close))


@app.put("/api/sales")
def sales_save(body: SalesIn, authorization: str | None = Header(None)):
    """판매 기록 입력 → 내일 준비 · 원가율 다시 계산. 로그인 표가 있으면 새 날짜를 올릴 때 판매율 분석 1회
    (같은 날짜를 고치면 안 셈, 무료 5회를 다 썼으면 새 날짜는 402)."""
    user = _sales_user(authorization)
    if user:
        st = trial._state(user, "sales")
        new = not _receipt_guard(lambda: sales.day(supabase_db.DEMO_STORE, body.date))["entered"]
        if new and not st["paid"] and st["used"] >= trial.FREE:
            raise HTTPException(402, trial.LOCKED_MSG)
    out = _receipt_guard(lambda: _store_changed(sales.save(supabase_db.DEMO_STORE, body.model_dump())))
    if user:
        out["trial"] = _auth(lambda: trial.count(user, "sales")) if out["new"] else trial._state(user, "sales")
    return out


# ---------------------------------------------------------------
# 영수증으로 원가율: 사진 읽기(Gemini) → 사장님 확인 · 수정 → 저장(Supabase) → 원가율 다시 계산
# 사진은 화면에서 줄여서(긴 쪽 1600px) base64 로 보냄 (Vercel 요청 크기 4.5MB 제한)
# ---------------------------------------------------------------
MAX_IMAGE = 4_000_000


def _image(b64, mime):
    if not b64:
        return None, None
    data = base64.b64decode(b64.split(",")[-1])
    if len(data) > MAX_IMAGE:
        raise HTTPException(413, "사진이 너무 커요. 다시 찍어 주세요.")
    if mime not in ("image/jpeg", "image/png", "image/webp"):
        raise HTTPException(400, "사진 파일(jpg · png)만 올릴 수 있어요")
    return data, mime


class ReceiptIn(BaseModel):
    image: str = ""
    mime: str = "image/jpeg"
    # 긴 영수증을 나눠 찍은 사진들 (위에서부터 차례로, 최대 receipts.MAX_PHOTOS 장). 'data:image/png;base64,…' 면 그 형식, 아니면 mime
    images: list[str] = []


def _photos(body):
    """image(한 장, 예전 화면) + images(여러 장) → [(bytes, mime)]."""
    raw = ([body.image] if body.image else []) + [x for x in body.images if x]
    if len(raw) > receipts.MAX_PHOTOS:
        raise HTTPException(400, f"사진은 한 번에 {receipts.MAX_PHOTOS}장까지 올릴 수 있어요")
    mime_of = lambda x: x[5:x.index(";")] if x.startswith("data:") and ";" in x[:40] else body.mime   # 'data:image/png;base64,…' → image/png
    return [_image(x, mime_of(x)) for x in raw]


class ReceiptSave(ReceiptIn):
    date: str | None = None
    supplier: str | None = None
    items: list[dict] = []


# ---------------------------------------------------------------
# 악용 막기: 접속한 곳(IP)마다 AI 를 쓰는 요청 횟수를 셈 (11/25, 배포된 사이트 — Groq · 제미나이 무료 한도가 바닥나면 사장님 챗봇 · 영수증이 멈춤)
# shortcut: 서버(Vercel 인스턴스)마다 메모리로 셈 → 여러 서버에 나뉘면 그만큼 더 허용됨. 악용이 실제로 보이면 Supabase 표로 옮길 것
# ---------------------------------------------------------------
_HITS, _HITS_LOCK = {}, threading.Lock()
LIMITS = {   # 종류: (1분에, 하루에)
    "chat": (8, 150), "receipt_anon": (3, 15), "receipt_user": (6, 60), "receipt_save": (6, 60),
}


def _client_ip(request):
    fwd = request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip") or ""
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


def _limit(request, kind):
    per_min, per_day = LIMITS[kind]
    now, key = time.time(), (kind, _client_ip(request))
    with _HITS_LOCK:
        q = [t for t in _HITS.get(key, []) if now - t < 86400]
        if sum(1 for t in q if now - t < 60) >= per_min or len(q) >= per_day:
            _HITS[key] = q
            raise HTTPException(429, "요청이 너무 많아요. 잠시 뒤 다시 해 주세요.")
        q.append(now)
        _HITS[key] = q
        if len(_HITS) > 20000:   # 메모리가 끝없이 늘지 않게 오래된 곳부터 정리
            for k in [k for k, v in _HITS.items() if not v or now - v[-1] > 86400][:10000]:
                _HITS.pop(k, None)


def _receipt_guard(fn):
    try:
        return _guard(fn)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/receipt/read")
def receipt_read(body: ReceiptIn, request: Request, authorization: str | None = Header(None)):
    photos = _photos(body)
    if not photos:
        raise HTTPException(400, "영수증 사진을 골라 주세요")
    token = _bearer(authorization)
    _limit(request, "receipt_user" if token else "receipt_anon")
    if not token:   # 로그인 표 없이 부르는 곳(모바일 시연 화면): 무료 횟수 대신 접속한 곳마다 하루 15번까지
        return _receipt_guard(lambda: receipts.read(photos))
    # 로그인한 사장님: 한 달 무료가 끝났으면 402, 읽기에 성공했을 때만 1회 셈 (첫 성공한 날부터 한 달 · 사진이 여러 장이어도 영수증 하나 = 1회)
    user = _auth(lambda: trial.check(token))
    result = _receipt_guard(lambda: receipts.read(photos))
    return {**result, "trial": _auth(lambda: trial.count(user))}


@app.get("/api/receipt/trial")
def receipt_trial(feature: str = "receipt", authorization: str | None = Header(None)):
    """무료 횟수: feature=receipt(영수증 분석, 기본) · sales(판매율 분석)."""
    if feature not in trial.FEATURES:
        raise HTTPException(400, "feature 는 receipt · sales 중 하나예요")
    return _auth(lambda: trial.status(_bearer(authorization), feature))


class FoundIn(BaseModel):
    purchase_id: int


@app.post("/api/receipt/trial/found")
def receipt_trial_found(body: FoundIn, authorization: str | None = Header(None)):
    """영수증을 저장한 뒤: 그 영수증의 '더 낸 돈'(구매가 점검)을 사장님 계정에 모아 둠."""
    if not _bearer(authorization):
        raise HTTPException(401, "로그인이 필요해요.")
    try:
        extra = (_guard(lambda: price_judge.judge(supabase_db.DEMO_STORE, body.purchase_id)).get("summary") or {}).get("extra_paid", 0)
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _auth(lambda: trial.add_found(_bearer(authorization), body.purchase_id, extra))


# ---------------------------------------------------------------
# 살피 플러스 구독 · 모의 결제 (account/subscription.py, 토스페이먼츠 테스트 결제 · 키 없으면 모의 승인)
# ---------------------------------------------------------------
class ConfirmIn(BaseModel):
    payment_key: str = ""
    order_id: str = ""
    amount: int | None = None


class CancelIn(BaseModel):
    undo: bool = False


@app.get("/api/subscribe")
def subscribe_status(authorization: str | None = Header(None)):
    """구독 상태: plan(free · plus) · 끝나는 날 · 해지 예약 · 최근 결제 · 결제 방식(toss 테스트 · mock)."""
    return _auth(lambda: subscription.status(_bearer(authorization)))


@app.post("/api/subscribe/checkout")
def subscribe_checkout(authorization: str | None = Header(None)):
    """결제창 열기 전: 주문 번호 · 금액(19,900원) · 결제창 열쇠(client key, 없으면 null = 모의 결제)."""
    return _auth(lambda: subscription.checkout(_bearer(authorization)))


@app.post("/api/subscribe/confirm")
def subscribe_confirm(body: ConfirmIn, authorization: str | None = Header(None)):
    """결제창에서 돌아온 paymentKey · orderId · amount 로 승인 → 30일 플러스. 모의 결제면 payment_key 없이 order_id · amount 만."""
    return _auth(lambda: subscription.confirm(_bearer(authorization), body.payment_key, body.order_id, body.amount))


@app.post("/api/subscribe/cancel")
def subscribe_cancel(body: CancelIn, authorization: str | None = Header(None)):
    """해지 예약 (지금 기간 끝까지는 플러스). undo=true 면 해지 취소."""
    return _auth(lambda: subscription.cancel(_bearer(authorization), body.undo))


@app.post("/api/receipt/save")
def receipt_save(body: ReceiptSave, request: Request):
    _limit(request, "receipt_save")
    photos = _photos(body)
    return _receipt_guard(lambda: _store_changed(receipts.save(supabase_db.DEMO_STORE, body.model_dump(), photos)))


@app.get("/api/costs")
def costs(authorization: str | None = Header(None)):
    """메뉴별 원가율 · 남는 돈 (판매율 분석) + 최근 영수증 목록.
    로그인 표를 보내고 판매율 분석 무료 5회를 다 썼으면 원가율 · 마진은 빼고 {locked: true, trial, receipts} 만 (영수증 목록은 그대로 보여 주게).
    보는 것은 횟수를 세지 않음 (세는 곳은 PUT /api/sales)."""
    data = _receipt_guard(_costs_data)
    user = _sales_user(authorization, check=False)
    if user:
        st = trial._state(user, "sales")
        if st["locked"]:
            return {"locked": True, "message": trial.LOCKED_MSG, "trial": st, "receipts": data["receipts"]}
    return data


def _costs_data():
    """원가율(보관 10분) + 최근 영수증(사진 주소가 1시간이라 보관값은 40분까지만). 둘 다 보관함에도 둠 → 새로 켜진 서버도 바로 (11초 → 0.5초).
    영수증 저장 · 고치기 · 지우기 · 메뉴 · 판매 · 재고를 바꾸면 _store_changed 가 비움."""
    with ThreadPoolExecutor(max_workers=2) as pool:   # 보관함 파일 하나 받는 데 0.3~0.8초 → 둘을 동시에
        f_report = pool.submit(shared, "costs_report", lambda: receipts.cost_report(supabase_db.DEMO_STORE, _forecasts()), 600)
        f_recent = pool.submit(shared, "receipts_recent", lambda: receipts.recent(supabase_db.DEMO_STORE), 600, 2400)
        return {**f_report.result(), "receipts": f_recent.result()}


def _store_changed(result):
    """가게 자료가 바뀌면 원가율 · 내일 준비 · 영수증 목록 · 내 메뉴 재료 보관값을 메모리와 보관함에서 지움 (다른 서버도 새로 계산)."""
    keys = [*STORE_KEYS, _demand_key()]
    for k in [k for k in _memo if k in keys or k.startswith("demand")]:
        _memo.pop(k, None)
    supabase_db.remove_files(CACHE_BUCKET, [f"cache/{k}.json" for k in keys])
    return result


@app.get("/api/receipt/{purchase_id}")
def receipt_detail(purchase_id: int):
    return _receipt_guard(lambda: receipts.detail(supabase_db.DEMO_STORE, purchase_id))


class ReceiptEdit(BaseModel):
    date: str | None = None
    supplier: str | None = None
    items: list[dict] = []


@app.put("/api/receipt/{purchase_id}")
def receipt_edit(purchase_id: int, body: ReceiptEdit):
    """저장한 영수증 고치기 (최근 영수증 → 수정하기 팝업)."""
    return _receipt_guard(lambda: _store_changed(receipts.edit(supabase_db.DEMO_STORE, purchase_id, body.model_dump())))


@app.get("/api/my-items")
def my_items():
    """우리 가게 메뉴에 들어가는 재료 (알림 '내 메뉴 재료만'). 메뉴가 자주 바뀌지 않아 10분 보관."""
    return _receipt_guard(lambda: shared("my_items", lambda: receipts.my_ingredients(supabase_db.DEMO_STORE), ttl=600))


class MenuIn(BaseModel):
    name: str = ""
    price: int | None = None
    recipe: list[dict] = []


def _menu_changed(result):
    """메뉴를 바꾸면 '내 메뉴 재료' 보관값을 비우고, 화면이 다시 그릴 원가율을 함께 돌려줌."""
    _store_changed(None)
    return {**result, **_costs_data()}


@app.get("/api/menus")
def menu_list():
    """메뉴 입력 창용: 재료 목록(최근 영수증 단가) · 메뉴(레시피 포함) · 자주 쓰는 메뉴 틀."""
    return _receipt_guard(lambda: menus.editor_data(supabase_db.DEMO_STORE))


@app.post("/api/menus")
def menu_add(body: MenuIn):
    return _receipt_guard(lambda: _menu_changed(menus.save(supabase_db.DEMO_STORE, None, body.model_dump())))


@app.put("/api/menus/{menu_id}")
def menu_edit(menu_id: int, body: MenuIn):
    return _receipt_guard(lambda: _menu_changed(menus.save(supabase_db.DEMO_STORE, menu_id, body.model_dump())))


class PriceIn(BaseModel):
    item_id: int
    price: int


@app.post("/api/menus/price")
def menu_item_price(body: PriceIn):
    """영수증 가격이 없는 재료에 가격 직접 넣기 (메뉴 고치기 창의 [가격 넣기])."""
    return _receipt_guard(lambda: _store_changed(menus.set_price(supabase_db.DEMO_STORE, body.item_id, body.price)))


@app.post("/api/menus/{menu_id}/stop")
def menu_stop(menu_id: int):
    """판매 중지 (메뉴를 지우면 판매 기록까지 지워져서 지우지 않음)."""
    return _receipt_guard(lambda: _menu_changed(menus.stop(supabase_db.DEMO_STORE, menu_id)))


class StockIn(BaseModel):
    items: list[dict] = []   # [{"item_id": 3, "on_hand": 4.5}] — 기준 단위(kg · 모 · 개 · L)


@app.get("/api/inventory")
def inventory_list():
    """재고 입력 창용: 메뉴 재료 + 재고 있는 재료의 남은 양 (영수증 저장 · 고치기 · 지우기 때 자동으로 바뀜)."""
    return _receipt_guard(lambda: inventory.listing(supabase_db.DEMO_STORE))


@app.put("/api/inventory")
def inventory_set(body: StockIn):
    """사장님이 고친 남은 양 저장 → 내일 준비(주문량) 다시 계산."""
    return _receipt_guard(lambda: _store_changed(inventory.set_qty(supabase_db.DEMO_STORE, body.items)))


class NewItemIn(BaseModel):
    name: str = ""
    unit: str = "kg"
    tab: str = "기타"


@app.post("/api/inventory/item")
def inventory_new_item(body: NewItemIn):
    """재고 창 검색에 없는 재료를 새로 만듦 → {item_id, item, unit, category} (남은 양은 [저장] 때 PUT 으로)."""
    return _receipt_guard(lambda: _store_changed(inventory.new_item(body.name, body.unit, body.tab)))


@app.delete("/api/inventory/{item_id}")
def inventory_remove(item_id: int):
    """직접 넣은 재료 빼기 (메뉴 재료는 400)."""
    return _receipt_guard(lambda: _store_changed(inventory.remove(supabase_db.DEMO_STORE, item_id)))


@app.get("/api/receipts")
def receipt_list():
    # shortcut: 1000장(Supabase 한 번에 주는 최대)까지, 넘으면 페이지 나눠 받기
    # 보관값 10분 (사진 주소가 1시간이라 보관함 값은 40분까지만) · 영수증 저장 · 고치기 · 지우기면 _store_changed 가 비움 (11/25: 매번 1.5 ~ 2.7초 → 보관값 0.1초)
    return _receipt_guard(lambda: shared("receipts_all", lambda: {"receipts": receipts.recent(supabase_db.DEMO_STORE, limit=1000)}, 600, 2400))


@app.delete("/api/receipt/{purchase_id}")
def receipt_delete(purchase_id: int):
    return _receipt_guard(lambda: _store_changed(receipts.remove(supabase_db.DEMO_STORE, purchase_id)))


# ---------------------------------------------------------------
# 사장님 계정: 회원가입 · 로그인 · 로그인 유지 · 로그아웃 · 탈퇴 (auth.py, Supabase 로그인)
# 로그인 표는 화면이 보관하고 'Authorization: Bearer <표>' 로 보냄
# ---------------------------------------------------------------


class SignupIn(BaseModel):
    name: str = ""
    phone: str = ""
    login_id: str = ""
    password: str = ""
    store: str = ""
    district: str = ""     # 대구 구 · 군
    place: str = ""        # 나머지 주소 (선택)
    alarm: bool = False    # 알림 받기 (선택 약관)
    terms_ok: bool = False


class LoginIn(BaseModel):
    id: str = ""           # 아이디 또는 휴대폰 번호
    password: str = ""


class RefreshIn(BaseModel):
    refresh_token: str = ""


class StoreSetupIn(BaseModel):
    name: str = ""
    store: str = ""
    district: str = ""
    place: str = ""
    alarm: bool = False
    terms_ok: bool = False


def _bearer(authorization):
    return (authorization or "").removeprefix("Bearer ").strip()


def _auth(fn):
    try:
        return fn()
    except auth.AuthError as e:
        raise HTTPException(e.status, str(e))
    except (ApiKeyMissing, ApiError) as e:
        raise HTTPException(503, f"{e}. 잠시 뒤 다시 해 주세요.")


@app.post("/api/auth/signup")
def auth_signup(body: SignupIn):
    return _auth(lambda: auth.signup(body.model_dump()))


@app.post("/api/auth/login")
def auth_login(body: LoginIn):
    return _auth(lambda: auth.login(body.id, body.password))


@app.post("/api/auth/refresh")
def auth_refresh(body: RefreshIn):
    return _auth(lambda: auth.refresh(body.refresh_token))


@app.get("/api/auth/kakao")
def auth_kakao(request: Request, next: str = "/", talk: bool = False, app: bool = False):
    """카카오 로그인 화면으로 보냄 (돌아올 곳 = 지금 사이트 주소, app=1 이면 안드로이드 앱)."""
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    return _auth(lambda: RedirectResponse(auth.kakao_url(f"{proto}://{host}", next, talk, app), status_code=302))


@app.post("/api/auth/store")
def auth_store(body: StoreSetupIn, authorization: str | None = Header(None)):
    """카카오로 처음 온 사장님의 가게 · 약관 한 번 받기."""
    return _auth(lambda: {"user": auth.setup_store(_bearer(authorization), body.model_dump())})


class KakaoConnectIn(BaseModel):
    provider_token: str = ""
    provider_refresh_token: str = ""


class KakaoOnIn(BaseModel):
    on: bool


@app.post("/api/kakao/connect")
def kakao_connect(body: KakaoConnectIn, authorization: str | None = Header(None)):
    """카카오 로그인에서 돌아온 카카오 표 저장 → 카카오톡 시세 알림을 보낼 수 있게."""
    return _auth(lambda: kakao_alert.connect(_bearer(authorization), body.provider_token, body.provider_refresh_token))


@app.get("/api/kakao/status")
def kakao_status(authorization: str | None = Header(None)):
    return _auth(lambda: kakao_alert.status(_bearer(authorization)))


@app.post("/api/kakao/on")
def kakao_on(body: KakaoOnIn, authorization: str | None = Header(None)):
    return _auth(lambda: kakao_alert.set_on(_bearer(authorization), body.on))


def _site(request):
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host")
    return f"{proto}://{host}"


@app.post("/api/kakao/link")
def kakao_link(request: Request, authorization: str | None = Header(None)):
    """카카오톡 연결 (아이디 · 카카오 계정 모두): 카카오 인증 주소를 돌려줌 → 화면이 그리로 보냄."""
    return _auth(lambda: {"url": kakao_alert.link_url(_bearer(authorization), _site(request))})


@app.get("/api/kakao/callback")
def kakao_callback(request: Request, code: str = "", state: str = "", error: str = "", error_description: str = ""):
    """카카오에서 돌아옴 → 카카오 표 저장 → 나의 가게로 (결과는 주소 ?kakao=ok / kakao_err=이유)."""
    from urllib.parse import quote
    if error:
        msg = "동의를 취소했어요" if error == "access_denied" else (error_description or error)
        return RedirectResponse(f"/?page=store&kakao_err={quote(msg)}", status_code=302)
    try:
        kakao_alert.callback(code, state, _site(request))
    except (auth.AuthError, ApiError, ApiKeyMissing) as e:
        return RedirectResponse(f"/?page=store&kakao_err={quote(str(e)[:200])}", status_code=302)
    return RedirectResponse("/?page=store&kakao=ok", status_code=302)


@app.post("/api/kakao/unlink")
def kakao_unlink(authorization: str | None = Header(None)):
    return _auth(lambda: kakao_alert.unlink(_bearer(authorization)))


@app.post("/api/kakao/test")
def kakao_test(authorization: str | None = Header(None)):
    """마이페이지 '지금 보내 보기' — 내 카톡 '나와의 채팅'으로 지금 시세 알림."""
    return _auth(lambda: kakao_alert.test(_bearer(authorization), _price_outlook()))


class PushSubIn(BaseModel):
    endpoint: str = ""
    keys: dict = {}


class PushOffIn(BaseModel):
    endpoint: str | None = None


@app.get("/api/push/status")
def push_status(authorization: str | None = Header(None)):
    """앱 알림: 열쇠가 있는지 · 이 계정에 켜 둔 기기 수."""
    return _auth(lambda: app_push.status(_bearer(authorization)))


@app.post("/api/push/subscribe")
def push_subscribe(body: PushSubIn, authorization: str | None = Header(None)):
    return _auth(lambda: app_push.subscribe(_bearer(authorization), body.model_dump()))


@app.post("/api/push/unsubscribe")
def push_unsubscribe(body: PushOffIn, authorization: str | None = Header(None)):
    return _auth(lambda: app_push.unsubscribe(_bearer(authorization), body.endpoint))


class FcmIn(BaseModel):
    token: str | None = None


@app.post("/api/push/fcm/subscribe")
def push_fcm_subscribe(body: FcmIn, authorization: str | None = Header(None)):
    """안드로이드 앱: 이 기기의 Firebase 알림 표 저장."""
    return _auth(lambda: app_push.fcm_subscribe(_bearer(authorization), body.token))


@app.post("/api/push/fcm/unsubscribe")
def push_fcm_unsubscribe(body: FcmIn, authorization: str | None = Header(None)):
    return _auth(lambda: app_push.fcm_unsubscribe(_bearer(authorization), body.token))


@app.post("/api/push/test")
def push_test(authorization: str | None = Header(None)):
    """설정 '지금 보내 보기' — 이 계정의 기기 모두(웹 · 안드로이드 앱)에 지금 앱 알림."""
    return _auth(lambda: app_push.test(_bearer(authorization), _price_outlook()))


def _run_cost_alerts(save=True):
    """새 시세 예측으로 원가율 다시 계산 → 어제와 비교해 원가율 알림 (store/cost_alert.py).
    다시 계산한 원가율은 원가율 보관값에도 넣음 → 화면 숫자와 알림 숫자가 같음."""
    out = cost_alert.check(supabase_db.DEMO_STORE, _forecasts(), save=save)
    if save:
        ts = time.time()
        _memo["costs_report"] = (ts, out["report"])
        _save_shared("costs_report", ts, out["report"])
        for k in [k for k in _memo if k.startswith("cost_alerts:")]:   # 알림 목록 보관값도 새로
            _memo.pop(k, None)
    return {k: v for k, v in out.items() if k != "report"}


@app.post("/api/jobs/cost-alerts")
def jobs_cost_alerts(preview: bool = False):
    """시세가 바뀐 뒤 원가율 다시 계산 → 원가율 알림 만들기 (보통은 /api/jobs/alerts 가 먼저 부름). preview=1 이면 저장하지 않고 보기만."""
    return _receipt_guard(lambda: _run_cost_alerts(save=not preview))


@app.get("/api/cost-alerts")
def cost_alerts(days: int = 7):
    """원가율 알림 목록 (새것부터, 최근 days일): [{id, message, sent_at, clicked_at}] — 화면 '다음 주 오름 → 다른 재료 어때?' 말풍선용."""
    return _receipt_guard(lambda: memo(f"cost_alerts:{days}", lambda: cost_alert.recent(supabase_db.DEMO_STORE, max(1, min(days, 30))), ttl=300))


@app.post("/api/jobs/alerts")
def jobs_alerts():
    """예약 실행용 (daily-learn.yml, 새벽 학습 뒤): 원가율 다시 계산 · 원가율 알림 → 아침 앱 알림 + 카카오톡 알림. 한 사람에게 하루 한 번."""
    outlook, out = _price_outlook(), {}
    try:
        out["cost_alerts"] = len(_run_cost_alerts()["alerts"])
    except Exception as e:   # 원가율 알림이 실패해도 시세 알림은 보냄
        out["cost_alerts_error"] = str(e)[:200]
    for name, fn in (("push", app_push.send_all), ("kakao", kakao_alert.send_all)):
        try:
            out.update(fn(outlook))
        except Exception as e:   # 하나가 실패해도 나머지는 보냄
            out[f"{name}_error"] = str(e)[:200]
    return out


@app.post("/api/jobs/kakao")
def jobs_kakao():
    """예약 실행용: 아침 카카오톡 시세 알림 (매일 새벽 학습 · /api/jobs/daily 뒤에 불림). 한 사람에게 하루 한 번만."""
    return _guard(lambda: kakao_alert.send_all(_price_outlook()))


@app.get("/api/auth/me")
def auth_me(authorization: str | None = Header(None)):
    return _auth(lambda: auth.me(_bearer(authorization)))


class StoreEditIn(BaseModel):
    store: str = ""
    district: str = ""


@app.patch("/api/auth/me")
def auth_store_edit(body: StoreEditIn, authorization: str | None = Header(None)):
    """마이페이지에서 가게 이름 · 구 바꾸기."""
    return _auth(lambda: auth.update_store(_bearer(authorization), body.model_dump()))


class CostsIn(BaseModel):
    costs: dict = {}


@app.get("/api/store/costs")
def store_costs_get(authorization: str | None = Header(None)):
    """마이페이지 '내 정보' 가게 비용 (좌석 · 쉬는 요일 · 업종 · 고정 · 판매 · 배달 비용, 만 원 단위). 넣은 적 없으면 costs = null."""
    return _auth(lambda: store_costs.get(_bearer(authorization)))


@app.put("/api/store/costs")
def store_costs_put(body: CostsIn, authorization: str | None = Header(None)):
    """가게 비용 저장 (계정 정보에 → 다른 기기에서도 같은 값). 모양이 틀린 칸은 버리고 저장한 값을 돌려줌."""
    return _auth(lambda: store_costs.save(_bearer(authorization), body.costs))


class ProfileEditIn(BaseModel):
    name: str = ""
    photo: str = ""            # base64 사진 (바꿀 때만)
    reset_photo: bool = False  # 내가 올린 사진을 지우고 원래 사진(카카오 사진 · 기본 그림)으로


@app.patch("/api/auth/profile")
def auth_profile_edit(body: ProfileEditIn, authorization: str | None = Header(None)):
    """마이페이지에서 사장님 이름 · 프로필 사진 바꾸기 (카카오로 로그인해도 같음)."""
    return _auth(lambda: auth.update_profile(_bearer(authorization), body.model_dump()))


@app.get("/api/auth/photo/{user_id}")
def auth_photo(user_id: str):
    """프로필 사진. 주소에 v(바꾼 번호)가 붙어 있어 사진이 바뀌면 주소도 바뀜 → 오래 기억해도 됨."""
    data, kind = _auth(lambda: auth.photo(user_id))
    if not data:
        raise HTTPException(404, "사진이 없어요")
    return Response(data, media_type=kind, headers={"Cache-Control": "private, max-age=2592000, immutable"})


@app.post("/api/auth/logout")
def auth_logout(authorization: str | None = Header(None)):
    _auth(lambda: auth.logout(_bearer(authorization)))
    return {"ok": True}


@app.delete("/api/auth/me")
def auth_withdraw(authorization: str | None = Header(None)):
    _auth(lambda: auth.withdraw(_bearer(authorization)))
    return {"ok": True}


# ---------------------------------------------------------------
# 살피 AI 채팅: 지난 대화는 화면(브라우저)이 보관했다가 함께 보냄
# (Vercel은 요청마다 다른 서버가 받을 수 있어 서버에 대화를 기억해 두지 않음)
# ---------------------------------------------------------------


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []
    session: str = ""      # 같은 채팅창의 대화 묶음 (화면이 만든 임의 번호, 대화 기록용)


def _answer(body, on_text=None, on_status=None):
    """질문 하나에 답하고 대화 기록까지 남김 → 답 글. (/api/chat 과 /api/chat/stream 이 같이 씀)"""
    question, started, agent, status = button(body.message[:1000]), time.time(), None, "ok"
    try:
        if question in BUTTON_ROUTES:   # 화면 버튼 질문은 답이 정해져 있어 3시간 동안 같은 답을 재사용 (모델 호출 없이 바로)
            def fresh():
                nonlocal agent
                agent = SalpiAgent()   # 버튼 답은 지난 대화와 무관하게 같아야 함
                return agent.ask(question)
            reply = shared("chat-" + hashlib.md5(question.encode()).hexdigest()[:8], fresh, ttl=3 * 3600)
            if agent is None:
                agent = type("Cached", (), {"last_tools": ["안내:버튼", "저장된 답"], "model": None})()
        else:
            agent = SalpiAgent(history=body.history)
            reply = agent.ask(question, on_text, on_status)
    except ApiKeyMissing as e:
        reply, status = str(e), "nokey"
    except Exception as e:
        busy = "429" in str(e) or "503" in str(e) or type(e).__name__ == "ServerError"
        status = "busy" if busy else "error"
        reply = ("지금 AI 서버가 바빠요. 잠시 뒤 다시 물어봐 주세요." if busy
                 else f"지금은 답을 만들지 못했어요 ({type(e).__name__}). 잠시 뒤 다시 물어봐 주세요.")
    if question:
        chat_log.save(body.session, len(body.history) // 2, question, reply, getattr(agent, "last_tools", []),
                      getattr(agent, "model", None), (time.time() - started) * 1000, status)
    return reply


def _chat_limit(body, request):
    """버튼 질문은 AI 를 안 써서 세지 않음. 직접 친 질문만 접속한 곳마다 1분 8번 · 하루 150번."""
    if button(body.message[:1000]) not in BUTTON_ROUTES:
        _limit(request, "chat")


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    _chat_limit(body, request)
    return {"reply": _answer(body)}


@app.post("/api/chat/stream")
def chat_stream(body: ChatIn, request: Request):
    """답이 써지는 대로 한 줄씩(JSON) 보냄: {"s": 지금 하는 일} · {"t": 글자 조각} ... 마지막에 {"done": true, "reply": 완성된 답}"""
    _chat_limit(body, request)
    pieces: queue.Queue = queue.Queue()

    def work():
        reply = _answer(body, lambda t: pieces.put({"t": t}), lambda s: pieces.put({"s": s}))
        pieces.put({"done": True, "reply": reply})

    threading.Thread(target=work, daemon=True).start()

    def lines():
        while True:
            item = pieces.get()
            yield json.dumps(item, ensure_ascii=False) + "\n"
            if item.get("done"):
                return

    return StreamingResponse(lines(), media_type="application/x-ndjson", headers={"X-Accel-Buffering": "no"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
