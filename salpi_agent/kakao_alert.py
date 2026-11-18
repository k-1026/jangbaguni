"""카카오톡 시세 알림 — 카카오 로그인한 사장님 본인 카톡으로 "나에게 보내기" (카카오톡 메시지 API).

알림톡(사업자 채널 · 심사 필요) 대신, 사장님이 카카오 로그인 때 '카카오톡 메시지 전송'에 동의하면
그 사장님 카톡의 '나와의 채팅'으로 아침 시세 알림을 보낸다. 숫자는 모두 계산(시세 예측 · 원가율)에서 나옴.

흐름
  1. 카카오 로그인 (auth.kakao_url 에 scopes=talk_message) → 돌아온 주소 # 뒤의 provider_token · provider_refresh_token 을
     화면이 /api/kakao/connect 로 보냄 → 계정의 app_metadata.kakao_talk 에 저장 (사장님이 직접 못 고치는 칸)
  2. 매일 아침 /api/jobs/kakao (새벽 학습 · /api/jobs/daily 뒤, daily-learn.yml) → send_all(): 알림을 켠 카카오 계정마다 메시지를 만들어 보냄
     카카오 표(access token)는 6~12시간이면 끝나서, 보낼 때마다 refresh token 으로 새로 받음
  3. 마이페이지 › 설정 › "카카오톡 시세 알림": 켜기 · 끄기 · 지금 보내 보기

필요한 것 (.env · Vercel): KAKAO_REST_API_KEY (카카오 앱 REST API 키 = Supabase 카카오 연결의 Client ID),
KAKAO_CLIENT_SECRET (카카오 앱에서 Client Secret 을 켰을 때만), SITE_URL (메시지 버튼이 열 주소, 기본 실제 사이트)
카카오 개발자 콘솔: 동의항목 '카카오톡 메시지 전송'(talk_message) 켜기 · 플랫폼 Web 사이트 도메인에 SITE_URL 등록
"""
import json
import os
import time
from datetime import datetime, timedelta, timezone

import requests

import auth
import supabase_db as db
from data_sources import ApiError

KST = timezone(timedelta(hours=9))
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
MAX_TEXT = 200   # 카카오 텍스트 메시지 한도
RISE, FALL = 2.0, -2.0   # 다음 7일 예상 변화율(%) — 이만큼 넘을 때만 알림


def site_url():
    return os.getenv("SITE_URL", "https://jangbaguni-ten.vercel.app").rstrip("/")


# ---------------------------------------------------------------
# 계정에 카카오 표 저장 · 켜기 · 끄기
# ---------------------------------------------------------------

def _save(user, talk):
    app = {**(user.get("app_metadata") or {}), "kakao_talk": talk}
    r = auth._call("PUT", f"admin/users/{user['id']}", admin=True, json={"app_metadata": app})
    if not r.ok:
        raise ApiError(f"카카오 알림 설정을 저장하지 못했어요 ({r.status_code})")
    return r.json()


def connect(token, provider_token, provider_refresh_token):
    """카카오 로그인에서 받은 카카오 표 저장. 처음 연결하면 알림을 켠 상태로."""
    user = auth.user_of(token)
    if (user.get("app_metadata") or {}).get("provider") != "kakao":
        raise auth.AuthError("카카오로 로그인한 계정만 카카오톡 알림을 받을 수 있어요.")
    if not provider_refresh_token:
        raise auth.AuthError("카카오 표가 없어요. 카카오로 다시 로그인해 주세요.")
    old = (user.get("app_metadata") or {}).get("kakao_talk") or {}
    _save(user, {"refresh_token": provider_refresh_token, "access_token": provider_token,
                 "expires_at": int(time.time()) + 5 * 3600, "on": old.get("on", True), "connected_at": int(time.time())})
    return status(token)


def status(token):
    user = auth.user_of(token)
    talk = (user.get("app_metadata") or {}).get("kakao_talk") or {}
    return {"kakao_login": (user.get("app_metadata") or {}).get("provider") == "kakao",
            "connected": bool(talk.get("refresh_token")), "on": bool(talk.get("on")),
            "last_sent": talk.get("last_sent"), "last_error": talk.get("last_error"),
            "ready": bool(os.getenv("KAKAO_REST_API_KEY", "").strip())}


def set_on(token, on):
    user = auth.user_of(token)
    talk = (user.get("app_metadata") or {}).get("kakao_talk") or {}
    if not talk.get("refresh_token"):
        raise auth.AuthError("먼저 카카오로 다시 로그인해서 '카카오톡 메시지 전송'에 동의해 주세요.")
    _save(user, {**talk, "on": bool(on)})
    return status(token)


# ---------------------------------------------------------------
# 카카오 API
# ---------------------------------------------------------------

def _access(user):
    """쓸 수 있는 카카오 표 (끝나 가면 refresh token 으로 새로 받고 계정에 저장)."""
    talk = (user.get("app_metadata") or {}).get("kakao_talk") or {}
    if talk.get("access_token") and talk.get("expires_at", 0) > time.time() + 300:
        return talk["access_token"], user
    key = os.getenv("KAKAO_REST_API_KEY", "").strip()
    if not key:
        raise ApiError(".env 의 KAKAO_REST_API_KEY 가 비어 있어요 (카카오 앱 REST API 키)")
    data = {"grant_type": "refresh_token", "client_id": key, "refresh_token": talk.get("refresh_token", "")}
    if os.getenv("KAKAO_CLIENT_SECRET", "").strip():
        data["client_secret"] = os.getenv("KAKAO_CLIENT_SECRET").strip()
    r = requests.post(TOKEN_URL, data=data, timeout=15)
    if not r.ok:
        raise ApiError(f"카카오 표를 새로 받지 못했어요 ({r.status_code}: {r.text[:120]}) — 카카오로 다시 로그인해 주세요")
    body = r.json()
    talk = {**talk, "access_token": body["access_token"], "expires_at": int(time.time()) + int(body.get("expires_in", 3600)),
            "refresh_token": body.get("refresh_token") or talk.get("refresh_token")}   # refresh token 은 끝나 갈 때만 새로 옴
    return body["access_token"], _save(user, talk)


