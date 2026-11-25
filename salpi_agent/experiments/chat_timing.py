"""챗봇이 어디서 느린지 재기 — 질문마다 ① 담당 고르기 ② AI 답 만들기(호출마다) ③ 도구(자료 가져오기)마다 걸린 시간.

실행:  .venv\\Scripts\\python -m experiments.chat_timing      (.env 의 GEMINI_API_KEY · 자료 API 키 필요, 몇 분)
결과:  experiments/results/chat_timing.json
지금 서버와 같은 SalpiAgent 를 그대로 쓰고, 시간만 재려고 도구 · AI 호출을 감쌈 (답은 바꾸지 않음)
"""
import functools
import json
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from google.genai import models as genai_models   # noqa: E402

from chat import agent as A   # noqa: E402

OUT = Path(__file__).resolve().parent / "results" / "chat_timing.json"
QUESTIONS = ["야채값 시세변동 추이 말해줘.", "지금 사면 이득인 야채 알려줘", "우리 가게 원가율 알려줘", "내일 얼마나 준비할까?",
             "양파 다음 주에 오를까?", "제육볶음 9000원에 팔면 남아?", "이번 주 날씨 때문에 배추값 어때?",
             "삼겹살 값 오르면 원가율 괜찮아? 내일 몇 그릇 준비해?"]
LOG = []   # (질문 번호, 종류, 이름, 초)


def timed(kind, name, fn):
    @functools.wraps(fn)
    def w(*a, **k):
        t = time.time()
        try:
            return fn(*a, **k)
        finally:
            LOG.append((CUR[0], kind, name, time.time() - t))
    return w


CUR = [0]
for k, ts in A.AGENT_TOOLS.items():
    A.AGENT_TOOLS[k] = [timed("도구", t.__name__, t) for t in ts]
_orig = genai_models.Models._generate_content
genai_models.Models._generate_content = lambda self, *a, **k: timed("AI", k.get("model", "?"), _orig)(self, *a, **k)


def main():
    out = []
    for i, q in enumerate(QUESTIONS):
        CUR[0] = i
        agent = A.SalpiAgent()
        t = time.time()
        try:
            agent.ask(q)
            status = "ok"
        except Exception as e:
            status = f"{type(e).__name__}: {str(e)[:80]}"
        total = time.time() - t
        mine = [x for x in LOG if x[0] == i]
        ai = [round(x[3], 1) for x in mine if x[1] == "AI"]
        tools = [(x[2], round(x[3], 1)) for x in mine if x[1] == "도구"]
        route = next((s for s in agent.last_tools if s.startswith("시간:안내")), "")
        out.append({"q": q, "total_s": round(total, 1), "route": agent.last_route, "route_time": route, "ai_calls_s": ai,
                    "tools_s": tools, "model": agent.model, "status": status})
        print(f"\n[{i + 1}] {q}  → 전체 {total:.1f}초 · 담당 {agent.last_route} · {route} · 모델 {agent.model} · {status}")
        print(f"    AI 호출 {len(ai)}번: {ai} (합 {sum(ai):.1f}초)")
        print(f"    도구 {len(tools)}번: {tools} (합 {sum(s for _, s in tools):.1f}초)")
    tot = sum(o["total_s"] for o in out)
    ai = sum(sum(o["ai_calls_s"]) for o in out)
    tl = sum(sum(s for _, s in o["tools_s"]) for o in out)
    print(f"\n합계: 전체 {tot:.0f}초 = AI 호출 {ai:.0f}초 ({ai / tot * 100:.0f}%) + 도구 {tl:.0f}초 ({tl / tot * 100:.0f}%) + 기타 (동시 실행이면 겹침)")
    slow = {}
    for o in out:
        for n, s in o["tools_s"]:
            slow.setdefault(n, []).append(s)
    print("도구별 평균: " + " · ".join(f"{n} {sum(v) / len(v):.1f}초({len(v)}번)" for n, v in sorted(slow.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))))
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
