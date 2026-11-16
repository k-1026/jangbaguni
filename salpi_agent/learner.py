"""시세 검증 담당: 매일 새벽 AI 예측 모델을 다시 학습 → 시험 → 더 나을 때만 스스로 교체.

실행:  .venv\\Scripts\\python learner.py              (학습 · 시험 · 보관함에 올리기, 몇 분)
       .venv\\Scripts\\python learner.py --dry-run    (올리지 않고 결과만 보기)
       .venv\\Scripts\\python learner.py --kinds 야채  (한 종류만)
매일 새벽 GitHub 예약 실행(.github/workflows/daily-learn.yml)이 돌림.

하루 흐름 (야채 · 과일 따로)
  1. 자료: 5년 치 파일(data/raw/1109_5y) + 그 뒤 날짜는 aT · 기상청 API로 받아 보관함에 쌓아 둔 것
  2. 지금 모델(챔피언)의 설정으로 어제까지 자료를 넣어 다시 학습 · 시험
  3. AI(제미나이)가 시험 결과 · 많이 틀린 품목 · 지난 실험 기록을 보고 오늘 해 볼 실험 2개를 고름
     (요인 빼기 · 넣기, 학습 설정 바꾸기 — 정해진 목록 안에서만. AI가 숫자를 만들거나 공식을 직접 고치지 않음)
  4. 실험 모델(도전자)을 같은 자료 · 같은 시험으로 채점
  5. 교체 기준을 넘는 도전자가 있으면 챔피언 교체 (아니면 그대로)
  6. 챔피언 설정으로 전체 자료를 학습한 모델을 보관함에 올림 → 서버가 1시간 안에 새 모델로 예측
     단, 고정 공식보다 못하면 화면에는 고정 공식을 그대로 씀 (use_on_screen = false)

지표 3개 (plan/forecast/1116_self_learning_forecast.md)
  정반대   : 오른다 했는데 내렸거나 그 반대 (±2% 기준) → 목표. 줄여야 함
  평균 오차 : |예상 변화율 − 실제 변화율| 평균 (%p) → 안전장치. 나빠지면 안 됨
  범위 적중 : 7일 뒤 실제 값이 화면의 예상 범위 안에 든 비율 → 화면 · 사장님용
교체 기준: 시험 기간(최근 1년)에서 정반대가 0.3%p 이상 줄고, 평균 오차는 같거나 줄 것
"""
import argparse
import json
import math
import os
import time
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone

import numpy as np

import backtest as B
import data_sources as ds
import forecast_model as FM
from analysis import FRUIT_REVERSION, FRUIT_VOLUME, VEG_REVERSION, VEG_VOLUME, reversion_factor, volume_factor
from gbdt import GBDT

KST = timezone(timedelta(hours=9))
BUCKET = "models"
PROMOTE_OPP = 0.3            # 정반대가 이만큼(%p) 이상 줄어야 교체
RANGE_Q = 70                 # 예상 범위 = 지난 1년 오차의 70% 지점 (범위 적중 70% 목표)
EXPERIMENTS_PER_DAY = 2

DEFAULT_CONFIG = {
    "features": ["item", "dev", "trend", "vchg", "wx", "rain", "cold", "hot", "volat", "chg3", "season", "to_major", "month"],
    "params": {"learning_rate": 0.05, "max_depth": 4, "min_leaf": 150, "objective": "l1", "l2": 5.0},
}
PARAM_GRID = {"learning_rate": [0.03, 0.05, 0.1], "max_depth": [3, 4, 5, 6], "min_leaf": [50, 100, 150, 300],
              "objective": ["l1", "l2"], "l2": [1.0, 5.0, 20.0]}
LOCKED = {"item", "dev"}     # 늘 쓰는 요인 (빼지 않음)
FEATURE_KO = {"item": "품목", "dev": "4주 평균과의 차이", "trend": "2주 기울기", "vchg": "반입량 변화", "vlevel": "반입량 수준",
              "wx": "날씨 점수", "rain": "비", "cold": "한파 일수", "hot": "폭염 일수", "volat": "변동성",
              "chg3": "최근 3거래일 변화", "chg7": "1주 전 대비", "season": "지난 해 같은 때", "to_major": "명절까지 남은 날",
              "month": "월", "dow": "요일"}