def _send(access, text):
    link = {"web_url": site_url(), "mobile_web_url": site_url()}
    template = {"object_type": "text", "text": text[:MAX_TEXT], "link": link, "button_title": "살피에서 보기"}
    r = requests.post(SEND_URL, headers={"Authorization": f"Bearer {access}"},
                      data={"template_object": json.dumps(template, ensure_ascii=False)}, timeout=15)
    if not r.ok:
        raise ApiError(f"카카오톡을 보내지 못했어요 ({r.status_code}: {r.text[:120]})")


# ---------------------------------------------------------------
# 메시지 만들기 (숫자는 시세 예측 · 원가율 계산 결과만)
# ---------------------------------------------------------------

def message(store_id=None, outlook=None):
    """→ 보낼 글 (200자 안). store_id 가 있으면 그 가게 메뉴 재료만, 없으면 대구 야채 전체에서.
    outlook: {재료: 다음 7일 예상 변화율 %} — 대시보드가 이미 계산했으면 받아 씀."""
    import analysis
    import receipts
    mine = None
    if store_id:
        try:
            mine = set(receipts.my_ingredients(store_id)["items"])
        except Exception:
            mine = None
    names = [n for n in analysis.ITEMS if not mine or n in mine]
    if outlook is None:
        outlook = {}
        for n in names:
            try:
                outlook[n] = analysis.forecast_item(n).get("expected_change_pct")
            except Exception:
                pass
    pairs = [(n, outlook.get(n)) for n in names if outlook.get(n) is not None]
    up = sorted((p for p in pairs if p[1] >= RISE), key=lambda p: -p[1])[:3]
    down = sorted((p for p in pairs if p[1] <= FALL), key=lambda p: p[1])[:2]
    day = datetime.now(KST)
    lines = [f"[살피] {day.month}/{day.day} 아침 시세 알림"]
    if up:
        lines.append("오를 것 같아요: " + ", ".join(f"{n} {v:+.0f}%" for n, v in up) + " → 필요한 만큼 미리 사 두세요")
    if down:
        lines.append("내릴 것 같아요: " + ", ".join(f"{n} {v:+.0f}%" for n, v in down) + " → 급하지 않으면 기다려 보세요")
    if not up and not down:
        lines.append("다음 7일 크게 움직일 재료는 없어요. 평소대로 사면 돼요")
    if store_id:
        try:
            high = [m for m in receipts.cost_report(store_id)["menus"] if m.get("high")]
            if high:
                lines.append("원가율 40% 넘은 메뉴: " + ", ".join(f"{m['menu']} {m['cost_ratio_pct']}%" for m in high[:2]))
        except Exception:
            pass
    lines.append(("내 메뉴 재료 · " if mine else "") + "대구 도매 7일 예측 기준")
    text = "\n".join(lines)
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1] + "…"


def send_to(user, outlook=None):
    store_id = (user.get("user_metadata") or {}).get("store_id")
    text = message(store_id, outlook)
    access, user = _access(user)
    _send(access, text)
    talk = (user.get("app_metadata") or {}).get("kakao_talk") or {}
    _save(user, {**talk, "last_sent": datetime.now(KST).isoformat(timespec="minutes"), "last_error": None})
    return text


def test(token):
    """마이페이지 '지금 보내 보기'."""
    user = auth.user_of(token)
    if not ((user.get("app_metadata") or {}).get("kakao_talk") or {}).get("refresh_token"):
        raise auth.AuthError("먼저 카카오로 다시 로그인해서 '카카오톡 메시지 전송'에 동의해 주세요.")
    return {"sent": True, "text": send_to(_admin_user(user["id"]))}


def _admin_user(user_id):
    r = auth._call("GET", f"admin/users/{user_id}", admin=True)
    if not r.ok:
        raise ApiError(f"계정을 읽지 못했어요 ({r.status_code})")
    return r.json()


def send_all(outlook=None):
    """매일 아침: 알림을 켠 카카오 계정 모두에게. 한 명이 실패해도 나머지는 보냄."""
    if not os.getenv("KAKAO_REST_API_KEY", "").strip():
        return {"kakao_sent": 0, "kakao_skipped": "KAKAO_REST_API_KEY 없음"}
    sent, failed = 0, 0
    for u in auth._users():
        talk = (u.get("app_metadata") or {}).get("kakao_talk") or {}
        if not talk.get("on") or not talk.get("refresh_token"):
            continue
        if (talk.get("last_sent") or "")[:10] == datetime.now(KST).date().isoformat():
            continue   # 오늘 이미 보냄 (예약 실행이 두 번 돌거나 누가 주소를 또 불러도 하루 한 번)
        try:
            send_to(u, outlook)
            sent += 1
        except Exception as e:
            failed += 1
            print(f"[카카오 알림] {u['id'][:8]} 실패: {e}", flush=True)
            try:
                _save(u, {**talk, "last_error": str(e)[:200]})
            except Exception:
                pass
    return {"kakao_sent": sent, "kakao_failed": failed}
