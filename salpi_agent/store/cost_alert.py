"""시세가 바뀌면 원가율 다시 계산 → 원가율 알림 (F6, 11/25).

매일 아침 새 시세 예측이 나온 뒤(POST /api/jobs/alerts · /api/jobs/cost-alerts) 메뉴별 원가율 · 다음 주 예상 원가율을
새 시세로 다시 계산하고, **어제 계산(보관함 cache/cost_snapshot_<가게>.json)과 비교해 새로 생긴 일만** 알림으로 만든다.

알림 종류 (메뉴마다 하루 최대 1개, 위에서부터 먼저)
  넘음      지금 원가율이 40% 이상이 됨 (어제는 아래)
  넘을 예정  지금은 40% 아래인데 다음 주 예상이 40% 이상이 됨 (어제 예상은 아래)          → "다른 재료 어때?"
  오름      다음 주 예상 원가율이 어제 예상보다 3%p 넘게 오름 (40%는 아직 안 넘음)         → "다른 재료 어때?"
  내려옴     어제는 40% 이상(지금 또는 다음 주)이었는데 오늘은 둘 다 아래
- 문장은 살피 말투로 '정보 1개 + 행동 1개' (schema.sql alerts.message). 숫자는 모두 원가율 계산(receipts.cost_report) 결과
- 행동: 바꿀 재료가 있으면 "○ 절반을 △로 바꾸면 …" (대체 재료), 없으면 판매가 제안 → 그것도 없으면 "영수증 단가를 확인"
- 만든 알림은 Supabase alerts(kind='원가율')에 남김 → 화면(GET /api/cost-alerts) · 아침 앱 · 카카오톡 알림이 읽음
- 어제 계산이 없으면(처음) 지금 40% 이상 · 다음 주 40% 이상인 메뉴를 알림
"""
import json
from datetime import datetime, timedelta, timezone

from sources import supabase_db as db
from store import receipts

KST = timezone(timedelta(hours=9))
TARGET = receipts.TARGET_RATIO
RISE_PP = 3.0          # 다음 주 예상이 어제보다 이만큼(%p) 넘게 오르면 알림
BUCKET = "models"


def _today():
    return datetime.now(KST).date()


def _snap_path(store_id):
    return f"cache/cost_snapshot_{store_id}.json"


def _load_snapshot(store_id):
    try:
        raw = db.download(BUCKET, _snap_path(store_id))
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _save_snapshot(store_id, report):
    snap = {"date": _today().isoformat(),
            "menus": {str(m["menu_id"]): {"menu": m["menu"], "ratio": m["cost_ratio_pct"], "next": m["next_ratio_pct"]}
                      for m in report["menus"]}}
    db.upload(BUCKET, _snap_path(store_id), json.dumps(snap, ensure_ascii=False).encode("utf-8"), "application/json")


def _high(ratio, nxt):
    return (ratio or 0) >= TARGET or (nxt or 0) >= TARGET


def _kind(m, before):
    """메뉴 하나 → 알림 종류 (없으면 None)."""
    r, n = m["cost_ratio_pct"], m["next_ratio_pct"]
    if r is None:
        return None
    if before is None:   # 처음 계산: 지금 높은 메뉴만
        return "넘음" if r >= TARGET else "넘을 예정" if (n or 0) >= TARGET else None
    br, bn = before.get("ratio"), before.get("next")
    if r >= TARGET and (br or 0) < TARGET:
        return "넘음"
    if r < TARGET and (n or 0) >= TARGET and (bn or 0) < TARGET and (br or 0) < TARGET:
        return "넘을 예정"
    if n is not None and bn is not None and n - bn > RISE_PP and n < TARGET and r < TARGET:
        return "오름"
    if _high(br, bn) and not _high(r, n):
        return "내려옴"
    return None