PARAM_KO = {"learning_rate": "학습 속도", "max_depth": "나무 깊이", "min_leaf": "잎 최소 건수", "objective": "오차 기준", "l2": "규제 세기"}


def today():
    return datetime.now(KST).date()


# ---------------------------------------------------------------
# 보관함 (Supabase Storage, 비공개 'models')
# ---------------------------------------------------------------

def load_json(path, default):
    import supabase_db
    raw = supabase_db.download(BUCKET, path)
    return json.loads(raw) if raw else default


def save_json(path, obj):
    import supabase_db
    supabase_db.upload(BUCKET, path, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), "application/json")


# ---------------------------------------------------------------
# 1. 자료: 5년 치 파일 + 그 뒤 날짜 (API로 받아 보관함에 쌓음)
# ---------------------------------------------------------------

def _day_agg(rows):
    """하루 정산 결과 → {품목: [반입량 kg, 금액]} (analysis.wholesale_series 와 같은 거르기)."""
    out = {}
    for name, cfg in ds.ITEMS.items():
        hits = [r for r in rows if r["gds_mclsf_nm"] == cfg["sale_name"]
                and (not cfg["sale_sub"] or cfg["sale_sub"] in (r["gds_sclsf_nm"] or "")) and r["unit_nm"] == "kg"]
        qty = sum(float(r["unit_tot_qty"] or 0) for r in hits)
        amount = sum(float(r["totprc"] or 0) for r in hits)
        if qty > 0 and amount > 0:
            out[name] = [qty, amount]
    return out


def load_data(upload=True):
    series, weather = B.load_veg()
    csv_end = max(p[0] for s in series.values() for p in s)
    w_end = max(weather)
    recent = load_json("forecast/recent_data.json", {"sale": {}, "weather": {}})
    end = today() - timedelta(1)                      # 오늘 경매는 아직 끝나지 않았을 수 있어 어제까지
    fetched = 0
    d = csv_end + timedelta(1)
    while d <= end:
        iso = d.isoformat()
        if iso not in recent["sale"] or (end - d).days <= 2:   # 최근 사흘은 늦게 올라오는 값이 있어 다시 받음
            try:
                recent["sale"][iso] = _day_agg(ds.sale_day(d))
                fetched += 1
            except Exception as e:
                print(f"  ! {iso} 경락 자료 받기 실패 ({e}) → 다음에 다시")
        d += timedelta(1)
    need = (end - w_end).days
    if need > 0:
        try:
            for w in ds.weather_days(min(need + 3, 100)):
                recent["weather"][w["date"]] = [w["rain_mm"], w["min_temp"], w["max_temp"]]
        except Exception as e:
            print(f"  ! 날씨 받기 실패 ({e})")
    if upload and fetched:
        save_json("forecast/recent_data.json", recent)
    for iso, agg in recent["sale"].items():
        d = date.fromisoformat(iso)
        if d > csv_end:
            for name, (q, a) in agg.items():
                series.setdefault(name, []).append((d, a / q, q))
    for s in series.values():
        s.sort()
    for iso, v in recent["weather"].items():
        d = date.fromisoformat(iso)
        if d > w_end:
            weather[d] = (v[0] or 0.0, v[1], v[2])
    last = max(p[0] for s in series.values() for p in s)
    print(f"자료: 5년 치 파일 ~{csv_end} + API {len([k for k in recent['sale'] if date.fromisoformat(k) > csv_end])}일 → 마지막 거래일 {last}")
    return series, weather, last


