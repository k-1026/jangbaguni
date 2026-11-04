"""영수증 사진 → 품목 · 수량 · 금액 읽기(Gemini) → 사장님 확인 → Supabase 저장 → 메뉴 원가율 다시 계산.

- 읽기만 AI가 하고, 원가율 · 판단 · 제안 숫자는 규칙으로 계산한다 (LLM은 숫자를 만들지 않는다)
- 사진은 Supabase Storage 비공개 보관함(receipts)에, 읽은 내용은 purchases · purchase_items 에 저장
- 사장님이 고친 '영수증 이름 → 재료' 짝은 item_aliases 에 쌓아 다음부터 바로 맞춤
"""

import json
import math
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

from google import genai
from google.genai import errors, types

import supabase_db as db
from data_sources import ApiKeyMissing

KST = timezone(timedelta(hours=9))
MODELS = [os.getenv("GEMINI_MODEL", "gemini-3.5-flash")] + [
    m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3-flash-preview,gemini-flash-latest,gemini-3.5-flash-lite").split(",")
    if m.strip()]
TARGET_RATIO = 30   # 목표 원가율(%)
# 대체 재료 후보 (값이 오르면 검토해 볼 만한 것만, 판단은 사장님이)
SUBSTITUTES = {"양파": "양배추", "대파": "쪽파 · 양파", "애호박": "감자 · 무", "돼지고기 앞다리": "돼지고기 뒷다리",
               "청양고추": "건고추 · 고춧가루", "감자": "무"}


def _norm(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def _josa(word, with_batchim, without):
    """받침에 따라 조사 고르기 (애호박이 / 양파가)."""
    ch = word[-1] if word else ""
    has = "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 > 0
    return word + (with_batchim if has else without)


def _items():
    return db.select("items", select="id,name,base_unit", order="id")


# ---------------------------------------------------------------
# 1) 읽기: 사진 → 품목 목록 (아직 저장하지 않음)
# ---------------------------------------------------------------

def _prompt(items):
    names = ", ".join(f"{i['name']}({i['base_unit']})" for i in items)
    return f"""식당 식자재 영수증(거래명세서 · 마트 영수증 · 손글씨 간이영수증) 사진이다. 적힌 내용만 읽어서 JSON으로만 답한다.
{{"date": "YYYY-MM-DD 또는 null", "supplier": "판매처 이름 또는 null", "total": 합계 금액(숫자) 또는 null,
 "items": [{{"raw_name": "영수증에 적힌 품목 이름 그대로", "qty": 수량(숫자), "amount": 그 줄의 금액(원, 숫자),
            "item": "아래 재료 목록 중 같은 재료 이름 또는 null", "qty_base": 그 재료 기준 단위로 바꾼 전체 양(숫자) 또는 null}}]}}
규칙
- 재료 목록(기준 단위): {names}
- qty_base 예: '깐양파 15kg' 1망 → 15, '돈앞다리 1kg' 12 → 12, '국산두부' 45 → 45, '포기김치 10kg' 2 → 20, '대파 1단' 3 → 3
- 단위를 알 수 없으면 qty_base 는 null. 목록에 없는 재료(봉투 · 배달비 등)는 item 을 null 로.
- 날짜에 연도가 없으면(예: 11/2) {datetime.now(KST).year}년으로 본다.
- 읽을 수 없는 글자는 추측하지 말고 null. 할인 · 부가세 · 합계 줄은 items 에 넣지 않는다."""


def read(image, mime):
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise ApiKeyMissing(".env 의 GEMINI_API_KEY 가 비어 있어요")
    items = _items()
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=60_000, retry_options=types.HttpRetryOptions(attempts=2)))
    last = None
    for model in MODELS:   # 무료 모델이 바쁘면(503 · 429) 다음 모델로
        try:
            r = client.models.generate_content(
                model=model, contents=[types.Part.from_bytes(data=image, mime_type=mime), _prompt(items)],
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0))
            data = json.loads(r.text)
            break
        except errors.APIError as e:
            if 400 <= e.code < 500 and e.code not in (404, 429):
                raise
            last = e
        except Exception as e:   # 시간 초과 · 연결 끊김 · 이상한 답
            last = e
        time.sleep(1)
    else:
        raise RuntimeError("지금 AI 서버가 바빠서 영수증을 읽지 못했어요. 잠시 뒤 다시 해 주세요.") from last

    # 전에 저장한 '영수증 이름 → 재료' 짝이 있으면 그걸 우선 (사장님이 고친 값)
    by_name = {i["name"]: i for i in items}
    aliases = {_norm(a["alias"]): a for a in db.select("item_aliases", select="alias,item_id,base_qty_per_unit")}
    by_id = {i["id"]: i for i in items}
    rows = []
    for x in data.get("items") or []:
        qty = _num(x.get("qty"))
        a = aliases.get(_norm(x.get("raw_name")))
        if a and qty:
            it, qty_base, how = by_id.get(a["item_id"]), qty * float(a["base_qty_per_unit"]), "저장된 짝"
        else:
            it, qty_base, how = by_name.get(x.get("item")), _num(x.get("qty_base")), "AI 추정"
        rows.append({"raw_name": str(x.get("raw_name") or "").strip(), "qty": qty, "amount": _num(x.get("amount")),
                     "item_id": it["id"] if it else None, "item": it["name"] if it else None,
                     "base_unit": it["base_unit"] if it else None, "qty_base": qty_base, "matched_by": how if it else None})
    total = _num(data.get("total"))
    line_sum = sum(r["amount"] or 0 for r in rows)
    return {"date": data.get("date"), "supplier": data.get("supplier"), "total": total, "items": rows,
            "items_list": [{"id": i["id"], "name": i["name"], "base_unit": i["base_unit"]} for i in items],
            "total_matches": total is None or abs(total - line_sum) < 1,   # 줄 금액 합 = 합계인지 (틀리면 다시 보라고 안내)
            "line_sum": line_sum, "model": model}


