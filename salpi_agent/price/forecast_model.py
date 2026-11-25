"""AI 학습 모델로 7일 시세 예측 (서버용: numpy 없이 순수 파이썬).

- 모델은 learner.py 가 매일 새벽 학습해 Supabase 보관함(models/forecast/<종류>.json)에 올림
- 서버는 1시간마다 새 모델을 읽고, 모델이 없거나 '고정 공식보다 낫다'는 시험을 못 넘었으면 고정 공식(analysis.py)을 그대로 씀
- 요인 계산(make_features)은 학습과 예측이 이 파일 하나를 같이 씀 → 학습 때와 화면 예측 때 숫자가 어긋나지 않음
- 기여도: 나무마다 지나간 갈림길에서 "이 요인 때문에 예상이 얼마나 바뀌었나"를 더함 → 요인별 % 합 = 예상 변화율
"""
import json
import math
import statistics
import threading
import time
from bisect import bisect_left, bisect_right
from datetime import date, timedelta

KINDS = {"야채": "veg", "과일": "fruit"}          # 종류 → 보관함 파일 이름
BAND = 2.0                                          # 오를 · 비슷 · 내릴 기준 (채점 · 화면과 같음)
MISSING = 63                                        # gbdt._Binner 의 빈 값 칸

# 설 · 추석 (명절까지 남은 날 요인). 2027은 한국천문연구원 음력 기준. 2016 ~ 2020은 서울 10년 학습 자료용
MAJOR_HOLIDAYS = [date(2016, 2, 8), date(2016, 9, 15), date(2017, 1, 28), date(2017, 10, 4), date(2018, 2, 16), date(2018, 9, 24),
                  date(2019, 2, 5), date(2019, 9, 13), date(2020, 1, 25), date(2020, 10, 1),
                  date(2021, 2, 12), date(2021, 9, 21), date(2022, 2, 1), date(2022, 9, 10), date(2023, 1, 22), date(2023, 9, 29),
                  date(2024, 2, 10), date(2024, 9, 17), date(2025, 1, 29), date(2025, 10, 6), date(2026, 2, 17), date(2026, 9, 25),
                  date(2027, 2, 7), date(2027, 9, 15)]
MAJOR_NEAR = 30   # 명절까지 이 날 수 안쪽일 때만 '다가오는 명절'로 따로 보여 줌

# 모델이 쓸 수 있는 요인 전부. 실제로 쓰는 요인은 모델마다 다름 (학습 담당이 넣고 빼며 시험)
ALL_FEATURES = ["item", "dev", "trend", "vchg", "vlevel", "wx", "rain", "cold", "hot", "volat", "chg3", "chg7",
                "season", "to_major", "month", "dow", "src"]   # src: 학습 줄 출처 (대구 0 · 서울 1), 화면 예측은 늘 0

# 화면에 보여 줄 이유 묶음 (요인 → 묶음 이름). 화면 app.js 의 plainReason 이 이 이름으로 한 줄 이유를 고름
GROUPS = {
    "dev": "4주 평균과의 차이",
    "vchg": "도매시장 반입량", "vlevel": "도매시장 반입량",
    "wx": "날씨(대구, 지난 7일)", "rain": "날씨(대구, 지난 7일)", "cold": "날씨(대구, 지난 7일)", "hot": "날씨(대구, 지난 7일)",
    "season": "계절(지난 해 같은 때)", "month": "계절(지난 해 같은 때)",
    "to_major": "다가오는 명절(설 · 추석)",
    "trend": "최근 값 흐름", "chg3": "최근 값 흐름", "chg7": "최근 값 흐름", "volat": "최근 값 흐름",
    "item": "품목 특성", "dow": "품목 특성", "src": "품목 특성",
}


def _pct(a, b):
    return (a / b - 1) * 100 if a and b else math.nan


def weather_effect(name, rain, cold, hot):
    from price.analysis import weather_effect as w   # 고정 공식의 날씨 점수를 요인 하나로 같이 줌
    return w(name, rain, cold, hot)[0]


def season_value(days, prices, asof):
    """앞선 해들의 같은 날 → 7일 뒤 변화(%)의 평균. 기준일보다 앞선 해만 씀 (미래를 보지 않음)."""
    seas = []
    for back in range(1, 6):
        d0 = asof - timedelta(365 * back)
        if not days or d0 < days[0]:
            break
        a = bisect_left(days, d0)
        b = bisect_right(days, d0 + timedelta(6))
        if a < len(days) and b < len(days) and abs((days[a] - d0).days) <= 3 and days[b] <= d0 + timedelta(10):
            seas.append((prices[b] / prices[a] - 1) * 100)
    return statistics.mean(seas) if seas else math.nan


def days_to_major(asof):
    return min([(h - asof).days for h in MAJOR_HOLIDAYS if (h - asof).days >= 0] or [99])


