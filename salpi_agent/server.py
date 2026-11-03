"""살피 웹 서버: 시세 대시보드 화면 + 데이터 API + 살피 AI 채팅.

실행: python server.py → http://localhost:8000
"""

import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import analysis
import foodspring
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
            memo("products", lambda: {"items": foodspring.all_products(4)})
        except Exception:
            pass   # 키가 없거나 API 장애면 화면에서 안내
    threading.Thread(target=warm, daemon=True).start()
    yield


app = FastAPI(title="살피", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB), name="static")

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
    rows = analysis.market_overview()
    for r in rows:
        f = analysis.forecast_item(r["item"])
        r["forecast"] = {k: f.get(k) for k in ("direction", "expected_change_pct", "range_pct", "confidence", "suggestion")}
    return rows


def _guard(fn):
    try:
        return fn()
    except (ApiKeyMissing, ApiError) as e:
        raise HTTPException(503, f"{e}. 잠시 뒤 새로고침해 주세요.")


@app.get("/")
def index():
    return FileResponse(WEB / "index.html")


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