def _num(v):
    try:
        f = float(str(v).replace(",", ""))
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------
# 2) 저장: 사장님이 확인 · 수정한 내용 → Supabase, 저장 전후 원가율 비교
# ---------------------------------------------------------------

def save(store_id, data, image=None, mime=None):
    rows = [r for r in data.get("items") or [] if r.get("raw_name") and r.get("amount")]
    if not rows:
        raise ValueError("저장할 품목이 없어요")
    for r in rows:
        if r.get("item_id") and not r.get("qty_base"):
            raise ValueError(f"'{r['raw_name']}'의 양(기준 단위)을 적어 주세요")
    day = data.get("date") or str(datetime.now(KST).date())
    before = {m["menu_id"]: m for m in cost_report(store_id)["menus"]}

    path = None
    if image:
        ext = {"image/png": "png", "image/webp": "webp"}.get(mime, "jpg")
        path = db.upload("receipts", f"{store_id}/{day}_{uuid.uuid4().hex[:8]}.{ext}", image, mime or "image/jpeg")
    p = db.insert("purchases", [{"store_id": store_id, "purchased_on": day, "supplier": data.get("supplier"),
                                 "total_amount": int(sum(float(r["amount"]) for r in rows)), "source": "ocr", "image_path": path}])[0]
    db.insert("purchase_items", [{"purchase_id": p["id"], "item_id": r.get("item_id"), "raw_name": r["raw_name"],
                                  "qty_base": float(r.get("qty_base") or r.get("qty") or 1), "amount": int(float(r["amount"]))}
                                 for r in rows])
    # 다음부터 같은 이름은 바로 맞추도록 짝 저장 (이미 있으면 사장님이 고친 값으로 바꿈)
    pairs = {}
    for r in rows:
        if r.get("item_id") and r.get("qty") and r.get("qty_base"):
            pairs[r["raw_name"]] = {"alias": r["raw_name"], "item_id": r["item_id"],
                                    "base_qty_per_unit": round(float(r["qty_base"]) / float(r["qty"]), 3)}
    db.upsert("item_aliases", list(pairs.values()), "alias")

    after = cost_report(store_id)
    for m in after["menus"]:
        b = before.get(m["menu_id"])
        m["before_ratio_pct"] = b["cost_ratio_pct"] if b else None
        m["change_pt"] = round(m["cost_ratio_pct"] - b["cost_ratio_pct"], 1) if b and m["cost_ratio_pct"] is not None and b["cost_ratio_pct"] is not None else None
    return {"purchase_id": p["id"], "date": day, "saved_items": len(rows), "image_saved": bool(path), **after}


