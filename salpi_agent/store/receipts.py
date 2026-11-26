"""영수증 사진 → 품목 · 수량 · 금액 읽기(Gemini) → 사장님 확인 → Supabase 저장 → 메뉴 원가율 다시 계산.

- 읽기만 AI가 하고, 원가율 · 판단 · 제안 숫자는 규칙으로 계산한다 (LLM은 숫자를 만들지 않는다)
- 사진은 Supabase Storage 비공개 보관함(receipts)에, 읽은 내용은 purchases · purchase_items 에 저장
- 사장님이 고친 '영수증 이름 → 재료' 짝은 item_aliases 에 쌓아 다음부터 바로 맞춤
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import base64
import hashlib
import json
import math
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone

import requests
from google import genai
from google.genai import errors, types

from sources import supabase_db as db
from store import inventory
from sources.data_sources import ApiError, ApiKeyMissing

KST = timezone(timedelta(hours=9))
MODELS = [os.getenv("GEMINI_MODEL", "gemini-3.8-flash")] + [
    m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-3-flash-preview,gemini-3.5-flash-lite").split(",")
    if m.strip()]
# 영수증 읽기는 사진을 읽는 모델만 · 11/25 붐비는 날 재 본 빠른 순 (3-flash-preview 2.6초, 3.8 · 3.7 은 붐비면 503)
RECEIPT_MODELS = [m.strip() for m in os.getenv(
    "RECEIPT_MODELS", "gemini-3-flash-preview,gemini-3.8-flash,gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-3.5-flash-lite").split(",")
    if m.strip()]
# 무료 한도가 바닥났거나(429, flash 는 모델마다 하루 20번) 붐비는(503) 모델은 잠시 건너뜀 → 영수증마다 같은 실패를 기다리지 않음
_COOL = {}
_READ = {}   # 같은 사진 → AI 가 읽은 결과 (메모리 · 보관함 models/cache/ocr_*.json) — 시연에서 같은 영수증을 다시 올리면 바로
TARGET_RATIO = 40   # 원가율 기준(%): 자영업자 카페 답(30 · 35 · 40%) 중 가장 보수적 값 · 업계 평균 재료비 비중 40.7%
# 대체 재료 후보 (값이 오르면 검토해 볼 만한 것만, 판단은 사장님이)
# 바꿨을 때 원가 · 마진을 계산할 수 있는 것만 둠: ① 같은 무게로 바꿔 넣을 수 있고 (생채소 ↔ 생채소) ② 가격을 알 수 있음 (도매 시세 or 우리 가게 영수증)
#   뺀 것 (11/16): 쪽파 · 돼지고기 뒷다리 = 가격 자료 없음 / 청양고추 → 건고추 · 고춧가루 = 생것과 마른 것이라 같은 무게로 못 바꿈
#   추가 (11/23): 고기는 같은 종류 안에서 다른 부위로만 바꿈 (돼지 → 다른 돼지고기 부위, 닭 → 닭 다른 부위). KAMIS 대구 소매가가 있는 부위만 (kg 단위 같음)
#     닭고기는 육계 통닭 가격 하나뿐이라 부위 대체 자료가 없어 후보 없음. 돼지 → 닭 같은 종류 바꿈은 맛 · 메뉴가 달라져 넣지 않음
SUBSTITUTES = {"양파": ["양배추"], "대파": ["양파"], "애호박": ["감자", "무"], "감자": ["무"],
               "돼지고기 앞다리": ["돼지고기 목심", "수입 돼지고기 삼겹살"], "돼지고기 삼겹살": ["돼지고기 앞다리", "돼지고기 목심", "수입 돼지고기 삼겹살"],
               "돼지고기 목심": ["돼지고기 앞다리", "수입 돼지고기 삼겹살"]}
# 국내산 → 수입산으로 바꾸면 메뉴판 · 원산지 게시판 표시도 바꿔야 함 (음식점 원산지 표시 의무) → 추천 문구에 같이 보여 줌
# 국내산 안에서 부위만 바꾸는 건 표시가 그대로라 안내하지 않음
IMPORTED_ORIGIN_NOTICE = "원산지 표시 변경 필요: 수입산은 메뉴판 · 원산지 게시판에 나라 이름까지 적어야 해요"
SWAP_SHARE = 0.5   # 오른 재료의 절반을 바꿨을 때로 계산 (전부 바꾸면 맛이 달라짐)
MAX_PHOTOS = 5     # 긴 영수증을 나눠 찍을 때 한 번에 받는 사진 수 (많을수록 느리고 무료 AI 한도를 빨리 씀)
PATH_SEP = "|"     # 사진 여러 장의 보관 위치를 purchases.image_path 한 칸에 이어 둠 (표를 바꾸지 않으려고)


def photo_paths(image_path):
    """purchases.image_path → 사진 보관 위치 목록 (한 장이면 [그 위치], 없으면 [])."""
    return [x for x in str(image_path or "").split(PATH_SEP) if x]


def _norm(s):
    return re.sub(r"\s+", "", str(s or "")).lower()


def _josa(word, with_batchim, without):
    """받침에 따라 조사 고르기 (애호박이 / 양파가)."""
    ch = word[-1] if word else ""
    tail = (ord(ch) - 0xAC00) % 28 if "가" <= ch <= "힣" else 0
    if with_batchim == "으로" and tail == 8:   # ㄹ 받침 뒤는 '로' (삼겹살로 · 쌀로)
        return word + without
    return word + (with_batchim if tail > 0 else without)


def _items():
    return inventory.shared_items(db.select("items", select="id,name,base_unit,note", order="id"))


# ---------------------------------------------------------------
# 1) 읽기: 사진 → 품목 목록 (아직 저장하지 않음)
# ---------------------------------------------------------------

PROMPT_VER = b"2"   # 11/26: 같은 종류면 가장 가까운 재료로 (모듬쌈 → 상추)


def _prompt(items, n_photos=1):
    names = ", ".join(f"{i['name']}({i['base_unit']})" for i in items)
    many = (f"\n사진 {n_photos}장은 긴 영수증 한 장을 위에서부터 차례로 나눠 찍은 것이다. 모든 사진을 이어서 영수증 하나로 읽고, "
            "사진끼리 겹쳐 찍혀 두 번 보이는 줄은 한 번만 넣는다. 날짜 · 판매처 · 합계도 영수증 하나 것으로 한 번만 답한다.") if n_photos > 1 else ""
    return f"""식당 식자재 영수증(거래명세서 · 마트 영수증 · 손글씨 간이영수증) 사진이다. 적힌 내용만 읽어서 JSON으로만 답한다.{many}
{{"date": "YYYY-MM-DD 또는 null", "supplier": "판매처 이름 또는 null", "total": 합계 금액(숫자) 또는 null,
 "items": [{{"raw_name": "영수증에 적힌 품목 이름 그대로", "qty": 수량(숫자), "amount": 그 줄의 금액(원, 숫자),
            "item": "아래 재료 목록 중 같은 재료 이름 또는 null", "qty_base": 그 재료 기준 단위로 바꾼 전체 양(숫자) 또는 null}}]}}
