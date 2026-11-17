"""단위 기준 (2026-11-17 확정, plan/1116_final_sprint_plan.md 2-2절)

- 무게로 파는 것은 kg, 액체는 L, 무게로 못 재는 것은 모(두부) · 개(계란 · 라면사리)
- 다른 단위 가격은 모두 이 기준 단위당 가격으로 바꿔서 비교
- 바꾼 결과마다 how 를 붙임:
    "정확" — 무게 · 용량이 그대로 적혀 있어서 계산만 함 (g → kg, 500g×2 등)
    "약"   — 환산표(1포기 ≈ ○kg, 비중)를 거침 → 화면은 "약 ○원/kg", 차이 10% 안은 "비슷해요"
    "모름" — 단위를 못 읽음 → 비교에서 뺌
"""
import re

LIQUID_ITEMS = {"간장", "참기름", "들기름", "식용유", "멸치액젓", "까나리액젓", "식초", "맛술", "물엿", "올리고당"}
COUNT_ITEMS = {"두부": "모", "계란": "개", "라면사리": "개"}

# 1개(포기 · 통) 무게(kg). 기본 규칙: 농산물 표준규격(국립농산물품질관리원 고시) 크기 구분의 L 구간 가운데값.
# KAMIS 조사 규격에 무게가 나오는 품목은 그 값을 우선. 출처가 약한 값은 "검토 필요"로 표시.
STD = "농산물 표준규격(국립농산물품질관리원 고시)"
PIECE_KG = {
    "배추":   (3.3,  f"KAMIS 대구 중도매 조사 규격 '그물망 3포기 10kg' (10 ÷ 3). {STD} 일반배추 L 3.0~4.0kg 안"),
    "양배추": (2.5,  f"{STD} 양배추 L 2.0~3.0kg 가운데"),
    "무":     (2.5,  f"{STD} 무 L 2.0~3.0kg 가운데"),
    "사과":   (0.275, f"{STD} 사과 L 250~300g 가운데"),
    "배":     (0.55, f"{STD} 배 L 500~600g 가운데"),
    "단감":   (0.225, f"{STD} 단감 L 200~250g 가운데"),
    "감귤":   (0.095, f"{STD} 온주밀감 M 83~106g 가운데 (KAMIS 소매 조사가 M과)"),
    "수박":   (8.5,  f"{STD} 수박 L 8~9kg 가운데"),
    "애호박": (0.27, "검토 필요: 표준규격은 길이(cm)만 있음. 요리 계량 자료 270g · seed.sql 영수증 짝 0.3kg"),
    "오이":   (0.15, "검토 필요: 표준규격에 무게 없음. 요리 계량 자료 150g"),
    "가지":   (0.15, "검토 필요: 표준규격에 무게 없음. 요리 계량 자료 150g"),
    "레몬":   (0.12, "검토 필요: 표준규격 없음. 자료마다 100~150g"),
}

# 1L 무게(kg). kg로 파는 액체를 L로 바꿀 때만 씀
DENSITY = {
    "간장":     (1.15, "검토 필요: 진간장 비중 약 1.15"),
    "참기름":   (0.92, "검토 필요: 식물성 기름 비중 약 0.92"),
    "들기름":   (0.93, "검토 필요: 식물성 기름 비중 약 0.93"),
    "식용유":   (0.92, "검토 필요: 식물성 기름 비중 약 0.92"),
    "멸치액젓": (1.2,  "검토 필요: 액젓 비중 약 1.2 (염도 20%대)"),
    "까나리액젓": (1.2, "검토 필요: 액젓 비중 약 1.2"),
    "식초":     (1.01, "검토 필요: 식초 비중 약 1.01"),
}

PIECE_WORDS = ("포기", "통", "개", "입", "과", "알", "구", "모", "마리", "단", "봉", "팩", "망", "박스", "상자")
_WEIGHT = {"kg": 1, "g": 0.001}
_VOLUME = {"l": 1, "ml": 0.001}


