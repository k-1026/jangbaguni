"""살피 말 담당의 '숫자 그대로' 규칙 검사: 답에 나온 숫자가 도구 결과(또는 사장님 질문)에 있던 숫자인지 확인.

- 왜: 살피 원칙은 "AI는 말하기만, 숫자는 계산 · 학습 모델만". 말투를 입히는 AI가 숫자를 바꾸거나 지어내면 안 됨
- 말투만 따로 다시 부르는 AI(말 담당)를 두면 답이 두 배 느려져서(plan/bm/1118_agent_split.md) 말투는 각 담당이 입히고,
  여기서는 AI를 부르지 않고 규칙으로 숫자만 맞춰 봄 → 결과는 chat_logs.tools 에 남김 (답은 바꾸지 않음)
- 같다고 보는 경우: 반올림(41.47 → 41.5 · 1,821.4 → 1,821) · 부호만 다름(−5% → 5% 내림) · 0.5% 안쪽 차이
- 세지 않는 숫자: 31 이하 정수(날짜 · 일수 · 개수 · "3가지"), 날짜 모양(11/24 · 2026-11-24)
"""

import re

_DATE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}|\d{1,2}\.\d{1,2}\s*\(")
_NUM = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def numbers(text):
    """글 속 숫자 → [float] (쉼표 뺌, 날짜 모양은 뺌)."""
    text = _DATE.sub(" ", str(text or ""))
    out = []
    for m in _NUM.finditer(text):
        try:
            out.append(float(m.group().replace(",", "")))
        except ValueError:
            pass
    return out


def _walk(obj, out):
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        out.append(abs(float(obj)))
    elif isinstance(obj, str):
        out.extend(numbers(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, out)


def source_numbers(tool_outputs, question=""):
    out = []
    _walk(list(tool_outputs or []), out)
    out.extend(numbers(question))
    return out


def _same(n, t):
    return (abs(n - t) <= max(0.051, abs(t) * 0.005)
            or n == round(t) or n == round(t, 1) or n == round(t, 2))


def check(reply, tool_outputs, question=""):
    """→ (센 숫자 개수, 도구 · 질문에 없던 숫자 목록)"""
    src = source_numbers(tool_outputs, question)
    counted = [n for n in numbers(reply) if not (n.is_integer() and n <= 31)]
    missing = [n for n in counted if not any(_same(n, t) for t in src)]
    return len(counted), missing


def label(reply, tool_outputs, question=""):
    """chat_logs.tools 에 넣을 한 줄. 예: '숫자:12개 모두 도구값' · '숫자:12개 중 도구에 없음 2 (9,500 · 39.3)'"""
    n, miss = check(reply, tool_outputs, question)
    if not n:
        return "숫자:없음"
    if not miss:
        return f"숫자:{n}개 모두 도구값"
    shown = " · ".join(f"{m:,.0f}" if m.is_integer() else f"{m:g}" for m in dict.fromkeys(miss))
    return f"숫자:{n}개 중 도구에 없음 {len(miss)} ({shown[:80]})"
