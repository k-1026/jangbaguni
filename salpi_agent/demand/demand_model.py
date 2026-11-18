"""판매량 학습 모델로 내일 메뉴별 그릇 수 예측 (서버용: numpy 없이 순수 파이썬).

- 모델은 demand_learn.py 가 시연 가게 더미 판매 기록(data/dummy_store)으로 한 번 학습해 models/demand_demo.json 에 저장
- 요인 계산(make_features)은 학습과 예측이 이 파일 하나를 같이 씀 → 학습 때와 화면 예측 때 숫자가 어긋나지 않음
- 맞히는 것: 그날 판매량 ÷ 최근 평소 수준(최근 24 영업일 평균). 예측 그릇 수 = 평소 수준 × 모델 값
  (손님이 천천히 늘거나 줄어도 '평소 대비 몇 배'는 잘 안 변해서, 학습 기간 밖으로 나가도 덜 흔들림)
- 실제 가게 기록이 아니라 가상 데이터로 배운 모델이라, 시연 가게(is_demo)에만 씀
"""
import json
import math
import statistics
from datetime import date, timedelta
from pathlib import Path

from price.forecast_model import Model

PATH = Path(__file__).resolve().parent / "models" / "demand_demo.json"
LEVEL_DAYS = 24      # 평소 수준 = 최근 24 영업일 평균 (약 4주)
SAME_WEEKS = 8       # 같은 요일 비율 = 최근 8주 같은 요일 평균 ÷ 평소 수준

FEATURES = ["menu", "weekday", "holiday", "avg_temp", "rainy", "hot", "home_game", "festival", "payday", "month",
            "wd_ratio", "trend"]
# 화면에 보여 줄 이유 묶음 (요인 → 이름). '요일'은 그날 요일 이름으로 바꿔 씀
GROUPS = {"weekday": "요일", "wd_ratio": "요일", "holiday": "공휴일", "avg_temp": "기온", "rainy": "비", "hot": "폭염",
          "home_game": "삼성 홈경기", "festival": "대구 축제", "payday": "월급날 무렵", "month": "계절", "trend": "최근 흐름",
          "menu": "메뉴 특성"}
FLAGS = {"holiday", "rainy", "hot", "home_game", "festival", "payday"}   # 있다/없다 요인


def level_and_ratios(hist, d):
    """hist: [(날짜, 그릇 수)] 영업일만, d 이전. → (평소 수준, 같은 요일 비율, 최근 흐름)"""
    past = [(x, q) for x, q in hist if x < d]
    if len(past) < 12:
        return None, math.nan, math.nan
    recent = [q for _x, q in past[-LEVEL_DAYS:]]
    level = statistics.mean(recent)
    if level <= 0:
        return None, math.nan, math.nan
    same = [q for x, q in past if x.weekday() == d.weekday() and x >= d - timedelta(7 * SAME_WEEKS)]
    wd_ratio = statistics.mean(same) / level if len(same) >= 3 else math.nan
    half = len(recent) // 2
    trend = statistics.mean(recent[half:]) / statistics.mean(recent[:half]) - 1 if half >= 5 and statistics.mean(recent[:half]) else math.nan
    return level, wd_ratio, trend


def make_features(menu_idx, hist, d, cal):
    """cal: {holiday, avg_temp, rainy, hot, home_game, festival} (없으면 빈 값). → (요인 dict, 평소 수준)"""
    level, wd_ratio, trend = level_and_ratios(hist, d)
    nan = math.nan
    f = {"menu": float(menu_idx), "weekday": float(d.weekday()), "holiday": float(bool(cal.get("holiday"))),
         "avg_temp": cal.get("avg_temp") if cal.get("avg_temp") is not None else nan,
         "rainy": float(cal["rainy"]) if cal.get("rainy") is not None else nan,
         "hot": float(cal["hot"]) if cal.get("hot") is not None else nan,
         "home_game": float(bool(cal.get("home_game"))), "festival": float(bool(cal.get("festival"))),
         "payday": float(25 <= d.day <= 28), "month": float(d.month), "wd_ratio": wd_ratio, "trend": trend}
    return f, level


# ---------------------------------------------------------------
# 서버: 저장된 모델 읽기 · 예측
# ---------------------------------------------------------------
_model = {"m": None, "blob": None}


def load():
    """(Model, blob) — 파일이 없으면 (None, None) → 규칙 예측 그대로."""
    if _model["blob"] is None and PATH.exists():
        blob = json.loads(PATH.read_text(encoding="utf-8"))
        _model["blob"] = blob
        _model["m"] = Model({**blob, "items": blob["menus"]})
    return _model["m"], _model["blob"]


def calendar_day(d, holidays, weather, blob):
    """예측할 날의 요인. weather: {날짜 문자열: (평균 기온, 비 오나, 폭염인가)} — 지난날은 관측, 앞날은 예보."""
    w = weather.get(str(d))
    games = set(blob.get("home_games", []))
    fests = blob.get("festivals", [])
    return {"holiday": str(d) in holidays, "avg_temp": w[0] if w else None, "rainy": w[1] if w else None,
            "hot": w[2] if w else None, "home_game": str(d) in games,
            "festival": any(a <= str(d) <= b for a, b in fests)}


WEEKDAYS = "월화수목금토일"


def predict(menu, hist, d, cal):
    """→ (그릇 수, 아래, 위, {이유: 평소 대비 비율}) 또는 None (모델 · 메뉴 · 기록이 없으면)."""
    m, blob = load()
    if not m or menu not in blob["menus"]:
        return None
    f, level = make_features(blob["menus"].index(menu), hist, d, cal)
    if not level:
        return None
    ratio, contrib, base = m.predict(f)
    mid = level * ratio
    lo_q, hi_q = blob["range_ratio"]                       # 검증 기간 오차로 정한 80% 범위 (예측 대비 배수)
    groups = {}
    for k, v in contrib.items():
        if k in FLAGS and f.get(k) != 1.0:   # 그날 해당하지 않는 일(공휴일 아님 · 경기 없음 등)은 이유로 보여 주지 않음
            continue
        name = GROUPS.get(k, k)
        if name == "요일":
            name = f"{WEEKDAYS[d.weekday()]}요일"
        groups[name] = groups.get(name, 0.0) + v
    groups.pop("메뉴 특성", None)
    factors = {k: round(v, 3) for k, v in sorted(groups.items(), key=lambda kv: -abs(kv[1])) if abs(v) >= 0.005}
    return round(mid), round(mid * lo_q), round(mid * hi_q), factors
