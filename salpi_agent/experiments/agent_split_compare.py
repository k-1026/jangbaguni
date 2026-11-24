"""살피 챗봇: 에이전트 나누기 전(하나) vs 나눈 뒤(안내 + 담당 3) — 시험 질문 20개로 비교.

실행:  .venv\\Scripts\\python -m experiments.agent_split_compare            (40번 묻기, 약 10 ~ 20분 · 무료 API 사용)
       .venv\\Scripts\\python -m experiments.agent_split_compare --only 3  (앞 3문제만, 빠르게 확인)

왜: 11/18에 챗봇을 '안내 + 시세 · 원가 · 내일준비 담당'으로 나눴음 (plan/bm/1112_agent_pipeline.md).
    좋아졌을 때만 유지하기로 했으니 숫자로 확인한다 — 걸린 시간 · AI 호출 수 · 정확도(맞는 도구를 불렀나).

두 방식 (같은 도구 · 같은 공통 규칙 · 같은 모델 순서)
  나누기 전: AI 하나가 담당 3개의 규칙을 모두 읽고, 도구 전부(14개) 중에서 고름 — 11/18 이전 구조를 그대로 다시 만듦
  나눈 뒤  : 지금 SalpiAgent.ask (버튼 질문은 규칙 · 자유 질문은 가벼운 모델이 담당 고름 → 담당은 자기 도구만)

재는 것
  시간      : 질문을 보내고 답이 올 때까지 (초)
  AI 호출 수 : 안내 모델 1번(버튼 · 낱말 규칙이면 0) + 담당마다 AI가 답을 만든 횟수(도구 부를 때마다 1번 더)
  정확도    : 질문마다 '꼭 불러야 할 도구'를 모두 불렀으면 맞음 (숫자를 지어내지 않고 도구 값을 썼나)
결과: 화면에 표 · experiments/results/agent_split_compare.json
"""
import argparse
import json
import time
from pathlib import Path

from google.genai import types

from chat import agent as A

# (질문, 꼭 불러야 할 도구 — 하나라도 빠지면 틀림)
QUESTIONS = [
    # 화면 버튼 5개 (index.html #quick)
    ("야채값 시세변동 추이 말해줘.", {"get_market_overview"}),
    ("지금 사면 이득인 야채 알려줘", {"recommend_buy_now"}),
    ("우리 가게 원가율 알려줘", {"get_store_cost_ratio"}),
    ("내일 얼마나 준비할까?", {"forecast_store_demand"}),
    ("이 가격에 팔아도 남아?", set()),                      # 메뉴 · 판매가를 먼저 되물어야 맞음 (도구 없이)
    # 시세
    ("양파 다음 주에 오를까?", {"forecast_item_price"}),
    ("대파 요즘 값 어때?", {"get_item_price_trend"}),
    ("돼지고기 앞다리 시세 알려줘", {"get_meat_seafood_prices"}),
    ("이번 주 대구 날씨 때문에 채소값 오를까?", {"get_weather_summary"}),
    ("다음 달 공휴일 언제야? 장사 준비해야 해서", {"get_upcoming_holidays"}),
    ("아보카도 시세도 볼 수 있어?", {"list_supported_items"}),
    # 원가 · 마진
    ("김치찌개 8000원에 팔면 얼마 남아?", {"calc_menu_margin"}),
    ("지난번 영수증 비싸게 산 거 있어?", {"judge_receipt_prices"}),
    ("원가율 높은 메뉴 어떻게 하면 좋을까?", {"get_store_cost_ratio"}),
    ("계산할 수 있는 메뉴 뭐 있어?", {"list_standard_menus"}),
    # 내일 준비
    ("내일 김치찌개 몇 그릇 팔릴까?", {"forecast_store_demand"}),
    ("두부 얼마나 주문해야 돼?", {"forecast_store_demand"}),
    # 섞인 질문 (담당 둘)
    ("양파 값 오른다던데 우리 원가율에 영향 있어?", {"get_store_cost_ratio", "forecast_item_price"}),
    ("내일 준비할 재료 중에 지금 사 두면 좋은 거 있어?", {"forecast_store_demand"}),
    ("이번 주 시세랑 내일 발주량 같이 알려줘", {"get_market_overview", "forecast_store_demand"}),
]

ALL_TOOLS = list(dict.fromkeys(t for ts in A.AGENT_TOOLS.values() for t in ts))
SINGLE_PROMPT = (f"{A.COMMON_PROMPT}\n" + "\n".join(A.AGENT_PROMPTS.values())
                 + f"\n아래는 살피 브랜드 규칙이다. 말투와 금칙어를 따른다.\n{A._brand_skill()}")


