"""고객 세그먼트: 대구 일반음식점 3만 곳을 비지도 학습(k-평균 군집)으로 묶기.

자료: data/raw/1118_daegu_restaurants.csv (공공데이터포털 '대구광역시_음식점 등록현황_20250523', 업소명 · 업종 · 업태 · 주소)
     면적 · 개업일은 이 자료에 없음 (전국 인허가 자료는 포털에서 바로 받을 수 없었음)

순서
  1. 업소마다: 업태 묶음(업태 + 이름 낱말로 '기타' 다시 나눔) · 프랜차이즈 여부(같은 상호가 대구에 5곳 이상) · 구 · 동
  2. 상권(동) 묶기: 동마다 업태 묶음 비율 · 가게 수 · 프랜차이즈 비율 → k-평균 → 상권 유형
  3. 가게 묶기: 업태 묶음 · 프랜차이즈 · 상권 유형 · 동 가게 수 · 같은 업태 경쟁 비율 → k-평균 → 세그먼트
     묶음 수는 3~8개 중 실루엣 점수(묶음끼리 얼마나 잘 떨어지나)로 고름
  4. 세그먼트마다 크기 · 특징 → 페르소나 10명이 어디에 드는지 · 살피가 먼저 노릴 묶음

실행:  .venv\\Scripts\\python segment.py   → data/segment/ 에 결과 표, 화면에 요약
scikit-learn 을 이 PC 보안 정책이 막아서 k-평균 · 실루엣은 numpy 로 직접 계산
"""
import csv
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "raw" / "1118_daegu_restaurants.csv"
OUT = ROOT / "data" / "segment"
SEED = 7

# 업태 → 묶음
GROUP_OF = {
    "한식": "한식", "탕류(보신용)": "한식", "냉면집": "한식",
    "분식": "분식", "김밥(도시락)": "분식",
    "식육(숯불구이)": "고기구이",
    "중국식": "중식", "일식": "일식·회", "회집": "일식·회", "복어취급": "일식·회",
    "경양식": "양식·외국", "외국음식전문점(인도,태국등)": "양식·외국", "패밀리레스토랑": "양식·외국", "뷔페식": "양식·외국",
    "호프/통닭": "치킨·주점", "정종/대포집/소주방": "치킨·주점", "감성주점": "치킨·주점", "라이브카페": "치킨·주점",
}
# '기타' · 빈 업태는 이름 낱말로 다시 나눔 (앞에서부터 처음 맞는 것)
NAME_RULES = [
    ("카페·디저트", r"카페|커피|cafe|coffee|베이커리|제과|빵|디저트|케이크|와플|빙수|도넛|tea|티하우스"),
    ("치킨·주점", r"치킨|통닭|호프|포차|주점|이자카야|펍|pub|bar|맥주|와인"),
    ("분식", r"분식|떡볶이|김밥|김밥|라면|토스트|핫도그|순대"),
    ("고기구이", r"고기|갈비|삼겹|막창|곱창|숯불|한우|정육|돼지|대패|양꼬치"),
    ("양식·외국", r"피자|버거|파스타|스테이크|브런치|타코|쌀국수|샌드위치|햄버거|레스토랑"),
    ("중식", r"반점|짬뽕|짜장|중화|마라"),
    ("일식·회", r"초밥|스시|돈까스|돈가스|라멘|우동|횟집|회센터|오마카세|이자카"),
    ("한식", r"국밥|찌개|백반|식당|한식|칼국수|국수|냉면|순두부|보쌈|족발|해장|곰탕|추어탕|찜|밥상|정식|도시락"),
]
FEATURE_GROUPS = ["한식", "분식", "고기구이", "중식", "일식·회", "양식·외국", "치킨·주점", "카페·디저트", "기타"]
# 살피가 돕기 좋은 업태: 매일 여러 재료를 직접 사서 메뉴 원가가 시세에 바로 흔들리는 식사 가게
MEAL = {"한식", "분식", "고기구이", "중식", "일식·회", "양식·외국"}

# 페르소나 10명 (data/simulation/personas.mjs) → 이 자료의 말로 바꿈
PERSONAS = [
    ("S1-A", "수성구 백반집", "한식", "수성구", False), ("S1-B", "달서구 국밥집", "한식", "달서구", False),
    ("S2-A", "북구 기사식당", "한식", "북구", False), ("S2-B", "동구 분식집", "분식", "동구", False),
    ("S3-A", "성서공단 위탁급식", None, "달서구", False), ("S3-B", "칠곡 프랜차이즈 3호점", "한식", "북구", True),
    ("S4-A", "중구 찌개집", "한식", "중구", False), ("S4-B", "서구 돼지국밥", "한식", "서구", False),
    ("S5-A", "남구 한정식", "한식", "남구", False), ("S5-B", "수성구 칼국수", "한식", "수성구", False),
]


