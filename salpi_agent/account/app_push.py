"""살피 앱 알림 (설치한 앱 · 휴대폰 알림) — 표준 푸시(Web Push, VAPID).

사장님이 살피 앱(홈 화면에 설치)에서 "앱 알림 켜기"를 누르면 휴대폰이 알림을 받을 주소(구독)를 주고,
서버가 그 주소로 아침 시세 알림을 보내면 휴대폰에 "살피" 알림이 울림 (앱을 닫아 둬도).
알림 내용은 카카오톡 알림과 같은 글(kakao_alert.message: 내 메뉴 재료 7일 예측 · 원가율 40% 넘은 메뉴).

- 구독은 계정의 app_metadata.push_subs 에 (기기마다 하나, 최대 5개). 끊긴 구독(404 · 410)은 보낼 때 지움
- 매일 아침 /api/jobs/alerts (daily-learn.yml, 새벽 학습 뒤) → send_all() — 한 사람에게 하루 한 번
필요한 것 (.env · Vercel): VAPID_PUBLIC_KEY · VAPID_PRIVATE_KEY (한 번 만든 열쇠 한 쌍, 바꾸면 모든 구독을 다시 해야 함)
아이폰: Safari → 공유 → 홈 화면에 추가 → 그 앱에서 켜야 알림이 옴 (iOS 16.4 이상)
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

from account import auth
from account import kakao_alert
from sources.data_sources import ApiError

KST = timezone(timedelta(hours=9))
MAX_SUBS = 5


def public_key():
    return os.getenv("VAPID_PUBLIC_KEY", "").strip()


def _keys():
    pub, priv = public_key(), os.getenv("VAPID_PRIVATE_KEY", "").strip()
    if not pub or not priv:
        raise ApiError(".env 의 VAPID_PUBLIC_KEY · VAPID_PRIVATE_KEY 가 비어 있어요 (앱 알림 열쇠)")
    return pub, priv


def _save(user, **fields):
    app = {**(user.get("app_metadata") or {}), **fields}
    r = auth._call("PUT", f"admin/users/{user['id']}", admin=True, json={"app_metadata": app})
    if not r.ok:
        raise ApiError(f"앱 알림 설정을 저장하지 못했어요 ({r.status_code})")
    return r.json()


def status(token):
    user = auth.user_of(token)
    app = user.get("app_metadata") or {}
    return {"ready": bool(public_key() and os.getenv("VAPID_PRIVATE_KEY", "").strip()), "public_key": public_key(),
            "devices": len(app.get("push_subs") or []), "on": app.get("push_on", True),
            "last_sent": app.get("push_last_sent"), "endpoints": [s["endpoint"][-24:] for s in app.get("push_subs") or []]}


def subscribe(token, sub):
    """이 기기의 구독 저장 (같은 주소면 바꿔 넣음)."""
    if not (sub or {}).get("endpoint") or not (sub.get("keys") or {}).get("p256dh"):
        raise auth.AuthError("알림 주소가 올바르지 않아요. 다시 켜 주세요.")
    user = auth.user_of(token)
    subs = [s for s in (user.get("app_metadata") or {}).get("push_subs") or [] if s["endpoint"] != sub["endpoint"]]
    subs = (subs + [{"endpoint": sub["endpoint"], "keys": {"p256dh": sub["keys"]["p256dh"], "auth": sub["keys"]["auth"]},
                     "added": int(time.time())}])[-MAX_SUBS:]
    _save(user, push_subs=subs, push_on=True)
    return status(token)


def unsubscribe(token, endpoint=None):
    """이 기기만(endpoint) 또는 모든 기기 끄기."""
    user = auth.user_of(token)
    subs = [s for s in (user.get("app_metadata") or {}).get("push_subs") or [] if endpoint and s["endpoint"] != endpoint]
    _save(user, push_subs=subs, push_on=bool(subs))
    return status(token)


def _push(user, payload):
    """사장님 기기 모두에 보냄 → 보낸 기기 수. 끊긴 구독은 지움."""
    from pywebpush import WebPushException, webpush
    pub, priv = _keys()
    subs, keep, sent, last = (user.get("app_metadata") or {}).get("push_subs") or [], [], 0, None
    for s in subs:
        try:
            webpush(subscription_info=s, data=json.dumps(payload, ensure_ascii=False), vapid_private_key=priv,
                    vapid_claims={"sub": f"mailto:noreply@{kakao_alert.site_url().split('//')[-1]}"}, ttl=12 * 3600, timeout=15)
            keep.append(s)
            sent += 1
        except WebPushException as e:
            code = getattr(e.response, "status_code", None)
            if code not in (404, 410):   # 404 · 410 = 앱을 지웠거나 알림을 끈 기기 → 지움
                keep.append(s)
            last = f"{code}: {str(e)[:120]}"
    fields = {"push_subs": keep}
    if sent:
        fields["push_last_sent"] = datetime.now(KST).isoformat(timespec="minutes")
    _save(user, **fields)
    if not sent and last:
        raise ApiError(f"앱 알림을 보내지 못했어요 ({last})")
    return sent


def payload_for(user, outlook=None):
    text = kakao_alert.message((user.get("user_metadata") or {}).get("store_id"), outlook)
    first, _, rest = text.partition("\n")
    return {"title": first.replace("[살피] ", "살피 · "), "body": rest, "url": "/m/#/store", "tag": "salpi-morning"}


def test(token, outlook=None):
    user = auth.user_of(token)
    if not (user.get("app_metadata") or {}).get("push_subs"):
        raise auth.AuthError("먼저 이 기기에서 '앱 알림 켜기'를 눌러 주세요.")
    p = payload_for(user, outlook)
    return {"sent": _push(user, p), **p}


def send_all(outlook=None):
    """매일 아침: 앱 알림을 켠 계정 모두에게. 한 사람에게 하루 한 번."""
    if not (public_key() and os.getenv("VAPID_PRIVATE_KEY", "").strip()):
        return {"push_sent": 0, "push_skipped": "VAPID 열쇠 없음"}
    today, users, devices, failed = datetime.now(KST).date().isoformat(), 0, 0, 0
    for u in auth._users():
        app = u.get("app_metadata") or {}
        if not app.get("push_subs") or app.get("push_on") is False or (app.get("push_last_sent") or "")[:10] == today:
            continue
        try:
            devices += _push(u, payload_for(u, outlook))
            users += 1
        except Exception as e:
            failed += 1
            print(f"[앱 알림] {u['id'][:8]} 실패: {e}", flush=True)
    return {"push_users": users, "push_devices": devices, "push_failed": failed}