def formula_pred(name, kind, f_points, weather_pct):
    pr = [p[1] for p in f_points]
    vols = [p[2] for p in f_points]
    fruit = kind == "과일"
    rev = reversion_factor(pr, *(FRUIT_REVERSION if fruit else VEG_REVERSION))
    vol = volume_factor(vols, *(FRUIT_VOLUME if fruit else VEG_VOLUME))
    return (rev["effect_pct"] if rev else 0) + (vol["effect_pct"] if vol else 0) + (0 if fruit else weather_pct)


def build_rows(series, weather, kind):
    """기준일마다 요인 · 고정 공식 예측 · 7일 뒤 실제 변화(7~10일 안 첫 거래일)."""
    names = sorted(n for n in series if n in ds.ITEMS and ds.kind_of(n) == kind)
    rows = []
    for idx, name in enumerate(names):
        s = series[name]
        days = [p[0] for p in s]
        prices = [p[1] for p in s]
        for i in range(30, len(s)):
            asof = days[i]
            j = bisect_right(days, asof + timedelta(6))
            if asof < date(2021, 3, 1) or j >= len(s) or days[j] > asof + timedelta(10):
                continue
            pts = s[max(0, i - 40): i + 1]
            f = FM.make_features(name, idx, pts, weather, asof, FM.season_value(days, prices, asof))
            win = [p for p in pts if p[0] > asof - timedelta(28)]
            rows.append((asof, idx, f, formula_pred(name, kind, win, f["wx"]), (prices[j] / prices[i] - 1) * 100))
    return names, rows


# ---------------------------------------------------------------
# 2 · 4. 학습 · 시험
# ---------------------------------------------------------------

def score(pred, act, half):
    cls = lambda x: np.where(x >= FM.BAND, 1, np.where(x <= -FM.BAND, -1, 0))
    p, a = cls(pred), cls(act)
    return {"n": int(len(act)), "opposite_pct": round(float(((p * a) == -1).mean() * 100), 2),
            "mae_pp": round(float(np.abs(pred - act).mean()), 3),
            "range_hit_pct": round(float((np.abs(act - pred) <= half).mean() * 100), 1),
            "direction_hit_pct": round(float((p == a).mean() * 100), 1)}   # 참고용 (판단에는 안 씀)


class Data:
    def __init__(self, names, rows):
        self.names = names
        self.asof = np.array([r[0] for r in rows])
        self.item = np.array([r[1] for r in rows])
        self.cols = {k: np.array([r[2][k] for r in rows], dtype=float) for k in FM.ALL_FEATURES}
        self.formula = np.array([r[3] for r in rows])
        self.y = np.array([r[4] for r in rows])
        last = self.asof.max()
        self.test = self.asof > last - timedelta(365)                 # 시험: 최근 1년
        self.pre = self.asof <= last - timedelta(375)                 # 시험 전 (7일 뒤 값이 시험 기간과 겹치지 않게 10일 띄움)
        pre_end = self.asof[self.pre].max()
        self.val = self.pre & (self.asof > pre_end - timedelta(365))  # 나무 수 고르기용
        self.fit = self.pre & (self.asof <= pre_end - timedelta(375))
        self.period = [str(self.asof[self.test].min()), str(last)]

    def X(self, feats):
        return np.column_stack([self.cols[k] for k in feats])

    def half_by_item(self, resid_abs, mask):
        """품목별 예상 범위 반폭 = 오차의 70% 지점 (건수가 적으면 전체)."""
        allq = float(np.percentile(resid_abs, RANGE_Q))
        out = {}
        for i, name in enumerate(self.names):
            r = resid_abs[self.item[mask] == i]
            out[name] = round(float(np.percentile(r, RANGE_Q)), 2) if len(r) >= 30 else round(allq, 2)
        return out, round(allq, 2)


def _gbdt(cfg, n_rounds=2000):
    return GBDT(cat_cols=[cfg["features"].index("item")], n_rounds=n_rounds, **cfg["params"])


