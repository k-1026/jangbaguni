"""싸게/비싸게 판정 — GET /api/price-judge?purchase_id=12 (없으면 가장 최근 영수증).

영수증 한 장의 품목마다 산 값(기준 단위당)을 두 가지와 비교한다. 숫자는 모두 계산 (AI 없음)
  1) 우리 가게 평소 단가: 그 영수증 앞 영수증 8장까지의 가운데값 (3장 이상 있을 때)
  2) 대구 시세 (야채만, 영수증 날짜가 시세 날짜와 10일 안쪽일 때): 북부도매시장 도매가 · 대구 소매 평균(KAMIS)

판정 (단위 기준 plan/1116_final_sprint_plan.md 2-2: 10% 안쪽은 "비슷해요")
  비싸게 샀어요  : 동네 소매 평균보다도 비쌈 (가게는 보통 소매가보다 싸게 삼), 또는 평소보다 10% 넘게 비싼데 비교할 시세가 없음
  시세가 올랐어요: 평소보다 10% 넘게 비싸지만 소매 평균보다는 쌈 → 가게 탓이 아니라 시세가 오른 것 (더 낸 돈으로 치지 않음)
  싸게 샀어요    : 평소보다 10% 넘게 쌈
  비슷해요     : 그 밖
  평소 단가가 없고 시세만 있으면 소매 평균과만 비교, 둘 다 없으면 "비교할 값 없음"
비싸게 산 품목은 '평소 단가로 샀다면 얼마 덜 냈는지'(더 낸 돈)를 같이 준다 → 원가 · 마진 에이전트가 더 싼 판매처 · 대체 재료로 이어 감
"""
import statistics
from datetime import date

import receipts
import supabase_db as db
from analysis import ITEMS, item_trend

BAND_PCT = 10
USUAL_N = 8
MARKET_DAYS = 10


def _pct(a, b):
    return round((a / b - 1) * 100, 1) if a and b else None


def _market(name, day, cache):
    """야채 시세 {"wholesale", "retail", "date"} — 영수증 날짜와 10일 넘게 떨어지면 None."""
    if name not in ITEMS:
        return None
    if name not in cache:
        try:
            t = item_trend(name)
            cache[name] = {"wholesale": t["wholesale"]["kg_price"], "date": t["wholesale"]["date"],
                           "retail": t["retail"]["base_price"] if t["retail"].get("base_how") != "모름" else None,
                           "retail_approx": t["retail"].get("base_how") == "약"}
        except Exception as e:   # 시세 API 문제 → 시세 비교만 빠짐
            print(f"[단가 판정] {name} 시세 실패: {e}", flush=True)
            cache[name] = None
    m = cache[name]
    if not m or not m.get("date"):
        return None
    if abs((date.fromisoformat(str(m["date"])[:10]) - date.fromisoformat(day)).days) > MARKET_DAYS:
        return None
    return m


def _verdict(price, usual, market):
    vs_usual = _pct(price, usual)
    vs_retail = _pct(price, market["retail"]) if market and market.get("retail") else None
    approx = bool(market and market.get("retail_approx"))   # 소매가가 포기 · 개 → kg 환산이면 10% 넘어야 비싸다고 봄
    if vs_retail is not None and vs_retail > (BAND_PCT if approx else 0):
        return "비싸게 샀어요", (f"대구 소매 평균{'(환산)' if approx else ''}보다도 {vs_retail:+.0f}%"
                                + (f" · 평소보다 {vs_usual:+.0f}%" if vs_usual is not None else ""))
    if vs_usual is not None and vs_usual > BAND_PCT:
        if vs_retail is not None:   # 평소보다 비싸지만 동네 소매가보다는 쌈 → 가게가 비싸게 산 게 아니라 시세가 오른 것
            return "시세가 올랐어요", f"평소보다 {vs_usual:+.0f}%지만 대구 소매 평균보다 {vs_retail:+.0f}% (시세가 오른 탓)"
        return "비싸게 샀어요", f"우리 가게 평소보다 {vs_usual:+.0f}%"
    if vs_usual is not None and vs_usual < -BAND_PCT:
        return "싸게 샀어요", f"우리 가게 평소보다 {vs_usual:+.0f}%"
    if vs_usual is None and vs_retail is None:
        return "비교할 값 없음", "이 재료는 아직 영수증이 적고 시세도 없어요"
    if vs_usual is not None:
        return "비슷해요", f"우리 가게 평소와 {vs_usual:+.0f}% 차이 (10% 안쪽)"
    return "비슷해요", f"대구 소매 평균보다 {vs_retail:+.0f}%"


