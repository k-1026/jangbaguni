"""살피 플러스 구독 · 모의 결제 (토스페이먼츠 테스트 결제).

흐름 (화면 ↔ 서버 ↔ 토스페이먼츠)
1) POST /api/subscribe/checkout  → 주문 번호 · 금액 · 결제창 열쇠(client key)를 줌. 주문은 계정(app_metadata.pending_order)에 적어 둠
2) 화면이 토스 결제창을 염 → 테스트 카드로 결제 → 성공 주소로 돌아오며 paymentKey · orderId · amount 를 받음
3) POST /api/subscribe/confirm  → 적어 둔 주문과 금액이 같은지 확인 → 토스 '결제 승인' API 호출 → 30일 플러스로 바꿈
4) POST /api/subscribe/cancel   → 다음 달부터 안 냄 (지금 기간 끝날 때까지는 플러스 그대로)

- 열쇠: .env 의 TOSS_CLIENT_KEY · TOSS_SECRET_KEY (토스페이먼츠 개발자센터 → API 키의 '테스트' 키, test_ 로 시작)
  테스트 키는 실제로 돈이 나가지 않음. 라이브 키(live_)는 받지 않음 → 이 서버는 모의 결제만 함
- 열쇠가 없으면 '모의 승인': 토스를 부르지 않고 금액만 확인해서 승인 (시연 · 내 컴퓨터용). 답에 mode = "mock" 으로 표시
- 구독 상태는 계정 정보(app_metadata)에 — 사장님이 직접 못 고치는 칸 (trial.py 의 plan == "plus" 와 같은 칸)
    plan = "plus" · plan_until = 끝나는 날(한국 날짜) · plan_cancel = 다음 달 안 냄 · payments = 최근 결제 12건
"""
import base64
import os
import uuid
from datetime import date, datetime, timedelta, timezone

import requests

from account import auth
from sources.data_sources import ApiError

PRICE = 19_900                     # 월 구독료 (plan/1116_final_sprint_plan.md 2-1절)
PLAN_DAYS = 30
ORDER_NAME = "살피 플러스 1개월"
TOSS_CONFIRM = "https://api.tosspayments.com/v1/payments/confirm"
KST = timezone(timedelta(hours=9))


def _today():
    return datetime.now(KST).date()


def _keys():
    ck, sk = os.getenv("TOSS_CLIENT_KEY", "").strip(), os.getenv("TOSS_SECRET_KEY", "").strip()
    if (ck and not ck.startswith("test_")) or (sk and not sk.startswith("test_")):
        raise auth.AuthError("모의 결제에는 토스페이먼츠 '테스트' 키(test_ 로 시작)만 쓸 수 있어요.", 503)
    return ck, sk


def state(app):
    """app_metadata → 구독 상태 (trial.py 도 이걸로 유료 여부를 봄)."""
    until = app.get("plan_until")
    active = app.get("plan") == "plus" and (not until or date.fromisoformat(until) >= _today())
    return {"plan": "plus" if active else "free", "paid": active, "until": until if active else None,
            "cancel_at_end": bool(app.get("plan_cancel")) if active else False, "price": PRICE,
            "payments": (app.get("payments") or [])[:12]}


def _save_app(user, app):
    r = auth._call("PUT", f"admin/users/{user['id']}", admin=True, json={"app_metadata": app})
    if not r.ok:
        raise ApiError(f"구독 정보를 저장하지 못했어요 ({r.status_code})")
    return r.json().get("app_metadata") or app


def status(token):
    user = auth.user_of(token)
    ck, sk = _keys()
    return {**state(user.get("app_metadata") or {}), "mode": "toss" if ck and sk else "mock"}


def checkout(token):
    """결제창을 열기 전에: 주문 번호를 만들어 계정에 적어 둠 (금액을 화면이 바꿔 보내도 승인 때 걸러짐)."""
    user = auth.user_of(token)
    ck, sk = _keys()
    order_id = f"salpi-{_today():%Y%m%d}-{uuid.uuid4().hex[:12]}"
    app = {**(user.get("app_metadata") or {}), "pending_order": {"order_id": order_id, "amount": PRICE}}
    _save_app(user, app)
    meta = user.get("user_metadata") or {}
    return {"order_id": order_id, "amount": PRICE, "order_name": ORDER_NAME, "client_key": ck or None,
            "customer_key": user["id"], "customer_name": meta.get("name") or "사장님",
            "mode": "toss" if ck and sk else "mock"}


def _toss_confirm(sk, payment_key, order_id, amount):
    auth_header = base64.b64encode(f"{sk}:".encode()).decode()
    try:
        r = requests.post(TOSS_CONFIRM, json={"paymentKey": payment_key, "orderId": order_id, "amount": amount},
                          headers={"Authorization": f"Basic {auth_header}", "Content-Type": "application/json"}, timeout=20)
    except requests.RequestException as e:
        raise ApiError(f"결제 회사에 연결하지 못했어요 ({type(e).__name__})") from None
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not r.ok:
        raise auth.AuthError(body.get("message") or f"결제를 승인하지 못했어요 ({r.status_code})", 400)
    return body


def confirm(token, payment_key, order_id, amount):
    """결제창에서 돌아온 값 확인 → 승인 → 30일 플러스 (이미 플러스면 끝나는 날에 30일 더함)."""
    user = auth.user_of(token)
    app = user.get("app_metadata") or {}
    pending = app.get("pending_order") or {}
    if not order_id or pending.get("order_id") != order_id:
        raise auth.AuthError("주문 정보를 찾지 못했어요. 처음부터 다시 결제해 주세요.", 400)
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        amount = None
    if amount != pending.get("amount"):
        raise auth.AuthError("결제 금액이 주문과 달라요. 처음부터 다시 결제해 주세요.", 400)

    ck, sk = _keys()
    if ck and sk:
        if not payment_key:
            raise auth.AuthError("결제 정보가 없어요. 처음부터 다시 결제해 주세요.", 400)
        paid = _toss_confirm(sk, payment_key, order_id, amount)
        record = {"order_id": order_id, "amount": amount, "mode": "toss", "method": paid.get("method"),
                  "approved_at": paid.get("approvedAt"), "receipt": (paid.get("receipt") or {}).get("url")}
    else:
        record = {"order_id": order_id, "amount": amount, "mode": "mock", "method": "모의 결제",
                  "approved_at": datetime.now(KST).isoformat(timespec="seconds"), "receipt": None}

    now = state(app)
    start = date.fromisoformat(now["until"]) if now["paid"] and now["until"] else _today() - timedelta(1)
    until = (start + timedelta(PLAN_DAYS)).isoformat()
    record["until"] = until
    # Supabase 는 app_metadata 를 통째로 바꾸지 않고 칸별로 합침 → 칸을 빼면 남아 있음. 빈 값(None)으로 덮어 같은 주문을 두 번 못 쓰게
    app = {**app, "pending_order": None}
    app.update({"plan": "plus", "plan_until": until, "plan_cancel": False,
                "payments": [record, *(app.get("payments") or [])][:12]})
    return {**state(_save_app(user, app)), "mode": record["mode"], "approved": record}


def cancel(token, undo=False):
    """구독 해지 예약 (지금 기간 끝까지는 플러스). undo=True 면 해지 취소."""
    user = auth.user_of(token)
    app = user.get("app_metadata") or {}
    if not state(app)["paid"]:
        raise auth.AuthError("지금 구독 중이 아니에요.", 400)
    return state(_save_app(user, {**app, "plan_cancel": not undo}))