def evaluate(D, cfg):
    """시험 전 자료로 학습 → 최근 1년 시험. 예상 범위 폭은 시험 전 1년(검증) 오차로 정함 (시험 답을 보지 않음)."""
    t = time.time()
    X = D.X(cfg["features"])
    probe = _gbdt(cfg).fit(X[D.fit], D.y[D.fit], X[D.val], D.y[D.val])
    n = max(probe.best_iteration, 20)
    m = _gbdt(cfg, n).fit(X[D.pre], D.y[D.pre])
    half_val, half_all = D.half_by_item(np.abs(D.y[D.val] - probe.predict(X[D.val])), D.val)
    pred = m.predict(X[D.test])
    half = np.array([half_val[D.names[i]] for i in D.item[D.test]])
    per_item = {}
    for i, name in enumerate(D.names):
        k = D.item[D.test] == i
        if k.sum() >= 20:
            per_item[name] = score(pred[k], D.y[D.test][k], half[k])
    imp = m.importance(len(cfg["features"]))
    tot = imp.sum() or 1
    return {"n_rounds": n, "metrics": score(pred, D.y[D.test], half), "items": per_item,
            "importance": {f: round(float(v / tot * 100)) for f, v in sorted(zip(cfg["features"], imp), key=lambda x: -x[1])},
            "test_abs_resid": np.abs(D.y[D.test] - pred), "seconds": round(time.time() - t)}


def formula_metrics(D):
    pred = D.formula[D.test]
    resid = np.abs(D.y[D.val] - D.formula[D.val])
    half_val, _ = D.half_by_item(resid, D.val)
    half = np.array([half_val[D.names[i]] for i in D.item[D.test]])
    return score(pred, D.y[D.test], half)


def better(a, b):
    """도전자 a 가 챔피언 b 를 이기나: 정반대 0.3%p 이상 ↓ 그리고 평균 오차 같거나 ↓"""
    return a["opposite_pct"] <= b["opposite_pct"] - PROMOTE_OPP and a["mae_pp"] <= b["mae_pp"]


# ---------------------------------------------------------------
# 3. AI 판단: 오늘 해 볼 실험 고르기 (정해진 목록 안에서만)
# ---------------------------------------------------------------

def menu(cfg):
    """챔피언 설정에서 한 가지만 바꾼 실험 목록 → [(id, 설명, 바꾼 설정)]"""
    out = []
    for f in cfg["features"]:
        if f not in LOCKED:
            out.append((f"drop:{f}", f"'{FEATURE_KO[f]}' 요인 빼기", {**cfg, "features": [x for x in cfg["features"] if x != f]}))
    for f in FM.ALL_FEATURES:
        if f not in cfg["features"]:
            out.append((f"add:{f}", f"'{FEATURE_KO[f]}' 요인 넣기", {**cfg, "features": cfg["features"] + [f]}))
    for p, values in PARAM_GRID.items():
        for v in values:
            if cfg["params"][p] != v:
                out.append((f"set:{p}={v}", f"{PARAM_KO[p]} {cfg['params'][p]} → {v}", {**cfg, "params": {**cfg["params"], p: v}}))
    return out


def _gemini_json(prompt):
    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        return None
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=key)
    models = [os.getenv("GEMINI_MODEL", "gemini-3.5-flash")] + [
        m.strip() for m in os.getenv("GEMINI_FALLBACK_MODELS", "gemini-3-flash-preview,gemini-flash-latest,gemini-3.5-flash-lite").split(",") if m.strip()]
    for model in models:
        try:
            r = client.models.generate_content(model=model, contents=prompt, config=types.GenerateContentConfig(
                response_mime_type="application/json", temperature=0.4))
            return json.loads(r.text)
        except Exception as e:
            print(f"  ! AI({model}) 실패: {type(e).__name__} → 다음 모델")
    return None


