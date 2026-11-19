"""영수증 분석 무료 체험 횟수 — 로그인한 사장님마다 5회.

- 쓴 횟수는 계정의 app_metadata.receipt_used 에 (영수증을 한 장 읽을 때마다 +1, 읽기에 실패하면 세지 않음)
- 유료 플랜이면 app_metadata.plan == "plus" → 횟수 제한 없음 (결제는 아직 없어서 Supabase에서 직접 넣어 줌)
- 5회를 다 쓰면 /api/receipt/read 가 402 를 돌려주고, 화면은 나의 가게 영수증 분석 칸을 흐리게 가림
"""
from account import auth
from sources.data_sources import ApiError

FREE_RECEIPTS = 5
LOCKED_MSG = "이 기능은 유료 플랜 사장님만 사용 가능해요"


def _state(user):
    app = user.get("app_metadata") or {}
    used = int(app.get("receipt_used") or 0)
    paid = app.get("plan") == "plus"
    found = sum(int(v or 0) for v in (app.get("receipt_found") or {}).values())
    return {"limit": FREE_RECEIPTS, "used": used, "left": max(0, FREE_RECEIPTS - used), "paid": paid,
            "locked": not paid and used >= FREE_RECEIPTS, "found": found}


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


def status(token):
    return _state(auth.user_of(token))


def check(token):
    """읽기 전에: 다 썼으면 AuthError(402). 쓸 수 있으면 계정을 돌려줌 (읽은 뒤 count 에 넘김)."""
    user = auth.user_of(token)
    if _state(user)["locked"]:
        raise auth.AuthError(LOCKED_MSG, 402)
    return user


def count(user):
    """영수증을 한 장 읽었을 때 +1 → 바뀐 횟수. 유료 플랜은 세지 않음."""
    st = _state(user)
    if st["paid"]:
        return st
    app = {**(user.get("app_metadata") or {}), "receipt_used": st["used"] + 1}
    r = auth._call("PUT", f"admin/users/{user['id']}", admin=True, json={"app_metadata": app})
    if not r.ok:
        raise ApiError(f"무료 횟수를 저장하지 못했어요 ({r.status_code})")
    return _state({**user, "app_metadata": app})