def base_unit(item):
    """품목의 기준 단위: kg · L · 모 · 개."""
    if item in COUNT_ITEMS:
        return COUNT_ITEMS[item]
    return "L" if item in LIQUID_ITEMS else "kg"


def _norm_unit(unit):
    u = (unit or "").strip().lower().replace("㎏", "kg").replace("ℓ", "l").replace("㎖", "ml").replace("리터", "l")
    u = u.split("(")[0].strip()
    return "개" if u in ("구", "입", "과", "알") else u


def to_base(item, qty, unit):
    """qty unit 만큼의 양을 그 품목 기준 단위로. → {"qty", "unit", "how", "note"}

    to_base("배추", 1, "포기")  → 3.3 kg, 약
    to_base("감자", 100, "g")   → 0.1 kg, 정확
    to_base("계란", 30, "구")   → 30 개, 정확
    to_base("멸치액젓", 1, "kg") → 0.833 L, 약
    """
    base = base_unit(item)
    u = _norm_unit(unit)
    try:
        qty = float(qty)
    except (TypeError, ValueError):
        return {"qty": None, "unit": base, "how": "모름", "note": "양을 못 읽음"}
    if qty <= 0:
        return {"qty": None, "unit": base, "how": "모름", "note": "양이 0"}

    if base == "kg":
        if u in _WEIGHT:
            return {"qty": qty * _WEIGHT[u], "unit": "kg", "how": "정확", "note": None}
        if item in PIECE_KG and (u in PIECE_WORDS or u == ""):
            kg, src = PIECE_KG[item]
            return {"qty": qty * kg, "unit": "kg", "how": "약", "note": f"1{unit or '개'} ≈ {kg:g}kg ({src})"}
    elif base == "L":
        if u in _VOLUME:
            return {"qty": qty * _VOLUME[u], "unit": "L", "how": "정확", "note": None}
        if u in _WEIGHT and item in DENSITY:
            d, src = DENSITY[item]
            return {"qty": qty * _WEIGHT[u] / d, "unit": "L", "how": "약", "note": f"1L ≈ {d:g}kg ({src})"}
    else:   # 모 · 개
        if u == base or u in ("개", base):
            return {"qty": qty, "unit": base, "how": "정확", "note": None}
        if u == "판" and item == "계란":
            return {"qty": qty * 30, "unit": "개", "how": "정확", "note": "1판 = 30개"}
    return {"qty": None, "unit": base, "how": "모름", "note": f"'{unit}'을(를) {base}로 바꿀 방법이 없음"}


def per_base_price(item, price, qty, unit):
    """qty unit 에 price 원 → 기준 단위당 가격. → {"price", "unit", "how", "note"} (못 바꾸면 price None)"""
    b = to_base(item, qty, unit)
    if b["qty"] is None or price is None:
        return {"price": None, "unit": b["unit"], "how": "모름", "note": b["note"]}
    return {"price": round(float(price) / b["qty"]), "unit": b["unit"], "how": b["how"], "note": b["note"]}


_PACK = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|㎏|g|ml|㎖|l|ℓ|리터|포기|통|개|입|구|모|단|봉|팩|마리)"
                   r"(?:\s*[x×*]\s*(\d+)\s*(?:개|봉|팩|입|통|ea)?)?", re.I)


def parse_pack(text):
    """상품 이름 · 규격 글자에서 (양, 단위)를 읽음. '양파 15kg' → (15, 'kg'), '감자 500g×2봉' → (1000, 'g'),
    '배추 3포기' → (3, '포기'). 무게 · 용량이 있으면 개수보다 우선. 못 읽으면 None."""
    found = []
    for m in _PACK.finditer(text or ""):
        qty, unit, times = float(m.group(1)), m.group(2), m.group(3)
        found.append((qty * (int(times) if times else 1), unit))
    if not found:
        return None
    for qty, unit in found:
        if _norm_unit(unit) in _WEIGHT or _norm_unit(unit) in _VOLUME:
            return qty, unit
    return found[0]