# ---------------------------------------------------------------
# 1. 업소 정리
# ---------------------------------------------------------------

def group_of(kind, name):
    g = GROUP_OF.get(kind)
    if g:
        return g
    low = name.lower()
    for grp, pat in NAME_RULES:
        if re.search(pat, low):
            return grp
    return "기타"


def brand_of(name):
    """'교촌치킨 범어점' → '교촌치킨', '맘스터치대구동성로점' → '맘스터치대구동성로' (띄어쓰기 없는 지점은 못 떼어 냄)."""
    n = re.sub(r"\(.*?\)", "", name).strip()
    parts = n.split()
    if len(parts) >= 2 and parts[-1].endswith("점"):
        n = " ".join(parts[:-1])
    return re.sub(r"\s+", "", n).lower()


def place_of(addr):
    m = re.search(r"대구광역시\s+(\S+)", addr)
    gu = m.group(1) if m else "?"
    dong = None
    p = re.search(r"\(([^)]*)\)\s*$", addr)
    if p:
        toks = [t for t in re.split(r"[ ,]", p.group(1)) if re.search(r"(동|가|리)\d*$", t) and not re.search(r"\d+층|호$", t)]
        dong = toks[-1] if toks else None
    if not dong:
        e = re.search(r"\s(\S+[읍면])\s", addr)
        dong = e.group(1) if e else None
    return gu, dong or "?"


def load():
    rows = list(csv.DictReader(open(SRC, encoding="utf-8")))
    shops = []
    for r in rows:
        gu, dong = place_of(r["업소주소"])
        shops.append({"name": r["업소명"].strip(), "kind": r["업태"].strip(), "group": group_of(r["업태"].strip(), r["업소명"]),
                      "brand": brand_of(r["업소명"]), "gu": gu, "dong": f"{gu} {dong}"})
    brands = Counter(s["brand"] for s in shops)
    for s in shops:
        s["chain"] = brands[s["brand"]] >= 5
    return shops


# ---------------------------------------------------------------
# k-평균 · 실루엣 (numpy)
# ---------------------------------------------------------------

def kmeans(X, k, rng, n_init=8, iters=100):
    best = None
    for _ in range(n_init):
        c = X[rng.integers(len(X))][None, :]
        while len(c) < k:   # k-means++ 시작점
            d = ((X[:, None, :] - c[None, :, :]) ** 2).sum(-1).min(1)
            c = np.vstack([c, X[rng.choice(len(X), p=d / d.sum())]])
        for _ in range(iters):
            lab = ((X[:, None, :] - c[None, :, :]) ** 2).sum(-1).argmin(1)
            new = np.array([X[lab == j].mean(0) if (lab == j).any() else c[j] for j in range(k)])
            if np.allclose(new, c):
                break
            c = new
        inertia = ((X - c[lab]) ** 2).sum()
        if best is None or inertia < best[0]:
            best = (inertia, lab, c)
    return best[1], best[2]


def silhouette(X, lab, rng, n=2500):
    idx = rng.choice(len(X), min(n, len(X)), replace=False)
    Xs, ls = X[idx], lab[idx]
    D = np.sqrt(((Xs[:, None, :] - Xs[None, :, :]) ** 2).sum(-1))
    s = []
    for i in range(len(Xs)):
        same = ls == ls[i]
        if same.sum() <= 1:
            s.append(0.0)
            continue
        a = D[i, same].sum() / (same.sum() - 1)
        b = min(D[i, ls == j].mean() for j in set(ls.tolist()) if j != ls[i])
        s.append((b - a) / max(a, b))
    return float(np.mean(s))


def choose_k(X, ks, rng):
    scores = {}
    for k in ks:
        lab, c = kmeans(X, k, rng)
        scores[k] = (silhouette(X, lab, rng), lab, c)
    k = max(scores, key=lambda k: scores[k][0])
    return k, scores


def z(a):
    a = np.asarray(a, float)
    return (a - a.mean(0)) / (a.std(0) + 1e-9)


# ---------------------------------------------------------------
# 2 · 3. 상권 묶기 → 가게 묶기
# ---------------------------------------------------------------

