"""무료 체험 횟수 — 로그인한 사장님마다 기능별 5회 (6번째부터 잠금).

- 기능(feature)마다 따로 셈. 쓴 횟수는 계정의 app_metadata 에
    receipt: 영수증 분석 → receipt_used (영수증을 한 장 읽을 때마다 +1, 읽기에 실패하면 세지 않음)
    sales  : 판매율 분석 (내일 예상 판매 /api/demand · 지금 판매로 남는 돈 /api/costs) → sales_used
             **새 날짜의 판매(몇 그릇)를 올릴 때 1회** (PUT /api/sales, 같은 날짜를 고쳐 올리면 안 셈). 화면을 보는 것은 안 셈
             5번째로 올린 날은 그날 끝까지 분석을 볼 수 있고(sales_last_day), 다음 날부터 잠금 · 6번째 날짜는 못 올림
  새 기능을 잠그려면 FEATURES 에 한 줄 더하고, 그 기능 서버에서 check → (성공하면) count 를 부르면 됨
- 살피 플러스 구독 중이면(subscription.state, 끝나는 날 안 지남) 횟수 제한 없음
- 5회를 다 쓰면 그 기능 서버가 402 를 돌려주고, 화면은 그 칸을 흐리게 가림
"""
from account import auth, subscription
from sources.data_sources import ApiError

FREE = 5
FREE_RECEIPTS = FREE   # 예전 이름 (다른 곳에서 부를 수 있어 남겨 둠)
FEATURES = {"receipt": "receipt_used", "sales": "sales_used"}
LAST_DAY = {"sales": "sales_last_day"}   # 마지막으로 센 날(한국 날짜) → 다 쓴 날은 그날 끝까지 열어 둠
LOCKED_MSG = "이 기능은 유료 플랜 사장님만 사용 가능해요"


def _key(feature):
    if feature not in FEATURES:
        raise ValueError(f"모르는 기능: {feature}")
    return FEATURES[feature]


def _state(user, feature="receipt"):
    app = user.get("app_metadata") or {}
    used = int(app.get(_key(feature)) or 0)
    sub = subscription.state(app)
    found = sum(int(v or 0) for v in (app.get("receipt_found") or {}).values())
    # 5번째로 쓴 날에는 그날 끝까지 볼 수 있음 (다음 날부터 잠금)
    used_today = feature in LAST_DAY and app.get(LAST_DAY[feature]) == subscription._today().isoformat()
    return {"feature": feature, "limit": FREE, "used": used, "left": max(0, FREE - used), "paid": sub["paid"],
            "plan_until": sub["until"], "locked": not sub["paid"] and used >= FREE and not used_today, "found": found}


def add_found(token, purchase_id, extra_paid):
    """저장한 영수증에서 찾은 '아낄 곳'(평소보다 더 낸 돈) 기록 → 잠금 화면 '5장으로 n원 아낄 곳을 찾았어요'.
    영수증마다 한 번만 (같은 영수증을 다시 저장하면 바꿔 넣음)."""
    user = auth.user_of(token)
    app = user.get("app_metadata") or {}
    found = {**(app.get("receipt_found") or {}), str(purchase_id): max(0, int(extra_paid or 0))}
    app = {**app, "receipt_found": found}
    r = auth._call("PUT", f"admin/users/{user['id']}", admin=True, json={"app_metadata": app})
    if not r.ok:
        raise ApiError(f"찾은 금액을 저장하지 못했어요 ({r.status_code})")
    return _state({**user, "app_metadata": app})


def status(token, feature="receipt"):
    return _state(auth.user_of(token), feature)


def check(token, feature="receipt"):
    """쓰기 전에: 다 썼으면 AuthError(402). 쓸 수 있으면 계정을 돌려줌 (성공한 뒤 count 에 넘김)."""
    user = auth.user_of(token)
    if _state(user, feature)["locked"]:
        raise auth.AuthError(LOCKED_MSG, 402)
    return user


def count(user, feature="receipt"):
    """한 번 썼을 때 +1 → 바뀐 횟수. 구독 중이면 세지 않음."""
    st = _state(user, feature)
    if st["paid"]:
        return st
    app = user.get("app_metadata") or {}
    stamp = {LAST_DAY[feature]: subscription._today().isoformat()} if feature in LAST_DAY else {}
    app = {**app, _key(feature): st["used"] + 1, **stamp}
    r = auth._call("PUT", f"admin/users/{user['id']}", admin=True, json={"app_metadata": app})
    if not r.ok:
        raise ApiError(f"무료 횟수를 저장하지 못했어요 ({r.status_code})")
    return _state({**user, "app_metadata": app}, feature)
