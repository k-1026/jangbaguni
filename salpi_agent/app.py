"""살피 시세 대시보드 + 에이전트 대화 화면.

실행: streamlit run app.py
"""

from pathlib import Path

import pandas as pd
import streamlit as st

import analysis
from agent import BRIEFING_PROMPT, SalpiAgent
from data_sources import ITEMS, ApiKeyMissing, daegu_events, holidays

ICON = Path(__file__).resolve().parent.parent / "brand" / "미어캣살피_캐릭터" / "살피_알림배지.png"
st.set_page_config(page_title="살피 시세 대시보드", page_icon=str(ICON) if ICON.exists() else None, layout="wide")


@st.cache_data(ttl=3600, show_spinner="도매시장 시세를 살피는 중이에요...")
def overview():
    return analysis.market_overview()


@st.cache_data(ttl=3600)
def trend(item):
    return analysis.item_trend(item)


@st.cache_data(ttl=3600, show_spinner="다음 주 가격을 따져 보는 중이에요...")
def forecasts():
    return [analysis.forecast_item(name) for name in ITEMS]


@st.cache_data(ttl=3600)
def weather():
    return analysis.weather_summary(14)


@st.cache_data(ttl=3600)
def events_and_holidays():
    return daegu_events(14), holidays(30)


def won(v):
    return f"{v:,.0f}원" if v is not None else "-"


def pct(v):
    return f"{v:+.1f}%" if v is not None else "-"


st.title("살피 시세 대시보드")
st.caption("대구 북부도매시장(매천시장) 경락가 · 대구 소매 조사가 · 대구 날씨 · 대구 행사 기준")

with st.sidebar:
    st.markdown("**살피는 아무것도 팔지 않아요.**\n\n공공 데이터로 시세를 살펴 드려요.")
    if st.button("새로 불러오기"):
        st.cache_data.clear()
        st.rerun()
    st.markdown("---")
    st.markdown("- 도매가: aT 정산정보 (kg당 가중평균)\n- 소매가: aT 일별 도·소매가 (KAMIS 조사, 상품)\n"
                "- 변화율: 최근 3거래일 평균 vs 1주 전\n- ±3% 안쪽은 '비슷해요'")

try:
    rows = overview()
except ApiKeyMissing as e:
    st.error(str(e))
    st.stop()

tab_price, tab_forecast, tab_env, tab_chat = st.tabs(["오늘 시세", "다음 주 예측", "날씨 · 행사", "살피에게 물어보기"])

# ---------------------------------------------------------------
with tab_price:
    cols = st.columns(3)
    for i, r in enumerate(rows):
        with cols[i % 3]:
            st.metric(f"{r['item']} · 도매 kg당", won(r["wholesale_kg"]),
                      f"{pct(r['wholesale_change_pct'])} (1주 전 대비)" if r["wholesale_change_pct"] is not None else None,
                      delta_color="inverse")   # 가격 상승 = 빨강

    st.subheader("한눈에 보기")
    st.dataframe(pd.DataFrame([{
        "재료": r["item"], "도매 kg당": won(r["wholesale_kg"]), "도매 1주 변화": pct(r["wholesale_change_pct"]),
        "판단": r["direction"], "소매 kg당": won(r["retail_kg"]), "소매 1주 변화": pct(r["retail_change_pct"]),
        "도매 기준일": r["wholesale_date"] or "-"} for r in rows]), hide_index=True, width="stretch")

    st.subheader("재료별 흐름")
    item = st.selectbox("재료 고르기", list(ITEMS))
    t = trend(item)
    hist = pd.DataFrame(t["wholesale_history"])
    if hist.empty:
        st.info("최근 2주 도매 거래 기록이 없어요.")
    else:
        st.line_chart(hist.set_index("date")[["kg_price"]].rename(columns={"kg_price": "도매 kg당(원)"}),
                      color="#E86A2E")
        st.bar_chart(hist.set_index("date")[["volume_kg"]].rename(columns={"volume_kg": "반입량(kg)"}),
                     color="#12302A", height=180)

