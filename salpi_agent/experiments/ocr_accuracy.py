"""영수증 OCR 정확도 (20장): 시연용 가상 영수증을 살피 영수증 읽기(store/receipts.read, 제미나이)에 넣고 정답지와 비교.

실행:  .venv\\Scripts\\python -m experiments.ocr_accuracy            (.env 의 GEMINI_API_KEY · SUPABASE_* 필요, 2~4분)
      .venv\\Scripts\\python -m experiments.ocr_accuracy --only 1116   (이름에 1116 이 든 영수증만, 결과 파일은 안 바꿈)
      .venv\\Scripts\\python -m experiments.ocr_accuracy --retry        (지난 결과에서 읽기 실패한 장만 다시 읽어 합침)
      제미나이 무료 한도가 차면 '바빠요'로 실패함 → 한도가 풀린 뒤 --retry

- 영수증 · 정답지: store/receipts_demo/ (make.py 로 만듦, answers.json = 줄마다 원문 이름 · 수량 · 금액 · 맞는 재료 · 기준 단위 양)
- 줄 짝짓기: 정답 줄마다 OCR 줄 하나 — ① 금액이 같은 줄 중 이름이 가장 비슷한 것 ② 없으면 이름이 충분히 비슷한 줄(금액 틀림)
- 채점 (줄 단위)
    줄 찾기     정답 줄을 OCR 이 읽어 냄
    금액 · 수량  그 줄의 금액 · 수량이 정확히 같음
    재료 맞추기  살피 재료 목록 중 같은 재료를 골랐나 (재료가 아닌 줄 = 배달비 · 봉투 등은 '없음'이 정답)
    기준 양     kg · 모 · 개 · L 로 바꾼 양이 정답과 5% 안 (정답에 양이 있는 줄만)
    남는 줄     정답에 없는데 OCR 이 만든 줄 (할인 · 합계를 품목으로 읽는 등)
  영수증 단위: 날짜 · 합계 금액 정확, 모든 줄 금액이 맞으면 '완벽'
- 결과: experiments/results/ocr_accuracy.json
"""
import json
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from store import receipts   # noqa: E402

DEMO = Path(__file__).resolve().parents[1] / "store" / "receipts_demo"
OUT = Path(__file__).resolve().parent / "results" / "ocr_accuracy.json"
QTY_TOL = 0.05


def _norm(s):
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def _sim(a, b):
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def kind_of(name):
    look = "사진(기울임 · 어두움)" if any(w in name for w in ("tilted", "dark", "photo")) else "깨끗한 스캔"
    kind = "손글씨" if "hand" in name else "마트 영수증" if "mart" in name else "거래명세서"
    return kind, look


def pair(answer, got):
    """정답 줄 → OCR 줄 (없으면 None). 한 OCR 줄은 한 번만."""
    used, out = set(), [None] * len(answer)
    for i, a in enumerate(answer):   # ① 금액 같은 줄
        cands = [(j, _sim(a["raw_name"], g["raw_name"])) for j, g in enumerate(got) if j not in used and g.get("amount") == a["amount"]]
        if cands:
            j = max(cands, key=lambda x: x[1])[0]
            used.add(j)
            out[i] = j
    for i, a in enumerate(answer):   # ② 이름만 비슷한 줄 (금액을 잘못 읽음)
        if out[i] is not None:
            continue
        cands = [(j, _sim(a["raw_name"], g["raw_name"])) for j, g in enumerate(got) if j not in used]
        if cands:
            j, s = max(cands, key=lambda x: x[1])
            if s >= 0.5:
                used.add(j)
                out[i] = j
    return out, [j for j in range(len(got)) if j not in used]