def area_types(shops, rng):
    by = defaultdict(list)
    for s in shops:
        if not s["dong"].endswith("?"):
            by[s["dong"]].append(s)
    dongs = [d for d, v in by.items() if len(v) >= 15]   # 가게 15곳 미만인 동은 비율이 흔들려서 뺌 (그 동 가게는 '작은 상권')
    feats = []
    for d in dongs:
        v = by[d]
        cnt = Counter(s["group"] for s in v)
        feats.append([cnt[g] / len(v) for g in FEATURE_GROUPS] + [math.log(len(v)), sum(s["chain"] for s in v) / len(v)])
    X = z(feats)
    k, scores = choose_k(X, range(3, 7), rng)
    lab = scores[k][1]
    # 이름 붙이기: 묶음 평균이 전체 평균보다 가장 높은 업태 · 가게 수
    F = np.array(feats)
    names = {}
    for j in range(k):
        m = F[lab == j].mean(0)
        over = sorted(((m[i] - F[:, i].mean()) / (F[:, i].std() + 1e-9), FEATURE_GROUPS[i]) for i in range(len(FEATURE_GROUPS)))[::-1]
        size = "큰 상권" if m[-2] > F[:, -2].mean() + 0.3 else "작은 상권" if m[-2] < F[:, -2].mean() - 0.3 else "보통 상권"
        names[j] = f"{size} · {over[0][1]}·{over[1][1]} 많음"
    area = {d: names[l] for d, l in zip(dongs, lab)}
    summary = {names[j]: {"동 수": int((lab == j).sum()), "가게 수": int(sum(len(by[d]) for d, l in zip(dongs, lab) if l == j)),
                          "평균 가게 수": round(float(np.exp(F[lab == j, -2]).mean())),
                          "업태 비율": {g: round(float(F[lab == j, i].mean() * 100)) for i, g in enumerate(FEATURE_GROUPS)},
                          "프랜차이즈 %": round(float(F[lab == j, -1].mean() * 100))} for j in range(k)}
    return area, summary, {kk: round(v[0], 3) for kk, v in scores.items()}, by


def shop_segments(shops, area, by, rng):
    types = sorted(set(area.values())) + ["작은 상권(가게 15곳 미만)"]
    rows = []
    for s in shops:
        s["area"] = area.get(s["dong"], "작은 상권(가게 15곳 미만)")
        n = len(by.get(s["dong"], [])) or 1
        same = sum(x["group"] == s["group"] for x in by.get(s["dong"], [])) / n
        s["dong_shops"], s["same_share"] = n, same
        rows.append([1.0 if s["group"] == g else 0.0 for g in FEATURE_GROUPS] + [1.0 if s["chain"] else 0.0]
                    + [1.0 if s["area"] == t else 0.0 for t in types] + [math.log(n), same])
    X = np.array(rows)
    # 업태 · 프랜차이즈 칸은 0/1 그대로, 숫자 칸만 표준화 (한쪽이 묶음을 다 정하지 않게 상권 칸은 0.7배)
    nf, nt = len(FEATURE_GROUPS) + 1, len(types)
    X[:, nf:nf + nt] *= 0.7
    X[:, -2:] = z(X[:, -2:]) * 0.5
    k, scores = choose_k(X, range(4, 9), rng)
    lab = scores[k][1]
    for s, l in zip(shops, lab):
        s["seg"] = int(l)
    return k, {kk: round(v[0], 3) for kk, v in scores.items()}


def describe(shops, k):
    segs = []
    total = len(shops)
    for j in range(k):
        v = [s for s in shops if s["seg"] == j]
        g = Counter(s["group"] for s in v).most_common(3)
        a = Counter(s["area"] for s in v).most_common(2)
        gu = Counter(s["gu"] for s in v).most_common(3)
        chain = sum(s["chain"] for s in v) / len(v)
        meal = sum(s["group"] in MEAL for s in v) / len(v)
        main = g[0][0] if g[0][1] / len(v) >= 0.6 else "·".join(x for x, _c in g)   # 한 업태가 60% 안 되면 섞인 묶음
        where = a[0][0].split(" · ")[0].replace("(가게 15곳 미만)", "")
        name = f"{'프랜차이즈' if chain >= 0.5 else '독립'} {main}" + (f" · {where}" if a[0][1] / len(v) >= 0.5 or "작은" in where else "")
        segs.append({"seg": j, "name": name, "shops": len(v), "share_pct": round(len(v) / total * 100, 1),
                     "groups": [(x, round(c / len(v) * 100)) for x, c in g], "areas": [(x, round(c / len(v) * 100)) for x, c in a],
                     "gu": [(x, round(c / len(v) * 100)) for x, c in gu], "chain_pct": round(chain * 100), "meal_pct": round(meal * 100),
                     "avg_dong_shops": round(sum(s["dong_shops"] for s in v) / len(v)),
                     "avg_same_share_pct": round(sum(s["same_share"] for s in v) / len(v) * 100)})
    # 살피 맞춤 점수: 식사 가게 비율(재료를 매일 직접 삼) × 독립 비율(본사 물류가 없음) × 같은 업태 경쟁(가격을 쉽게 못 올림)
    for x in segs:
        x["fit"] = round(x["meal_pct"] / 100 * (1 - x["chain_pct"] / 100) * (0.5 + x["avg_same_share_pct"] / 100), 3)
    return sorted(segs, key=lambda x: -x["shops"])


