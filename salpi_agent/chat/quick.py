"""채팅창 버튼 질문은 AI 없이 바로 답함 (11/25: 제미나이가 붐비면 버튼 하나에 20~36초 → 시연 불가).

숫자는 도구가 돌려준 값만 쓰고(지어내지 않음), 문장은 살피 말투 규칙(brand/SKILL.md)대로 짧게:
첫 줄 = 답 → 재료당 한 줄 → 마지막에 날짜 · 출처. 도구 값은 서버가 미리 계산해 둔 보관값이라 보통 1초 안.
"""
import re


def _pct(v):
    return f"{v:+.0f}%" if v is not None else "-"


def _won(v):
    return f"{round(v):,}원" if v is not None else "-"


def trend(overview, buy):
    """야채값 시세변동 추이 말해줘."""
    rows = [r for r in overview.get("rows") or [] if r.get("wholesale_change_pct") is not None]
    if not rows:
        return None
    up = sorted([r for r in rows if r["wholesale_change_pct"] >= 3], key=lambda r: -r["wholesale_change_pct"])[:3]
    down = sorted([r for r in rows if r["wholesale_change_pct"] <= -3], key=lambda r: r["wholesale_change_pct"])[:3]
    lines = [f"사장님, 지난주보다 **{up[0]['item']}** 값이 가장 많이 올랐어요." if up
             else "사장님, 지난주보다 크게 오른 재료는 없어요."]
    if up:
        lines.append("**많이 오른 재료**")
        lines += [f"- {r['item']} {_won(r['wholesale_kg'])}/kg ({_pct(r['wholesale_change_pct'])})" for r in up]
    if down:
        lines.append("**많이 내린 재료**")
        lines += [f"- {r['item']} {_won(r['wholesale_kg'])}/kg ({_pct(r['wholesale_change_pct'])})" for r in down]
    pick = (buy.get("cheap_now") or []) + (buy.get("buy_now_before_rise") or [])
    if pick:
        lines.append("**지금 사기 좋은 재료**: " + " · ".join(r["item"] for r in pick[:3]))
    day = rows[0].get("wholesale_date")
    lines.append(f"{day[5:].replace('-', '/') if day else ''} 대구 북부도매시장 kg당 도매가 기준")
    return "\n".join(lines)


def buy_now(buy):
    """지금 사면 이득인 야채 알려줘"""
    if not buy or buy.get("error"):
        return None
    lines = []
    rise, cheap, wait = buy.get("buy_now_before_rise") or [], buy.get("cheap_now") or [], buy.get("wait") or []
    first = (rise or cheap or [None])[0]
    lines.append(f"사장님, 지금은 **{first['item']}**부터 챙기시면 좋아요." if first else "사장님, 지금 서둘러 살 재료는 없어요. 평소대로 사시면 돼요.")
    if rise:
        lines.append("**오르기 전에 미리 사 두면 좋은 재료**")
        lines += [f"- {r['item']} {_won(r['kg_price'])}/kg · 다음 주 {_pct(r['expected_change_pct'])} 예상 ({r['main_reason']})" for r in rise]
    if cheap:
        lines.append("**지금 싼 재료**")
        lines += [f"- {r['item']} {_won(r['kg_price'])}/kg · 지난주보다 {_pct(r['week_change_pct'])}" for r in cheap]
    if wait:
        lines.append("**기다리면 좋은 재료**")
        lines += [f"- {r['item']} 다음 주 {_pct(r['expected_change_pct'])} 예상 → 급하지 않으면 기다려 보세요" for r in wait]
    lines.append("대구 북부도매시장 kg당 도매가 · 살피 다음 주 예측 기준")
    return "\n".join(lines)