# ---------------------------------------------------------------
# 3) 원가율: 메뉴마다 최근 구매가로 1인분 재료비 · 원가율 · 많이 오른 재료 · 제안
# ---------------------------------------------------------------

def _price_history(store_id):
    """재료별 kg(모)당 구매가 기록 [(날짜, 단가)] — 오래된 것부터."""
    purchases = {p["id"]: p for p in db.select("purchases", store_id=f"eq.{store_id}", select="id,purchased_on")}
    hist = {}
    for r in db.select("purchase_items", purchase_id=f"in.({','.join(map(str, purchases)) or 0})",
                       select="purchase_id,item_id,unit_price_base,id", order="id"):
        if r["item_id"] and r["unit_price_base"]:
            hist.setdefault(r["item_id"], []).append((purchases[r["purchase_id"]]["purchased_on"], float(r["unit_price_base"])))
    return {k: sorted(v) for k, v in hist.items()}


def cost_report(store_id=db.DEMO_STORE):
    menus = db.select("v_menu_cost_ratio", store_id=f"eq.{store_id}", order="menu_id")
    recipes = db.select("recipe_items", menu_id=f"in.({','.join(str(m['menu_id']) for m in menus) or 0})",
                        select="menu_id,item_id,qty_per_serving,loss_rate,items(name,base_unit)")
    hist = _price_history(store_id)
    out = []
    for m in menus:
        ratio = float(m["cost_ratio_pct"]) if m["cost_ratio_pct"] is not None else None
        cost = float(m["cost_per_serving"] or 0)
        parts = []
        for r in (x for x in recipes if x["menu_id"] == m["menu_id"]):
            h = hist.get(r["item_id"]) or []
            per = float(r["qty_per_serving"]) / (1 - float(r["loss_rate"]))
            if h:
                first, last = h[0][1], h[-1][1]
                parts.append({"item": r["items"]["name"], "unit": r["items"]["base_unit"], "cost": round(per * last),
                              "first_price": round(first), "latest_price": round(last), "since": h[0][0], "latest_date": h[-1][0],
                              "change_pct": round((last / first - 1) * 100, 1) if first else None,
                              "cost_up": round(per * (last - first))})   # 1인분 재료비가 얼마나 늘었나(원)
        parts.sort(key=lambda p: -p["cost"])
        riser = max(parts, key=lambda p: p["cost_up"], default=None)
        riser = riser if riser and riser["cost_up"] >= 30 else None   # 1인분 30원 미만은 알릴 만큼 아님
        if ratio is None:
            verdict = "가격 모름"
        elif ratio <= TARGET_RATIO:
            verdict = "충분해요"
        elif ratio <= 35:
            verdict = "빠듯해요"
        else:
            verdict = "높아요"
        tips = []
        if ratio is not None and ratio > TARGET_RATIO:
            tips.append(f"판매가를 {math.ceil(cost / (TARGET_RATIO / 100) / 500) * 500:,}원으로 올리면 원가율 {TARGET_RATIO}% 안쪽이에요")
        if riser:
            tips.append(f"{_josa(riser['item'], '이', '가')} {riser['since'][5:].replace('-', '/')} 이후 {riser['change_pct']:+.0f}% 올라 "
                        f"1인분 재료비가 {riser['cost_up']:,}원 늘었어요")
            if riser["item"] in SUBSTITUTES and ((ratio or 0) > TARGET_RATIO or (riser["change_pct"] or 0) >= 20):
                tips.append(f"{riser['item']} 일부를 {_josa(SUBSTITUTES[riser['item']], '으로', '로')} 바꾸는 걸 검토해 보세요")
        out.append({"menu_id": m["menu_id"], "menu": m["menu_name"], "price": m["price"], "cost_per_serving": round(cost),
                    "cost_ratio_pct": ratio, "margin": round(m["price"] - cost), "verdict": verdict,
                    "items_without_price": m["items_without_price"], "top_items": parts[:3], "riser": riser, "tips": tips})
    return {"target_ratio_pct": TARGET_RATIO, "menus": out,
            "method": "재료마다 가장 최근 영수증 단가 × 1인분 양(손질 손실 포함). 판매가 제안은 500원 단위 올림"}