def persona_map(shops, segs):
    out = []
    for pid, name, grp, gu, chain in PERSONAS:
        if grp is None:
            out.append((pid, name, "해당 없음 (위탁급식은 일반음식점이 아니라 집단급식소)", None))
            continue
        cand = Counter(s["seg"] for s in shops if s["group"] == grp and s["gu"] == gu and s["chain"] == chain)
        if not cand:
            cand = Counter(s["seg"] for s in shops if s["group"] == grp and s["chain"] == chain)
        seg, c = cand.most_common(1)[0]
        tot = sum(cand.values())
        nm = next(x["name"] for x in segs if x["seg"] == seg)
        out.append((pid, name, nm, round(c / tot * 100)))
    return out


def main():
    rng = np.random.default_rng(SEED)
    shops = load()
    print(f"대구 일반음식점 {len(shops):,}곳 · 프랜차이즈로 본 곳 {sum(s['chain'] for s in shops):,}곳")
    print("업태 묶음:", Counter(s["group"] for s in shops).most_common())
    area, area_sum, area_scores, by = area_types(shops, rng)
    print(f"상권 유형 실루엣 {area_scores} → {len(area_sum)}개")
    for n, v in area_sum.items():
        print(f"  {n}: 동 {v['동 수']} · 가게 {v['가게 수']:,} · 평균 {v['평균 가게 수']}곳 · 프랜차이즈 {v['프랜차이즈 %']}% · {v['업태 비율']}")
    k, seg_scores = shop_segments(shops, area, by, rng)
    print(f"가게 세그먼트 실루엣 {seg_scores} → {k}개")
    segs = describe(shops, k)
    for x in segs:
        print(f"  [{x['seg']}] {x['name']}: {x['shops']:,}곳 ({x['share_pct']}%) · 업태 {x['groups']} · 상권 {x['areas']} · "
              f"프랜차이즈 {x['chain_pct']}% · 식사 {x['meal_pct']}% · 같은 업태 경쟁 {x['avg_same_share_pct']}% · 맞춤 {x['fit']}")
    pm = persona_map(shops, segs)
    for p in pm:
        print("  페르소나", p)

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "1118_segments.csv", "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["세그먼트", "이름", "가게 수", "비율 %", "업태 (상위 3, %)", "상권 (상위 2, %)", "구 (상위 3, %)",
                    "프랜차이즈 %", "식사 가게 %", "동 평균 가게 수", "같은 업태 경쟁 %", "살피 맞춤 점수"])
        for x in segs:
            w.writerow([x["seg"], x["name"], x["shops"], x["share_pct"], x["groups"], x["areas"], x["gu"], x["chain_pct"],
                        x["meal_pct"], x["avg_dong_shops"], x["avg_same_share_pct"], x["fit"]])
    with open(OUT / "1118_area_types.csv", "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["상권 유형", "동 수", "가게 수", "동 평균 가게 수", "프랜차이즈 %"] + [f"{g} %" for g in FEATURE_GROUPS])
        for n, v in area_sum.items():
            w.writerow([n, v["동 수"], v["가게 수"], v["평균 가게 수"], v["프랜차이즈 %"]] + [v["업태 비율"][g] for g in FEATURE_GROUPS])
    with open(OUT / "1118_persona_map.csv", "w", encoding="utf-8-sig", newline="") as fp:
        w = csv.writer(fp)
        w.writerow(["페르소나", "이름", "들어가는 세그먼트", "같은 업태 · 구 가게 중 그 세그먼트 %"])
        w.writerows(pm)
    return shops, segs, area_sum, area_scores, seg_scores, pm


if __name__ == "__main__":
    main()