def cost(rep):
    """우리 가게 원가율 알려줘"""
    menus = (rep or {}).get("menus") or []
    if not menus:
        return None
    high = [m for m in menus if m.get("high")]
    lines = ["우리 가게 영수증 기준이에요. " + (f"**{', '.join(m['menu'] for m in high)}** 원가율이 40%를 넘어요."
                                             if high else "모든 메뉴가 원가율 40% 아래예요.")]
    for m in menus:
        nxt = m.get("next_ratio_pct")
        tail = f" (다음 주 {nxt}%)" if nxt is not None and abs(nxt - m["cost_ratio_pct"]) >= 1 else ""
        lines.append(f"- {m['menu']} 원가율 **{m['cost_ratio_pct']}%**{tail} · 한 그릇 {_won(m['margin'])} 남아요 · {m['verdict']}")
    for m in high:
        lines.append(f"**{m['menu']} 마진 지키는 방법 3가지**")
        pu, sw, pm = m.get("price_up"), m.get("swap"), m.get("push_menu")
        lines.append(f"① 가격 조정: {_won(pu['price'])}으로 {_won(pu['raise'])} 올리면 원가율 {pu['new_ratio_pct']}%" if pu else "① 가격 조정: -")
        lines.append(f"② 대체 재료: {sw['from']} 절반을 {sw['to']}로 바꾸면 1인분 {_won(sw['saving_per_serving'])} 아껴 원가율 {sw['new_ratio_pct']}%"
                     if sw else "② 대체 재료: 지금은 바꿀 만한 재료가 없어요")
        lines.append(f"③ 메뉴 제안: {pm['menu']}은 한 그릇에 {_won(pm['margin'])} 남아요. 오늘의 메뉴로 밀어 보세요" if pm else "③ 메뉴 제안: -")
    if high:
        lines.append("고르시는 건 사장님이에요.")
    return "\n".join(lines)


def demand(d):
    """내일 얼마나 준비할까?"""
    if not d or d.get("error") or not d.get("menus"):
        return None
    lines = [f"사장님, 내일 {d['target_date']}은 **모두 {d['total_bowls']}그릇** 정도 나갈 것 같아요."]
    lines += [f"- {m['menu']} {m['bowls']}그릇 ({m['range']}) · {m['reason']}" for m in d["menus"]]
    if d.get("orders"):
        lines.append("**지금 주문할 재료**")
        lines += [f"- {o['item']} {o['order']} · {o['decision']}" for o in d["orders"][:5]]
    if d.get("enough_stock"):
        lines.append("넉넉한 재료: " + " · ".join(d["enough_stock"][:6]))
    lines.append("우리 가게 판매 기록 · 재고 기준 (시연 가게는 가상 판매 기록)")
    return "\n".join(lines)


ASK_MENU = ("어떤 메뉴를 얼마에 팔지 알려 주세요. 예: **제육볶음 9,000원**\n"
            "재료를 직접 알려 주시면 그대로 계산할게요. 예: 돼지고기 앞다리 150g, 양파 100g")


# 살피 소개 · 인사: AI 없이 정해진 답 (11/25 팀 결정 — 이름 뜻 · 3살 · 35cm · 0.7~1kg · 엄마 살피맘)
NAME = "저는 시장의 원가율과 마진, 시장 시세를 살핀다는 뜻의 미어캣 살피예요. 궁금한 점이 있으시면 언제든 물어봐 주세요."
THANKS = "감사합니다! 언제든지 원가·마진, 시세 계산이 필요하시면 알려드릴게요. 좋은 하루 보내세요."
TALK = [
    (r"고마|감사|땡큐|ㄱㅅ", THANKS),
    (r"이름|누구(야|세요|니|예요)|살피(가|는|란|야)? ?(뭐|무슨|왜|뜻)|뭐 ?하는 ?(애|친구|거)", NAME),
    (r"몇 ?살|나이", "저는 3살이에요."),
    (r"키(가|는|\s|$|\?)|키 ?(몇|얼마)", "키는 약 35cm예요."),
    (r"몸무게|무게|몇 ?(kg|킬로)", "몸무게는 약 0.7~1kg이에요."),
    (r"엄마|어머니|부모", "엄마는 대구에 사는 '살피맘'이에요."),
    (r"^(안녕|반가|하이|hi|hello)", "안녕하세요, 사장님! 살피예요. 시세 · 원가 · 내일 준비량, 궁금한 걸 물어봐 주세요."),
]


def small_talk(text):
    """짧은 소개 · 인사 질문 → 정해진 답, 아니면 None. 시세 · 원가 질문이 섞인 건 부르는 쪽에서 거름."""
    t = text.strip().lower()
    if len(t) > 15:
        return None
    return next((a for pat, a in TALK if re.search(pat, t)), None)
