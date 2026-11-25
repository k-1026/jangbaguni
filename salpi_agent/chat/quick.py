"""채팅창 버튼 질문은 AI 없이 바로 답함 (11/25: 제미나이가 붐비면 버튼 하나에 20~36초 → 시연 불가).

숫자는 도구가 돌려준 값만 쓰고(지어내지 않음), 문장은 살피 말투 규칙(brand/SKILL.md)대로 짧게:
첫 줄 = 답 → 재료당 한 줄 → 마지막에 날짜 · 출처. 도구 값은 서버가 미리 계산해 둔 보관값이라 보통 1초 안.
"""


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
