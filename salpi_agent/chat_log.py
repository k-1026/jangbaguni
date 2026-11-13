"""살피 챗봇 대화 기록: 질문 · 답 · 쓴 도구 · 걸린 시간을 Supabase chat_logs 에 저장.

- 왜: 사장님이 실제로 무엇을 묻는지(VOC 다음으로 좋은 자료), 어느 도구를 골랐는지 · 얼마나 걸렸는지
  (에이전트 나누기 전후 비교, plan/bm/1112_agent_pipeline.md 5절)
- 가게 · 로그인 정보와 묶지 않음. 같은 창의 대화만 session(화면이 만든 임의 번호)으로 묶음
- 전화번호 · 이메일 · 주민번호 · 카드번호처럼 보이는 글자는 저장 전에 가림
- 저장이 실패해도 대화는 그대로 (사장님 화면에는 영향 없음)
"""

import re

import supabase_db as db

_MASKS = [
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "[이메일]"),
    (re.compile(r"\d{6}\s*-\s*[1-4]\d{6}"), "[주민번호]"),
    (re.compile(r"\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}"), "[카드번호]"),
    (re.compile(r"(\+?82[\s-]?0?|0)1[016789][\s-]?\d{3,4}[\s-]?\d{4}"), "[전화번호]"),
    (re.compile(r"0(2|[3-6][1-5])[\s-]?\d{3,4}[\s-]?\d{4}"), "[전화번호]"),
]


def mask(text: str) -> str:
    for pattern, label in _MASKS:
        text = pattern.sub(label, text)
    return text


def save(session, turn, question, reply, tools, model, ms, status):
    """status: ok(답함) · busy(AI 서버 바쁨) · error(그 밖의 실패) · nokey(키 없음)"""
    try:
        db.insert("chat_logs", [{
            "session_id": str(session or "")[:64] or None,
            "turn": int(turn or 0),
            "question": mask(question)[:1000],
            "reply": mask(reply or "")[:4000],
            "tools": list(dict.fromkeys(tools or [])),    # 부른 순서대로, 겹친 이름은 하나만
            "model": model,
            "ms": int(ms),
            "status": status,
        }])
    except Exception:
        pass   # Supabase 키가 없거나 표가 아직 없으면 저장만 건너뜀