def choose_experiments(kind, cfg, champ, formula, past):
    """AI가 실험을 고름. AI를 못 쓰면 최근 2주 안 해 본 것부터 차례로."""
    options = menu(cfg)
    ids = [o[0] for o in options]
    tried = [e["id"] for h in past for e in h.get("experiments", [])]
    worst = sorted(champ["items"].items(), key=lambda kv: -kv[1]["opposite_pct"])[:5]
    prompt = f"""너는 식자재 도매 시세 7일 예측 모델을 매일 개선하는 '시세 검증 담당' AI다.
종류: {kind}. 모델: 그래디언트 부스팅. 목표 지표는 '정반대 비율'(줄일 것), 안전장치는 '평균 오차'(나빠지면 안 됨).
교체 기준: 정반대 {PROMOTE_OPP}%p 이상 감소 + 평균 오차 같거나 감소.

[지금 모델 설정] 요인: {', '.join(FEATURE_KO[f] for f in cfg['features'])} / 학습 설정: {json.dumps(cfg['params'], ensure_ascii=False)}
[최근 1년 시험] 지금 모델: {json.dumps(champ['metrics'], ensure_ascii=False)} / 고정 공식: {json.dumps(formula, ensure_ascii=False)}
[요인 중요도 %] {json.dumps({FEATURE_KO[k]: v for k, v in champ['importance'].items()}, ensure_ascii=False)}
[정반대가 많은 품목] {json.dumps({k: {'정반대': v['opposite_pct'], '평균오차': v['mae_pp']} for k, v in worst}, ensure_ascii=False)}
[지난 실험 (최근 것부터)] {json.dumps([{'날짜': h['date'], '실험': [(e['id'], e['metrics']['opposite_pct'], e['metrics']['mae_pp'], e['promoted']) for e in h.get('experiments', [])]} for h in past[:10]], ensure_ascii=False)}

고를 수 있는 실험 (id: 설명):
{chr(10).join(f'- {i}: {d}' for i, d, _ in options)}

오늘 해 볼 실험 {EXPERIMENTS_PER_DAY}개를 위 id 중에서 골라라. 최근에 해 봤는데 효과가 없던 것은 피하라.
JSON으로만 답하라: {{"experiments": [{{"id": "...", "why": "고른 이유 한 문장"}}], "diagnosis": "지금 모델이 어디서 왜 틀리는지 2~3문장"}}
diagnosis 와 why 는 쉬운 한국어로, 위에 주어진 숫자만 인용하고 새 숫자를 만들지 마라."""
    ai = _gemini_json(prompt) or {}
    picked = []
    for e in ai.get("experiments") or []:
        if isinstance(e, dict) and e.get("id") in ids and e["id"] not in [p["id"] for p in picked]:
            picked.append({"id": e["id"], "why": str(e.get("why", ""))[:200], "by": "AI"})
    for i in ids:   # AI가 못 고른 만큼 채움: 최근에 안 해 본 것부터
        if len(picked) >= EXPERIMENTS_PER_DAY:
            break
        if i not in tried and i not in [p["id"] for p in picked]:
            picked.append({"id": i, "why": "최근 2주 안 해 본 실험 (차례대로)", "by": "규칙"})
    cfgs = {o[0]: (o[1], o[2]) for o in options}
    return [{**p, "label": cfgs[p["id"]][0], "config": cfgs[p["id"]][1]} for p in picked[:EXPERIMENTS_PER_DAY]], \
        str(ai.get("diagnosis") or "")[:600]


# ---------------------------------------------------------------
# 5 · 6. 교체 · 배포
# ---------------------------------------------------------------

def deploy_blob(D, kind, cfg, res, formula, series):
    X = D.X(cfg["features"])
    final = _gbdt(cfg, res["n_rounds"]).fit(X, D.y)
    half, half_all = D.half_by_item(res["test_abs_resid"], D.test)
    t = today()
    season = {}
    for name in D.names:
        days = [p[0] for p in series[name]]
        prices = [p[1] for p in series[name]]
        season[name] = {(t + timedelta(k)).isoformat(): round(v, 3)
                        for k in range(-14, 31) if math.isfinite(v := FM.season_value(days, prices, t + timedelta(k)))}
    m = res["metrics"]
    return {
        "version": f"ai-{FM.KINDS[kind]}-{t:%Y%m%d}", "kind": kind, "trained_at": datetime.now(KST).isoformat(timespec="seconds"),
        "config": cfg, "features": cfg["features"], "n_rounds": res["n_rounds"], "items": D.names,
        "booster": final.export(), "season": season, "range_half_pct": half, "range_half_pct_all": half_all,
        "metrics": m, "formula_metrics": formula, "test_period": D.period, "train_rows": int(len(D.y)),
        # 고정 공식보다 정반대 · 평균 오차 둘 다 낫거나 같을 때만 화면에 씀
        "use_on_screen": m["opposite_pct"] <= formula["opposite_pct"] and m["mae_pp"] <= formula["mae_pp"],
    }