def judge(store_id=db.DEMO_STORE, purchase_id=None):
    if purchase_id is None:
        latest = db.select("purchases", store_id=f"eq.{store_id}", select="id", order="purchased_on.desc,id.desc", limit="1")
        if not latest:
            return {"error": "저장한 영수증이 없어요"}
        purchase_id = latest[0]["id"]
    ps = db.select("purchases", id=f"eq.{purchase_id}", store_id=f"eq.{store_id}", select="id,purchased_on,supplier")
    if not ps:
        raise ValueError("영수증을 찾지 못했어요")
    p = ps[0]
    day = p["purchased_on"]
    rows = db.select("purchase_items", purchase_id=f"eq.{purchase_id}", order="id",
                     select="id,raw_name,item_id,qty_base,amount,unit_price_base,items(name,base_unit)")
    hist = receipts._price_history(store_id)
    cache, lines = {}, []
    for r in rows:
        if not r["item_id"] or not r["unit_price_base"]:
            continue
        name, unit = r["items"]["name"], r["items"]["base_unit"]
        price = float(r["unit_price_base"])
        before = [v for d, v in hist.get(r["item_id"], []) if d < day][-USUAL_N:]
        usual = statistics.median(before) if len(before) >= 3 else None
        market = _market(name, day, cache)
        verdict, why = _verdict(price, usual, market)
        extra = round((price - usual) * float(r["qty_base"])) if usual and verdict == "비싸게 샀어요" and price > usual else 0
        saved = round((usual - price) * float(r["qty_base"])) if usual and verdict == "싸게 샀어요" else 0
        lines.append({
            "line_id": r["id"], "raw_name": r["raw_name"], "item": name, "unit": unit, "qty_base": float(r["qty_base"]),
            "amount": r["amount"], "unit_price": round(price), "usual_price": round(usual) if usual else None,
            "usual_receipts": len(before), "vs_usual_pct": _pct(price, usual),
            "wholesale_price": round(market["wholesale"]) if market and market.get("wholesale") else None,
            "retail_price": round(market["retail"]) if market and market.get("retail") else None,
            "market_date": str(market["date"])[:10] if market else None,
            "verdict": verdict, "why": why, "extra_paid": extra, "saved": saved,
        })
    order = {"비싸게 샀어요": 0, "시세가 올랐어요": 1, "싸게 샀어요": 2, "비슷해요": 3, "비교할 값 없음": 4}
    lines.sort(key=lambda x: (order[x["verdict"]], -x["extra_paid"]))
    return {"purchase_id": p["id"], "date": day, "supplier": p["supplier"], "lines": lines,
            "summary": {"expensive": sum(x["verdict"] == "비싸게 샀어요" for x in lines),
                        "market_up": sum(x["verdict"] == "시세가 올랐어요" for x in lines),
                        "cheap": sum(x["verdict"] == "싸게 샀어요" for x in lines),
                        "similar": sum(x["verdict"] == "비슷해요" for x in lines),
                        "extra_paid": sum(x["extra_paid"] for x in lines), "saved": sum(x["saved"] for x in lines)},
            "method": f"품목마다 산 값(기준 단위당)을 우리 가게 평소 단가(앞 영수증 {USUAL_N}장까지의 가운데값) · "
                      f"대구 시세(야채, 영수증 날짜와 {MARKET_DAYS}일 안쪽)와 비교. {BAND_PCT}% 안쪽은 비슷해요"}