def make_features(name, item_idx, points, weather, asof, season):
    """points: [(날짜, kg당 가격, 반입량 kg)] 중 기준일 이전 28일 · weather: {날짜: (비 mm, 최저, 최고)}.
    돌려줌: {요인: 값}, 값이 없으면 NaN. 화면 설명용 숫자(_show)도 같이."""
    win = [p for p in points if asof - timedelta(28) < p[0] <= asof]
    pr = [p[1] for p in win]
    vols = [p[2] for p in win]
    f = {k: math.nan for k in ALL_FEATURES}
    f["item"] = float(item_idx)
    avg = statistics.mean(pr)
    f["dev"] = _pct(pr[-1], avg)
    # 2주 기울기 (backtest.old_trend 와 같은 계산, 세기 조정 없이)
    rec = [p for p in win if p[0] > asof - timedelta(15)]
    xs = [(p[0] - asof).days for p in rec]
    f["trend"] = (statistics.linear_regression(xs, [p[1] for p in rec]).slope * 7 / statistics.mean(p[1] for p in rec) * 100
                  if len(rec) >= 4 and len(set(xs)) >= 2 else 0.0)
    if len(vols) >= 8:
        f["vchg"] = _pct(statistics.mean(vols[-3:]), statistics.mean(vols[-13:-3]))
    if vols and statistics.mean(vols):
        f["vlevel"] = _pct(vols[-1], statistics.mean(vols))
    w = [weather[d] for d in (asof - timedelta(k) for k in range(7)) if d in weather]
    if w:
        f["rain"] = sum(x[0] or 0 for x in w)
        f["cold"] = float(sum(1 for x in w if (x[1] if x[1] is not None else 99) <= -3))
        f["hot"] = float(sum(1 for x in w if (x[2] or 0) >= 33))
        f["wx"] = weather_effect(name, f["rain"], f["cold"], f["hot"])
    else:
        f["wx"] = 0.0
    rets = [math.log(b / a) for a, b in zip(pr, pr[1:]) if a and b]
    if len(rets) > 2:
        f["volat"] = statistics.pstdev(rets) * 100
    if len(pr) >= 4:
        f["chg3"] = _pct(pr[-1], pr[-4])
    week = [p for p in win if p[0] <= asof - timedelta(7)]
    if week:
        f["chg7"] = _pct(pr[-1], week[-1][1])
    f["season"] = season if season is not None else math.nan
    f["to_major"] = float(days_to_major(asof))
    f["month"] = float(asof.month)
    f["dow"] = float(asof.weekday())
    f["src"] = 0.0
    f["_show"] = {"avg": avg, "last": pr[-1], "n": len(pr)}
    return f


# ---------------------------------------------------------------
# 학습된 모델 읽기 · 예측 (numpy 없이)
# ---------------------------------------------------------------

def _prepare(node):
    """[값, 건수] / [요인, 왼쪽 칸, 왼쪽, 오른쪽] → (값, 건수, 요인, 왼쪽 칸 set, 왼쪽, 오른쪽). 갈림 마디 값 = 아래 잎들의 건수 가중 평균."""
    if len(node) == 2:
        return (node[0], node[1], None, None, None, None)
    left, right = _prepare(node[2]), _prepare(node[3])
    n = left[1] + right[1]
    val = (left[0] * left[1] + right[0] * right[1]) / n if n else 0.0
    return (val, n, node[0], set(node[1]), left, right)


class Model:
    def __init__(self, blob):
        self.blob = blob
        self.features = blob["features"]
        b = blob["booster"]
        self.init, self.lr, self.edges, self.cat = b["init"], b["learning_rate"], b["edges"], set(b["cat_cols"])
        self.trees = [_prepare(t) for t in b["trees"]]
        self.items = blob["items"]

    def _bins(self, f):
        out = []
        for i, name in enumerate(self.features):
            x = f.get(name, math.nan)
            if x is None or not math.isfinite(x):
                out.append(MISSING)
            elif i in self.cat:
                out.append(int(x))
            else:
                out.append(bisect_right(self.edges[i], x))
        return out

    def predict(self, f):
        """→ (예상 변화율 %, {요인: 기여 %}, 기본값 %)"""
        bins = self._bins(f)
        contrib = {}
        base = self.init
        for t in self.trees:
            base += self.lr * t[0]
            node = t
            while node[2] is not None:
                nxt = node[4] if bins[node[2]] in node[3] else node[5]
                name = self.features[node[2]]
                contrib[name] = contrib.get(name, 0.0) + self.lr * (nxt[0] - node[0])
                node = nxt
        return base + sum(contrib.values()), contrib, base


# ---------------------------------------------------------------
# 서버: 보관함에서 모델 읽기 (1시간마다 새로)
# ---------------------------------------------------------------
_cache = {"at": 0.0, "models": {}}
_lock = threading.Lock()
TTL = 3600


def reset():
    with _lock:
        _cache["at"] = 0.0


