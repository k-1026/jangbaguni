"""예측 기록 · 7일 뒤 채점 · 식봄 판매가 기록 (Supabase forecast_log · price_snapshots).

- record: 그날 화면에 나간 7일 예측을 그대로 저장. 같은 날 · 품목은 처음 저장한 값을 바꾸지 않음
- score : 기준 날짜에서 7일이 지난 예측을 실제 가격과 비교해 채점 (범위 안? 방향 맞음?)
- snapshot_shop: 식봄 재료별 상품 판매가를 하루 한 번 저장 (도매 시세보다 며칠 늦게 따라가는지 비교용)
- scorecard: 최근 몇 주 채점 결과 요약 (화면 적중률 표시용)

모두 서버가 이미 계산한 대시보드 결과(/api/overview · /api/meat-seafood)를 받아 씀 → 시세 API를 더 부르지 않음.
채점 기준은 backtest.py 와 같음: 방향 ±2%, 실제 = 기준 날짜 + 7일 이후 첫 시세 날짜(3일 안).
"""

from datetime import date, datetime, timedelta, timezone

import supabase_db
from analysis import FORMULA_VERSION

KST = timezone(timedelta(hours=9))
BAND = 2.0          # 오를 · 유지 · 내릴 기준 (화면 문구와 같음)
LOOK_AHEAD = 3      # 7일 뒤 시세가 없으면 사흘 안의 첫 시세로 채점


def today():
    return datetime.now(KST).date()


def _direction(pct):
    return "up" if pct >= BAND else "down" if pct <= -BAND else "flat"


def _rows_for_log(veg_rows, extra_rows):
    """대시보드 결과 → forecast_log 줄. 제철이 아니라 거래가 적은 과일(화면에서 숨김)은 빼고 저장."""
    run, out = today().isoformat(), []
    for r in veg_rows or []:
        f = r.get("forecast") or {}
        if f.get("error") or not f.get("base_kg_price") or len(r.get("history") or []) < 8:
            continue
        lo, hi = f.get("expected_kg_price_range") or (None, None)
        out.append({"run_date": run, "item": r["item"], "kind": r.get("kind", "야채"), "base_date": f["base_date"],
                    "base_price": f["base_kg_price"], "unit": "kg", "expected_change_pct": f["expected_change_pct"],
                    "range_low": lo, "range_high": hi, "direction": _direction(f["expected_change_pct"]),
                    "factors": [{"factor": x["factor"], "effect_pct": x["effect_pct"]} for x in f.get("factors", [])],
                    "formula_version": FORMULA_VERSION})
    for r in extra_rows or []:
        f = r.get("forecast") or {}
        if f.get("error") or not f.get("base_price"):
            continue
        lo, hi = f.get("expected_price_range") or (None, None)
        out.append({"run_date": run, "item": r["item"], "kind": r.get("group", ""), "base_date": f["base_date"],
                    "base_price": f["base_price"], "unit": f.get("unit") or "kg", "expected_change_pct": f["expected_change_pct"],
                    "range_low": lo, "range_high": hi, "direction": _direction(f["expected_change_pct"]),
                    "factors": [{"factor": x["factor"], "effect_pct": x["effect_pct"]} for x in f.get("factors", [])],
                    "formula_version": FORMULA_VERSION})
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
    due = supabase_db.select("forecast_log", actual_price="is.null", base_date=f"lte.{(today() - timedelta(7)).isoformat()}",
                             select="run_date,item,base_date,base_price,range_low,range_high,direction")
    hist, done = _histories(veg_rows, extra_rows), 0
    for row in due:
        target = date.fromisoformat(row["base_date"]) + timedelta(7)
        hit = next(((d, p) for d, p in hist.get(row["item"], []) if target <= date.fromisoformat(d) <= target + timedelta(LOOK_AHEAD)), None)
        if not hit:
            continue   # 아직 시세가 안 올라왔거나 그날 거래가 없음 → 다음에 다시
        d, p = hit
        change = (p / float(row["base_price"]) - 1) * 100
        lo, hi = row.get("range_low"), row.get("range_high")
        supabase_db.update("forecast_log", {
            "actual_date": d, "actual_price": p, "actual_change_pct": round(change, 2),
            "in_range": (float(lo) <= p <= float(hi)) if lo is not None and hi is not None else None,
            "direction_hit": _direction(change) == row["direction"],
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
    rows = supabase_db.select("forecast_log", actual_date=f"gte.{since}", direction_hit="not.is.null",
                              select="item,kind,direction,actual_change_pct,direction_hit,in_range,formula_version")

    def summary(group):
        n = len(group)
        if not n:
            return {"n": 0}
        opp = sum(1 for r in group if {r["direction"], _direction(float(r["actual_change_pct"]))} == {"up", "down"})
        ranged = [r for r in group if r["in_range"] is not None]
        return {"n": n, "direction_hit_pct": round(sum(r["direction_hit"] for r in group) / n * 100, 1),
                "in_range_pct": round(sum(r["in_range"] for r in ranged) / len(ranged) * 100, 1) if ranged else None,
                "opposite_pct": round(opp / n * 100, 1)}

    by_kind, by_item = {}, {}
    for r in rows:
        by_kind.setdefault(r["kind"], []).append(r)
        by_item.setdefault(r["item"], []).append(r)
    return {"weeks": weeks, "since": since, "formula_version": FORMULA_VERSION, "all": summary(rows),
            "kinds": {k: summary(v) for k, v in by_kind.items()},
            "items": {k: {**summary(v), "kind": v[0]["kind"]} for k, v in by_item.items()},
            "note": "채점은 기준 날짜 + 7일 이후 첫 시세와 비교. 방향은 ±2% 기준 (오를 · 유지 · 내릴)"}
