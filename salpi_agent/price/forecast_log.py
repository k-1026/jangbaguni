"""예측 기록 · 7일 뒤 채점 · 식봄 판매가 기록 (Supabase forecast_log · price_snapshots).

- record: 그날 화면에 나간 7일 예측을 그대로 저장. 같은 날 · 품목은 처음 저장한 값을 바꾸지 않음
- score : 기준 날짜에서 7일이 지난 예측을 실제 가격과 비교해 채점 (범위 안? 방향 맞음?)
- snapshot_shop: 식봄 재료별 상품 판매가를 하루 한 번 저장 (도매 시세보다 며칠 늦게 따라가는지 비교용)
- scorecard: 최근 몇 주 채점 결과 요약 (화면 적중률 표시용, 품목 · 기준 날짜마다 한 번만 셈)

모두 서버가 이미 계산한 대시보드 결과(/api/overview · /api/meat-seafood)를 받아 씀 → 시세 API를 더 부르지 않음.
채점 기준은 backtest.py 와 같음: 방향 ±2%, 실제 = 기준 날짜 + 7일 이후 첫 시세 날짜(3일 안).
주 평균 모델(formula_version 'ai-week-…', 11/25~): 실제 = 기준 날짜 다음 날 ~ 7일 시세 평균, 기준 값 = 이번 주 평균.
  확신이 없어 방향을 말하지 않은 예측(화면 'unsure', 표에는 direction 'flat' 으로 저장 — 표의 check 제약 때문)은
  방향 채점에서 빼고, 말한 비율을 따로 셈
  다음 주 거래일이 WEEK_MIN_DAYS(4)일 이상 모이면 먼저 채점(잠정)하고, 7일이 다 차면 그 평균으로 다시 채점(확정)
  — 주 평균 모델 첫 채점을 12/2 오전에 보이게 (7일을 다 기다리면 시세가 하루 넘게 늦게 올라와 12/4 ~ 12/5)
- scorecard: 야채 · 과일은 주 평균 모델 채점이 하나라도 있으면 그 종류는 주 평균 모델만 셈 (예전 '7일 뒤 하루 값' 모델과 섞지 않음)
"""

from datetime import date, datetime, timedelta, timezone

from sources import supabase_db
from price.analysis import FORMULA_VERSION

KST = timezone(timedelta(hours=9))
BAND = 2.0          # 오를 · 유지 · 내릴 기준 (화면 문구와 같음)
LOOK_AHEAD = 3      # 7일 뒤 시세가 없으면 사흘 안의 첫 시세로 채점
WEEK_MIN_DAYS = 4   # 주 평균 모델: 다음 주 거래일이 이만큼 모이면 먼저 채점 (잠정)
SURE_PCT = 8.0      # 확신 높은 예측: 예측 폭이 이만큼 이상 (11/27 실전 기록: 방향 맞음 83.3% · 예측의 14%, plan/forecast/1127_accuracy_80.md)


def today():
    return datetime.now(KST).date()


def _direction(pct):
    return "up" if pct >= BAND else "down" if pct <= -BAND else "flat"


def _is_week(row):
    return str(row.get("formula_version") or "").startswith("ai-week")


def _unstated(row):
    """주 평균 모델이 방향을 말하지 않은 예측 (화면 '크게 바뀌지 않을 것 같아요')."""
    return str(row.get("formula_version") or "").startswith("ai-week") and row["direction"] == "flat"


def _rows_for_log(veg_rows, extra_rows):
    """대시보드 결과 → forecast_log 줄. 제철이 아니라 거래가 적은 과일(화면에서 숨김)은 빼고 저장."""
    run, out = today().isoformat(), []
    for r in veg_rows or []:
        f = r.get("forecast") or {}
        if f.get("error") or not f.get("base_kg_price") or len(r.get("history") or []) < 8:
            continue
        lo, hi = f.get("expected_kg_price_range") or (None, None)
        week = f.get("week_change_pct") is not None   # 주 평균 모델: 기준 = 이번 주 평균, % = 다음 주 평균 ÷ 이번 주 평균
        out.append({"run_date": run, "item": r["item"], "kind": r.get("kind", "야채"), "base_date": f["base_date"],
                    "base_price": f["base_week_avg"] if week else f["base_kg_price"], "unit": "kg",
                    "expected_change_pct": f["week_change_pct"] if week else f["expected_change_pct"],
                    "range_low": lo, "range_high": hi,
                    "direction": ("flat" if f["direction_code"] == "unsure" else f["direction_code"]) if week
                                 else _direction(f["expected_change_pct"]),
                    "factors": [{"factor": x["factor"], "effect_pct": x["effect_pct"]} for x in f.get("factors", [])],
                    "formula_version": f.get("version") or FORMULA_VERSION})
    for r in extra_rows or []:
        f = r.get("forecast") or {}
        if f.get("error") or not f.get("base_price"):
            continue
        lo, hi = f.get("expected_price_range") or (None, None)
        out.append({"run_date": run, "item": r["item"], "kind": r.get("group", ""), "base_date": f["base_date"],
                    "base_price": f["base_price"], "unit": f.get("unit") or "kg", "expected_change_pct": f["expected_change_pct"],
                    "range_low": lo, "range_high": hi, "direction": _direction(f["expected_change_pct"]),
                    "factors": [{"factor": x["factor"], "effect_pct": x["effect_pct"]} for x in f.get("factors", [])],
                    "formula_version": f.get("version") or FORMULA_VERSION})
    return out