def models():
    """{"야채": Model, "과일": Model} — 읽기 실패 · 화면 사용 꺼짐이면 빠짐 (→ 고정 공식)."""
    with _lock:
        if time.time() - _cache["at"] < TTL:
            return _cache["models"]
        out = {}
        try:
            from sources import supabase_db
            for kind, key in KINDS.items():
                raw = supabase_db.download("models", f"forecast/{key}.json")
                if raw:
                    blob = json.loads(raw)
                    if blob.get("use_on_screen"):
                        out[kind] = Model(blob)
        except Exception as e:   # 보관함 · 키 문제 → 고정 공식으로 (화면은 멈추지 않음)
            print(f"[AI 예측] 모델 읽기 실패, 고정 공식 사용: {e}", flush=True)
        _cache.update(at=time.time(), models=out)
        return out


def history():
    """매일 학습 기록 (최근 것부터)."""
    from sources import supabase_db
    raw = supabase_db.download("models", "forecast/history.json")
    return list(reversed(json.loads(raw))) if raw else []


def _detail(group, f, contrib_pct):
    s = f["_show"]
    if group == "4주 평균과의 차이":
        from price.analysis import avg_gap_text   # 숫자는 화면 '최근 한 달 시세 위치'에 있어 말로만
        return avg_gap_text("4주", f["dev"])
    if group == "도매시장 반입량":
        from price.analysis import volume_text
        return volume_text(f["vchg"]) if math.isfinite(f["vchg"]) else "물량 기록이 짧아요"
    if group.startswith("날씨"):
        if not math.isfinite(f["rain"]):
            return "날씨 기록 없음"
        # 0인 항목(영하 0일 등)은 빼고 있었던 것만
        parts = [p for p, on in ((f"비 {f['rain']:.0f}mm", f["rain"] >= 1), (f"영하 3도 이하 {f['cold']:.0f}일", f["cold"] > 0),
                                 (f"33도 이상 {f['hot']:.0f}일", f["hot"] > 0)) if on]
        return " · ".join(parts) or "비 · 추위 · 더위 없었어요"
    if group.startswith("계절"):
        if not math.isfinite(f["season"]):
            return f"{int(f['month'])}월의 평소 움직임"
        if abs(f["season"]) < 1:
            return "예년 이맘때 거의 그대로였어요"
        return f"예년 이맘때 {abs(f['season']):.1f}% {'올랐' if f['season'] > 0 else '내렸'}어요"
    if group.startswith("다가오는 명절"):
        return f"명절까지 {int(f['to_major'])}일 남았어요"
    if group == "최근 값 흐름":
        # 예: 1주 새 −24% 내렸는데 이유는 '오를 쪽' → 많이 내린 뒤 되돌아오는 움직임이라고 말로 풀어 줌
        move = f["chg7"] if math.isfinite(f["chg7"]) else f["chg3"]
        if not math.isfinite(move):
            return "최근 거래가 적어요"
        if abs(move) < 3:
            return "1주 새 거의 그대로예요"
        if move * contrib_pct < 0:   # 많이 내렸는데 ▲ (또는 반대) → 되돌아오는 움직임
            return f"{abs(move):.0f}% {'내려서 반등할' if move < 0 else '올라서 내려올'} 수 있어요"
        return f"1주 새 {abs(move):.0f}% {'내렸' if move < 0 else '올랐'}어요"
    return "이 품목이 평소에 움직이는 정도"


def forecast(name, kind, points, weather, asof):
    """학습 모델 예측 → analysis.forecast_item 과 같은 모양의 일부. 쓸 모델이 없으면 None."""
    m = models().get(kind)
    if not m or name not in m.items or len(points) < 8:
        return None
    season = (m.blob.get("season", {}).get(name) or {}).get(asof.isoformat())
    f = make_features(name, m.items.index(name), points, weather, asof, season)
    total, contrib, base = m.predict(f)
    groups = {}
    far = f["to_major"] > MAJOR_NEAR   # 명절이 멀면 '날짜에 따른 움직임'이라 계절에 합침 (80일 뒤 명절이 7일 예측 이유로 보이지 않게)
    for k, v in contrib.items():
        g = GROUPS["season"] if k == "to_major" and far else GROUPS.get(k, "품목 특성")
        groups[g] = groups.get(g, 0.0) + v
    groups["품목 특성"] = groups.get("품목 특성", 0.0) + base   # 모든 품목 공통 기본값도 품목 특성에 합침
    factors = [{"factor": g, "effect_pct": round(v, 1), "detail": _detail(g, f, v)} for g, v in groups.items()]
    factors.sort(key=lambda x: -abs(x["effect_pct"]))
    half = (m.blob.get("range_half_pct") or {}).get(name) or m.blob.get("range_half_pct_all") or 8.0
    return {"expected_change_pct": round(total, 1), "range_pct": [round(total - half, 1), round(total + half, 1)],
            "factors": factors, "version": m.blob["version"], "metrics": m.blob.get("metrics")}
