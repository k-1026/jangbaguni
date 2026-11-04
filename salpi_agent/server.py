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
import foodspring
import receipts
import supabase_db
from agent import SalpiAgent
from data_sources import ITEMS, ApiError, ApiKeyMissing, daegu_events, holidays

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"



@asynccontextmanager
async def lifespan(_app):
    """서버가 켜지면 뒤에서 시세를 미리 받아 둠 (첫 화면이 빨리 뜨게)."""
    def warm():
        try:
            memo("overview", _overview)
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
             "KTO_TOUR_API_KEY", "KAMIS_CERT_KEY", "KAMIS_CERT_ID", "GEMINI_API_KEY", "SUPABASE_URL", "SUPABASE_SECRET_KEY"]


@app.get("/api/health")
def health():
    return {"keys": {k: bool(os.getenv(k, "").strip()) for k in KEY_NAMES}}


@app.get("/api/overview")
def overview():
    return _guard(lambda: {"items": memo("overview", _overview)})


@app.get("/api/item/{name}")
def item(name: str):
    if name not in ITEMS:
        raise HTTPException(404, f"'{name}'은(는) 아직 지원하지 않아요")
    return _guard(lambda: memo(f"item:{name}", lambda: analysis.item_detail(name)))


@app.get("/api/products")
def products():
    """식봄 실제 상품 · 가격 (재료마다 4개). 살피 시세 정보는 화면에서 /api/overview 와 합침."""
    return memo("products", lambda: {"items": foodspring.all_products(4)})


@app.get("/api/context")
def context():
    return _guard(lambda: memo("context", lambda: {
        "weather": analysis.weather_summary(7), "holidays": holidays(30), "events": daegu_events(14)}))


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