def _calls_and_tools(chat):
    """대화 기록에서 AI가 답을 만든 횟수(= 호출 수)와 부른 도구."""
    hist = chat.get_history(curated=False)
    calls = sum(1 for c in hist if c.role == "model")
    tools = [p.function_call.name for c in hist for p in (c.parts or []) if getattr(p, "function_call", None)]
    return calls, tools


def ask_single(bot, q):
    """나누기 전: AI 하나 + 도구 전부."""
    last = None
    for model in bot.models:
        chat = bot.client.chats.create(model=model, config=types.GenerateContentConfig(
            system_instruction=SINGLE_PROMPT, tools=ALL_TOOLS, temperature=0.3))
        try:
            text = chat.send_message(q).text or ""
            calls, tools = _calls_and_tools(chat)
            return text, tools, calls, model
        except Exception as e:   # 바쁨 → 다음 모델 (SalpiAgent 와 같은 순서)
            last = e
    raise last


def ask_split(bot, q):
    """나눈 뒤: 지금 챗봇 그대로. 호출 수를 세려고 담당 대화를 잠깐 감쌈."""
    counted, real = [], bot.client

    class Chats:
        def create(self, **kw):
            chat = real.chats.create(**kw)
            counted.append(chat)
            return chat

    class Client:   # client.chats 는 부를 때마다 새로 만들어져서, 대신 감싼 client 를 잠깐 끼움
        models, chats = real.models, Chats()
    bot.client = Client()
    try:
        text = bot.ask(q)
    finally:
        bot.client = real
    how = bot.last_tools[0].split(":")[1]
    calls = (1 if how == "모델" else 0) + sum(_calls_and_tools(c)[0] for c in counted)
    tools = [t for t in bot.last_tools if ":" not in t]
    return text, tools, calls, bot.model, bot.last_route, how


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, default=len(QUESTIONS))
    ap.add_argument("--pause", type=float, default=6.0, help="질문 사이 쉬는 초 (무료 API 분당 한도)")
    args = ap.parse_args()
    bot = A.SalpiAgent()
    rows = []
    for i, (q, need) in enumerate(QUESTIONS[: args.only], 1):
        row = {"no": i, "question": q, "need": sorted(need)}
        for mode, fn in (("before", ask_single), ("after", ask_split)):
            t0 = time.time()
            try:
                out = fn(bot, q)
                sec = round(time.time() - t0, 1)
                text, tools, calls, model = out[:4]
                ok = need <= set(tools) if need else not tools or "?" in text
                row[mode] = {"sec": sec, "calls": calls, "tools": tools, "ok": ok, "model": model, "answer": text[:300]}
                if mode == "after":
                    row[mode].update(route=out[4], how=out[5])
            except Exception as e:
                row[mode] = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
            r = row[mode]
            print(f"{i:>2} {mode:<6} " + (f"{r['sec']:>5}초 호출 {r['calls']} {'맞음' if r['ok'] else '틀림'} {r['tools']}"
                                          if "sec" in r else r["error"]), flush=True)
            time.sleep(args.pause)
        rows.append(row)

    def summary(mode):
        ok = [r[mode] for r in rows if "sec" in r[mode]]
        if not ok:
            return {"n": 0}
        secs = sorted(x["sec"] for x in ok)
        return {"n": len(ok), "errors": len(rows) - len(ok), "avg_sec": round(sum(secs) / len(ok), 1),
                "median_sec": secs[len(secs) // 2], "avg_calls": round(sum(x["calls"] for x in ok) / len(ok), 2),
                "accuracy_pct": round(sum(x["ok"] for x in ok) / len(ok) * 100, 1)}

    result = {"run_at": time.strftime("%Y-%m-%d %H:%M"), "models": bot.models, "before": summary("before"),
              "after": summary("after"), "rows": rows}
    out = Path(__file__).parent / "results" / "agent_split_compare.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n방식     | 질문 | 평균 시간 | 가운데 시간 | 평균 AI 호출 | 정확도 | 실패")
    for mode, name in (("before", "나누기 전"), ("after", "나눈 뒤 ")):
        s = result[mode]
        if s["n"]:
            print(f"{name} | {s['n']:>4} | {s['avg_sec']:>6}초 | {s['median_sec']:>8}초 | {s['avg_calls']:>10} | "
                  f"{s['accuracy_pct']:>5}% | {s['errors']}")
    print(f"저장: {out}")


if __name__ == "__main__":
    main()
