"""단가 판정 정답표 확인: 판매처(식봄) 상품 30개를 사람이 직접 kg당으로 바꾼 값 vs 살피 자동 환산.

실행:  .venv\\Scripts\\python -m experiments.unit_price_check        (인터넷 · 키 필요 없음, 1초)

- 정답표: experiments/answers/unit_price_answers.csv (11/24 식봄 상품 이름 · 규격 · 판매가를 그대로 적어 둠)
- 살피 자동 환산: 더 싼 판매처(price/cheaper.py _foodspring)와 같은 순서
    식봄이 준 무게(foodspring._kg: 규격 + 이름에서 처음 나온 'N kg') → 없으면 units.parse_pack → units.per_base_price
- 맞음: 정답과 차이 5% 안 · 비슷: 10% 안(환산 '약'이면 화면이 '비슷해요'로 묶는 범위) · 틀림: 10% 넘게 · 못 읽음: 비교에서 빠짐
- 결과: experiments/results/unit_price_check.json
"""
import csv
import json
from pathlib import Path

from price.units import parse_pack, per_base_price
from sources.foodspring import _kg

HERE = Path(__file__).resolve().parent
ANSWERS = HERE / "answers" / "unit_price_answers.csv"
OUT = HERE / "results" / "unit_price_check.json"


def auto(item, name, standard, price):
    kg = _kg(standard, name)
    if kg:
        b = per_base_price(item, price, kg, "kg")
        return b["price"], f"{kg:g}kg", "정확"
    pack = parse_pack(f"{standard} {name}")
    if not pack:
        return None, None, "모름"
    b = per_base_price(item, price, *pack)
    return b["price"], f"{pack[0]:g}{pack[1]}", b["how"]


def grade(got, answer):
    if got is None:
        return "못 읽음", None
    gap = (got / answer - 1) * 100
    return ("맞음" if abs(gap) <= 5 else "비슷" if abs(gap) <= 10 else "틀림"), round(gap, 1)


def main():
    rows = list(csv.DictReader(ANSWERS.open(encoding="utf-8-sig")))
    out = []
    for r in rows:
        got, read_as, how = auto(r["item"], r["name"], r["standard"], int(r["sale_price"]))
        verdict, gap = grade(got, int(r["answer_per_kg"]))
        out.append({"no": int(r["no"]), "item": r["item"], "name": r["name"], "standard": r["standard"],
                    "sale_price": int(r["sale_price"]), "answer_per_kg": int(r["answer_per_kg"]), "answer_how": r["how"],
                    "exclude": r["exclude"], "auto_per_kg": got, "auto_read_as": read_as, "auto_how": how,
                    "verdict": verdict, "gap_pct": gap})
    count = {}
    for o in out:
        count[o["verdict"]] = count.get(o["verdict"], 0) + 1
    fresh = [o for o in out if not o["exclude"]]
    summary = {"n": len(out), "count": count,
               "fresh_n": len(fresh), "fresh_ok": sum(o["verdict"] in ("맞음", "비슷") for o in fresh),
               "excluded_shown": sum(1 for o in out if o["exclude"] and o["auto_per_kg"] is not None)}
    OUT.write_text(json.dumps({"summary": summary, "rows": out}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(summary)
    for o in out:
        if o["verdict"] != "맞음" or o["exclude"]:
            print(f"{o['no']:>2} {o['item']:5} {o['verdict']:4} 정답 {o['answer_per_kg']:>6} · 자동 {o['auto_per_kg']} "
                  f"({o['auto_read_as']}, {o['auto_how']}) 차이 {o['gap_pct']}% {o['exclude']} | {o['name']}")


if __name__ == "__main__":
    main()