# ---------------------------------------------------------------
# 4) 최근 영수증 목록 · 지우기 (시연에서 영수증 읽기로 넣은 것만 지울 수 있음)
# ---------------------------------------------------------------

def recent(store_id, limit=8):
    ps = db.select("purchases", store_id=f"eq.{store_id}", select="id,purchased_on,supplier,total_amount,source,image_path",
                   order="purchased_on.desc,id.desc", limit=str(limit))
    counts = {}
    for r in db.select("purchase_items", purchase_id=f"in.({','.join(str(p['id']) for p in ps) or 0})", select="purchase_id"):
        counts[r["purchase_id"]] = counts.get(r["purchase_id"], 0) + 1
    return [{**p, "items": counts.get(p["id"], 0), "image_path": bool(p["image_path"])} for p in ps]


# 시연 기본 데이터(seed.sql) 영수증 4장은 같은 내용으로 그린 시연용 영수증 그림을 보여 줌
DEMO_IMAGES = {"2026-10-12": "receipt_1012_statement", "2026-10-19": "receipt_1019_statement",
               "2026-10-26": "receipt_1026_mart", "2026-11-02": "receipt_1102_handwritten"}


def detail(store_id, purchase_id):
    """영수증 한 장: 날짜 · 판매처 · 품목 줄 · 사진(10분 동안만 열리는 주소)."""
    ps = db.select("purchases", id=f"eq.{purchase_id}", store_id=f"eq.{store_id}",
                   select="id,purchased_on,supplier,total_amount,source,image_path,created_at")
    if not ps:
        raise ValueError("영수증을 찾지 못했어요")
    p = ps[0]
    rows = db.select("purchase_items", purchase_id=f"eq.{purchase_id}", order="id",
                     select="raw_name,qty_base,amount,unit_price_base,items(name,base_unit)")
    if p["image_path"]:
        image = db.signed_url(p["image_path"])
    elif p["source"] == "demo" and p["purchased_on"] in DEMO_IMAGES:
        image = f"/receipts_demo/{DEMO_IMAGES[p['purchased_on']]}.png"
    else:
        image = None
    return {**p, "image_url": image, "image_path": None,
            "items": [{"raw_name": r["raw_name"], "item": (r["items"] or {}).get("name"), "unit": (r["items"] or {}).get("base_unit"),
                       "qty_base": float(r["qty_base"]), "amount": r["amount"],
                       "unit_price": round(float(r["unit_price_base"])) if r["unit_price_base"] else None} for r in rows]}


def remove(store_id, purchase_id):
    gone = db.delete("purchases", id=f"eq.{purchase_id}", store_id=f"eq.{store_id}", source="eq.ocr")
    if not gone:
        raise ValueError("영수증 읽기로 넣은 영수증만 지울 수 있어요")
    for g in gone:
        if g.get("image_path"):
            db.remove_file(g["image_path"])
    return cost_report(store_id)