# ---------------------------------------------------------------
with tab_forecast:
    st.caption("최근 시세 흐름 · 반입량 · 대구 날씨 · 공휴일 · 대구 행사를 더해 계산한 추정이에요. "
               "주산지 날씨와 수입량은 아직 반영하지 않았어요.")
    fs = forecasts()
    st.dataframe(pd.DataFrame([{
        "재료": f["item"], "다음 7일": f.get("direction", "-"),
        "예상 변화": pct(f.get("expected_change_pct")),
        "범위": f"{f['range_pct'][0]:+.0f}% ~ {f['range_pct'][1]:+.0f}%" if f.get("range_pct") else "-",
        "예상 kg당": f"{won(f['expected_kg_price_range'][0])} ~ {won(f['expected_kg_price_range'][1])}"
                    if f.get("expected_kg_price_range") else "-",
        "믿을 만한 정도": f.get("confidence", "-"), "살피 제안": f.get("suggestion", "-")} for f in fs]),
        hide_index=True, width="stretch")
    for f in fs:
        with st.expander(f"{f['item']} — 왜 그렇게 봤나요?"):
            st.dataframe(pd.DataFrame([{"이유": x["factor"], "영향": pct(x["effect_pct"]), "내용": x["detail"]}
                                       for x in f.get("factors", [])]), hide_index=True, width="stretch")

# ---------------------------------------------------------------
with tab_env:
    w = weather()
    left, right = st.columns(2)
    with left:
        st.subheader("대구 날씨 (최근 2주)")
        if w.get("days"):
            df = pd.DataFrame(w["daily"]).set_index("date")
            st.line_chart(df[["max_temp", "min_temp"]].rename(columns={"max_temp": "최고(℃)", "min_temp": "최저(℃)"}),
                          color=["#E86A2E", "#12302A"])
            st.bar_chart(df[["rain_mm"]].rename(columns={"rain_mm": "강수량(mm)"}), color="#4BA3A0", height=160)
    with right:
        ev, hol = events_and_holidays()
        st.subheader("다가오는 공휴일 (30일)")
        st.write(", ".join(f"{h['date'][4:6]}/{h['date'][6:]} {h['name']}" for h in hol) or "없어요")
        st.subheader(f"대구 행사 · 축제 (14일, {len(ev)}개)")
        st.dataframe(pd.DataFrame([{"행사": e["title"], "기간": f"{e['start'][4:6]}/{e['start'][6:]} ~ {e['end'][4:6]}/{e['end'][6:]}",
                                    "장소": e["addr"]} for e in ev]), hide_index=True, width="stretch")

# ---------------------------------------------------------------
with tab_chat:
    if "agent" not in st.session_state:
        try:
            st.session_state.agent = SalpiAgent()
            st.session_state.messages = []
        except ApiKeyMissing as e:
            st.warning(str(e))
            st.stop()

    for role, text in st.session_state.messages:
        st.chat_message(role).write(text)

    asked = st.chat_input("예: 양파 요즘 올랐어? / 대파 다음 주에 오를까?")

    # 대화창 아래 기본 선택지: 누르면 그 질문을 대신 보내 줌
    st.markdown("**바로 물어보기**")
    quick = {
        "아침 브리핑": BRIEFING_PROMPT,
        "요즘 많이 오른 재료": "지난주보다 많이 오른 재료를 순서대로 알려 줘.",
        "요즘 많이 내린 재료": "지난주보다 많이 내린 재료를 순서대로 알려 줘.",
        "다음 주 조심할 재료": "다음 주에 오를 가능성이 있는 재료를 모두 알려 주고, 미리 사 둘지 말해 줘.",
        "날씨 · 행사 영향": "최근 대구 날씨와 다가오는 공휴일·행사가 재료값에 어떤 영향을 줄지 알려 줘.",
    }
    cols = st.columns(len(quick))
    for col, (label, prompt) in zip(cols, quick.items()):
        if col.button(label, width="stretch"):
            asked = prompt

    item = st.pills("재료 골라서 물어보기", list(ITEMS), default=list(ITEMS)[0])
    c1, c2 = st.columns(2)
    if c1.button(f"{item} 지금 시세", width="stretch"):
        asked = f"{item} 요즘 시세 올랐어 내렸어?"
    if c2.button(f"{item} 다음 주 예측", width="stretch"):
        asked = f"{item} 다음 주에 오를까 내릴까? 이유도 알려 줘."

    if asked:
        with st.spinner("살피가 살펴보는 중이에요..."):
            try:
                answer = st.session_state.agent.ask(asked)
            except Exception as e:
                answer = f"지금은 답을 만들지 못했어요 ({type(e).__name__}). 잠시 뒤 다시 물어봐 주세요."
        st.session_state.messages += [("user", asked), ("assistant", answer)]
        st.rerun()
