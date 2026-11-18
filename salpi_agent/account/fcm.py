"""안드로이드 앱(Capacitor, com.salpi.mobile) 알림 — Firebase 클라우드 메시징(FCM HTTP v1).

앱에서 "앱 알림 켜기"를 누르면 휴대폰이 FCM 표(token)를 받아 서버에 저장하고(app_push.fcm_subscribe),
서버가 그 표로 알림을 보내면 앱을 닫아 둬도 휴대폰에 "살피" 알림이 울림.
웹 푸시(VAPID)는 브라우저 · 설치형 웹앱용, 이 파일은 안드로이드 앱용.

필요한 것 (.env · Vercel): FCM_SERVICE_ACCOUNT
  Firebase 콘솔 → 프로젝트 설정 → 서비스 계정 → "새 비공개 키 생성"으로 받은 JSON 파일 내용 그대로
  (한 줄로 넣기 어려우면 파일 내용을 base64 로 바꿔 넣어도 됨)
앱 쪽: 같은 Firebase 프로젝트의 google-services.json 을 salpi_agent/mobile/android/app/ 에 두고 앱을 다시 빌드
"""
import base64
import json
import os
import threading
import time

import requests

from sources.data_sources import ApiError

SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
CHANNEL = "salpi_alerts"   # 앱이 만드는 알림 채널 (mobile/js/viewmodels/MyVM.js 와 같은 이름)
_token = {"value": None, "until": 0.0}
_lock = threading.Lock()


class Gone(Exception):
    """앱을 지웠거나 표가 바뀐 기기 → 저장한 표를 지움."""


def _account():
    raw = os.getenv("FCM_SERVICE_ACCOUNT", "").strip()
    if not raw:
        return None
    if not raw.startswith("{"):
        raw = base64.b64decode(raw).decode("utf-8")
    return json.loads(raw)


def ready():
    try:
        acc = _account()
        return bool(acc and acc.get("private_key") and acc.get("client_email") and acc.get("project_id"))
    except Exception:
        return False


def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _access_token():
    """서비스 계정 열쇠로 Google 출입증(1시간)을 받아 둠 — 추가 라이브러리 없이 JWT 를 직접 서명."""
    with _lock:
        if _token["value"] and time.time() < _token["until"] - 60:
            return _token["value"]
        if not ready():
            raise ApiError(".env 의 FCM_SERVICE_ACCOUNT 가 비어 있거나 올바르지 않아요 (Firebase 서비스 계정 JSON)")
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
        acc, now = _account(), int(time.time())
        uri = acc.get("token_uri") or "https://oauth2.googleapis.com/token"
        head = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}).encode())
        claim = _b64(json.dumps({"iss": acc["client_email"], "scope": SCOPE, "aud": uri, "iat": now, "exp": now + 3600}).encode())
        key = serialization.load_pem_private_key(acc["private_key"].encode(), password=None)
        sig = _b64(key.sign(f"{head}.{claim}".encode(), padding.PKCS1v15(), hashes.SHA256()))
        r = requests.post(uri, data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                                     "assertion": f"{head}.{claim}.{sig}"}, timeout=15)
        if not r.ok:
            raise ApiError(f"Firebase 인증에 실패했어요 ({r.status_code}: {r.text[:120]})")
        j = r.json()
        _token.update(value=j["access_token"], until=now + int(j.get("expires_in", 3600)))
        return _token["value"]


def send(token, payload):
    """기기 하나에 알림. 성공하면 True, 끊긴 기기면 Gone, 그 밖의 실패는 ApiError."""
    url = f"https://fcm.googleapis.com/v1/projects/{_account()['project_id']}/messages:send"
    tag = payload.get("tag") or "salpi"
    msg = {"message": {
        "token": token,
        "notification": {"title": payload["title"], "body": payload["body"]},
        "data": {"url": payload.get("url") or "", "tag": tag},
        "android": {"priority": "high", "ttl": "43200s",
                    "notification": {"channel_id": CHANNEL, "tag": tag, "icon": "ic_stat_salpi", "color": "#3B7A0A"}},
    }}
    r = requests.post(url, json=msg, headers={"Authorization": f"Bearer {_access_token()}"}, timeout=15)
    if r.ok:
        return True
    text = r.text[:300]
    if r.status_code == 404 or "UNREGISTERED" in text or (r.status_code == 400 and "registration token" in text.lower()):
        raise Gone(text)
    raise ApiError(f"FCM {r.status_code}: {text[:160]}")