규칙
- 재료 목록(기준 단위): {names}
- qty_base 예: '깐양파 15kg' 1망 → 15, '돈앞다리 1kg' 12 → 12, '국산두부' 45 → 45, '포기김치 10kg' 2 → 20, '대파 1단' 3 → 3
- item 은 같은 종류면 목록에서 가장 가까운 재료로 고른다. 예: 꽃상추 · 청상추 · 모듬쌈 → 상추, 깐양파 → 양파, 대패삼겹 · 오겹살 → 돼지고기 삼겹살, 생닭 · 닭다리 → 닭고기
- 같은 종류가 목록에 없거나(예: 콩나물인데 목록에 없음) 식재료가 아니면(봉투 · 배달비 · 음료) item 은 null. 모양만 비슷한 다른 재료로 억지로 맞추지 않는다.
- 단위를 알 수 없으면 qty_base 는 null.
- 날짜에 연도가 없으면(예: 11/2) {datetime.now(KST).year}년으로 본다.
- 읽을 수 없는 글자는 추측하지 말고 null. 할인 · 부가세 · 합계 줄은 items 에 넣지 않는다."""


def read(images):
    """images: [(사진 bytes, mime)] — 1장이면 지금처럼, 여러 장(긴 영수증을 나눠 찍음)이면 AI 한 번에 같이 넣어 영수증 하나로 읽음."""
    if not images:
        raise ValueError("영수증 사진을 골라 주세요")
    if len(images) > MAX_PHOTOS:
        raise ValueError(f"사진은 한 번에 {MAX_PHOTOS}장까지 올릴 수 있어요")
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise ApiKeyMissing(".env 의 GEMINI_API_KEY 가 비어 있어요")
    items = _items()
    data, model = _ai_read(key, images, items)
    return _rows_from(data, items, model, len(images))


# 영수증을 먼저 Groq 무료 사진 모델로 읽음 (11/25: 마트 영수증 1.5초 · 제미나이 8 ~ 20초, 제미나이 무료 한도와 따로 하루 1,000번)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_VISION_MODEL = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b").strip()


def _as_dict(data):
    if isinstance(data, list):   # 품목 목록만 [..] 으로 줄 때가 있음 (11/24 OCR 20장 시험에서 6장)
        data = {"items": data[0].get("items", data) if len(data) == 1 and isinstance(data[0], dict) and "items" in data[0] else data}
    if not isinstance(data, dict):
        raise ValueError("영수증 답 모양이 이상해요")
    return data


def _groq_read(images, items):
    """Groq 사진 모델로 읽기 → dict, 못 읽으면 None (그러면 제미나이로). 키가 없거나 한도에 걸려 쉬는 중이면 바로 None."""
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key or _COOL.get("groq", 0) > time.time():
        return None
    content = [{"type": "text", "text": _prompt(items, len(images))}] + [
        {"type": "image_url", "image_url": {"url": f"data:{m or 'image/jpeg'};base64,{base64.b64encode(b).decode()}"}} for b, m in images]
    body = {"model": GROQ_VISION_MODEL, "messages": [{"role": "user", "content": content}], "temperature": 0,
            "max_tokens": 1500,   # 요청한 최대 길이도 분당 토큰 한도에 잡혀서 줄임
            "reasoning_effort": "none", "response_format": {"type": "json_object"}}
    try:
        for _ in range(2):
            r = requests.post(GROQ_URL, timeout=20, headers={"Authorization": f"Bearer {key}"}, json=body)
            wait = float(r.headers.get("retry-after") or 20) if r.status_code == 429 else 0
            if not wait or wait > 6:
                break
            time.sleep(wait)   # 분당 토큰 한도: 몇 초만 기다리면 풀리면 기다렸다 다시 (제미나이는 무료 한도가 금방 바닥남)
        if r.status_code == 429:
            _COOL["groq"] = time.time() + min(float(r.headers.get("retry-after") or 20), 600)
            return None
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"].strip()
        data = _as_dict(json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", text)))
        return data if data.get("items") else None
    except Exception as e:   # 시간 초과 · 이상한 답 · 장애 → 제미나이로
        print(f"[영수증 Groq] 실패, 제미나이로: {type(e).__name__}: {str(e)[:120]}", flush=True)
        _COOL["groq"] = time.time() + 30
        return None


def _keep(h, data):
    _READ[h] = data
    try:
        db.upload("models", f"cache/ocr_{h}.json", json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")
    except Exception:
        pass   # 저장 실패해도 읽은 결과는 그대로


def _ai_read(key, images, items):
    """사진 → AI 가 읽은 원래 답(dict) · 모델. 같은 사진이면 저장해 둔 답을 씀 (재료 짝 맞추기는 늘 새로 함)."""
    # PROMPT_VER: 읽기 규칙을 바꾸면 올려서, 예전 규칙으로 읽어 저장해 둔 답을 쓰지 않게 함
    h = hashlib.sha1(PROMPT_VER + b"".join(b for b, _ in images)).hexdigest()[:20]
    if h in _READ:
        return _READ[h], "저장된 결과"
    try:
        raw = db.download("models", f"cache/ocr_{h}.json")
        if raw:
            _READ[h] = json.loads(raw)
            return _READ[h], "저장된 결과"
    except Exception:
        pass
    data = _groq_read(images, items)
    if data:
        _keep(h, data)
        return data, f"groq:{GROQ_VISION_MODEL}"
    # 25초 넘게 답이 없으면 다음 모델로 · 같은 모델 재시도 · 쉬는 시간 없음 (11/25: 예전 60초 × 재시도 2번 + 1초씩 쉬기 → 붐비면 몇 분)
    # 앞의 두 모델에 동시에 보내고 먼저 온 맞는 답을 씀 (하나가 붐벼 느려도 기다리지 않게)
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=25_000, retry_options=types.HttpRetryOptions(attempts=1)))
    contents = [*(types.Part.from_bytes(data=b, mime_type=m) for b, m in images), _prompt(items, len(images))]

    def one(model):
        try:
            r = client.models.generate_content(model=model, contents=contents,
                                               config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0))
            data = json.loads(r.text)
            if isinstance(data, list):   # 예비 모델이 품목 목록만 [..] 으로 줄 때가 있음 (11/24 OCR 20장 시험에서 6장)
                data = {"items": data[0].get("items", data) if len(data) == 1 and isinstance(data[0], dict) and "items" in data[0] else data}
            if not isinstance(data, dict):
                raise ValueError("영수증 답 모양이 이상해요")
            return data, model
        except errors.APIError as e:
            _COOL[model] = time.time() + (1800 if e.code == 429 else 120 if e.code in (503, 504) else 0)
            raise
        except Exception:   # 시간 초과 · 연결 끊김 · 이상한 답
            _COOL[model] = time.time() + 120
            raise

    now = time.time()
    order = [m for m in RECEIPT_MODELS if _COOL.get(m, 0) < now] or RECEIPT_MODELS[-1:]
    last = None
    for group in (order[:2], order[2:]):
        if not group:
            continue
        pool = ThreadPoolExecutor(len(group))
        futs = [pool.submit(one, m) for m in group]
        try:
            for f in as_completed(futs):
                try:
                    data, model = f.result()
                except errors.APIError as e:
                    if 400 <= e.code < 500 and e.code not in (404, 429):
                        raise
                    last = e
                    continue
                except Exception as e:
                    last = e
                    continue
                _READ[h] = data
                try:
                    db.upload("models", f"cache/ocr_{h}.json", json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json")
                except Exception:
                    pass   # 저장 실패해도 읽은 결과는 그대로
                return data, model
        finally:
            pool.shutdown(wait=False, cancel_futures=True)   # 늦게 온 쪽은 기다리지 않음
    raise RuntimeError("지금 AI 서버가 바빠서 영수증을 읽지 못했어요. 잠시 뒤 다시 해 주세요.") from last


def _rows_from(data, items, model, n_photos):

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
            # AI 가 재료 목록 모양 그대로 '양파(kg)' 처럼 단위를 붙여 줄 때가 있음 → 괄호를 떼고 찾음 (11/24 OCR 20장: 마트 영수증 4줄)
            name = str(x.get("item") or "").strip()
            it = by_name.get(name) or by_name.get(re.sub(r"\s*\([^)]*\)\s*$", "", name))
            qty_base, how = _num(x.get("qty_base")), "AI 추정"
            if it and qty:
                qty_base = _piece_qty(it["name"], str(x.get("raw_name") or ""), qty, qty_base)
        rows.append({"raw_name": str(x.get("raw_name") or "").strip(), "qty": qty, "amount": _num(x.get("amount")),
                     "item_id": it["id"] if it else None, "item": it["name"] if it else None,
                     "base_unit": it["base_unit"] if it else None, "qty_base": qty_base, "matched_by": how if it else None})
    total = _num(data.get("total"))
    line_sum = sum(r["amount"] or 0 for r in rows)
    return {"date": data.get("date"), "supplier": data.get("supplier"), "total": total, "items": rows,
            "items_list": [{"id": i["id"], "name": i["name"], "base_unit": i["base_unit"]} for i in items],
            "total_matches": total is None or abs(total - line_sum) < 1,   # 줄 금액 합 = 합계인지 (틀리면 다시 보라고 안내)
            "line_sum": line_sum, "model": model, "photos": n_photos}


def _piece_qty(item, raw_name, qty, ai_qty_base):
    """개 · 통 · 단으로 산 재료(애호박 1개 · 양배추(통))는 살피 환산표(units.PIECE_KG)로 기준 양을 계산
    → 단가 판정 · 원가율과 같은 기준 (AI 는 애호박 1개를 0.3kg 로 보거나 비워 둠). 무게가 적힌 줄은 AI 값 그대로."""
    from price import units
    if item not in units.PIECE_KG:
        return ai_qty_base
    pack = units.parse_pack(raw_name)
    if pack and units._norm_unit(pack[1]) in units.PIECE_WORDS:     # '애호박 1개' · '배추 3포기' → 묶음 개수 × 1개 무게
        b = units.to_base(item, pack[0], pack[1])
        return round(qty * b["qty"], 3) if b["qty"] else ai_qty_base
    if pack is None and ai_qty_base is None:                       # '양배추(통)' · '애호박' 처럼 무게 없이 개수만 → 1개씩
        return round(qty * units.PIECE_KG[item][0], 3)
    return ai_qty_base


def _num(v):
    try:
        f = float(str(v).replace(",", ""))
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------
# 2) 저장: 사장님이 확인 · 수정한 내용 → Supabase, 저장 전후 원가율 비교
# ---------------------------------------------------------------

def _checked_rows(data):
    """금액 있는 줄만, 재료를 고른 줄은 양이 있어야 함."""
    rows = [r for r in data.get("items") or [] if r.get("raw_name") and r.get("amount")]
    if not rows:
        raise ValueError("저장할 품목이 없어요")
    for r in rows:
        if r.get("item_id") and not r.get("qty_base"):
            raise ValueError(f"'{r['raw_name']}'의 양(기준 단위)을 적어 주세요")
    return rows


def _item_rows(purchase_id, rows):
    return [{"purchase_id": purchase_id, "item_id": r.get("item_id"), "raw_name": r["raw_name"],
             "qty_base": float(r.get("qty_base") or r.get("qty") or 1), "amount": int(float(r["amount"]))} for r in rows]


def _with_change(store_id, before):
    """저장 뒤 원가율 + 저장 전과 비교한 변화(%p)."""
    after = cost_report(store_id)
    for m in after["menus"]:
        b = before.get(m["menu_id"])
        m["before_ratio_pct"] = b["cost_ratio_pct"] if b else None
        m["change_pt"] = round(m["cost_ratio_pct"] - b["cost_ratio_pct"], 1) if b and m["cost_ratio_pct"] is not None and b["cost_ratio_pct"] is not None else None
    return after


def _restock(store_id, delta):
    """영수증으로 재고 늘리고 줄이기. 재고 저장이 실패해도 영수증 저장은 그대로 (재고는 화면에서 고칠 수 있음)."""
    try:
        inventory.adjust(store_id, delta)
    except (ApiError, ApiKeyMissing) as e:
        print(f"재고 반영 실패: {e}")


def save(store_id, data, images=()):
    """images: [(사진 bytes, mime)] — 여러 장이면 모두 보관하고 위치를 image_path 한 칸에 '|'로 이어 둠."""
    rows = _checked_rows(data)
    if len(images) > MAX_PHOTOS:
        raise ValueError(f"사진은 한 번에 {MAX_PHOTOS}장까지 올릴 수 있어요")
    day = data.get("date") or str(datetime.now(KST).date())
    before = {m["menu_id"]: m for m in cost_report(store_id)["menus"]}

    base = f"{store_id}/{day}_{uuid.uuid4().hex[:8]}"
    saved = []
    for k, (b, m) in enumerate(images):   # 첫 장은 예전과 같은 이름, 둘째 장부터 _2 · _3 …
        ext = {"image/png": "png", "image/webp": "webp"}.get(m, "jpg")
        saved.append(db.upload("receipts", f"{base}{f'_{k + 1}' if k else ''}.{ext}", b, m or "image/jpeg"))
    path = PATH_SEP.join(saved) or None
    p = db.insert("purchases", [{"store_id": store_id, "purchased_on": day, "supplier": data.get("supplier"),
                                 "total_amount": int(sum(float(r["amount"]) for r in rows)), "source": "ocr", "image_path": path}])[0]
    lines = _item_rows(p["id"], rows)
    db.insert("purchase_items", lines)
    _restock(store_id, inventory.qty_by_item(lines))   # 산 만큼 재고 늘리기
    # 다음부터 같은 이름은 바로 맞추도록 짝 저장 (이미 있으면 사장님이 고친 값으로 바꿈)
    pairs = {}
    for r in rows:
        if r.get("item_id") and r.get("qty") and r.get("qty_base"):
            pairs[r["raw_name"]] = {"alias": r["raw_name"], "item_id": r["item_id"],
                                    "base_qty_per_unit": round(float(r["qty_base"]) / float(r["qty"]), 3)}
    db.upsert("item_aliases", list(pairs.values()), "alias")

    after = _with_change(store_id, before)
    return {"purchase_id": p["id"], "date": day, "saved_items": len(rows), "image_saved": bool(path), "photos_saved": len(images), **after}


def edit(store_id, purchase_id, data):
    """저장한 영수증 고치기: 날짜 · 판매처 · 품목 줄을 사장님이 고친 내용으로 바꿈 (사진은 그대로)."""
    rows = _checked_rows(data)
    before = {m["menu_id"]: m for m in cost_report(store_id)["menus"]}
    fields = {"supplier": data.get("supplier"), "total_amount": int(sum(float(r["amount"]) for r in rows))}
    if data.get("date"):
        fields["purchased_on"] = data["date"]
    if not db.update("purchases", fields, id=f"eq.{purchase_id}", store_id=f"eq.{store_id}"):
        raise ValueError("영수증을 찾지 못했어요")
    # 줄은 통째로 바꿈 (빠진 줄 · 더한 줄 모두 반영). 새 줄을 먼저 넣고 예전 줄을 지워서, 중간에 실패해도 줄이 사라지지 않게
    old_rows = db.select("purchase_items", purchase_id=f"eq.{purchase_id}", select="id,item_id,qty_base")
    old = [r["id"] for r in old_rows]
    lines = _item_rows(purchase_id, rows)
    db.insert("purchase_items", lines)
    if old:
        db.delete("purchase_items", id=f"in.({','.join(map(str, old))})")
    # 재고는 바뀐 만큼만 (새 양 − 예전 양)
    delta = inventory.qty_by_item(lines)
    for i, q in inventory.qty_by_item(old_rows).items():
        delta[i] = delta.get(i, 0) - q
    _restock(store_id, delta)
    # 이름 → 재료 짝도 고친 값으로 (원래 수량을 모르면 1개 기준으로 보지 않고 건너뜀)
    db.upsert("item_aliases", [{"alias": r["raw_name"], "item_id": r["item_id"],
                                "base_qty_per_unit": round(float(r["qty_base"]) / float(r["qty"]), 3)}
                               for r in rows if r.get("item_id") and r.get("qty") and r.get("qty_base")], "alias")
    after = _with_change(store_id, before)
    return {"purchase_id": purchase_id, "date": fields.get("purchased_on"), "saved_items": len(rows), **after}


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
    # 날짜로만 정렬 (같은 날은 나중에 넣은 줄이 뒤) → 마지막 값이 원가율 뷰(v_latest_purchase_price)의 최근 단가와 같음
    return {k: sorted(v, key=lambda x: x[0]) for k, v in hist.items()}


def _wholesale(name, cache):
    """도매 시세(kg당)와 다음 7일 예측. 시세가 없는 재료면 None."""
    if name not in cache:
        cache[name] = None
        try:
            from price import analysis
            if name in analysis.ITEMS:
                f = analysis.forecast_item(name)
                if f.get("base_kg_price"):
                    cache[name] = f
            elif name in analysis.EXTRA_ITEMS and analysis.EXTRA_ITEMS[name]["group"] == "육류":   # 고기: 대구 소매가(kg) + 7일 예측
                t = analysis.extra_trend(name)
                f = t.get("forecast") or {}
                if t.get("price") and t.get("unit") == "kg" and f.get("expected_change_pct") is not None:
                    cache[name] = {"base_kg_price": t["price"], "expected_change_pct": f["expected_change_pct"],
                                   "direction": f.get("direction")}
        except Exception as e:   # 시세 API 문제 → 그 후보만 건너뜀
            print(f"[대체 재료] {name} 시세 실패: {e}", flush=True)
    return cache[name]


def _swap(riser, per, cost, price, store_price, cache):
    """오른 재료의 절반을 후보로 바꿨을 때 가장 많이 아끼는 것 (다음 주 예상 가격 기준).
    후보 가격을 모르거나 · 안 아껴지거나 · 후보가 오른 재료보다 더 오를 예정이면 뺌."""
    cands = []
    fr = _wholesale(riser["item"], cache)
    from_next = riser["latest_price"] * (1 + (fr["expected_change_pct"] if fr else 0) / 100)
    for to in SUBSTITUTES.get(riser["item"], []):
        fc = _wholesale(to, cache)
        if not fc:
            continue
        if fr and fc["expected_change_pct"] >= fr["expected_change_pct"]:   # 대체 재료가 더 오를 예정이면 바꿔도 소용없음
            continue
        if to in store_price:
            to_price, basis = store_price[to], "우리 가게 영수증 단가"
        elif fr:   # 영수증 단가와 도매가는 수준이 달라서, 두 재료의 도매가 비율로 우리 가게 단가를 환산 (같은 기준끼리 비교)
            to_price, basis = riser["latest_price"] * fc["base_kg_price"] / fr["base_kg_price"], "도매 시세 비율로 환산"
        else:
            continue
        to_next = to_price * (1 + fc["expected_change_pct"] / 100)
        saving = per * SWAP_SHARE * (from_next - to_next)
        if saving < 10:
            continue
        new_cost = cost - saving
        cands.append({"from": riser["item"], "to": to, "share_pct": round(SWAP_SHARE * 100), "price_basis": basis,
                "from_price": riser["latest_price"], "to_price": round(to_price), "saving_per_serving": round(saving),
                "new_cost": round(new_cost), "new_ratio_pct": round(new_cost / price * 100, 1) if price else None,
                "new_margin": round(price - new_cost), "to_outlook": fc["direction"], "to_change_pct": fc["expected_change_pct"],
                "from_change_pct": fr["expected_change_pct"] if fr else None, "basis_note": "다음 주 예상 가격으로 계산",
                "origin_notice": IMPORTED_ORIGIN_NOTICE if to.startswith("수입") and not riser["item"].startswith("수입") else None})
    if not cands:
        return None
    cands.sort(key=lambda c: -c["saving_per_serving"])
    best = cands[0]
    # 가장 많이 아끼는 것 말고 다른 후보도 보여 줌 (예: 닭고기가 1순위여도 수입 돼지고기는 같은 돼지고기라 메뉴 맛이 덜 바뀜)
    best["others"] = [{k: c[k] for k in ("to", "saving_per_serving", "new_ratio_pct", "origin_notice")} for c in cands[1:]]
    return best


def cost_report(store_id=db.DEMO_STORE, forecasts=None):
    """forecasts: {재료 이름: 시세 예측(analysis.forecast_item 결과)} — 첫 화면 시세(/api/overview)에 이미 있으면 넘겨 받아
    재료마다 시세 API · AI 모델을 다시 부르지 않음 (없는 재료만 _wholesale 이 직접 계산)."""
    def menus_and_recipes():
        menus = db.select("v_menu_cost_ratio", store_id=f"eq.{store_id}", order="menu_id")
        return menus, db.select("recipe_items", menu_id=f"in.({','.join(str(m['menu_id']) for m in menus) or 0})",
                                select="menu_id,item_id,qty_per_serving,loss_rate,items(name,base_unit)")
    # 서로 기다릴 필요 없는 Supabase 읽기는 동시에 (차례로 하면 약 3.7초)
    with ThreadPoolExecutor(max_workers=3) as pool:
        f_menus, f_hist, f_items = pool.submit(menus_and_recipes), pool.submit(_price_history, store_id), pool.submit(_items)
        (menus, recipes), hist, items = f_menus.result(), f_hist.result(), f_items.result()
    names = {i["id"]: i["name"] for i in items}
    store_price = {names[k]: v[-1][1] for k, v in hist.items() if k in names}   # 재료 이름 → 우리 가게 최근 영수증 단가
    cache = {k: f for k, f in (forecasts or {}).items() if f and f.get("base_kg_price") and f.get("expected_change_pct") is not None}
    out = []
    for m in menus:
        ratio = float(m["cost_ratio_pct"]) if m["cost_ratio_pct"] is not None else None
        cost = float(m["cost_per_serving"] or 0)
        parts = []
        for r in (x for x in recipes if x["menu_id"] == m["menu_id"]):
            h = hist.get(r["item_id"]) or []
            per = float(r["qty_per_serving"]) / (1 - float(r["loss_rate"]))
            if h:
                # 비교 기준: 최근 영수증보다 4주 이상 앞선 영수증 중 가장 최근 것 (없으면 첫 영수증) — 1년 치가 쌓여도 '최근 한 달 새' 변화로 봄
                cut = str(datetime.fromisoformat(h[-1][0]).date() - timedelta(28))
                since, first = ([x for x in h if x[0] <= cut] or h[:1])[-1]
                last = h[-1][1]
                parts.append({"item": r["items"]["name"], "unit": r["items"]["base_unit"], "cost": round(per * last),
                              "first_price": round(first), "latest_price": round(last), "since": since, "latest_date": h[-1][0],
                              "change_pct": round((last / first - 1) * 100, 1) if first else None,
                              "cost_up": round(per * (last - first)), "_per": per})   # 1인분 재료비가 얼마나 늘었나(원)
        parts.sort(key=lambda p: -p["cost"])
        risers = sorted((p for p in parts if p["cost_up"] >= 30), key=lambda p: -p["cost_up"])   # 1인분 30원 미만은 알릴 만큼 아님
        riser = risers[0] if risers else None
        # 다음 주 예상 원가율: 시세가 있는 재료(야채)는 7일 예측만큼 단가가 바뀐다고 보고 다시 계산 (유저플로우 v2 왼쪽 갈래)
        next_cost, next_up = cost, None
        for p in parts:
            fc = _wholesale(p["item"], cache)
            if fc:
                delta = p["_per"] * p["latest_price"] * fc["expected_change_pct"] / 100
                next_cost += delta
                if delta >= 10 and (not next_up or delta > next_up["cost_up"]):   # 다음 주 1인분 재료비를 가장 많이 올리는 재료 (원가율 알림 '왜')
                    next_up = {"item": p["item"], "change_pct": fc["expected_change_pct"], "cost_up": round(delta)}
        next_ratio = round(next_cost / m["price"] * 100, 1) if m["price"] and ratio is not None else None
        high = ratio is not None and (ratio >= TARGET_RATIO or (next_ratio or 0) >= TARGET_RATIO)
        if ratio is None:
            verdict = "가격 모름"
        elif ratio < TARGET_RATIO:
            verdict = "괜찮아요" if (next_ratio or 0) < TARGET_RATIO else "다음 주 높아져요"
        else:
            verdict = "높아요"
        # 순서: 대체 재료 추천 → 그 이유(오른 재료) → 판매가 제안 (메뉴 제안은 모든 메뉴를 본 뒤 아래에서)
        tips, swap, price_up = [], None, None
        why = lambda r: (f"{_josa(r['item'], '이', '가')} {r['since'][5:].replace('-', '/')} 이후 {r['change_pct']:+.0f}% 올라 "
                         f"1인분 재료비가 {r['cost_up']:,}원 늘었어요")
        # 많이 오른 재료부터: 바꿨을 때 원가를 계산할 수 있는 대체 재료가 있는 첫 재료 (화면의 '대체 재료 추천' 상자)
        for r in risers:
            if high or (r["change_pct"] or 0) >= 20:
                swap = _swap(r, r["_per"], cost, m["price"], store_price, cache)
                if swap:
                    swap["reason"] = why(r)
                    tips.append(f"{r['item']} 절반을 {_josa(swap['to'], '으로', '로')} 바꾸면 1인분 {swap['saving_per_serving']:,}원 아껴 "
                                f"원가율 {ratio}% → {swap['new_ratio_pct']}%예요")
                    break
        if high and not swap:   # 오른 재료에 대체 후보가 없으면(예: 돼지고기) 바꿀 수 있는 다른 재료 중 가장 많이 아끼는 것
            for p in parts:
                s = _swap(p, p["_per"], cost, m["price"], store_price, cache)
                if s and (not swap or s["saving_per_serving"] > swap["saving_per_serving"]):
                    swap = {**s, "reason": f"원가율이 {TARGET_RATIO}%를 넘어 바꿀 수 있는 재료부터 찾았어요"}
            if swap:
                tips.append(f"{swap['from']} 절반을 {_josa(swap['to'], '으로', '로')} 바꾸면 1인분 {swap['saving_per_serving']:,}원 아껴 "
                            f"원가율 {ratio}% → {swap['new_ratio_pct']}%예요")
        if swap and swap.get("origin_notice"):
            tips.append(swap["origin_notice"])
        if riser:
            tips.append(why(riser))
        if high:
            base = max(cost, next_cost)   # 다음 주에 오를 것까지 버티는 값
            new_price = math.ceil(base / (TARGET_RATIO / 100) / 500) * 500
            if base / new_price * 100 >= TARGET_RATIO:
                new_price += 500
            price_up = {"price": new_price, "raise": new_price - m["price"], "new_ratio_pct": round(base / new_price * 100, 1),
                        "new_margin": round(new_price - base), "basis": "다음 주 예상 원가" if next_cost > cost + 1 else "지금 원가"}   # 원가율 · 남는 금액 모두 같은 원가(base)로
            tips.append(f"판매가를 {new_price:,}원으로 {new_price - m['price']:,}원 올리면 원가율 {price_up['new_ratio_pct']}%로 "
                        f"{TARGET_RATIO}% 아래예요")
        out.append({"menu_id": m["menu_id"], "menu": m["menu_name"], "price": m["price"], "cost_per_serving": round(cost),
                    "cost_ratio_pct": ratio, "next_ratio_pct": next_ratio, "margin": round(m["price"] - cost), "verdict": verdict,
                    "high": high, "items_without_price": m["items_without_price"],
                    "top_items": [{k: v for k, v in p.items() if k != "_per"} for p in parts[:3]],
                    "riser": {k: v for k, v in riser.items() if k != "_per"} if riser else None, "tips": tips, "swap": swap,
                    "price_up": price_up, "push_menu": None, "next_up": next_up})
    # 메뉴 제안: 원가율이 높은 메뉴가 있으면, 지금 · 다음 주 모두 40% 아래인 메뉴 중 한 그릇에 가장 많이 남는 메뉴를 밀어 보자고 제안
    good = [x for x in out if x["cost_ratio_pct"] is not None and not x["high"]]
    best = max(good, key=lambda x: x["margin"], default=None)
    for x in out:
        if x["high"] and best:
            x["push_menu"] = {"menu": best["menu"], "margin": best["margin"], "cost_ratio_pct": best["cost_ratio_pct"],
                              "next_ratio_pct": best["next_ratio_pct"], "margin_gap": best["margin"] - x["margin"]}
            x["tips"].append(f"{_josa(best['menu'], '은', '는')} 한 그릇에 {best['margin']:,}원 남아요(원가율 {best['cost_ratio_pct']}%). "
                             f"오늘의 메뉴 · 세트로 밀어 보세요")
    return {"target_ratio_pct": TARGET_RATIO, "menus": out,
            "method": "재료마다 가장 최근 영수증 단가 × 1인분 양(손질 손실 포함). 다음 주 예상은 야채만 7일 시세 예측 반영. "
                      f"원가율 {TARGET_RATIO}% 이상(지금 또는 다음 주)이면 가격 조정 · 대체 재료 · 메뉴 제안. 판매가 제안은 500원 단위 올림"}


def my_ingredients(store_id):
    """우리 가게 메뉴(판매 중)에 들어가는 재료 → 그 재료가 들어가는 메뉴들. 알림을 '내 메뉴 재료만'으로 거를 때 씀."""
    menus = db.select("menus", store_id=f"eq.{store_id}", is_active="eq.true", select="id,name", order="id")
    names = {m["id"]: m["name"] for m in menus}
    out = {}
    for r in db.select("recipe_items", menu_id=f"in.({','.join(map(str, names)) or 0})", select="menu_id,items(name)"):
        out.setdefault(r["items"]["name"], []).append(names[r["menu_id"]])
    return {"menus": list(names.values()), "items": out}


# ---------------------------------------------------------------
# 4) 최근 영수증 목록 · 지우기 (기본 데이터 영수증도 지울 수 있음)
# ---------------------------------------------------------------

def recent(store_id, limit=8):
    """최근 영수증 목록 + 사진 미리보기 주소 (1시간 동안 열리는 주소 → 보관할 때는 1시간보다 짧게)."""
    ps = db.select("purchases", store_id=f"eq.{store_id}", select="id,purchased_on,supplier,total_amount,source,image_path",
                   order="purchased_on.desc,id.desc", limit=str(limit))
    counts, names = {}, {}
    for r in db.select("purchase_items", purchase_id=f"in.({','.join(str(p['id']) for p in ps) or 0})", select="purchase_id,raw_name", order="id"):
        counts[r["purchase_id"]] = counts.get(r["purchase_id"], 0) + 1
        names.setdefault(r["purchase_id"], []).append(r["raw_name"])
    urls = db.signed_urls([photo_paths(p["image_path"])[0] for p in ps if p["image_path"]], seconds=3600)   # 사진 줄 미리보기는 첫 장 (한 번에, 1시간)
    return [{**p, "items": counts.get(p["id"], 0), "image_path": bool(p["image_path"]), "image_url": _image_url(p, urls),
             "photos": len(photo_paths(p["image_path"])),
             "names": names.get(p["id"], [])[:4]} for p in ps]   # 사진 없는 영수증은 품목 몇 줄로 작은 영수증을 그림


# 시연 기본 데이터(seed.sql) 영수증 4장은 같은 내용으로 그린 시연용 영수증 그림을 보여 줌
DEMO_IMAGES = {"2026-10-12": "receipt_1012_statement", "2026-10-19": "receipt_1019_statement",
               "2026-10-26": "receipt_1026_mart", "2026-11-02": "receipt_1102_handwritten"}


def _image_url(p, urls):
    if p["image_path"]:
        return urls.get(photo_paths(p["image_path"])[0])
    if p["source"] == "demo" and p["purchased_on"] in DEMO_IMAGES:
        return f"/receipts_demo/{DEMO_IMAGES[p['purchased_on']]}.png"
    return None


def detail(store_id, purchase_id):
    """영수증 한 장: 날짜 · 판매처 · 품목 줄 · 사진(10분 동안만 열리는 주소)."""
    ps = db.select("purchases", id=f"eq.{purchase_id}", store_id=f"eq.{store_id}",
                   select="id,purchased_on,supplier,total_amount,source,image_path,created_at")
    if not ps:
        raise ValueError("영수증을 찾지 못했어요")
    p = ps[0]
    rows = db.select("purchase_items", purchase_id=f"eq.{purchase_id}", order="id",
                     select="raw_name,item_id,qty_base,amount,unit_price_base,items(name,base_unit)")
    images = [db.signed_url(x) for x in photo_paths(p["image_path"])]
    if not images and p["source"] == "demo" and p["purchased_on"] in DEMO_IMAGES:
        images = [f"/receipts_demo/{DEMO_IMAGES[p['purchased_on']]}.png"]
    # image_url = 첫 장 (지금 화면) · image_urls = 나눠 찍은 사진 전부 (위에서부터 차례로)
    return {**p, "image_url": images[0] if images else None, "image_urls": images, "image_path": None,
            "items_list": [{"id": i["id"], "name": i["name"], "base_unit": i["base_unit"]} for i in _items()],
            "items": [{"raw_name": r["raw_name"], "item_id": r["item_id"], "item": (r["items"] or {}).get("name"), "unit": (r["items"] or {}).get("base_unit"),
                       "qty_base": float(r["qty_base"]), "amount": r["amount"],
                       "unit_price": round(float(r["unit_price_base"])) if r["unit_price_base"] else None} for r in rows]}


def remove(store_id, purchase_id):
    lines = db.select("purchase_items", purchase_id=f"eq.{purchase_id}", select="item_id,qty_base")
    gone = db.delete("purchases", id=f"eq.{purchase_id}", store_id=f"eq.{store_id}")   # 기본(시연) 영수증도 지울 수 있음
    if not gone:
        raise ValueError("영수증을 찾지 못했어요")
    _restock(store_id, {i: -q for i, q in inventory.qty_by_item(lines).items()})   # 지운 영수증만큼 재고 줄이기
    for g in gone:
        for x in photo_paths(g.get("image_path")):
            db.remove_file(x)
    return cost_report(store_id)
