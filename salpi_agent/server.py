"""살피 웹 서버: 시세 대시보드 화면 + 데이터 API + 살피 AI 채팅.

실행: python server.py → http://localhost:8000
"""

import os
import base64
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from datetime import date

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import analysis
import demand
import forecast_log
import foodspring
import mart_price
import receipts
import supabase_db
from agent import SalpiAgent
from data_sources import ITEMS, ApiError, ApiKeyMissing, event_detail, holidays, month_events

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"



@asynccontextmanager
async def lifespan(_app):
    """서버가 켜지면 뒤에서 시세를 미리 받아 둠 (첫 화면이 빨리 뜨게)."""
    def warm():
        try:
            memo("overview", _overview)
            _daily("forecast")
        except Exception:
            pass   # 키가 없거나 API 장애면 화면에서 안내
    threading.Thread(target=warm, daemon=True).start()
    yield


app = FastAPI(title="살피", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB), name="static")
app.mount("/receipts_demo", StaticFiles(directory=ROOT / "receipts_demo"), name="receipts_demo")   # 시연용 가상 영수증

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
             "KCA_PRICE_API_KEY"]


@app.get("/api/health")
def health():
    return {"keys": {k: bool(os.getenv(k, "").strip()) for k in KEY_NAMES}}


@app.get("/api/overview")
def overview():
    out = _guard(lambda: {"items": memo("overview", _overview)})
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
    out = _guard(lambda: memo("meat_seafood", lambda: {"items": analysis.extra_overview()}))
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
    """예약 실행용: 예측 저장 · 채점 · 식봄 판매가 저장을 바로 실행하고 결과 수를 돌려줌."""
    return _guard(lambda: {**_run_forecast_job(), **_run_shop_job()})


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
    return _guard(lambda: memo("mart", mart_price.mart_prices, ttl=6 * 3600))


@app.get("/api/context")
def context():
    return _guard(lambda: memo("context", lambda: {
        "weather": analysis.weather_summary(7), "holidays": holidays(30), "events": month_events()}))


# ---------------------------------------------------------------
# 우리 가게 내일 준비: 판매 기록(Supabase)으로 메뉴별 그릇 수 · 재료 필요량 · 발주 추천
# 지금은 시연용 가게 한 곳 (로그인이 없어서)
# ---------------------------------------------------------------


def _price_outlook():
    """대시보드 시세 예측이 이미 계산돼 있으면 그대로 씀 (없으면 demand 가 필요한 재료만 계산)."""
    hit = _memo.get("overview")
    return {r["item"]: (r.get("forecast") or {}).get("expected_change_pct") for r in hit[1]} if hit else None


@app.get("/api/demand")
def demand_forecast(target: str | None = None):
    try:
        day = date.fromisoformat(target) if target else None
    except ValueError:
        raise HTTPException(400, "날짜는 2026-11-05 형식으로 보내 주세요")
    # 대시보드 시세가 아직 준비 전이면 기다리지 않고 시세 없이 계산 (1분 뒤 다시 계산할 때 시세 반영)
    outlook = _price_outlook()
    key = f"demand:{day}:{'price' if outlook else 'noprice'}"
    return _guard(lambda: memo(key, lambda: demand.forecast(target=day, price_outlook=outlook or {}), ttl=600 if outlook else 60))


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


class ReceiptSave(ReceiptIn):
    date: str | None = None
    supplier: str | None = None
    items: list[dict] = []


def _receipt_guard(fn):
    try:
        return _guard(fn)
    except (ValueError, RuntimeError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/receipt/read")
def receipt_read(body: ReceiptIn):
    data, mime = _image(body.image, body.mime)
    if not data:
        raise HTTPException(400, "영수증 사진을 골라 주세요")
    return _receipt_guard(lambda: receipts.read(data, mime))


@app.post("/api/receipt/save")
def receipt_save(body: ReceiptSave):
    data, mime = _image(body.image, body.mime)
    return _receipt_guard(lambda: receipts.save(supabase_db.DEMO_STORE, body.model_dump(), data, mime))


@app.get("/api/costs")
def costs():
    return _receipt_guard(lambda: {**receipts.cost_report(supabase_db.DEMO_STORE), "receipts": receipts.recent(supabase_db.DEMO_STORE)})


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
    return _receipt_guard(lambda: receipts.edit(supabase_db.DEMO_STORE, purchase_id, body.model_dump()))


@app.get("/api/my-items")
def my_items():
    """우리 가게 메뉴에 들어가는 재료 (알림 '내 메뉴 재료만'). 메뉴가 자주 바뀌지 않아 10분 보관."""
    return _receipt_guard(lambda: memo("my_items", lambda: receipts.my_ingredients(supabase_db.DEMO_STORE), ttl=600))


@app.get("/api/receipts")
def receipt_list():
    return _receipt_guard(lambda: {"receipts": receipts.recent(supabase_db.DEMO_STORE, limit=50)})


@app.delete("/api/receipt/{purchase_id}")
def receipt_delete(purchase_id: int):
    return _receipt_guard(lambda: receipts.remove(supabase_db.DEMO_STORE, purchase_id))


# ---------------------------------------------------------------
# 살피 AI 채팅: 지난 대화는 화면(브라우저)이 보관했다가 함께 보냄
# (Vercel은 요청마다 다른 서버가 받을 수 있어 서버에 대화를 기억해 두지 않음)
# ---------------------------------------------------------------


class ChatIn(BaseModel):
    message: str
    history: list[dict] = []


@app.post("/api/chat")
def chat(body: ChatIn):
    try:
        reply = SalpiAgent(history=body.history).ask(body.message.strip()[:1000])
    except ApiKeyMissing as e:
        reply = str(e)
    except Exception as e:
        busy = "429" in str(e) or "503" in str(e) or type(e).__name__ == "ServerError"
        reply = ("지금 AI 서버가 바빠요. 잠시 뒤 다시 물어봐 주세요." if busy
                 else f"지금은 답을 만들지 못했어요 ({type(e).__name__}). 잠시 뒤 다시 물어봐 주세요.")
    return {"reply": reply}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