def record(veg_rows, extra_rows):
    rows = _rows_for_log(veg_rows, extra_rows)
    supabase_db.insert_ignore("forecast_log", rows, "run_date,item")
    return len(rows)


def _histories(veg_rows, extra_rows):
    """품목 → [(날짜, 가격)] (대시보드가 이미 받아 둔 4~5주 기록)."""
    out = {}
    for r in veg_rows or []:
        out[r["item"]] = [(h["date"], h["kg_price"]) for h in r.get("history") or [] if h.get("kg_price")]
    for r in extra_rows or []:
        out[r["item"]] = [(h["date"], h["price"]) for h in r.get("history") or [] if h.get("price")]
    return out


def score(veg_rows, extra_rows):
    """기준 날짜에서 7일이 지난, 아직 채점 안 한 예측을 채점. 채점한 줄 수를 돌려줌."""
    hist, done = _histories(veg_rows, extra_rows), 0
    starts = [date.fromisoformat(h[0][0]) for h in hist.values() if h]
    if not starts:
        return 0
    # 대시보드 기록(4~5주)보다 오래된 예측은 7일 뒤 시세가 없어 채점할 수 없음 → 매번 다시 찾지 않게 뺌
    oldest = min(starts) - timedelta(7)
    cols = "run_date,item,base_date,base_price,range_low,range_high,direction,formula_version,actual_date"
    due = supabase_db.select("forecast_log", actual_price="is.null",
                             **{"and": f"(base_date.gte.{oldest.isoformat()},base_date.lte.{(today() - timedelta(WEEK_MIN_DAYS)).isoformat()})"},
                             select=cols)
    # 주 평균 모델의 잠정 채점(7일이 다 안 찬 것)은 거래일이 더 모이면 다시 채점
    due += [r for r in supabase_db.select("forecast_log", actual_price="not.is.null", formula_version="like.ai-week*",
                                          base_date=f"gte.{(today() - timedelta(21)).isoformat()}", select=cols)
            if date.fromisoformat(r["actual_date"]) < date.fromisoformat(r["base_date"]) + timedelta(7)]
    for row in due:
        base_day = date.fromisoformat(row["base_date"])
        target = base_day + timedelta(7)
        if _is_week(row):
            # 주 평균: 다음 날 ~ 7일 시세 평균. 거래일 WEEK_MIN_DAYS일 이상이면 잠정, 7일 뒤 시세가 올라오면 확정
            pts = [(d, p) for d, p in hist.get(row["item"], []) if base_day < date.fromisoformat(d) <= target]
            later = any(date.fromisoformat(d) > target for d, _ in hist.get(row["item"], []))
            if len(pts) < WEEK_MIN_DAYS and not (later and len(pts) >= 2):
                continue
            if later or target <= date.fromisoformat(pts[-1][0]):
                pts_date = target.isoformat()   # 확정: 실제 날짜를 목표일로 적어 다시 채점하지 않음
            else:
                pts_date = pts[-1][0]
            if row.get("actual_date") == pts_date:
                continue   # 새로 모인 거래일이 없음
            hit = (pts_date, round(sum(p for _, p in pts) / len(pts)))
        elif date.fromisoformat(row["base_date"]) > today() - timedelta(7):
            continue   # 예전 모델은 7일이 지나야 채점
        else:
            hit = next(((d, p) for d, p in hist.get(row["item"], []) if target <= date.fromisoformat(d) <= target + timedelta(LOOK_AHEAD)), None)
        if not hit:
            continue   # 아직 시세가 안 올라왔거나 그날 거래가 없음 → 다음에 다시
        d, p = hit
        change = (p / float(row["base_price"]) - 1) * 100
        lo, hi = row.get("range_low"), row.get("range_high")
        supabase_db.update("forecast_log", {
            "actual_date": d, "actual_price": p, "actual_change_pct": round(change, 2),
            "in_range": (float(lo) <= p <= float(hi)) if lo is not None and hi is not None else None,
            "direction_hit": None if _unstated(row) else _direction(change) == row["direction"],
            "scored_at": datetime.now(timezone.utc).isoformat(),
        }, run_date=f"eq.{row['run_date']}", item=f"eq.{row['item']}")
        done += 1
    return done