def run_kind(kind, series, weather, past_all, upload):
    key = FM.KINDS[kind]
    print(f"\n===== {kind} =====")
    names, rows = build_rows(series, weather, kind)
    D = Data(names, rows)
    print(f"기준일 {len(D.y):,}건 (학습 {D.pre.sum():,} / 시험 {D.test.sum():,}, 시험 기간 {D.period[0]} ~ {D.period[1]})")
    prev = load_json(f"forecast/{key}.json", None) if upload else None
    cfg = (prev or {}).get("config") or DEFAULT_CONFIG
    formula = formula_metrics(D)
    champ = evaluate(D, cfg)
    print(f"고정 공식   {fmt(formula)}")
    print(f"지금 모델   {fmt(champ['metrics'])}  (나무 {champ['n_rounds']}개, {champ['seconds']}초)")
    past = [h for h in past_all if h["kind"] == kind and h["date"] >= str(today() - timedelta(14))]
    exps, diagnosis = choose_experiments(kind, cfg, champ, formula, past)
    best = None
    for e in exps:
        r = evaluate(D, e["config"])
        e["metrics"], e["promoted"] = r["metrics"], False
        print(f"실험 {e['id']:<24}{fmt(r['metrics'])}  [{e['by']}] {e['why']}")
        if better(r["metrics"], champ["metrics"]) and (not best or r["metrics"]["opposite_pct"] < best[1]["metrics"]["opposite_pct"]):
            best = (e, r)
    if best:
        best[0]["promoted"] = True
        cfg, champ = best[0]["config"], best[1]
        print(f"→ 교체: {best[0]['label']}")
    else:
        print("→ 교체 기준을 넘은 실험이 없어 지금 모델 유지 (오늘 자료로 다시 학습만)")
    blob = deploy_blob(D, kind, cfg, champ, formula, series)
    print(f"화면 사용: {'AI 모델' if blob['use_on_screen'] else '고정 공식 (AI 모델이 아직 못 이김)'} · 버전 {blob['version']}")
    if upload:
        save_json(f"forecast/{key}.json", blob)
    return {
        "date": str(today()), "kind": kind, "version": blob["version"], "config": cfg, "metrics": champ["metrics"],
        "formula_metrics": formula, "use_on_screen": blob["use_on_screen"], "test_period": D.period,
        "experiments": [{k: e[k] for k in ("id", "label", "why", "by", "metrics", "promoted")} for e in exps],
        "promoted": bool(best), "diagnosis": diagnosis, "importance": champ["importance"],
        "worst_items": dict(sorted(champ["items"].items(), key=lambda kv: -kv[1]["opposite_pct"])[:5]),
    }


def fmt(m):
    return f"정반대 {m['opposite_pct']:5.1f}% · 평균 오차 {m['mae_pp']:5.2f}%p · 범위 적중 {m['range_hit_pct']:5.1f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="보관함에 올리지 않음")
    ap.add_argument("--kinds", nargs="*", default=list(FM.KINDS))
    a = ap.parse_args()
    upload = not a.dry_run
    t = time.time()
    series, weather, _ = load_data(upload)
    history = load_json("forecast/history.json", []) if upload else []
    past = list(reversed(history))
    for kind in a.kinds:
        entry = run_kind(kind, series, weather, past, upload)
        history.append(entry)
    if upload:
        save_json("forecast/history.json", history[-400:])
    print(f"\n끝 ({round(time.time() - t)}초)")


if __name__ == "__main__":
    main()