def score(name, ans, res):
    got = res.get("items") or []
    match, extra = pair(ans["items"], got)
    lines = []
    for a, j in zip(ans["items"], match):
        g = got[j] if j is not None else None
        row = {"answer": a["raw_name"], "read_as": g["raw_name"] if g else None, "found": g is not None,
               "amount_ok": bool(g) and g.get("amount") == a["amount"],
               "qty_ok": bool(g) and g.get("qty") is not None and float(g["qty"]) == float(a["qty"]),
               "item_answer": a.get("item"), "item_read": g.get("item") if g else None,
               "item_ok": bool(g) and (g.get("item") or None) == a.get("item"),
               "qty_base_answer": a.get("qty_base"), "qty_base_read": g.get("qty_base") if g else None}
        if a.get("qty_base") is not None and row["item_ok"]:
            qb = g.get("qty_base")
            row["qty_base_ok"] = qb is not None and abs(float(qb) - a["qty_base"]) <= a["qty_base"] * QTY_TOL
        lines.append(row)
    kind, look = kind_of(name)
    return {"name": name, "kind": kind, "look": look, "lines": lines,
            "extra_lines": [got[j]["raw_name"] for j in extra],
            "date_ok": res.get("date") == ans["date"], "date_read": res.get("date"),
            "total_ok": res.get("total") == ans["total"], "total_read": res.get("total"),
            "perfect": all(r["found"] and r["amount_ok"] for r in lines) and not extra}


def summary(receipts_):
    lines = [l for r in receipts_ for l in r["lines"]]
    n = len(lines)
    pct = lambda k, rows=lines: round(sum(1 for l in rows if l.get(k)) / len(rows) * 100, 1) if rows else None
    qb = [l for l in lines if "qty_base_ok" in l]
    ing = [l for l in lines if l["item_answer"]]
    return {"receipts": len(receipts_), "lines": n,
            "line_found_pct": pct("found"), "amount_pct": pct("amount_ok"), "qty_pct": pct("qty_ok"),
            "item_pct": pct("item_ok"), "item_ingredient_pct": pct("item_ok", ing),
            "qty_base_pct": pct("qty_base_ok", qb), "qty_base_n": len(qb),
            "extra_lines": sum(len(r["extra_lines"]) for r in receipts_),
            "date_pct": round(sum(r["date_ok"] for r in receipts_) / len(receipts_) * 100, 1),
            "total_pct": round(sum(r["total_ok"] for r in receipts_) / len(receipts_) * 100, 1),
            "perfect_receipts": sum(r["perfect"] for r in receipts_)}


def main():
    answers = json.loads((DEMO / "answers.json").read_text(encoding="utf-8"))
    only = sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None
    keep = {}
    if "--retry" in sys.argv and OUT.exists():   # 읽기 실패한 장만 다시
        keep = {r["name"]: r for r in json.loads(OUT.read_text(encoding="utf-8"))["receipts"] if not r.get("error")}
    out = []
    for name, ans in answers.items():
        if only and only not in name:
            continue
        if name in keep:
            out.append(keep[name])
            continue
        t = time.time()
        try:
            res = receipts.read((DEMO / f"{name}.png").read_bytes(), "image/png")
        except Exception as e:
            print(f"{name}: 읽기 실패 {e}")
            res = {"items": [], "error": str(e)}
        r = score(name, ans, res)
        if res.get("error"):
            r["error"] = res["error"]
        r["model"] = res.get("model")
        r["seconds"] = round(time.time() - t, 1)
        out.append(r)
        bad = [l for l in r["lines"] if not (l["found"] and l["amount_ok"] and l["item_ok"])]
        print(f"{name:38} {r['seconds']:>5}s  줄 {sum(l['found'] for l in r['lines'])}/{len(r['lines'])}  "
              f"금액 {sum(l['amount_ok'] for l in r['lines'])}  재료 {sum(l['item_ok'] for l in r['lines'])}  "
              f"날짜 {'O' if r['date_ok'] else 'X'} 합계 {'O' if r['total_ok'] else 'X'}  남는 줄 {len(r['extra_lines'])}"
              + (f"  | {[(l['answer'], l['read_as'], l['item_read']) for l in bad][:3]}" if bad else ""))
    groups = {}
    for r in out:
        groups.setdefault(r["kind"], []).append(r)
        groups.setdefault(r["look"], []).append(r)
    result = {"all": summary(out), "groups": {k: summary(v) for k, v in groups.items()}, "receipts": out}
    if not only:
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result["all"], ensure_ascii=False))
    for k, v in result["groups"].items():
        print(k, json.dumps(v, ensure_ascii=False))


if __name__ == "__main__":
    main()