def snapshot_shop(shop):
    """식봄 재료별 상품 판매가 (foodspring.all_products 결과) 하루 한 번."""
    snap, rows = today().isoformat(), []
    for item, goods in (shop or {}).items():
        for g in goods or []:
            if g.get("url") and g.get("sale_price"):
                rows.append({"snap_date": snap, "source": "식봄", "item": item, "product_name": g.get("name") or "",
                             "url": g["url"], "sale_price": g["sale_price"], "original_price": g.get("original_price"),
                             "kg": g.get("kg"), "price_per_kg": g.get("price_per_kg")})
    supabase_db.insert_ignore("price_snapshots", rows, "snap_date,source,url")
    return len(rows)


def scorecard(weeks=4):
    """최근 weeks주 동안 채점된 예측 요약: 종류별 · 품목별 방향 적중 · 범위 적중 · 정반대 비율."""
    since = (today() - timedelta(weeks * 7)).isoformat()
    rows = supabase_db.select("forecast_log", actual_date=f"gte.{since}", actual_price="not.is.null",
                              select="item,kind,base_date,run_date,direction,expected_change_pct,actual_change_pct,direction_hit,in_range,formula_version")
    # 주말 · 휴장일에는 같은 기준 날짜로 만든 예측이 여러 날 저장됨 → 품목 · 기준 날짜마다 처음 저장한 것 하나만 셈
    first = {}
    for r in sorted(rows, key=lambda r: r["run_date"]):
        first.setdefault((r["item"], r["base_date"]), r)
    rows = list(first.values())
    # 야채 · 과일: 주 평균 모델 채점이 있으면 그 종류는 주 평균 모델만 (11/26 바꾼 새 방식으로 예측률을 보여 줌)
    week_kinds = {r["kind"] for r in rows if _is_week(r)}
    rows = [r for r in rows if _is_week(r) or r["kind"] not in week_kinds]

    def summary(group):
        if not group:
            return {"n": 0}
        said = [r for r in group if not _unstated(r)]   # 방향을 말한 예측만 방향 채점 (주 평균 모델의 '크게 안 바뀔 듯'은 뺌)
        n = len(said)
        opp = sum(1 for r in said if {r["direction"], _direction(float(r["actual_change_pct"]))} == {"up", "down"})
        ranged = [r for r in group if r["in_range"] is not None]
        sure = [r for r in said if abs(float(r.get("expected_change_pct") or 0)) >= SURE_PCT]
        return {"n": n, "direction_hit_pct": round(sum(bool(r["direction_hit"]) for r in said) / n * 100, 1) if n else None,
                "in_range_pct": round(sum(r["in_range"] for r in ranged) / len(ranged) * 100, 1) if ranged else None,
                "opposite_pct": round(opp / n * 100, 1) if n else None,
                "stated_share_pct": round(n / len(group) * 100, 1), "scored": len(group),
                "sure": {"n": len(sure), "share_pct": round(len(sure) / len(group) * 100, 1),
                         "direction_hit_pct": round(sum(bool(r["direction_hit"]) for r in sure) / len(sure) * 100, 1) if sure else None}}

    weekly = summary([r for r in rows if _is_week(r)])
    by_kind, by_item = {}, {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r)
        by_item.setdefault(r["item"], []).append(r)
    return {"weeks": weeks, "since": since, "formula_version": FORMULA_VERSION, "all": summary(rows),
            "kinds": {k: summary(v) for k, v in by_kind.items()},
            "items": {k: {**summary(v), "kind": v[0]["kind"]} for k, v in by_item.items()},
            "week_model": weekly, "week_kinds": sorted(week_kinds),
            "note": "채점은 기준 날짜 + 7일 이후 첫 시세와 비교. 방향은 ±2% 기준 (오를 · 유지 · 내릴). "
                    "주 평균 모델(ai-week)은 다음 주 평균과 비교하고, 방향을 말한 예측만 방향을 채점 (stated_share_pct = 말한 비율)"}
