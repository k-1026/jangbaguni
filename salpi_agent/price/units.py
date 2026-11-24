"""단위 기준 (2026-11-17 확정, plan/1116_final_sprint_plan.md 2-2절)

- 무게로 파는 것은 kg, 액체는 L, 무게로 못 재는 것은 모(두부) · 개(계란 · 라면사리)
- 다른 단위 가격은 모두 이 기준 단위당 가격으로 바꿔서 비교
- 바꾼 결과마다 how 를 붙임:
    "정확" — 무게 · 용량이 그대로 적혀 있어서 계산만 함 (g → kg, 500g×2 등)
    "약"   — 환산표(1포기 ≈ ○kg)를 거침 → 화면은 "약 ○원/kg", 차이 10% 안은 "비슷해요"
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
    "수박":   (7.0,  "11월 대구 가격 역산: 북부도매 경락 1,855원/kg · 중도매 상품 1통 약 14,700원 → 중도매가 경락보다 비싸려면 8kg 미만, 중도매 웃돈 10~15% 가정 시 약 7kg (11/17). 표준규격 L 8~9kg는 제철 기준"),
    "애호박": (0.25, "식봄 '애호박(상, 1입)' 규격 0.25kg (11/17). 표준규격은 길이만 있음"),
    "오이":   (0.2,  "식봄 '취청오이(상 5입 1Kg)' → 1개 200g (11/17). 표준규격에 무게 없음"),
    # 가지 · 레몬: 무게 근거가 약해 화면에는 100g당 값도 같이 보여 줌 (web/app.js PER100_ITEMS)
    "가지":   (0.15, "표준규격에 무게 없음. 요리 계량 자료 150g"),
    "레몬":   (0.12, "표준규격 없음. 자료마다 100~150g의 가운데"),
    # 포장 단위(단 · 속): 파는 곳마다 다를 수 있어 상품명에 무게가 있으면 그 값을 먼저 씀
    "대파":   (1.0,  "식봄 '흙대파(1단 1Kg)' · '10단/망 10kg' (11/17)"),
    "시금치": (0.25, "식봄 '시금치 1단-약250g' (11/17)"),
    "깻잎":   (0.02, "식봄 '깻잎 10속 200g' → 1속 20g (11/17)"),
    # 낱개(식봄 규격의 개당 무게 범위 가운데)
    "양파":   (0.22, "식봄 '180~230g/개' · '250g내외/개' (11/17)"),
    "당근":   (0.165, "식봄 '세척당근 130~200g/개' 가운데 (11/24)"),   # 0.25 → 0.165: plan/forecast/1124_unit_price_answer_key.md
    "감자":   (0.15, "식봄 '80g이상/개(대)' ~ '180g이상/개(왕왕)' (11/17)"),
    "토마토": (0.2,  "식봄 '3~4과 1Kg' · '5~7과 1Kg' (11/17)"),
}

PIECE_WORDS = ("포기", "통", "개", "입", "과", "알", "구", "모", "마리", "단", "속", "봉", "팩", "망", "박스", "상자")
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
    to_base("멸치액젓", 1, "kg") → 모름 (kg 액체는 비교에서 뺌)
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
        # kg로 파는 액체는 비중 근거가 약해 L로 안 바꿈 → 아래에서 "모름" (비교에서 빠짐)
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


_PACK = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|㎏|g|ml|㎖|l|ℓ|리터|포기|통|개|입|구|모|단|속|봉|팩|마리)(?![a-wyz])"   # 'kgx10'의 x는 곱하기
                   r"(?:\s*[x×*]\s*(\d+)\s*(?:개|봉|팩|입|통|ea)?)?", re.I)
_RANGE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:kg|㎏|g)?\s*~\s*(\d+(?:\.\d+)?)\s*(kg|㎏|g)(?![a-z])", re.I)
_PER_PIECE = re.compile(r"^\s*(이상|내외|미만)?\s*/\s*(개|과|입)")   # '80g이상/개' 같은 1개 무게 ('/EA'는 한 봉 전체라 해당 없음)
_BARE_KG = re.compile(r"(^|[\s(_,])kg\s*(단위)?(?=[\s)_,]|$)", re.I)   # '흙당근(실속 KG)': 숫자 없이 kg → 1kg 단위로 팖


def parse_pack(text):
    """상품 이름 · 규격 글자에서 전체 (양, 단위)를 읽음. 못 읽으면 None.
    '양파 15kg' → (15, 'kg') · '감자 500g×2봉' → (1000, 'g') · '배추 3포기' → (3, '포기')
    '감자 (대, 80g이상/개, 1Kg/EA)' → (1, 'Kg'): 1개 무게(○g/개)는 빼고, 무게 · 용량이 여럿이면 가장 큰 것
    (예: '깻잎 20g내외*10단 200g' → 200g). 무게 · 용량이 없으면 처음 나온 개수."""
    text = text or ""
    # 범위 무게('5~8kg', '3.7kg~4kg')는 어림값 → 정확한 무게가 없을 때만, 처음 나온 것(규격 칸)의 가운데
    ranges = [(m, (float(m.group(1)) + float(m.group(2))) / 2) for m in _RANGE.finditer(text)
              if not _PER_PIECE.match(text[m.end():])]
    for m, _ in ranges:
        text = text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
    weights, counts = [], []
    for m in _PACK.finditer(text):
        qty, unit, times = float(m.group(1)), m.group(2), m.group(3)
        qty *= int(times) if times else 1
        u = _norm_unit(unit)
        if u in _WEIGHT or u in _VOLUME:
            if _PER_PIECE.match(text[m.end():]):
                continue
            weights.append((qty * _WEIGHT.get(u, _VOLUME.get(u)), qty, unit))
        else:
            counts.append((qty, unit))
    if weights:
        _, qty, unit = max(weights)
        return qty, unit
    if ranges:
        m, mid = ranges[0]
        return mid, m.group(3)
    if counts:
        return counts[0]
    return (1.0, "kg") if _BARE_KG.search(text or "") else None