def _action(m):
    """행동 한 줄: 대체 재료 → 판매가 → 영수증 확인."""
    sw = m.get("swap")
    if sw and sw.get("new_ratio_pct") is not None:
        return (f"{sw['from']} 절반을 {receipts._josa(sw['to'], '으로', '로')} 바꾸면 1인분 {sw['saving_per_serving']:,}원 아껴 "
                f"{sw['new_ratio_pct']}%예요. 다른 재료 어때요?")
    pu = m.get("price_up")
    if pu:
        return f"판매가를 {pu['price']:,}원으로 {pu['raise']:,}원 올리면 {pu['new_ratio_pct']}%예요"
    return "최근 영수증 단가가 맞는지 한번 봐 주세요"


def _why(m):
    up = m.get("next_up")
    if up:
        return f"다음 주 {receipts._josa(up['item'], '이', '가')} {up['change_pct']:+.0f}% 오를 것 같아 "
    return ""


def _message(kind, m, before):
    name, r, n = m["menu"], m["cost_ratio_pct"], m["next_ratio_pct"]
    if kind == "넘음":
        return f"{receipts._josa(name, '은', '는')} 원가율이 {r}%로 {TARGET}%를 넘었어요. {_action(m)}"
    if kind == "넘을 예정":
        return f"{_why(m)}{name} 원가율이 {r}% → {n}%로 {TARGET}%를 넘을 것 같아요. {_action(m)}"
    if kind == "오름":
        return f"{_why(m)}{name} 다음 주 원가율이 {before.get('next')}% → {n}%로 올라요. {_action(m)}"
    return f"{name} 원가율이 {r}%로 {TARGET}% 아래로 내려왔어요. 지금 값대로 팔아도 괜찮아요"


def check(store_id=db.DEMO_STORE, forecasts=None, save=True):
    """새 시세로 원가율 다시 계산 → 어제와 비교해 알림. → {"date", "alerts": [...], "report": 원가율 계산 결과, "first": 어제 계산 없음}
    save=False 면 알림 · 오늘 계산을 저장하지 않음 (미리 보기)."""
    report = receipts.cost_report(store_id, forecasts)
    snap = _load_snapshot(store_id)
    first = not snap
    if snap and snap.get("date") == _today().isoformat():
        prev = None   # 오늘 이미 비교함 → 다시 알리지 않음 (예약 실행이 두 번 돌아도 하루 한 번)
    else:
        prev = (snap or {}).get("menus", {})
    alerts = []
    if prev is not None:
        for m in report["menus"]:
            before = None if first else prev.get(str(m["menu_id"]))
            if not first and before is None:
                continue   # 새로 추가한 메뉴는 다음 날부터 비교
            kind = _kind(m, before)
            if kind:
                alerts.append({"menu_id": m["menu_id"], "menu": m["menu"], "kind": kind,
                               "ratio": m["cost_ratio_pct"], "next_ratio": m["next_ratio_pct"],
                               "before": before, "swap": m.get("swap"), "next_up": m.get("next_up"),
                               "message": _message(kind, m, before or {})})
    if save:
        if alerts:
            db.insert("alerts", [{"store_id": store_id, "kind": "원가율", "message": a["message"]} for a in alerts])
        if prev is not None:
            _save_snapshot(store_id, report)
    return {"date": _today().isoformat(), "first": first, "already_checked": prev is None, "alerts": alerts, "report": report}


def recent(store_id=db.DEMO_STORE, days=7):
    """최근 days일 원가율 알림 (새것부터) — 화면 말풍선 · 아침 알림용."""
    since = (datetime.now(KST) - timedelta(days=days)).isoformat()
    rows = db.select("alerts", store_id=f"eq.{store_id}", kind="eq.원가율", sent_at=f"gte.{since}",
                     select="id,message,sent_at,clicked_at", order="sent_at.desc,id.desc", limit="30")
    return {"days": days, "alerts": rows}


def today_messages(store_id):
    """오늘 만든 원가율 알림 문장들 (아침 앱 · 카카오톡 알림에 붙임)."""
    start = datetime.combine(_today(), datetime.min.time(), KST).isoformat()
    rows = db.select("alerts", store_id=f"eq.{store_id}", kind="eq.원가율", sent_at=f"gte.{start}",
                     select="message", order="id")
    return [r["message"] for r in rows]
