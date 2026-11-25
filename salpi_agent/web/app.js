// 살피 시세 대시보드 화면 동작
const $ = (s) => document.querySelector(s);
const won = (v) => (v == null ? "-" : `${Math.round(v).toLocaleString("ko-KR")}원`);
const pct = (v) => (v == null ? "-" : `${v > 0 ? "+" : ""}${v.toFixed(1)}%`);
// 값 사이 구분: 가운뎃점 대신 얇은 세로선 (style.css .sep)
const SEP = `<span class="sep" aria-hidden="true"></span>`;
const arrowPct = (v) => (v == null ? "-" : `${Math.abs(v).toFixed(1)}%${v > 0 ? "↑" : v < 0 ? "↓" : ""}`);   // 예측 띠: 4.6%↑ · 2.0%↓
const cls = (v, band = 0) => (v == null ? "" : v > band ? "up" : v < -band ? "down" : "");
const mmdd = (d) => `${d.slice(5, 7)}.${d.slice(8, 10)}`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

// 사러 가기: 판매처 고르기 창. 살피는 팔지 않고 연결만 함 (재료 페이지에서 열면 그 재료 검색 결과로, 첫 화면에서 열면 각 사이트 첫 화면으로)
// 쿠팡 파트너스 제휴 주소는 서버(price/seller_links.py)가 바꿔 줌 — 키는 .env COUPANG_ACCESS_KEY · COUPANG_SECRET_KEY
// 로고는 각 사이트가 공개한 사이트 아이콘(img/shops/)을 그대로 씀 (모양 · 색 바꾸지 않음)
const BUY_SHOPS = [
  { name: "식봄",          logo: "foodspring", home: "https://www.foodspring.co.kr", search: (q) => `https://www.foodspring.co.kr/search/all?key=${q}` },
  { name: "쿠팡",          logo: "coupang",    home: "https://www.coupang.com",      search: (q) => `https://www.coupang.com/np/search?q=${q}` },
  { name: "농협몰",        logo: "nonghyup",   home: "https://www.nonghyupmall.com", search: (q) => `https://www.nonghyupmall.com/BC1F010M/srchTotalList.nh?searchTerm_main=${q}&CHAN_C=1101&chanC=1101` },
  { name: "이마트몰",      logo: "emart",      home: "https://emart.ssg.com",        search: (q) => `https://emart.ssg.com/search.ssg?query=${q}` },
  { name: "롯데마트 제타", logo: "zetta",      home: "https://lottemartzetta.com",   search: (q) => `https://lottemartzetta.com/products/search?q=${q}` },
  { name: "배민상회",      logo: "baemin",     home: "https://mart.baemin.com",      search: (q) => `https://mart.baemin.com/search/result?w=${q}` },
];
// 식봄은 서버가 준 검색 주소(foodspring_url)가 있으면 그것을 씀
const buyUrl = (s, item, foodspringUrl) => {
  if (!item) return s.home;
  if (s.logo === "foodspring" && foodspringUrl) return foodspringUrl;
  return s.search(encodeURIComponent(item));
};
function openBuyPicker(item, foodspringUrl) {
  document.querySelector(".buy-pick")?.remove();
  const box = document.createElement("div");
  box.className = "buy-pick";
  box.innerHTML = `<div class="buy-pick-card" role="dialog" aria-modal="true" aria-label="구매할 곳 고르기">
    <h3>${item ? `${esc(item)}, 어디서 살까요?` : "어디서 살까요?"}</h3>
    <div class="buy-pick-list">${BUY_SHOPS.map((s) => `<a href="${esc(buyUrl(s, item, foodspringUrl))}" data-shop="${s.logo}" target="_blank" rel="noopener noreferrer">
      <span class="buy-pick-logo"><img src="/static/img/shops/${s.logo}.png" alt="" width="44" height="44" loading="lazy"></span>
      <b>${esc(s.name)}</b></a>`).join("")}</div>
    <p class="buy-pick-note buy-pick-ad" hidden></p>
    <button type="button" class="buy-pick-close">닫기</button></div>`;
  const close = () => { box.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  box.addEventListener("click", (e) => { if (e.target === box || e.target.closest(".buy-pick-close") || e.target.closest("a")) close(); });
  document.addEventListener("keydown", onKey);
  document.body.appendChild(box);
  box.querySelector("a").focus();
  applyBuyLinks(box, item, "buy-pick-ad");
}
// 판매처 주소는 서버(/api/buy-links)가 정함: 쿠팡 파트너스 키가 있으면 제휴 주소 + 대가성 안내 문구, 없으면 안내를 숨김
// 창은 위 기본 주소로 바로 열고, 서버 답이 오면 주소만 바꿈 (재료마다 한 번만 물어봄)
const buyLinkCache = {};
async function applyBuyLinks(box, item, adClass) {
  try {
    const key = item || "";
    const d = buyLinkCache[key] ||= await getJSON(`/api/buy-links?item=${encodeURIComponent(key)}`);
    for (const s of d.shops || []) {
      const a = box.querySelector(`a[data-shop="${s.logo}"]`);
      if (a) { a.href = s.url; if (s.affiliate) a.rel = "noopener noreferrer sponsored"; }
    }
    const note = box.querySelector(`.${adClass}`);
    if (note) { note.textContent = d.ad_note || ""; note.hidden = !d.ad_note; }
  } catch (e) { delete buyLinkCache[item || ""]; }
}
document.addEventListener("click", (e) => {
  const b = e.target.closest("[data-buy]");
  if (b) openBuyPicker(b.dataset.buy, b.dataset.fs);
});

let overview = [];          // 재료별 시세 · 날짜별 기록 · 예측 (/api/overview 한 번으로 받음)
let boardTab = "야채";      // 시세 대시보드 탭: 농산물 야채 · 농산물 과일(북부도매시장 경락가) · 수산물 · 육류
// 야채 · 과일은 /api/overview 한 번으로 받고 kind 로 나눔. 제철이 아니라 4주 동안 거래가 8일 안 되는 과일은 숨김
const PRODUCE = (t) => t === "야채" || t === "과일";
const kindOf = (r) => r.kind || "야채";
const produceRows = (kind = boardTab) => overview.filter((r) => kindOf(r) === kind && r.wholesale_kg && (r.history || []).length >= 8);
let vegBasis = "";          // 농산물 탭의 기준 문구 (다른 탭에 갔다 돌아올 때 되돌림)
const charts = {};          // 슬라이드별 차트 (보이는 슬라이드만 그림)
const ITEM = new URLSearchParams(location.search).get("item");   // 재료 전용 페이지(/?item=토마토)의 재료 이름
if (ITEM) {
  document.body.classList.add("item-view");
  $("#itemPage").hidden = false;
}
// 로그인 상태: 서버(/api/auth/*, Supabase 로그인)가 준 로그인 표를 이 브라우저에 보관 → 서버에 'Authorization: Bearer' 로 보냄
// '로그인 유지'를 켜면 브라우저를 닫아도 유지(localStorage), 끄면 창을 닫으면 풀림(sessionStorage). 비밀번호는 보관하지 않음
const LOGIN_KEY = "salpi_login";
function readLogin() {
  try { return JSON.parse(localStorage.getItem(LOGIN_KEY) || sessionStorage.getItem(LOGIN_KEY) || "null"); } catch (e) { return null; }
}
function saveLogin(user, keep) {
  try {
    (keep ? localStorage : sessionStorage).setItem(LOGIN_KEY, JSON.stringify(user));
    return true;
  } catch (e) { return false; }
}
function clearLogin() {
  try { localStorage.removeItem(LOGIN_KEY); sessionStorage.removeItem(LOGIN_KEY); } catch (e) {}
}
// 서버 답 → 이 브라우저에 보관할 것 (로그인 표 + 사장님 · 가게 이름)
const sessionToLogin = (s) => ({ id: s.user.login_id || s.user.name, provider: s.user.provider, name: s.user.name, store: s.user.store_name, store_id: s.user.store_id,
  profile: s.user, access_token: s.access_token, refresh_token: s.refresh_token, expires_at: s.expires_at, at: Date.now() });
async function authCall(url, { method = "POST", body, token } = {}) {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(data.detail || "잠시 뒤 다시 해 주세요."), { status: r.status });
  return data;
}
// 로그아웃: 서버에서 로그인 표를 무효로 하고 · 이 브라우저 기억을 지우고 첫 화면으로 (나의 가게처럼 로그인이 필요한 페이지에 남지 않게)
function logout() {
  const u = readLogin();
  if (u?.access_token) fetch("/api/auth/logout", { method: "POST", headers: { Authorization: `Bearer ${u.access_token}` }, keepalive: true }).catch(() => {});
  clearLogin();
  location.replace("/");
}
// 탈퇴 뒤 첫 화면에서 한 번만 인사
const BYE_KEY = "salpi_bye";
try {
  if (sessionStorage.getItem(BYE_KEY)) {
    sessionStorage.removeItem(BYE_KEY);
    const t = document.createElement("div");
    t.className = "bye-toast";
    t.setAttribute("role", "status");
    t.textContent = "탈퇴했어요. 그동안 이용해 주셔서 감사해요";
    document.body.append(t);
    setTimeout(() => t.remove(), 4000);
  }
} catch (e) {}
const SIGNED_IN = !!readLogin();
// 카카오톡 연결에서 돌아옴 (/api/kakao/callback → /?page=store&kakao=ok | kakao_err=이유): 결과를 기억하고 주소는 깨끗이
(() => {
  const q = new URLSearchParams(location.search);
  if (!q.has("kakao") && !q.has("kakao_err")) return;
  if (q.get("page") === "signup") return;   // 카카오 첫 가입 화면(?page=signup&kakao=1)의 kakao=1 은 지우지 않음
  try {
    if (q.get("kakao") === "ok") sessionStorage.setItem("salpi_kakao_ok", "1");
    if (q.get("kakao_err")) sessionStorage.setItem("salpi_kakao_err", q.get("kakao_err"));
    sessionStorage.setItem("salpi_kakao_show", "1");
  } catch (e) {}
  q.delete("kakao"); q.delete("kakao_err");
  window.history.replaceState(null, "",`${location.pathname}${q.toString() ? `?${q}` : ""}${location.hash}`);
})();
const PAGE = new URLSearchParams(location.search).get("page");
// 로그인 뒤 돌아갈 곳: 우리 사이트 안 주소(/ 로 시작)만 받음
const safeNext = (u) => (u && u.startsWith("/") && !u.startsWith("//") ? u : "/");
const LOGIN_NEXT = safeNext(new URLSearchParams(location.search).get("next"));
const LOGIN_URL = `/?page=login&next=${encodeURIComponent(location.pathname + location.search + location.hash)}`;   // 로그인 뒤 지금 페이지로 돌아옴
const goLogin = () => location.assign(LOGIN_URL);
// 로그인 안 하고 나의 가게로 바로 들어오면 로그인 페이지로, 이미 로그인했는데 로그인 · 회원가입 페이지면 원래 가려던 곳으로
const AUTH_PAGE = !ITEM && (PAGE === "login" || PAGE === "signup");
if (!ITEM && PAGE === "store" && !SIGNED_IN) location.replace(LOGIN_URL);
if (AUTH_PAGE && SIGNED_IN) location.replace(LOGIN_NEXT);
const LOGIN_VIEW = AUTH_PAGE && !SIGNED_IN && PAGE === "login";
const SIGNUP_VIEW = AUTH_PAGE && !SIGNED_IN && PAGE === "signup";
const AUTH_VIEW = LOGIN_VIEW || SIGNUP_VIEW;   // 무늬 바탕 카드 페이지 (첫 화면 칸들은 숨김)
if (AUTH_VIEW) {
  document.body.classList.add("auth-view", LOGIN_VIEW ? "login-view" : "signup-view");
  document.title = `${LOGIN_VIEW ? "로그인" : "회원가입"} · 살피`;
}
// 나의 가게 페이지(/?page=store): 내일 준비 · 메뉴별 원가율 · 영수증 분석은 사장님 로그인 시에만
const STORE_VIEW = !ITEM && SIGNED_IN && PAGE === "store";
if (STORE_VIEW) document.body.classList.add("store-view");
// 위쪽 버튼: 로그인 전에는 [로그인]만, 로그인 후에는 나의 가게 · 알림 · 마이페이지
$("#storeBtn").hidden = $("#bellBtn").hidden = $("#meBtn").hidden = !SIGNED_IN;
$("#loginBtn").hidden = SIGNED_IN || AUTH_VIEW;
$("#loginBtn").href = LOGIN_URL;

// 페이지를 열 때 로그인 표 확인: 서버 연결 전 임시 로그인이면 다시 로그인, 곧 끝나는 표는 새로 받음 (못 받으면 로그아웃)
(async () => {
  const u = readLogin();
  if (!u) return;
  const relogin = () => { clearLogin(); location.replace(PAGE === "store" ? LOGIN_URL : location.href); };
  if (!u.refresh_token) return relogin();
  if ((u.expires_at || 0) * 1000 - Date.now() > 60000) return;
  try {
    const keep = (() => { try { return !!localStorage.getItem(LOGIN_KEY); } catch (e) { return false; } })();
    saveLogin(sessionToLogin(await authCall("/api/auth/refresh", { body: { refresh_token: u.refresh_token } })), keep);
  } catch (e) { relogin(); }
})();

// 카카오에서 돌아옴 (/?page=oauth#access_token=...): 가게가 있으면 바로 로그인, 처음이면 가게 정보만 받는 가입 화면으로
const OAUTH_KEY = "salpi_oauth";   // 가게 정보를 받기 전까지 카카오 로그인 표를 잠깐 보관 (이 창에서만)
const kakaoStart = () => location.assign(`/api/auth/kakao?next=${encodeURIComponent(LOGIN_NEXT)}`);
// 이미 로그인한 사장님이 마이페이지 '카카오로 연결'(카카오톡 메시지 동의)로 돌아올 때도 여기를 지나야 카카오 표가 저장됨 (11/18 고침)
if (!ITEM && PAGE === "oauth") (async () => {
  const h = new URLSearchParams(location.hash.slice(1));
  const fail = (m) => location.replace(`/?page=login&next=${encodeURIComponent(LOGIN_NEXT)}&err=${encodeURIComponent(m)}`);
  if (!h.get("access_token")) return fail(h.get("error_description") || "카카오 로그인을 하지 못했어요. 다시 해 주세요.");
  const s = { access_token: h.get("access_token"), refresh_token: h.get("refresh_token"),
    expires_at: Number(h.get("expires_at")) || Math.floor(Date.now() / 1000) + Number(h.get("expires_in") || 3600) };
  try { s.user = await authCall("/api/auth/me", { method: "GET", token: s.access_token }); } catch (e) { return fail(e.message); }
  // 카카오톡 시세 알림용 카카오 표 저장 ('카카오톡 메시지 전송'에 동의했을 때만 옴, 실패해도 로그인은 그대로)
  let linkErr = "";
  if (h.get("provider_refresh_token")) {
    try { await authCall("/api/kakao/connect", { token: s.access_token, body: { provider_token: h.get("provider_token") || "", provider_refresh_token: h.get("provider_refresh_token") } }); }
    catch (e) { linkErr = e.message; }
  } else linkErr = "카카오가 메시지 권한 표를 보내 주지 않았어요 ('카카오톡 메시지 전송' 동의를 확인해 주세요)";
  try { if (sessionStorage.getItem("salpi_kakao_link")) { sessionStorage.removeItem("salpi_kakao_link"); if (linkErr) sessionStorage.setItem("salpi_kakao_err", linkErr); } } catch (e) {}
  if (s.user.store_id) { saveLogin(sessionToLogin(s), true); return location.replace(LOGIN_NEXT); }
  try { sessionStorage.setItem(OAUTH_KEY, JSON.stringify(s)); } catch (e) {}
  location.replace(`/?page=signup&kakao=1&next=${encodeURIComponent(LOGIN_NEXT)}`);
})();

// 로그인 · 회원가입 카드에서 같이 쓰는 것: 안내 한 줄, 비밀번호 보기 눈 버튼, 아직 연결 전인 버튼(data-soon)
function authMsg(box) {
  return (text) => { box.textContent = text; box.hidden = !text; };
}
function eyeToggle(btn, input) {
  btn.onclick = () => {
    const show = input.type === "password";
    input.type = show ? "text" : "password";
    btn.setAttribute("aria-pressed", String(show));
    btn.setAttribute("aria-label", show ? "비밀번호 숨기기" : "비밀번호 보기");
  };
}
function soonButtons(form, msg) {
  form.addEventListener("click", (e) => {
    const s = e.target.closest("[data-soon]");
    if (!s) return;
    e.preventDefault();
    msg(`${s.dataset.soon}은(는) 곧 연결돼요.`);
  });
}
// 로그인 ↔ 회원가입을 오가도 원래 가려던 곳(next)은 그대로
const authLink = (page) => `/?page=${page}&next=${encodeURIComponent(LOGIN_NEXT)}`;

// 로그인 페이지
if (LOGIN_VIEW) {
  const msg = authMsg($("#loginMsg"));
  eyeToggle($("#loginEye"), $("#loginPw"));
  soonButtons($("#loginForm"), msg);   // 간편 로그인 · 아이디 찾기 · 비밀번호 찾기는 아직 연결 전
  $("#loginToSignup").href = authLink("signup");
  $("#loginKakao").onclick = kakaoStart;
  const loginErr = new URLSearchParams(location.search).get("err");   // 카카오 로그인 실패하고 돌아온 경우
  if (loginErr) msg(loginErr);
  $("#loginForm").onsubmit = async (e) => {
    e.preventDefault();
    const id = $("#loginId").value.trim(), pw = $("#loginPw").value;
    if (!id) { msg("아이디 또는 휴대폰 번호를 입력해 주세요."); $("#loginId").focus(); return; }
    if (!pw) { msg("비밀번호를 입력해 주세요."); $("#loginPw").focus(); return; }
    const btn = e.submitter || $("#loginForm button[type=submit]");
    if (btn) btn.disabled = true;
    try {
      const s = await authCall("/api/auth/login", { body: { id, password: pw } });   // 아이디 또는 휴대폰 번호
      if (!saveLogin(sessionToLogin(s), $("#loginKeep").checked)) { msg("이 브라우저에서는 로그인 상태를 기억할 수 없어요."); return; }
      location.replace(LOGIN_NEXT);
    } catch (err) {
      msg(err.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  };
  $("#loginId").focus();
}

// 회원가입 페이지
if (SIGNUP_VIEW) {
  const msg = authMsg($("#signupMsg"));
  const fail = (text, el) => { msg(text); el?.focus(); };
  eyeToggle($("#suEye"), $("#suPw"));
  soonButtons($("#signupForm"), msg);   // 아직 연결 전인 버튼은 '준비 중' 안내
  $("#signupToLogin").href = authLink("login");
  $("#suKakao").onclick = kakaoStart;
  // 카카오로 처음 온 사장님: 이름 · 가게 · 약관만 받음 (휴대폰 · 아이디 · 비밀번호는 카카오가 대신)
  const pending = (() => { try { return JSON.parse(sessionStorage.getItem(OAUTH_KEY) || "null"); } catch (e) { return null; } })();
  const KAKAO_MODE = new URLSearchParams(location.search).get("kakao") === "1" && !!pending?.access_token;
  if (KAKAO_MODE) {
    $("#signupForm").classList.add("kakao-mode");
    $("#signupForm h1").textContent = "가게 정보";
    $("#suKakaoNote").hidden = false;
    $("#suName").value = pending.user?.name || "";
  }

  // 휴대폰 인증: 번호를 바꾸면 인증을 다시 받아야 함
  let verified = false, left = 0, tick = null;
  const phoneDigits = () => $("#suPhone").value.replace(/\D/g, "");
  const resetCode = () => {
    verified = false;
    clearInterval(tick);
    $("#suCodeBox").hidden = true;
    $("#suSend").textContent = "인증번호 받기";
  };
  $("#suPhone").oninput = () => {
    const d = phoneDigits().slice(0, 11);   // 숫자만 넣어도 010-1234-5678 모양으로
    $("#suPhone").value = d.length > 7 ? `${d.slice(0, 3)}-${d.slice(3, d.length - 4)}-${d.slice(-4)}` : d.length > 3 ? `${d.slice(0, 3)}-${d.slice(3)}` : d;
    resetCode();
  };
  const showTimer = () => { $("#suTimer").textContent = `${String(Math.floor(left / 60)).padStart(2, "0")}:${String(left % 60).padStart(2, "0")}`; };
  $("#suSend").onclick = () => {
    if (!/^01\d{8,9}$/.test(phoneDigits())) return fail("휴대폰 번호를 확인해 주세요.", $("#suPhone"));
    msg("");
    resetCode();
    $("#suCodeBox").hidden = false;
    $("#suCodeOk").hidden = true;
    $("#suCode").value = "";
    $("#suCode").disabled = $("#suVerify").disabled = false;
    $("#suSend").textContent = "다시 받기";
    left = 180;
    showTimer();
    tick = setInterval(() => { left = Math.max(0, left - 1); showTimer(); if (!left) clearInterval(tick); }, 1000);
    $("#suCode").focus();
  };
  $("#suVerify").onclick = () => {
    if (!left) return fail("인증 시간이 지났어요. 인증번호를 다시 받아 주세요.");
    if (!/^\d{6}$/.test($("#suCode").value)) return fail("인증번호 6자리를 입력해 주세요.", $("#suCode"));
    // 임시: 문자 보내기가 아직 연결 전이라 6자리를 넣으면 인증된 것으로 봄
    verified = true;
    clearInterval(tick);
    msg("");
    $("#suCodeOk").hidden = false;
    $("#suCode").disabled = $("#suVerify").disabled = true;
  };

  // 비밀번호 확인: 두 칸이 같은지 바로 알려 줌
  const pwHint = () => {
    const a = $("#suPw").value, b = $("#suPw2").value, h = $("#suPwHint");
    h.hidden = !b;
    h.textContent = a === b ? "비밀번호가 같아요" : "비밀번호가 달라요";
    h.classList.toggle("ok", a === b);
  };
  $("#suPw").oninput = $("#suPw2").oninput = pwHint;

  // 약관: 전체 동의 ↔ 각 항목
  const terms = [...document.querySelectorAll(".su-term")];
  $("#suAll").onchange = () => terms.forEach((t) => { t.checked = $("#suAll").checked; });
  terms.forEach((t) => { t.onchange = () => { $("#suAll").checked = terms.every((x) => x.checked); }; });

  $("#signupForm").onsubmit = async (e) => {
    e.preventDefault();
    const name = $("#suName").value.trim(), id = $("#suId").value.trim(), pw = $("#suPw").value, store = $("#suStore").value.trim();
    const gu = $("#suGu").value;   // 대구 구 · 군만 받음 (살피는 대구 시세 서비스)
    if (!name) return fail("이름을 입력해 주세요.", $("#suName"));
    if (KAKAO_MODE) {
      if (!store) return fail("가게 이름을 입력해 주세요.", $("#suStore"));
      if (!gu) return fail("가게가 있는 구 · 군을 골라 주세요.", $("#suGu"));
      if (terms.some((t) => t.dataset.required !== undefined && !t.checked)) return fail("필수 약관에 동의해 주세요.");
      try {
        const r = await authCall("/api/auth/store", { token: pending.access_token, body: { name, store, district: gu,
          alarm: $("#suAlarm").checked, terms_ok: true } });
        if (!saveLogin(sessionToLogin({ ...pending, user: r.user }), true)) return fail("이 브라우저에서는 로그인 상태를 기억할 수 없어요.");
        try { sessionStorage.removeItem(OAUTH_KEY); } catch (err) {}
        location.replace(LOGIN_NEXT);
      } catch (err) { fail(err.message); }
      return;
    }
    if (!verified) return fail("휴대폰 번호를 인증해 주세요.", $("#suPhone"));
    if (!/^[A-Za-z0-9_]{4,}$/.test(id)) return fail("아이디는 영문 · 숫자 4자 이상으로 정해 주세요.", $("#suId"));
    if (pw.length < 8 || !/[A-Za-z]/.test(pw) || !/\d/.test(pw)) return fail("비밀번호는 영문 · 숫자를 섞어 8자 이상으로 정해 주세요.", $("#suPw"));
    if (pw !== $("#suPw2").value) return fail("비밀번호가 서로 달라요.", $("#suPw2"));
    if (!store) return fail("가게 이름을 입력해 주세요.", $("#suStore"));
    if (!gu) return fail("가게가 있는 구 · 군을 골라 주세요.", $("#suGu"));
    if (terms.some((t) => t.dataset.required !== undefined && !t.checked)) return fail("필수 약관에 동의해 주세요.");
    const btn = e.submitter || $("#signupForm button[type=submit]");
    if (btn) btn.disabled = true;
    try {
      const s = await authCall("/api/auth/signup", { body: { name, phone: phoneDigits(), login_id: id, password: pw, store, district: gu,
        alarm: $("#suAlarm").checked, terms_ok: true } });
      if (!saveLogin(sessionToLogin(s), true)) return fail("이 브라우저에서는 로그인 상태를 기억할 수 없어요.");
      location.replace(LOGIN_NEXT);
    } catch (err) {
      fail(err.message);
    } finally {
      if (btn) btn.disabled = false;
    }
  };
  $("#suName").focus();
}

// auth: 로그인했으면 로그인 표를 같이 보냄 (판매율 분석 무료 횟수를 세는 곳). 실패하면 status 가 붙은 오류
async function getJSON(url, { auth = false } = {}) {
  const token = auth && SIGNED_IN ? readLogin()?.access_token : null;
  const r = await fetch(url, token ? { headers: { Authorization: `Bearer ${token}` } } : undefined);
  const body = await r.json();
  if (!r.ok) throw Object.assign(new Error(body.detail || "데이터를 불러오지 못했어요"), { status: r.status });
  return body;
}

// 판매율 분석(내일 예상 판매 · 메뉴별 원가율 · 남는 돈) 무료 5회를 다 쓰면: 두 칸을 잠금 안내로 바꿈 (영수증 잠금과 같은 모양)
// 횟수는 서버(account/trial.py, feature=sales)가 하루에 처음 볼 때 1회로 셈
const SALES_LOCK = `<div class="receipt-lock sales-lock"><div class="lock-panel">
    <p class="lock-title">무료 체험이 끝났어요</p>
    <p class="lock-sub">살피 플러스로 판매율 분석을 <b>무제한</b> 써 보세요</p>
    <button class="lock-btn sales-sub-btn" type="button">구독하러 가기</button></div></div>`;
function showSalesLock() {
  $("#storeBasis").textContent = "";
  $("#menuForecast").innerHTML = SALES_LOCK;
  $("#orderCard").hidden = true;
  $("#costCard").innerHTML = SALES_LOCK;
  if ($("#menuAddBtn")) $("#menuAddBtn").hidden = true;
}
const byItem = (name) => overview.find((r) => r.item === name);
const expOf = (r) => r.forecast?.expected_change_pct ?? 0;
// '이렇게 본 이유' 카드 이름: 괄호 설명은 빼고, 어려운 이름은 쉬운 말로 (서버 이름은 그대로 — plainReason · 챗봇이 씀)
const FACTOR_EASY = { "4주 평균과의 차이": "지금 값 수준", "한 달 평균과의 차이": "지금 값 수준" };
const factorName = (name) => { const n = name.replace(/\s*\(.*\)/, ""); return FACTOR_EASY[n] || n; };
// '품목 특성'은 AI 계산의 기본값(품목마다 거의 같은 값)이라 이유로는 보여 주지 않음 — 예상 변화율 계산에는 그대로 들어감
const isReason = (x) => !x.factor.startsWith("품목 특성");
// 7일 뒤 가운데 예상값 (10원 단위). 예상 범위(±20%대)는 넓어서 숫자로는 보여 주지 않고 그래프 부채꼴로만
const midPrice = (base, exp) => (base ? Math.round((base * (1 + (exp || 0) / 100)) / 10) * 10 : null);
// 예측 한마디: 오를 / 떨어질 / 유지될
function verdict(f) {
  const e = f?.expected_change_pct ?? 0;
  if (e >= 2) return { kind: "up", text: "다음 주 오를 가능성이 있어요" };
  if (e <= -2) return { kind: "down", text: "다음 주 떨어질 가능성이 있어요" };
  return { kind: "flat", text: "다음 주 유지될 가능성이 커요" };
}

// ---------------------------------------------------------------
// 첫 화면: 요약 · 슬라이드(전체 → 야채별)
// ---------------------------------------------------------------
async function loadOverview(attempt = 1) {
  try {
    overview = (await getJSON("/api/overview")).items;
  } catch (e) {
    if (attempt < 4) { setTimeout(() => loadOverview(attempt + 1), 5000); return; }   // 서버가 막 켜졌을 때는 잠시 뒤 다시
    if (ITEM) { if (!itemDone) $("#itemHead").innerHTML = `<p class="muted">시세를 불러오지 못했어요. ${esc(e.message)}</p>`; return; }
    if (PRODUCE(boardTab)) $("#slider").innerHTML = `<article class="slide card loading-card"><b>시세를 불러오지 못했어요</b>
      <p class="muted">${esc(e.message)}</p><button class="sort" onclick="location.reload()">다시 불러오기</button></article>`;
    $("#summary").innerHTML = "";
    return;
  }
  const dated = overview.map((r) => r.wholesale_date).filter(Boolean).sort();
  vegBasis = dated.length ? `대구 북부도매시장 · ${mmdd(dated.at(-1))} 기준` : "";
  if (PRODUCE(boardTab)) $("#basis").textContent = vegBasis;
  if (ITEM) { renderItemPage(); deliverAlerts(); return; }

  const veg = produceRows("야채");   // 왼쪽 요약 칸은 야채만 (문구가 '야채')
  const up = veg.filter((r) => (r.wholesale_change_pct ?? 0) >= 3);
  const down = veg.filter((r) => (r.wholesale_change_pct ?? 0) <= -3);
  const week = (r) => r.wholesale_change_pct;
  summaryLists = {
    up: [...up].sort((a, b) => week(b) - week(a)).map((r) => [r.item, week(r)]),
    down: [...down].sort((a, b) => week(a) - week(b)).map((r) => [r.item, week(r)]),
  };
  const chip = (key, tone, count, label) => `<button class="chip ${tone}" type="button" data-list="${key}" aria-expanded="false" aria-controls="summaryList-${key}"><b>${count}개</b><small>${label}</small><i class="chip-caret" aria-hidden="true"><svg viewBox="0 0 12 12"><path d="M2.5 4.5 6 8l3.5-3.5"/></svg></i></button>`;
  $("#summary").innerHTML = `
    ${chip("up", "up", up.length, "지난주보다 <em>오른</em> 야채")}
    ${chip("down", "down", down.length, "지난주보다 <em>내린</em> 야채")}`;

  if (PRODUCE(boardTab)) renderSlides();
  deliverAlerts();
}

// 요약 칸을 누르면 해당 야채 목록을 펼침 · 다시 누르면 접음 · 야채를 누르면 그 대시보드에서 멈춤
let summaryLists = {};
// 다른 칸으로 바꿀 때는 지금 목록이 접히는 동시에 새 목록이 펼쳐짐 (목록마다 칸을 따로 만들고, 접힌 칸은 지움)
function openSummaryList(key) {
  const box = document.createElement("div");
  box.className = "summary-list";
  box.id = `summaryList-${key}`;
  box.innerHTML = summaryHTML(summaryLists[key] || []);
  $("#summary").appendChild(box);
  box.offsetHeight;   // 접힌 상태를 먼저 그려야 펼쳐지는 움직임이 보임
  box.classList.add("open");
}
function closeSummaryLists() {
  $("#summary").querySelectorAll(".summary-list.open").forEach((box) => {
    box.classList.remove("open");
    box.inert = true;
    box.setAttribute("aria-hidden", "true");
    setTimeout(() => box.remove(), 500);   // style.css 접힘 시간(.45초)이 지난 뒤
  });
}
$("#summary").onclick = (e) => {
  const item = e.target.closest(".summary-list button[data-item]");
  if (item) return showItem(item.dataset.item);
  const b = e.target.closest("button.chip");
  if (!b) return;
  if (b.dataset.item) return showItem(b.dataset.item);
  const open = b.getAttribute("aria-expanded") !== "true";
  $("#summary").querySelectorAll("[aria-expanded]").forEach((c) => c.setAttribute("aria-expanded", "false"));
  b.setAttribute("aria-expanded", open);
  closeSummaryLists();
  if (open) openSummaryList(b.dataset.list);
};
// 두 겹으로 감쌈: 바깥은 높이 0 → 실제 높이로 움직이고(접히는 목록과 펼치는 목록 높이 합이 넘치지 않게), 안쪽은 버튼 그림자 여백
const summaryHTML = (list) => `<div class="summary-clip"><div class="summary-inner">${list.map(([item, v]) =>
  `<button type="button" data-item="${esc(item)}"><b>${esc(item)}</b> <span class="${v > 0 ? "rise" : "fall"}">${pct(v)}</span></button>`).join("")
  || "<p>해당하는 야채가 없어요</p>"}</div></div>`;


// 고른 재료의 대시보드로 가서 자동 넘김을 멈춤 (야채 · 과일은 그 탭으로 옮김)
function showItem(name) {
  const r = byItem(name);
  if (r && boardTab !== kindOf(r)) setBoardTab(kindOf(r));
  setPaused(true);
  goSlide(slides().findIndex((s) => s.dataset.item === name));
  $(".hero-board").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

// 예측 근거를 사장님 말로 한 줄만: 판단과 같은 방향에서 가장 큰 이유
function plainReason(factors, kind) {
  const sign = { up: 1, down: -1 }[kind];
  if (!sign) return "";
  const top = (factors || []).filter((x) => isReason(x) && x.effect_pct * sign > 0).sort((a, b) => Math.abs(b.effect_pct) - Math.abs(a.effect_pct))[0];
  if (!top) return "";
  if (top.factor.startsWith("도매시장")) return `시장에 들어오는 양이 ${sign > 0 ? "줄었어요" : "늘었어요"}`;
  if (top.factor.startsWith("날씨")) return "최근 날씨 영향이 있어요";
  if (top.factor.includes("공휴일")) return "공휴일을 앞두고 있어요";
  if (top.factor.includes("평균과의 차이")) return `지금이 평소보다 ${sign > 0 ? "싸요" : "비싸요"}`;
  // 아래는 AI 학습 모델의 이유 (forecast_model.GROUPS)
  if (top.factor.startsWith("계절")) return `해마다 이맘때 ${sign > 0 ? "오르는" : "내리는"} 때예요`;
  if (top.factor.includes("명절")) return "설 · 추석을 앞두고 있어요";
  if (top.factor.startsWith("최근 값 흐름")) return `최근 값 흐름을 보면 ${sign > 0 ? "오를" : "내릴"} 수 있어요`;
  return "대구 행사가 많아요";
}

// 슬라이드 순서: 전체 → 오를 가능성 높은 순 → 유지 → 떨어질 가능성
function slideOrder() { return [...produceRows()].sort((a, b) => expOf(b) - expOf(a)); }

const LOADING_SLIDE = (what, note = "") => `<article class="slide card loading-card"><div class="spinner"></div>
  <b>${what} 시세를 받아 오는 중이에요</b>${note ? `<p class="muted">${note}</p>` : ""}</article>`;

// 지금 탭의 슬라이드를 새로 그림: 1장 전체 비교 막대 → 2장부터 품목별
function renderSlides() {
  Object.values(charts).forEach((c) => c.destroy());
  Object.keys(charts).forEach((k) => delete charts[k]);
  lastSlide = -1;
  cur = 0;
  $("#slider").scrollLeft = 0;
  if (!PRODUCE(boardTab)) renderExtraSlides();
  else if (!overview.length) $("#slider").innerHTML = LOADING_SLIDE("새벽", "처음 열 때는 1분쯤 걸려요. 그다음부터는 바로 떠요.");
  else renderVegSlides();
  onSlideChange(0);
}

function renderVegSlides() {
  const rows = produceRows();
  $("#slider").innerHTML = `
    <article class="slide card" data-item="" data-title="전체 ${boardTab} 시세">
      <div class="chart-head">
        <div><h3>전체 ${boardTab} 시세</h3><p class="price-now muted">지난주보다 얼마나 올랐나 · 내렸나 (도매 kg당)</p></div>
        <div class="legend"><span><i class="lg up"></i>올랐어요</span><span><i class="lg down"></i>내렸어요</span></div>
      </div>
      <div class="chart-box"><canvas></canvas></div>
      <p class="overview-note">다음 주 <b class="up">오를 가능성 ${rows.filter((r) => expOf(r) >= 2).length}개</b> ·
        <b>유지 ${rows.filter((r) => Math.abs(expOf(r)) < 2).length}개</b> ·
        <b class="down">떨어질 가능성 ${rows.filter((r) => expOf(r) <= -2).length}개</b>${boardTab === "과일"
        ? " · 제철이 아니라 거래가 적은 과일은 빼고 보여 줘요" : ""}</p>
    </article>` + slideOrder().map(itemSlide).join("");
}

// 재료 한 장: 메인 슬라이드와 재료 페이지가 함께 씀
// 포즈별 치수 (원본 그림 높이 240px 기준, 화면에서는 좌우반전)
// body: 머리 꼭대기~발끝 길이 (머리 위 시계 · 경광등은 뺌) → 화면에서 미어캣 키가 모두 같게 그림 크기를 맞춤
// foot: 그림에서 가장 아래 닿는 곳 (쇼핑백 살피는 발보다 낮은 가방 밑을 맞춰 대시보드 밖으로 나가지 않게) · my: 입 높이 · side: 입 높이에서 몸이 가장 왼쪽으로 나온 곳
// → 말풍선은 몸 바깥 왼쪽에 두고 꼬리만 입 쪽을 가리킴 (살피가 말풍선을 가리지 않게)
const POSE_SIZE = {
  alert_down: { body: 206, foot: 238, my: 65, side: 192 }, alert_flat1: { body: 182, foot: 238, my: 115, side: 150 },
  alert_flat2: { body: 230, foot: 238, my: 98, side: 170 }, alert_rise1: { body: 178, foot: 238, my: 122, side: 168 },
  alert_rise2: { body: 226, foot: 238, my: 82, side: 240 },
};
const poseVars = (p) => Object.entries(POSE_SIZE[p]).map(([k, v]) => `--${k}:${v}`).join(";");

// 차트 끝(최근 4거래일)이 어느 쪽으로 갔나: 그래프를 보는 눈과 같게 (±3% 안쪽은 비슷)
function recentMove(prices) {
  const v = prices.filter((x) => x > 0);
  if (v.length < 4) return "flat";
  const p = ((v.at(-1) - v.at(-4)) / v.at(-4)) * 100;
  return p >= 3 ? "up" : p <= -3 ? "down" : "flat";
}

// 살피 그림 · 말풍선 · 한마디: 다음 주 예측을 따르되, 차트(최근)와 반대 방향이면 둘 다 말함
// (예: 최근 올랐는데 다음 주 내릴 것 → "최근 올랐지만 다음 주엔 떨어질 가능성" + 알람시계 살피 "며칠 기다려 보세요")
// 오름: 경광등 살피(2 · 4번째 포즈 번갈아) · 유지 · 엇갈림: 알람시계 살피(1 · 3번째) · 내림: 쇼핑백 살피(6번째)
function salpiSays(prices, f, idx = 0) {
  const v = verdict(f), m = recentMove(prices);
  const crossed = (m === "up" && v.kind === "down") || (m === "down" && v.kind === "up");
  if (crossed) {
    return { kind: v.kind, crossed,
      text: `최근 ${m === "up" ? "올랐지만" : "내렸지만"} 다음 주엔 ${v.kind === "up" ? "오를" : "떨어질"} 가능성이 있어요`,
      say: v.kind === "down" ? "오른 값에 급히 사지 말고 며칠 기다려 보세요" : "내린 지금 필요한 만큼 사 두세요",
      pose: `alert_flat${(idx % 2) + 1}` };
  }
  // 유지: 한 달(최근 22거래일) 중 지금 값 위치로 한마디 — 계속 내려 싼 편이면 그렇다고 말함
  const month = prices.filter((x) => x > 0).slice(-22);
  const lo = Math.min(...month), hi = Math.max(...month), at = hi > lo ? (month.at(-1) - lo) / (hi - lo) : 0.5;
  const flatSay = month.length < 5 ? "평소대로 구매하셔도 좋아요"
    : at <= 0.3 ? "한 달 중 싼 편이라 지금 사셔도 괜찮아요" : at >= 0.7 ? "한 달 중 비싼 편이에요. 필요한 만큼만 사세요" : "평소대로 구매하셔도 좋아요";
  return { kind: v.kind, crossed, text: v.text,
    say: { up: "미리 사두는 게 좋을 것 같아요.", flat: flatSay, down: "급하지 않으면 나중에 사셔도 좋아요" }[v.kind],
    pose: v.kind === "down" ? "alert_down" : `alert_${v.kind === "up" ? "rise" : "flat"}${(idx % 2) + 1}` };
}

// 예측 띠 한 줄: '다음 주 약 ○원/kg (4.6%↑) | 지금이 평소보다 싸요' (대시보드 · 재료 페이지 같음)
const fcRange = (mid, unit, change, why) => `다음 주 약 ${won(mid)}/${unit} (${arrowPct(change)})${why ? `${SEP}${why}` : ""}`;
function itemSlide(r, idx) {
  const f = r.forecast || {};
  const v = salpiSays((r.history || []).map((h) => h.kg_price), f, idx);
  const why = plainReason(f.factors, v.kind);
  const { pose, say } = v;
  return `
<article class="slide card" data-item="${esc(r.item)}">
  <div class="chart-head">
    <div>
      <h3>${esc(r.item)} 시세</h3>
      <p class="price-now"><strong>${won(r.wholesale_kg)}/kg</strong>
        <span class="${cls(r.wholesale_change_pct, 3)}">1주 전보다 ${pct(r.wholesale_change_pct)}</span>${PER100_ITEMS.has(r.item) && r.wholesale_kg ? ` <span>· 100g ${won(r.wholesale_kg / 10)}</span>` : ""}</p>
    </div>
    <div class="legend">
      <span><i class="lg line"></i>도매 kg당</span><span><i class="lg fc"></i>7일 예측</span>
      <span><i class="lg rain"></i>비</span><span><i class="lg event"></i>행사</span><span><i class="lg hol"></i>공휴일</span>
    </div>
  </div>
  <div class="chart-box"><canvas></canvas></div>
  <div class="fc-strip ${v.kind}">
    <div class="fc-text">
      <span class="verdict">${v.text}</span>
      <span class="range">${fcRange(midPrice(f.base_kg_price, f.expected_change_pct), "kg", f.expected_change_pct, why)}</span>
    </div>
    <div class="advice" style="${poseVars(pose)}"><span class="say">${say}</span><img class="pose" src="/static/img/${pose}.png" alt=""></div>
  </div>
</article>`;
}

// 슬라이드 넘기기: 화살표 · 8초 자동 · 휴대폰 손가락. 끝에서 처음으로(처음에서 끝으로) 돌아감
const slider = $("#slider");
const slides = () => [...slider.querySelectorAll(".slide")];
const SLIDE_PAD = 32, SLIDE_GAP = 64;   // style.css 의 .slider 여백 · 간격과 같게
function slideIndex() { return Math.round(slider.scrollLeft / (slider.clientWidth - 2 * SLIDE_PAD + SLIDE_GAP)); }
let cur = 0;   // 지금 보고 있는 장 (화살표는 이 값 기준 — 넘어가는 도중의 스크롤 위치로 계산하면 어긋남)
function goSlide(i, behavior = "smooth") {
  const s = slides();
  if (!s.length) return;
  cur = ((i % s.length) + s.length) % s.length;
  slider.scrollTo({ left: s[cur].offsetLeft - s[0].offsetLeft, behavior });
  onSlideChange(cur);
}
let lastSlide = -1;
function onSlideChange(target) {
  const s = slides(), i = target ?? Math.min(slideIndex(), s.length - 1);
  $("#dots").textContent = s.length > 1 ? `${i + 1} / ${s.length}` : "";
  if (i === lastSlide) return;
  lastSlide = i;
  drawSlideChart(i);
}
$("#prevSlide").onclick = () => { goSlide(cur - 1); restartAuto(); };
$("#nextSlide").onclick = () => { goSlide(cur + 1); restartAuto(); };

// 휴대폰: 손가락으로 옆으로 밀면 넘김 (마우스 끌기는 그래프 보기와 겹쳐서 쓰지 않음)
let touchX = null;
slider.addEventListener("pointerdown", (e) => { if (e.pointerType === "touch") touchX = e.clientX; });
slider.addEventListener("pointerup", (e) => {
  if (touchX == null) return;
  const dx = e.clientX - touchX;
  touchX = null;
  if (Math.abs(dx) > 50) { goSlide(cur + (dx < 0 ? 1 : -1)); restartAuto(); }
});

// 8초마다 자동으로 다음 장. 대시보드에 마우스를 올려 보는 동안은 멈춤
const AUTO_MS = 8000;
let autoTimer = null, hovering = false, paused = false;
function restartAuto() {
  clearInterval(autoTimer);
  if (paused) return;
  autoTimer = setInterval(() => { if (!hovering && !document.hidden && slides().length > 1) goSlide(cur + 1); }, AUTO_MS);
}
$(".hero-board").addEventListener("mouseenter", () => { hovering = true; });
$(".hero-board").addEventListener("mouseleave", () => { hovering = false; });
if (!ITEM) restartAuto();

// 일시정지 버튼: 누르면 자동 넘김을 멈추고 다시 누르면 이어서 넘김
function setPaused(on) {
  paused = on;
  const b = $("#pauseSlide");
  b.setAttribute("aria-pressed", on);
  b.setAttribute("aria-label", on ? "자동 넘김 다시 시작" : "자동 넘김 멈춤");
  b.title = on ? "다시 시작" : "멈춤";
  b.innerHTML = on ? '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M3 1.5v9l7.5-4.5z"/></svg>'
    : '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2.5 1.5h2.5v9H2.5zM7 1.5h2.5v9H7z"/></svg>';
  restartAuto();
}
$("#pauseSlide").onclick = () => setPaused(!paused);

function drawSlideChart(i) {
  const el = slides()[i];
  const canvas = el?.querySelector("canvas");
  if (!canvas || charts[i]) return;
  const item = el.dataset.item;
  if (PRODUCE(boardTab)) charts[i] = item ? drawItemChart(canvas, byItem(item)) : drawOverviewChart(canvas, vegBars());
  else charts[i] = item ? drawExtraItemChart(canvas, extraByItem(item)) : drawOverviewChart(canvas, extraBars());
}

// ---------------------------------------------------------------
// 시세 종류 탭: 농산물 · 수산물 · 육류. 셋 다 같은 슬라이드(1장 전체 비교 막대 → 품목별)
// 수산물 · 육류는 경매 자료(반입량)가 없어 한 달 평균과의 차이 · 명절 · 행사(+ 한우 · 돼지는 경락가)로 7일 예측 (/api/meat-seafood)
// ---------------------------------------------------------------
let extra = null;      // 육류 · 수산물 시세 (처음 한 번 받음, 검색에도 씀)
let extraReq = null;   // 받는 중인 요청 (탭 · 검색 · 재료 페이지가 같이 기다림)

const extraList = () => (Array.isArray(extra) ? extra : []);
const extraByItem = (name) => extraList().find((r) => r.item === name);
const extraRows = () => extraList().filter((r) => r.group === boardTab && r.price);
const basisName = (r) => r.basis_label || (r.price_basis === "중도매" ? "북부도매시장 중도매가" : "대구 소매 평균");
// 고기는 kg당 값이 커서 100g당 값도 같이 (정육점 표기와 같게)
// 가지 · 레몬은 1개 무게 근거가 약하고 낱개로 사는 양이 적어 100g당이 더 와닿음
const PER100_ITEMS = new Set(["가지", "레몬"]);
const per100 = (r) => ((r.group === "육류" || PER100_ITEMS.has(r.item)) && r.unit === "kg" ? ` · 100g ${won(r.price / 10)}` : "");

const extraExp = (r) => r.forecast?.expected_change_pct ?? 0;
// 농산물 차트 · 예측 칸을 그대로 쓰도록 모양을 맞춤 (price → kg_price, expected_price_range → expected_kg_price_range)
function vegShape(r) {
  const f = r.forecast && !r.forecast.error
    ? { ...r.forecast, expected_kg_price_range: r.forecast.expected_price_range, base_kg_price: r.forecast.base_price } : null;
  const history = (r.history || []).map((h, i, a) => ({ date: h.date, kg_price: h.price, diff: i ? h.price - a[i - 1].price : null,
    rain_mm: h.rain_mm ?? null, events: h.events || [], holiday: h.holiday || null }));
  return { item: r.item, history, forecast: f };
}

function renderExtraSlides() {
  if (!extra) { $("#basis").textContent = ""; $("#slider").innerHTML = LOADING_SLIDE(boardTab); return; }
  if (extra.error) {
    $("#slider").innerHTML = `<article class="slide card loading-card"><b>${boardTab} 시세를 불러오지 못했어요</b>
      <p class="muted">${esc(extra.error)}</p><button class="sort" type="button" id="extraRetry">다시 불러오기</button></article>`;
    $("#extraRetry").onclick = () => { extra = null; extraReq = null; setBoardTab(boardTab); };
    return;
  }
  const rows = extraRows();
  const dated = rows.map((r) => r.date).filter(Boolean).sort();
  $("#basis").textContent = dated.length ? `대구 · ${mmdd(dated.at(-1))} 기준` : "";
  const order = [...rows].sort((a, b) => extraExp(b) - extraExp(a));
  $("#slider").innerHTML = `
    <article class="slide card" data-item="">
      <div class="chart-head">
        <div><h3>전체 ${boardTab} 시세</h3><p class="price-now muted">지난주보다 얼마나 올랐나 · 내렸나 (${boardTab === "육류" ? "대구 소매 평균" : "북부도매시장 중도매가 중심"})</p></div>
        <div class="legend"><span><i class="lg up"></i>올랐어요</span><span><i class="lg down"></i>내렸어요</span></div>
      </div>
      <div class="chart-box"><canvas></canvas></div>
      <p class="overview-note">다음 주 <b class="up">오를 가능성 ${rows.filter((r) => extraExp(r) >= 2).length}개</b> ·
        <b>유지 ${rows.filter((r) => Math.abs(extraExp(r)) < 2).length}개</b> ·
        <b class="down">떨어질 가능성 ${rows.filter((r) => extraExp(r) <= -2).length}개</b></p>
    </article>` + order.map(extraSlide).join("");
}

// 품목 한 장: 메인 슬라이드와 재료 페이지가 함께 씀
function extraSlide(r, idx) {
  const f = r.forecast || {};
  const v = salpiSays((r.history || []).map((h) => h.price), f, idx);
  const why = plainReason(f.factors, v.kind);
  const { pose, say } = v;
  const range = f.expected_price_range ? fcRange(midPrice(f.base_price, f.expected_change_pct), esc(r.unit || ""), f.expected_change_pct, why)
    : `예측할 자료가 부족해요${why ? SEP + why : ""}`;
  return `
<article class="slide card" data-item="${esc(r.item)}">
  <div class="chart-head">
    <div>
      <h3>${esc(r.item)} 시세</h3>
      <p class="price-now"><strong>${won(r.price)}/${esc(r.unit || "")}</strong>
        <span class="${cls(r.week_change_pct, 3)}">1주 전보다 ${pct(r.week_change_pct)}</span>${per100(r) ? ` <span>· ${per100(r).slice(3)}</span>` : ""}</p>
    </div>
    <div class="legend">
      <span><i class="lg line"></i>${esc(basisName(r))} ${esc(r.unit || "")}당</span><span><i class="lg fc"></i>7일 예측</span>
      ${r.group === "수산물" ? `<span><i class="lg rain"></i>비</span>` : ""}<span><i class="lg event"></i>행사</span><span><i class="lg hol"></i>공휴일</span>
    </div>
  </div>
  <div class="chart-box"><canvas></canvas></div>
  <div class="fc-strip ${v.kind}">
    <div class="fc-text">
      <span class="verdict">${v.text}</span>
      <span class="range">${range}</span>
    </div>
    <div class="advice" style="${poseVars(pose)}"><span class="say">${say}</span><img class="pose" src="/static/img/${pose}.png" alt=""></div>
  </div>
</article>`;
}

const drawExtraItemChart = (canvas, r) => drawItemChart(canvas, vegShape(r), `${basisName(r)} ${r.unit}당`);

function loadExtra() {
  extraReq ||= getJSON("/api/meat-seafood")
    .then((b) => { extra = b.items; })
    .catch((e) => { extra = { error: e.message }; })
    .then(() => {
      if (!PRODUCE(boardTab)) renderSlides();
      if (ITEM) renderItemPage();
    });
  return extraReq;
}

function setBoardTab(tab) {
  boardTab = tab;
  $("#boardTabs").querySelectorAll("[data-tab]").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === tab));
  if (PRODUCE(tab)) $("#basis").textContent = vegBasis;
  else if (!extra) loadExtra();
  renderSlides();
  restartAuto();
}
$("#boardTabs").onclick = (e) => {
  const b = e.target.closest("[data-tab]");
  if (b && b.dataset.tab !== boardTab) setBoardTab(b.dataset.tab);
};
// 탭 사이 왼쪽 · 오른쪽 화살표 이동
$("#boardTabs").onkeydown = (e) => {
  if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
  const tabs = [...$("#boardTabs").querySelectorAll("[data-tab]")];
  const i = tabs.findIndex((b) => b.dataset.tab === boardTab);
  const next = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
  setBoardTab(next.dataset.tab);
  next.focus();
};

// 전체 비교 막대: rows = [{ name, value(1주 변화 %), tip }]
const vegBars = () => produceRows().filter((r) => r.wholesale_change_pct != null).map((r) => ({
  name: r.item, value: r.wholesale_change_pct,
  tip: ` 1주 ${pct(r.wholesale_change_pct)} · ${won(r.wholesale_kg)}/kg · ${verdict(r.forecast).text}` }));
const extraBars = () => extraRows().map((r) => ({
  name: r.item, value: r.week_change_pct ?? 0,
  tip: ` 1주 ${pct(r.week_change_pct)} · ${won(r.price)}/${r.unit} · ${basisName(r)}` }));

function drawOverviewChart(canvas, bars) {
  const rows = [...bars].sort((a, b) => b.value - a.value);
  // 이웃한 이름끼리 겹치지 않는 글자 크기: 막대 한 칸 너비 ÷ (가장 긴 이웃 두 이름의 평균 글자 수 + 띄움 0.5자)
  const longestPair = Math.max(1, ...rows.slice(1).map((r, i) => (r.name.length + rows[i].name.length) / 2));
  const labelSize = (c) => Math.max(9, Math.min(14, Math.floor((c.chart.width - 48) / rows.length / (longestPair + 0.5))));
  return new Chart(canvas.getContext("2d"), {
    type: "bar",
    data: {
      labels: rows.map((r) => r.name),
      datasets: [{ data: rows.map((r) => r.value), borderRadius: 4,
        backgroundColor: rows.map((r) => (r.value >= 0 ? "#E2453C" : "#1E9E7A")) }],
    },
    options: {
      maintainAspectRatio: false,
      plugins: { legend: { display: false },
        tooltip: { callbacks: { label: (c) => rows[c.dataIndex].tip } } },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#1F2622", font: (c) => ({ size: labelSize(c), weight: "700" }), autoSkip: false, maxRotation: 0 } },
        y: { grid: { color: "#F0EDE6" }, ticks: { color: "#8A918C", font: { size: 11 }, callback: (v) => `${v}%` } },
      },
      onClick: (_e, els) => { if (els.length) showItem(rows[els[0].index].name); },
    },
  });
}

// 행사 수(위쪽 띠) · 공휴일(세로 점선)을 그리는 차트 플러그인
const overlayPlugin = {
  id: "overlay",
  beforeDatasetsDraw(c, _args, opts) {
    const { ctx, chartArea: a, scales: { x } } = c;
    const step = (x.getPixelForValue(1) - x.getPixelForValue(0)) || 10;
    ctx.save();
    (opts.eventCounts || []).forEach((n, i) => {
      if (!n) return;
      ctx.fillStyle = `rgba(255, 200, 60, ${Math.min(0.15 + n * 0.08, 0.55)})`;
      ctx.fillRect(x.getPixelForValue(i) - step / 2, a.top, step, 7);
    });
    ctx.setLineDash([4, 4]);
    ctx.strokeStyle = "#E2453C";
    ctx.fillStyle = "#E2453C";
    ctx.font = "11px Noto Sans KR";
    (opts.holidays || []).forEach(({ i, name }) => {
      const px = x.getPixelForValue(i);
      ctx.beginPath(); ctx.moveTo(px, a.top + 9); ctx.lineTo(px, a.bottom); ctx.stroke();
      ctx.fillText(name, px + 3, a.top + 20);
    });
    ctx.restore();
  },
};

function drawItemChart(canvas, d, label = "도매 kg당") {
  const h = d.history || [];
  const f = d.forecast;
  const labels = h.map((r) => mmdd(r.date));
  const price = h.map((r) => r.kg_price);
  const fcLine = h.map(() => null), lo = h.map(() => null), hi = h.map(() => null);
  if (h.length && f && !f.error && f.expected_kg_price_range) {
    const base = h.at(-1).kg_price;
    fcLine[h.length - 1] = lo[h.length - 1] = hi[h.length - 1] = base;
    const start = new Date(h.at(-1).date);
    for (let k = 1; k <= 7; k++) {
      labels.push(mmdd(new Date(start.getTime() + k * 864e5).toISOString().slice(0, 10)));
      price.push(null);
      fcLine.push(k === 7 ? base * (1 + f.expected_change_pct / 100) : null);
      lo.push(k === 7 ? f.expected_kg_price_range[0] : null);
      hi.push(k === 7 ? f.expected_kg_price_range[1] : null);
    }
  }
  const rain = labels.map((_, i) => h[i]?.rain_mm ?? null);
  const eventCounts = labels.map((_, i) => h[i]?.events.length ?? 0);
  const hols = h.map((r, i) => (r.holiday ? { i, name: r.holiday } : null)).filter(Boolean);
  const ctx = canvas.getContext("2d");
  const grad = ctx.createLinearGradient(0, 0, 0, 260);
  grad.addColorStop(0, "rgba(91, 194, 54, 0.30)");
  grad.addColorStop(1, "rgba(91, 194, 54, 0.02)");
  return new Chart(ctx, {
    data: {
      labels,
      datasets: [
        { type: "line", label, data: price, borderColor: "#5BC236", backgroundColor: grad, fill: true,
          tension: 0.15, pointRadius: 3, pointBackgroundColor: "#5BC236", borderWidth: 2, yAxisID: "y", order: 1 },
        { type: "line", label: "예측 상단", data: hi, borderColor: "transparent", backgroundColor: "rgba(232,106,46,0.12)",
          fill: "+1", spanGaps: true, pointRadius: 0, yAxisID: "y", order: 2 },
        { type: "line", label: "예측 하단", data: lo, borderColor: "transparent", spanGaps: true, pointRadius: 0, yAxisID: "y", order: 2 },
        { type: "line", label: "다음 7일 예측", data: fcLine, borderColor: "#E86A2E", borderDash: [6, 5], spanGaps: true,
          pointRadius: (c) => (c.dataIndex === labels.length - 1 ? 4 : 0), pointBackgroundColor: "#E86A2E", borderWidth: 2, yAxisID: "y", order: 0 },
        { type: "bar", label: "강수량(mm)", data: rain, backgroundColor: "rgba(120, 175, 230, 0.55)", yAxisID: "rain", order: 3, barPercentage: 0.6 },
      ],
    },
    options: {
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: false },
        overlay: { eventCounts, holidays: hols },
        tooltip: {
          filter: (item) => item.raw != null && !["예측 상단", "예측 하단"].includes(item.dataset.label),
          callbacks: {
            label: (c) => c.dataset.label === "강수량(mm)" ? ` 비 ${c.raw}mm` : ` ${c.dataset.label} ${won(c.raw)}`,
            afterBody: (items) => {
              const r = h[items[0].dataIndex];
              if (!r) return f && !f.error ? [`7일 뒤 ${won(midPrice(f.base_kg_price, f.expected_change_pct))} 안팎`] : [];
              const out = [];
              if (r.max_temp != null) out.push(`기온 ${r.min_temp}~${r.max_temp}℃`);
              if (r.holiday) out.push(`공휴일: ${r.holiday}`);
              if (r.events.length) out.push(`행사 ${r.events.length}개: ${r.events.slice(0, 2).join(", ")}${r.events.length > 2 ? " 외" : ""}`);
              return out;
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { maxTicksLimit: 7, color: "#8A918C", font: { size: 11 } } },
        y: { position: "right", grid: { color: "#F0EDE6" }, ticks: { color: "#8A918C", font: { size: 11 }, callback: (v) => won(v) } },
        rain: { position: "left", display: false, min: 0, max: Math.max(40, ...rain.filter(Boolean)) * 4 },
      },
    },
    plugins: [overlayPlugin],
  });
}

// ---------------------------------------------------------------
// 재료 전용 페이지 (/?item=토마토): 그 재료의 날짜별 시세 · 예측 · 식봄 연결만 보여 줌
// ---------------------------------------------------------------
// 야채 시세(overview)와 육류 · 수산물 시세(extra) 중 먼저 찾은 쪽으로 한 번만 그림
let itemDone = false;
function renderItemPage() {
  if (itemDone) return;
  const r = byItem(ITEM);
  if (!r) {
    const x = extraByItem(ITEM);
    if (x) { itemDone = true; renderExtraItemPage(x); return; }
    if (overview.length && extra) $("#itemHead").innerHTML = `<h1>${esc(ITEM)}</h1><p class="muted">아직 시세를 제공하지 않는 재료예요.</p>`;
    return;
  }
  itemDone = true;
  document.title = `${r.item} 시세 · 살피`;
  // 제목 아래 살피 한마디는 빼고 이름만 (같은 말이 아래 예측 띠에 있음)
  $("#itemHead").innerHTML = `
    <div><h1>${esc(r.item)}</h1></div>
    <button type="button" class="item-shop" data-buy="${esc(r.item)}" data-fs="${esc(r.foodspring_url || "")}">사러 가기 →</button>`;
  $("#itemBody").hidden = false;
  $("#itemDash").innerHTML = itemSlide(r, 0);
  drawItemChart($("#itemDash canvas"), r);
  itemScoreLine(r.item);
  renderDetail(r.item);
  renderItemGoods();
}

// 재료 페이지 맨 위 재료 이름 아래: 이 재료의 지난 4주 살피 예측률 (/api/forecast-score?weeks=4, 첫 화면 칸과 같은 채점)
// 50% 아래는 숫자만 두지 않고 재료 탓(가격 변동이 큼)으로 설명, 예측 3번 미만은 '채점 중'
async function itemScoreLine(name) {
  let s;
  try { s = (await getJSON("/api/forecast-score?weeks=4")).items?.[name]; } catch (e) { return; }
  const box = $("#itemHead > div");   // 맨 위 재료 이름 바로 아래 (비어 있던 자리)
  if (!s || !box) return;
  const p = s.direction_hit_pct;
  const text = s.n < SCORE_MIN ? "이 재료 예측은 아직 채점 중이에요"
    : p < 50 ? `가격 변동이 커서 예측이 어려운 재료예요${SEP}살피 예측률 ${p}%`
    : `<b>살피 예측률 ${p}%</b>`;
  box.insertAdjacentHTML("beforeend", `<p class="item-score${s.n < SCORE_MIN || p < 50 ? " muted" : ""}">${text}</p>`);
}

// 육류 · 수산물 재료 페이지: 대시보드(4주 그래프) · 시세판(조사일별 증감) · 한 달 시세 위치. 예측 칸은 없다는 안내
function renderExtraItemPage(r) {
  document.title = `${r.item} 시세 · 살피`;
  const d = vegShape(r);
  $("#itemHead").innerHTML = `
    <div><h1>${esc(r.item)}</h1><p class="muted">${esc(r.group)}</p></div>
    <button type="button" class="item-shop" data-buy="${esc(r.item)}" data-fs="${esc(r.foodspring_url || "")}">사러 가기 →</button>`;
  $("#itemBody").hidden = false;
  $("#itemDash").innerHTML = extraSlide(r, 0);
  drawExtraItemChart($("#itemDash canvas"), r);
  itemScoreLine(r.item);
  boardItem = { item: r.item, history: d.history, label: `${basisName(r)} ${r.unit}당` };
  renderBoard();
  renderForecast(d.forecast, d.history, r.unit);   // 출처는 화면 맨 아래 안내 문구에 있어 따로 적지 않음
  renderGradeTable(r.grade_table);
}

// 등급별 도매 경락가 표 (한우 · 돼지만, 재료 페이지에만 — 대시보드에는 넣지 않음)
// 그래프 없이 표 한 장 + 한 문장 ("사장님이 사는 값은 경락가의 ○배") — 출처는 화면 맨 아래 안내 문구에
function renderGradeTable(t) {
  $("#gradeTable")?.remove();
  if (!t || !t.rows?.length) return;
  const pig = t.rows.some((x) => x.all_price != null);
  const unitCnt = pig ? "마리" : "상자";
  const r = t.retail;
  const times = r && t.compare_price ? r.price / t.compare_price : null;
  const cmpName = t.compare_grade ? `${t.compare_grade}등급 도매 경락가` : "통째(도체) 도매 경락가";
  const serving = r ? Math.round((r.price * SERVING_G) / 1000 / 10) * 10 : null;
  $("#priceBoard").insertAdjacentHTML("beforebegin", `
    <section class="card grade-table" id="gradeTable">
      <div class="grade-head"><h3>등급별 도매 경락가</h3>
        <p class="muted">${esc(t.market)} · ${mmdd(t.date)} 경매 · kg당${pig ? " · 돼지 통째(도체)" : ""}</p></div>
      <div class="g-body"><div>
      <table class="g-table">
        <thead><tr><th>등급</th><th class="r">경락가</th>${pig ? `<th class="r">전국 평균</th>` : ""}<th class="r">나온 양</th></tr></thead>
        <tbody>${t.rows.map((x) => `<tr class="${x.grade === t.compare_grade ? "on" : ""}">
          <th scope="row">${esc(x.grade)}${x.grade === t.compare_grade ? "<small>소매와 같은 등급</small>" : ""}</th>
          <td class="r">${x.price ? won(x.price) : "-"}</td>
          ${pig ? `<td class="r muted">${x.all_price ? won(x.all_price) : "-"}</td>` : ""}
          <td class="r">${x.count ? `${Math.round(x.count).toLocaleString("ko-KR")}${unitCnt}` : "-"}</td>
        </tr>`).join("")}</tbody>
      </table>
      ${pig ? `<p class="muted small g-pig">돼지는 부위 경매가 없어 통째 값과 견줬어요</p>` : ""}
      </div>
      ${times ? `<aside class="g-side">
        <p class="g-times"><small>사장님이 사는 값 ${won(r.price)}은</small>${esc(cmpName)}의<b>${times.toFixed(1)}배</b></p>
        <p class="g-serving">1인분(${SERVING_G}g)이면 재료비 약 <b>${won(serving)}</b></p>
        <div class="g-menus" id="gMenus"></div>
      </aside>` : ""}
      </div>
    </section>`);
  fillGradeMenus(ITEM);
}

const SERVING_G = 150;   // 고기 1인분 기준 무게 (식당 1인분 보통 150g · 화면에 '약'으로 표시)

// 오른쪽 맨 아래: 이 재료가 들어가는 내 메뉴 · 원가율 (로그인 · 내 메뉴에 있을 때만)
async function fillGradeMenus(item) {
  if (!SIGNED_IN || !item) return;
  try {
    const [mine, costs] = await Promise.all([getJSON("/api/my-items"), getJSON("/api/costs", { auth: true })]);
    const names = (mine.items || {})[item] || [];
    const el = $("#gMenus");
    if (!names.length || !el) return;
    const rate = Object.fromEntries((costs.menus || []).map((m) => [m.menu, m]));
    el.innerHTML = `<p class="g-menus-h">이 재료가 들어가는 내 메뉴</p>
      <ul>${names.slice(0, 4).map((n) => `<li><span>${esc(n)}</span>${rate[n]
        ? `<b class="${rate[n].high ? "up" : ""}">원가율 ${rate[n].cost_ratio_pct}%</b>` : ""}</li>`).join("")}</ul>
      <a href="/?page=store#costs">메뉴별 원가율 보기 ›</a>`;
  } catch (e) { /* 못 불러오면 이 줄만 안 보여 줌 */ }
}

function renderItemGoods() {
  const r = byItem(ITEM);
  if (!r || !shopLoaded) return;
  const goods = (shop[ITEM] || []).slice(0, 8);
  $("#itemGoodsWrap").hidden = !goods.length;   // 상품을 못 받으면 위 구매 버튼만 남김
  $("#itemGoods").innerHTML = goods.map((g) => productCard({ item: ITEM, g })).join("");
}

function renderDetail(name) {
  const d = byItem(name);
  if (!d) return;
  boardItem = d;
  renderBoard();
  renderForecast(d.forecast, d.history);
}

// 시세판: 최근 10거래일의 직전 거래일 대비 증감 (등락액 원 / 등락률 %)
const BOARD_DAYS = 10;
let boardItem = null, boardMode = "won";

const rate = (r) => (r.diff == null || r.kg_price === r.diff ? null : (r.diff / (r.kg_price - r.diff)) * 100);
const arrow = (v) => (v > 0 ? "▲" : v < 0 ? "▼" : "");
const number = (v) => Math.round(v).toLocaleString("ko-KR");
// 그래프 값 · 표시: 등락액은 원, 등락률은 %
const boardValue = (r) => (boardMode === "won" ? r.diff : rate(r));
const boardText = (v) => (boardMode === "won" ? `${number(Math.abs(v))}원` : `${Math.abs(v).toFixed(1)}%`);
const boardSigned = (v) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${boardText(v)}`;

// 눈금 간격: 1 · 2 · 5 × 10ⁿ 중 위아래로 세 칸 안팎이 나오는 값
function boardScale(peak) {
  const raw = (peak || 1) / 3, unit = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 5, 10].map((m) => m * unit).find((v) => v >= raw);
  return { step, top: step * Math.ceil((peak || 1) / step) };
}

function renderBoard() {
  const d = boardItem;
  const rows = (d.history || []).slice(-BOARD_DAYS);
  const last = rows.at(-1);
  if (!last) { $("#priceBoard").innerHTML = `<p class="muted">최근 거래 기록이 없어요</p>`; return; }
  const prev = (d.history || []).at(-2);
  const moved = rows.filter((r) => boardValue(r) != null);
  const ups = moved.filter((r) => r.diff > 0), downs = moved.filter((r) => r.diff < 0);
  const total = (list) => list.reduce((a, r) => a + boardValue(r), 0) / (boardMode === "won" ? 1 : list.length || 1);
  const totalName = boardMode === "won" ? "합계" : "평균";
  const big = [...moved].sort((a, b) => Math.abs(boardValue(b)) - Math.abs(boardValue(a)))[0];
  const change = boardValue(last);

  const { step, top } = boardScale(Math.max(0, ...moved.map((r) => Math.abs(boardValue(r)))));
  const place = (v) => 50 - (v / top) * 50;   // 값 → 위에서부터 %
  const ticks = [];
  for (let v = -top; v <= top + step / 2; v += step) ticks.push(v);
  const tickText = (v) => (v > 0 ? "+" : v < 0 ? "-" : "") + (boardMode === "won" ? number(Math.abs(v)) : `${+Math.abs(v).toFixed(1)}%`);

  const cols = rows.map((r) => {
    const v = boardValue(r);
    if (v == null) return `<div class="board-col"></div>`;
    const h = (Math.abs(v) / top) * 50, kind = v > 0 ? "up" : v < 0 ? "down" : "";
    const bar = kind ? `<i class="board-bar ${kind}" style="top:${v > 0 ? place(v) : 50}%;height:${h}%"></i>` : "";
    const at = v >= 0 ? `bottom:calc(${50 + h}% + 3px)` : `top:calc(${50 + h}% + 3px)`;
    return `<div class="board-col">${bar}<b class="board-val ${kind}" style="${at}">${arrow(v)}${boardMode === "won" ? number(Math.abs(v)) : boardText(v)}</b></div>`;
  }).join("");

  const days = rows.map((r) => `<div class="board-day ${r === last ? "today" : ""}"><span>${mmdd(r.date)}</span><b>${won(r.kg_price)}</b></div>`).join("");

  $("#priceBoard").innerHTML = `
    <div class="board-head">
      <div>
        <p class="board-label">${esc(d.item)} · ${esc(d.label || "도매 kg당")} · ${mmdd(last.date)} 기준</p>
        <p class="board-now"><b>${number(last.kg_price)}<small>원</small></b>
          ${change == null ? "" : `<span><strong class="${cls(change)}">${arrow(change)} ${boardSigned(change)}</strong> 직전 거래일${prev ? `(${mmdd(prev.date)})` : ""} 대비</span>`}</p>
      </div>
      <button class="board-toggle" type="button" aria-label="증감 표시 단위 바꾸기 (지금 ${boardMode === "won" ? "등락액 원" : "등락률 %"})">
        <span class="${boardMode === "won" ? "on" : ""}">등락액 원</span>
        <span class="${boardMode === "pct" ? "on" : ""}">등락률 %</span>
      </button>
    </div>
    <div class="board-stats">
      <div class="board-stat"><small>상승한 날</small><b>${ups.length}일</b><span>${totalName} ${ups.length ? boardSigned(total(ups)) : "-"}</span></div>
      <div class="board-stat"><small>하락한 날</small><b>${downs.length}일</b><span>${totalName} ${downs.length ? boardSigned(total(downs)) : "-"}</span></div>
      <div class="board-stat"><small>가장 크게 움직인 날</small><b>${big ? `${mmdd(big.date)} <span class="${cls(boardValue(big))}" style="margin:0;font-size:inherit">${arrow(boardValue(big))} ${boardText(boardValue(big))}</span>` : "-"}</b></div>
    </div>
    <div class="board-scroll"><div class="board-inner" style="--days:${rows.length}">
      <div class="board-plot">
        ${ticks.map((v) => `<div class="board-tick ${v === 0 ? "zero" : ""}" style="top:${place(v)}%"><span>${tickText(v)}</span></div>`).join("")}
        <div class="board-cols">${cols}</div>
      </div>
      <div class="board-days">${days}</div>
    </div></div>
    <p class="board-legend">
      <span><i style="background:var(--up)"></i>▲ 상승</span><span><i style="background:var(--down)"></i>▼ 하락</span>
    </p>`;
  const scroll = $(".board-scroll");
  scroll.scrollLeft = scroll.scrollWidth;   // 좁은 화면은 최근 날짜부터 보이게
}
// 토글 아무 곳이나 누르면 원 ↔ % 전환
$("#priceBoard").addEventListener("click", (e) => {
  if (!e.target.closest(".board-toggle")) return;
  boardMode = boardMode === "won" ? "pct" : "won";
  renderBoard();
});

function renderForecast(f, history = [], unit = "kg") {
  if (!f || f.error) { $("#forecastCard").innerHTML = ""; return; }
  const v = verdict(f);
  const big = (x) => Math.abs(x.effect_pct) >= 0.1;
  const reasons = f.factors.filter(isReason);
  // 결론과 같은 쪽 이유를 먼저 (오를 → ▲ 먼저, 떨어질 → ▼ 먼저, 유지 → 합이 큰 쪽 먼저), 같은 쪽 안에서는 큰 것부터
  const lead = { up: 1, down: -1 }[v.kind] ?? (reasons.reduce((s, x) => s + x.effect_pct, 0) >= 0 ? 1 : -1);
  const first = (x) => (x.effect_pct * lead > 0 ? 0 : 1);
  const moved = reasons.filter(big).sort((a, b) => first(a) - first(b) || Math.abs(b.effect_pct) - Math.abs(a.effect_pct));
  const still = reasons.filter((x) => !big(x));
  const [lo, hi] = f.expected_kg_price_range || [];
  const mid = midPrice(f.base_kg_price, f.expected_change_pct);
  $("#forecastCard").className = `card forecast-card fc-${v.kind}`;   // up · down 이름은 전체 글자색 규칙과 겹쳐서 fc- 를 붙임
  $("#forecastCard").innerHTML = `
    <div class="fc-summary">
      <p class="dir">${esc(v.text)}</p>
      <p class="tip">${esc(f.suggestion)}</p>
      ${fcSpark(history, lo, hi)}
      <div class="fc-range">
        <div><small>지금 (${esc(unit)}당)</small><b>${won(f.base_kg_price)}</b></div>
        <i aria-hidden="true">→</i>
        <div><small>7일 뒤 예상</small><b>${won(mid)} 안팎</b></div>
      </div>
    </div>
    <div class="fc-reasons">
      <h4>이렇게 본 이유</h4>
      <div class="reason-grid">${moved.map((x) => `<div class="reason ${x.effect_pct > 0 ? "r-up" : "r-down"}">
        <span class="reason-icon" aria-hidden="true">${x.effect_pct > 0 ? "▲" : "▼"}</span>
        <div><b>${esc(factorName(x.factor))}</b><small>${esc(x.detail)}</small></div>
        <strong>${pct(x.effect_pct)}</strong>
      </div>`).join("") || `<p class="muted">뚜렷하게 오르거나 내릴 이유가 없어요</p>`}</div>
      ${still.length ? `<p class="reason-still"><span>영향 없음</span>${still.map((x) => `<em title="${esc(x.detail)}">${esc(factorName(x.factor))}</em>`).join("")}</p>` : ""}
      ${monthRange(history, f.base_kg_price)}
    </div>`;
}

// 최근 2주(거래일) 시세 선 + 오늘에서 7일 뒤 예상 범위(부채꼴)
function fcSpark(history, lo, hi) {
  const rows = history.slice(-14).filter((r) => r.kg_price > 0);
  if (rows.length < 4 || lo == null || hi == null) return "";
  const vals = [...rows.map((r) => r.kg_price), lo, hi];
  const min = Math.min(...vals), max = Math.max(...vals), pad = (max - min) * 0.12 || 1;
  const W = 300, H = 100, PAST = 200;   // 앞 200칸은 지난 2주, 뒤 100칸은 다음 7일
  const y = (v) => (H - ((v - (min - pad)) / (max - min + 2 * pad)) * H).toFixed(1);
  const x = (i) => ((i / (rows.length - 1)) * PAST).toFixed(1);
  const line = rows.map((r, i) => `${x(i)},${y(r.kg_price)}`).join(" ");
  const last = rows.at(-1).kg_price, mid = (lo + hi) / 2;
  return `<div class="fc-spark">
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="최근 2주 ${won(rows[0].kg_price)}에서 오늘 ${won(last)}, 7일 뒤 ${won(Math.round((lo + hi) / 20) * 10)} 안팎 예상">
        <polygon class="band" points="${PAST},${y(last)} ${W},${y(hi)} ${W},${y(lo)}"/>
        <line class="today" x1="${PAST}" x2="${PAST}" y1="0" y2="${H}"/>
        <polyline class="past" points="${line}"/>
        <line class="next" x1="${PAST}" y1="${y(last)}" x2="${W}" y2="${y(mid)}"/>
      </svg>
      <p class="fc-spark-axis"><span>${mmdd(rows[0].date)}</span><span class="t">오늘</span><span>7일 뒤</span></p>
    </div>`;
}

// 최근 한 달(거래일) 최저 · 평균 · 최고와 지금 가격이 그 사이 어디쯤인지
function monthRange(history, now) {
  const prices = history.slice(-22).map((r) => r.kg_price).filter((v) => v > 0);
  if (prices.length < 5 || !now) return "";
  const lo = Math.min(...prices), hi = Math.max(...prices), avg = prices.reduce((a, v) => a + v, 0) / prices.length;
  const at = hi === lo ? 50 : ((now - lo) / (hi - lo)) * 100;
  const where = at >= 70 ? "비싼 편" : at <= 30 ? "싼 편" : "보통";
  const vsAvg = ((now - avg) / avg) * 100;
  const avgAt = hi === lo ? 50 : Math.max(28, Math.min(72, ((avg - lo) / (hi - lo)) * 100));   // 양끝 글자와 겹치지 않게
  return `<div class="month-range">
      <h4>최근 한 달 시세 위치</h4>
      <p class="month-say">지금 가격은 한 달 중 <b class="m-${at >= 70 ? "high" : at <= 30 ? "low" : "mid"}">${where}</b>이에요 · 평균보다 ${pct(vsAvg)}</p>
      <div class="month-bar" role="img" aria-label="한 달 최저 ${won(lo)}, 최고 ${won(hi)} 사이에서 지금 ${won(now)}">
        <b class="avg-tick" style="left:${avgAt}%"></b>
        <i style="left:${Math.max(0, Math.min(100, at))}%"><em style="transform:translateX(-${Math.round(Math.max(0, Math.min(100, at)))}%)">지금 ${won(now)}</em></i>
      </div>
      <div class="month-scale">
        <span class="lo"><small>한 달 최저</small>${won(lo)}</span>
        <span class="avg" style="left:${avgAt}%"><small>평균</small>${won(Math.round(avg))}</span>
        <span class="hi"><small>한 달 최고</small>${won(hi)}</span>
      </div>
    </div>`;
}

// ---------------------------------------------------------------
// 판매 기록 입력 (/api/sales, store/sales.py): 하루 메뉴별 홀 · 배달 그릇 수
// 자동 저장: 숫자를 고치고 칸을 벗어나면(Enter · Tab · 다른 곳 누르기) 바로 저장 → 위에 '저장하는 중 / ✓ 저장됨'
// 저장되면 잠깐 뒤 내일 준비 · 원가율을 다시 불러옴 (여러 칸을 연달아 넣어도 한 번만)
// 펼치면 왼쪽 표(메뉴가 많으면 표 안에서 스크롤) + 오른쪽 요약(총 매출 · 그릇 · 홀 / 배달 · 저장 상태). [접기]를 누르면 한 줄 요약
// 빈칸 = 안 넣음, 0 = 안 팔림. 단 이미 저장된 칸을 비우면 0(안 팔림)으로 저장 (흐린 '0'으로 미리 보여 줌)
// 서버와 같은 규칙(0 이상 정수 · 하루 2000그릇 · 60일 전까지)을 먼저 화면에서 확인
// ---------------------------------------------------------------
const SALES_MAX = 2000, SALES_BACK_DAYS = 60;
const WEEKDAY = ["일", "월", "화", "수", "목", "금", "토"];
// saving: 지금 저장 중인 요청(Promise) · again: 저장 중에 또 고쳐서 끝나면 한 번 더 · failed: 마지막 저장이 실패함
const sales = { today: null, data: null, open: true, saving: null, again: false, failed: false, timer: null, refresh: null, savedAt: null };
const dayShift = (d, n) => { const x = new Date(`${d}T00:00:00`); x.setDate(x.getDate() + n); return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`; };
const dayLabel = (d) => `${mmdd(d)} (${WEEKDAY[new Date(`${d}T00:00:00`).getDay()]})`;
const salesSum = (menus, key) => menus.reduce((s, m) => s + (m[key] || 0), 0);
const nowLabel = () => new Date().toLocaleTimeString("ko-KR", { hour: "numeric", minute: "2-digit" });

async function salesPut(body) {
  const token = SIGNED_IN ? readLogin()?.access_token : null;   // 로그인했으면 판매율 분석 횟수를 셈 (새 날짜만)
  const r = await fetch("/api/sales", { method: "PUT", body: JSON.stringify(body),
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) } });
  const out = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(out.detail || "잠시 뒤 다시 해 주세요"), { status: r.status });
  return out;
}

// date 없으면 서버 기준 오늘(한국 시간). open: 표를 펼칠지 (기본 펼침)
async function loadSales(date, open = true) {
  try {
    const d = await getJSON(date ? `/api/sales?date=${date}` : "/api/sales");
    if (!sales.today) sales.today = d.date;
    sales.data = d;
    sales.open = open;
    sales.failed = false;
    if (date) sales.savedAt = null;
    renderSales();
  } catch (e) {
    $("#salesCard").innerHTML = `<p class="muted">판매 기록을 불러오지 못했어요. ${esc(e.message)}</p>`;
  }
}

function renderSales() {
  const d = sales.data, isToday = d.date === sales.today;
  $("#sales h2").textContent = isToday ? "오늘 판매 기록" : `${dayLabel(d.date)} 판매 기록`;
  $("#salesBadge").hidden = d.entered || !isToday;
  if (!d.menus.length) {
    $("#salesCard").innerHTML = `<p class="muted">판매 중인 메뉴가 없어요. 아래 메뉴별 원가율에서 메뉴를 먼저 추가해 주세요.</p>`;
    return;
  }
  const dayName = dayLabel(d.date);
  const num = (n) => n.toLocaleString("ko-KR");
  if (!sales.open) {   // 접힌 한 줄: 날짜 · 저장 상태 | 총 판매량 | 매출 | 채널별 | [펼치기]
    const hall = salesSum(d.menus, "hall"), deliv = salesSum(d.menus, "delivery");
    const stat = (label, value, cls = "") => `<div class="sf-stat"><span>${label}</span><b class="${cls}">${value}</b></div>`;
    $("#salesCard").innerHTML = `
      <div class="sales-fold-row">
        <div class="sf-day">
          <span class="sf-dot${d.entered ? "" : " empty"}" aria-hidden="true"></span>
          <div><b>${dayName}</b><small>${d.entered ? `저장됨${sales.savedAt ? ` ${SEP} ${sales.savedAt}` : ""} ${SEP} 내일 준비 반영` : "아직 안 넣었어요"}</small></div>
        </div>
        ${d.entered ? `${stat("총 판매량", `${num(d.total)}그릇`)}${stat(isToday ? "오늘 매출" : "매출", won(d.sales_won), "money")}
          ${stat("판매 방식", `홀 ${num(hall)} ${SEP} 배달 ${num(deliv)}`)}` : ""}
        <button class="sales-unfold" type="button" data-sales="unfold" aria-expanded="false" aria-controls="salesCard" aria-label="판매 기록 펼치기" title="펼치기">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button>
      </div>`;
    return;
  }
  const min = dayShift(sales.today, -SALES_BACK_DAYS);
  const cell = (m, key, label) => `<input class="sales-in" type="text" inputmode="numeric" autocomplete="off" maxlength="4"
      data-mid="${m.menu_id}" data-key="${key}" value="${m[key] ?? ""}" placeholder="${m[key] != null ? "0" : "-"}" aria-label="${esc(m.name)} ${label} 그릇 수">`;
  $("#salesCard").innerHTML = `
    <div class="sales-bar">
      <div class="sales-bar-left"><label class="sales-date"><span class="sales-day-label">${isToday ? "오늘" : `${WEEKDAY[new Date(`${d.date}T00:00:00`).getDay()]}요일`}</span>
        <input type="date" id="salesDate" value="${d.date}" min="${min}" max="${sales.today}" aria-label="날짜 고르기"></label></div>
      <div class="sales-bar-right">
        <button class="sales-unfold" type="button" data-sales="fold" aria-expanded="true" aria-controls="salesCard" aria-label="판매 기록 접기" title="접기">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 15l6-6 6 6"/></svg></button>
      </div>
    </div>
    <div class="sales-split">
      <div class="sales-left">
        <div class="sales-scroll">
          <table class="sales-grid">
            <thead><tr><th scope="col">메뉴</th>
              <th scope="col">홀 판매</th><th scope="col">배달 판매</th><th scope="col" class="num">합계</th><th scope="col" class="num rev">매출</th></tr></thead>
            <tbody>${d.menus.map((m) => `<tr data-mid="${m.menu_id}">
              <th scope="row">${esc(m.name)}<small>${won(m.price)}</small></th>
              <td>${cell(m, "hall", "홀 판매")}</td><td>${cell(m, "delivery", "배달 판매")}</td><td class="num sales-sum" data-sum="${m.menu_id}"></td>
              <td class="num rev" data-rev="${m.menu_id}"></td>
            </tr>`).join("")}</tbody>
          </table>
        </div>
      </div>
      <aside class="sales-panel" aria-label="판매 요약">
        <div class="sales-status" id="salesStatus" role="status" aria-live="polite"></div>
        <p class="sp-label">${isToday ? "오늘" : dayLabel(d.date)} 총 매출</p>
        <p class="sp-money" id="spMoney">0원</p>
        <p class="sp-bowls" id="spBowls">총 0그릇 판매</p>
        <dl class="sp-channels" id="spChannels"></dl>
      </aside>
    </div>`;
  salesTotals();
  salesStatus(d.entered ? "saved" : d.last_sales_date ? "last" : "", d.entered ? sales.savedAt : null);
}

// 오른쪽 요약 맨 위 상태 칩: 저장하는 중 · ✓ 저장됨 · 저장 못 함(다시 시도) · 마지막으로 넣은 날
function salesStatus(kind, time) {
  const el = $("#salesStatus");
  if (!el) return;
  el.className = `sales-status ${kind}`;
  el.title = kind === "saved" && time ? `${time} 저장` : "";
  el.hidden = !kind;
  el.innerHTML = kind === "saving" ? "저장하는 중…"
    : kind === "saved" ? `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12l5 5 9-10"/></svg>${dayLabel(sales.data.date)} 저장됨`
    : kind === "failed" ? `저장 못 했어요 <button type="button" class="sales-retry" data-sales="retry">다시 시도</button>`
    : kind === "last" ? `아직 안 넣었어요 ${SEP} 마지막 ${dayLabel(sales.data.last_sales_date)}`
    : "";
}

// 칸 값 읽기: "" → null(안 넣음), 숫자가 아니면 NaN
const salesVal = (el) => { const v = el.value.trim(); return v === "" ? null : /^\d+$/.test(v) ? +v : NaN; };
const savedVal = (el) => sales.data.menus.find((m) => String(m.menu_id) === el.dataset.mid)?.[el.dataset.key] ?? null;
// 저장될 값: 이미 저장된 칸을 비우면 0 (안 팔림), 처음부터 빈칸이면 null (안 넣음)
const effVal = (el) => { const v = salesVal(el); return v === null && savedVal(el) !== null ? 0 : v; };

// 메뉴별 합계 칸 + 오른쪽 요약(총 매출 · 그릇 · 홀 / 배달)을 입력하는 대로 다시 계산
function salesTotals() {
  const num = (n) => n.toLocaleString("ko-KR");
  const ch = { hall: { n: 0, won: 0 }, delivery: { n: 0, won: 0 } };
  sales.data.menus.forEach((m) => {
    const row = {};
    ["hall", "delivery"].forEach((key) => {
      const el = document.querySelector(`#salesCard .sales-in[data-mid="${m.menu_id}"][data-key="${key}"]`);
      const v = el ? effVal(el) : m[key] ?? null;
      row[key] = v;
      if (Number.isFinite(v)) { ch[key].n += v; ch[key].won += v * m.price; }
    });
    const s = $(`#salesCard [data-sum="${m.menu_id}"]`);
    if (s) {
      const any = row.hall !== null || row.delivery !== null;
      s.textContent = any ? num((Number.isFinite(row.hall) ? row.hall : 0) + (Number.isFinite(row.delivery) ? row.delivery : 0)) : "-";
    }
    // 메뉴별 매출 = (홀 + 배달) × 판매가 — 단가 칸 자리에 (단가는 메뉴 이름 옆에 작게)
    const r = $(`#salesCard [data-rev="${m.menu_id}"]`);
    if (r) {
      const n = (Number.isFinite(row.hall) ? row.hall : 0) + (Number.isFinite(row.delivery) ? row.delivery : 0);
      r.textContent = n > 0 ? won(n * m.price) : "-";   // 0그릇(안 팔림)이면 0원 대신 '-'
    }
    $(`#salesCard tr[data-mid="${m.menu_id}"]`)?.classList.toggle("has", row.hall !== null || row.delivery !== null);
  });
  const bowls = ch.hall.n + ch.delivery.n, money = ch.hall.won + ch.delivery.won;
  $("#spMoney").innerHTML = `${num(Math.round(money))}<small>원</small>`;   // 숫자는 크게, '원'은 작게
  $("#spBowls").innerHTML = `총 <b>${num(bowls)}그릇</b> 판매`;
  // 홀 / 배달 한 줄: 이름 | 그릇 | 금액 — 세 칸으로 줄 맞춤
  const line = (label, c, cls = "") => `<div class="${cls}"><dt>${label}</dt><dd>${num(c.n)}<span class="unit">그릇</span></dd><dd class="won">${won(c.won)}</dd></div>`;
  $("#spChannels").innerHTML = line("홀", ch.hall) + line("배달", ch.delivery, "deliv");
}

// 저장된 값과 다르고 규칙에 맞는 칸만 → [{menu_id, hall, delivery}] (안 바뀐 쪽은 null = 그대로)
function salesChanges() {
  const items = {};
  document.querySelectorAll("#salesCard .sales-in").forEach((el) => {
    const v = effVal(el);
    if (v === null || Number.isNaN(v) || v > SALES_MAX || v === savedVal(el)) return;
    (items[el.dataset.mid] ||= { menu_id: +el.dataset.mid, hall: null, delivery: null })[el.dataset.key] = v;
  });
  return Object.values(items);
}
const salesPending = () => !!sales.data && sales.open && (salesChanges().length > 0 || !!sales.saving);

// 고친 칸 저장. 저장 중에 또 고치면 끝난 뒤 한 번 더. 끝나면 내일 준비 · 원가율을 잠깐 뒤 한 번만 다시 불러옴
async function autoSave() {
  clearTimeout(sales.timer);
  if (sales.saving) { sales.again = true; return sales.saving; }
  const items = salesChanges();
  if (!items.length) return;
  const date = sales.data.date;
  salesStatus("saving");
  sales.saving = salesPut({ date, items }).then((r) => {
    if (sales.data.date !== date) return;   // 저장 중에 다른 날로 옮김
    sales.data = r;
    sales.failed = false;
    $("#salesBadge").hidden = r.entered || r.date !== sales.today;
    $("#salesCard .sales-err")?.remove();
    // 이제 저장된 칸은 비우면 0이 됨 → 흐린 '0'으로 미리 보여 줌
    document.querySelectorAll("#salesCard .sales-in").forEach((el) => { el.placeholder = savedVal(el) !== null ? "0" : "-"; });
    sales.savedAt = nowLabel();
    salesStatus("saved", sales.savedAt);
    clearTimeout(sales.refresh);
    sales.refresh = setTimeout(() => { loadDemand(); loadCosts(false); }, 1500);
  }).catch((e) => {
    sales.failed = true;
    salesStatus("failed");
    salesMsg(e.status === 402 ? `${e.message} (이미 넣은 날짜는 계속 고칠 수 있어요)` : e.message);
  }).finally(() => {
    sales.saving = null;
    if (sales.again && !sales.failed) { sales.again = false; autoSave(); }
    sales.again = false;
  });
  return sales.saving;
}

// 날짜를 옮기거나 접기 전에: 고친 게 있으면 먼저 저장. 실패하면 넘어갈지 물어봄
async function salesFlush() {
  if (!sales.data || !sales.open) return true;
  await autoSave();
  if (sales.saving) await sales.saving;
  return !sales.failed || confirm("저장하지 못한 숫자가 있어요. 저장하지 않고 넘어갈까요?");
}

function salesMsg(text) {
  $("#salesCard .sales-err")?.remove();
  $("#salesCard").insertAdjacentHTML("afterbegin", `<p class="sales-err" role="alert">${esc(text)}</p>`);
}

// 칸을 벗어날 때: 규칙에 안 맞으면 표시만 하고 저장 안 함 · 저장된 칸을 비웠으면 0으로 채우고 저장
function salesLeave(el) {
  const v = salesVal(el);
  if (Number.isNaN(v) || v > SALES_MAX) {
    el.classList.add("bad");
    return salesMsg(`${el.getAttribute("aria-label")}: 0부터 ${SALES_MAX.toLocaleString("ko-KR")} 사이 숫자로 넣어 주세요`);
  }
  if (v === null && savedVal(el) !== null) el.value = "0";
  if (!salesChanges().length) return;
  salesStatus("saving");
  clearTimeout(sales.timer);
  sales.timer = setTimeout(autoSave, 300);   // Enter 로 여러 칸을 빠르게 넘어가도 한 번에 묶어 저장
}

// [접기] · [펼치기] · 저장 못 했을 때 [다시 시도]
$("#salesCard").addEventListener("click", async (e) => {
  const act = e.target.closest("[data-sales]")?.dataset.sales;
  if (act === "retry") { sales.failed = false; autoSave(); }
  if (act === "fold" && await salesFlush()) { sales.open = false; renderSales(); $('#salesCard [data-sales="unfold"]')?.focus(); }
  if (act === "unfold") { sales.open = true; renderSales(); $("#salesCard .sales-in")?.focus(); }
});
$("#salesCard").addEventListener("change", async (e) => {
  if (e.target.classList.contains("sales-in")) return salesLeave(e.target);
  if (e.target.id !== "salesDate") return;
  const day = e.target.value;
  if (!day || day === sales.data.date) return;
  if (day > sales.today || day < dayShift(sales.today, -SALES_BACK_DAYS)) {
    e.target.value = sales.data.date;
    return salesMsg(`오늘부터 ${SALES_BACK_DAYS}일 전까지만 넣을 수 있어요`);
  }
  if (await salesFlush()) loadSales(day, true); else e.target.value = sales.data.date;
});
$("#salesCard").addEventListener("input", (e) => {
  if (!e.target.classList.contains("sales-in")) return;
  e.target.value = e.target.value.replace(/[^\d]/g, "");   // 숫자만 (음수 · 소수점 · 글자는 들어가지 않게)
  e.target.classList.remove("bad");
  salesTotals();
});
$("#salesCard").addEventListener("focusin", (e) => { if (e.target.classList.contains("sales-in")) e.target.select(); });
// Enter: 다음 칸으로 (홀 → 배달 → 다음 메뉴 홀). 칸을 벗어나면서 저장됨. 마지막 칸이면 칸에서 나감
$("#salesCard").addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || !e.target.classList.contains("sales-in")) return;
  e.preventDefault();
  const all = [...document.querySelectorAll("#salesCard .sales-in")];
  const next = all[all.indexOf(e.target) + 1];
  if (next) next.focus(); else e.target.blur();
});
// 칸에 숫자를 넣고 칸을 벗어나기 전에 창을 닫으려 하면 물어봄
addEventListener("beforeunload", (e) => { if (salesPending()) e.preventDefault(); });

// ---------------------------------------------------------------
// 우리 가게 내일 준비 (판매 기록 → 예상 그릇 수 → 재료 필요량 · 발주)
// ---------------------------------------------------------------
const qty = (v, unit) => (unit === "모" ? `${Math.round(v)}모` : `${(+v).toFixed(1)}${unit}`);
// 메뉴별 재료 양: 1kg · 1L 아래는 g · ml로 (10 단위), 개 · 모는 모자라지 않게 올림
function ingQty(v, unit) {
  if (unit === "개" || unit === "모") return `${Math.ceil(v)}${unit}`;
  if ((unit === "kg" || unit === "L") && v < 1) return `${Math.max(10, Math.round(v * 100) * 10)}${unit === "kg" ? "g" : "ml"}`;
  return `${(+v).toFixed(1)}${unit}`;
}

// 가장 영향이 큰 이유 한 줄 (factors: 0.05 = 평소보다 +5%)
function demandReason(factors) {
  const [name, v] = Object.entries(factors).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0] || [];
  if (name === "휴무일") return "가게 쉬는 날이에요";
  if (v == null || Math.abs(v) < 0.02) return "평소와 비슷하게 팔릴 날이에요";
  const p = Math.round(Math.abs(v) * 100);
  if (name === "최근 2주 흐름") return `최근 2주 판매가 그 전보다 ${p}% ${v > 0 ? "늘었어요" : "줄었어요"}`;
  if (name.endsWith("요일") || name === "공휴일") return `${name}은 평소보다 ${p}% ${v > 0 ? "많이" : "적게"} 팔려요`;
  return `${name} 영향으로 평소보다 ${p}% ${v > 0 ? "많이" : "적게"} 팔릴 것 같아요`;   // 학습 모델 이유 (기온 · 삼성 홈경기 · 월급날 무렵 등)
}

// 카드 안에 들어갈 짧은 이유 (예: "금요일 +16%")
function demandShort(factors) {
  const [name, v] = Object.entries(factors).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0] || [];
  if (name === "휴무일") return "가게 쉬는 날";
  if (v == null || Math.abs(v) < 0.02) return "평소와 비슷";
  return `${name} ${v > 0 ? "+" : "−"}${Math.round(Math.abs(v) * 100)}%`;
}

const weekday = (s) => "일월화수목금토"[new Date(`${s}T00:00:00`).getDay()];

// 내일 예상이 평소(최근 14일 평균)와 얼마나 다른지 한눈에 (3% 안쪽은 비슷하다고 봄)
function usualChip(predicted, usual) {
  const diff = predicted - usual;
  if (Math.abs(diff) < usual * 0.03) return `<span class="demand-chip">평소 수준</span>`;
  return diff > 0
    ? `<span class="demand-chip up">평소 +${diff}</span>`
    : `<span class="demand-chip down">평소 −${-diff}</span>`;
}

async function loadDemand() {
  let d;
  try {
    d = await getJSON("/api/demand", { auth: true });
  } catch (e) {
    if (e.status === 402) return showSalesLock();
    $("#storeBasis").textContent = "";
    $("#menuForecast").innerHTML = `<p class="muted">판매 기록을 불러오지 못했어요. ${esc(e.message)}</p>`;
    return;
  }
  if (d.error) { $("#menuForecast").innerHTML = `<p class="muted">${esc(d.error)}</p>`; return; }
  const day = `${mmdd(d.target_date)}(${d.target_weekday})`;
  // 메뉴끼리 그릇 수를 막대 높이로 비교할 수 있게 같은 눈금을 씀 (위 여백은 숫자 자리)
  const max = Math.max(...d.menus.flatMap((m) => [m.predicted, ...m.recent.map((x) => x.qty)]), 1) * 1.2;
  $("#storeBasis").textContent = `판매 기록 ${mmdd(d.last_sales_date)}까지`;
  $("#storeBasis").title = d.method;
  // 메뉴별 숫자 카드: 많이 팔릴 순서로 한 줄에
  const menus = [...d.menus].sort((a, b) => b.predicted - a.predicted);
  $("#menuForecast").innerHTML = `
    <div class="prep-head">
      <h3>내일 ${day}${d.is_holiday ? " · 공휴일" : ""} 예상 판매
        <span>${d.is_open ? `모두 <b>${d.total_predicted}그릇</b>` : "가게 쉬는 날이에요"}</span></h3>
      <button class="order-all demand-all" type="button">근거 모두 보기</button>
    </div>
    <div class="dm-cards">${menus.map((m) => {
      const pct = (v) => (v / max) * 100;
      const usual = Math.round(m.recent.reduce((s, x) => s + x.qty, 0) / (m.recent.length || 1));
      const bars = m.recent.map((x) => {
        const wd = weekday(x.date);
        return `<span title="${mmdd(x.date)}(${wd}) ${x.qty}그릇"><i class="${wd === d.target_weekday ? "same" : ""}" style="height:${pct(x.qty)}%"></i></span>`;
      }).join("");
      return `<div class="demand-item">
        <button class="order-row dm-card" type="button" aria-expanded="false" aria-controls="demand-${m.menu_id}">
          <span class="dm-name">${esc(m.menu)}<i class="order-arrow" aria-hidden="true"></i></span>
          <b class="dm-num">${m.predicted}<small>그릇</small></b>
          ${d.is_open ? usualChip(m.predicted, usual) : ""}
        </button>
        <div class="demand-detail" id="demand-${m.menu_id}" hidden>
          <p class="dm-why" title="${esc(demandReason(m.factors))}"><b>${esc(demandShort(m.factors))}</b><small>예상 ${m.range[0]} ~ ${m.range[1]}그릇</small></p>
          <div class="spark" role="img" aria-label="${esc(m.menu)} 평소 ${usual}그릇, 내일 예상 ${m.predicted}그릇">
            ${bars}<span title="내일 예상 ${m.predicted}그릇 (${m.range[0]} ~ ${m.range[1]})"><i class="next" style="height:${pct(m.predicted)}%"></i></span>
            <div class="spark-usual" style="bottom:${pct(usual)}%"><em>평소 ${usual}</em></div>
          </div>
          <p class="demand-legend"><span><i class="same"></i>지난 ${d.target_weekday}요일</span><span><i class="next"></i>내일</span></p>
          ${m.ingredients?.length && m.predicted ? `<div class="dm-ing"><h4>내일 필요한 재료</h4>
            <ul>${m.ingredients.map((g) => `<li><span>${esc(g.item)}</span><b>${ingQty(g.qty, g.unit)}</b></li>`).join("")}</ul></div>` : ""}
        </div>
      </div>`;
    }).join("")}</div>`;
  $("#orderCard").innerHTML = `
    <div class="prep-head">
      <h3>재고 관리 <span>주문할 재료 <b>${d.items.filter((i) => i.order_qty > 0).length}개</b></span></h3>
      <span class="prep-btns"><button class="order-all stock-edit" type="button">재고 입력</button>
        <button class="order-all stock-all" type="button">근거 모두 보기</button></span>
    </div>
    <div class="stock-cols">${orderGroups(d.items).map((g) => `<section class="stock-col ${g.key}">
      <h4>${g.title}${g.note ? `<small>${g.note}</small>` : ""}</h4>
      <div class="stock-list">${g.items.map((i) => orderItem(i, g.key)).join("")}</div>
    </section>`).join("")}</div>
    <p class="order-foot">주문량 = 입고까지 필요량 + 여유 10% − 재고</p>`;
  requestAnimationFrame(fitStockLists);
}

// 재고 관리 칸마다 재료 5개 높이까지만 보이고 나머지는 칸 안에서 스크롤
// (실제 줄 높이를 재서 맞춤 · 화면이 숨겨져 있어 못 재면 CSS 기본 높이를 씀)
function fitStockLists() {
  document.querySelectorAll(".stock-list").forEach((l) => {
    const sixth = l.children[5];
    l.style.maxHeight = sixth && sixth.offsetTop ? `${sixth.offsetTop}px` : "";
  });
}
window.addEventListener("resize", () => requestAnimationFrame(fitStockLists));

// 표의 판단을 사장님이 움직일 순서로 묶음 (빈 묶음은 숨김)
function orderGroups(items) {
  const rising = (i) => i.decision === "지금 사기" && i.price_change_pct >= 2;
  return [
    { key: "first", title: "먼저 사기", note: "시세가 오를 수 있어요", items: items.filter(rising) },
    { key: "normal", title: "평소대로 주문", note: "다음 입고 전에 모자라요", items: items.filter((i) => i.decision === "지금 사기" && !rising(i)) },
    { key: "split", title: "조금만 사기", note: "시세가 내릴 수 있어요", items: items.filter((i) => i.decision === "나눠 사기") },
    { key: "wait", title: "이번엔 안 사도 돼요", note: "재고가 충분해요", items: items.filter((i) => i.decision === "기다리기") },
  ].filter((g) => g.items.length);
}

function orderItem(i, key) {
  const change = i.price_change_pct;
  const chip = key === "first" || key === "split"
    ? `<span class="demand-chip ${change > 0 ? "up" : "down"}">다음 주 ${change > 0 ? "+" : "−"}${Math.abs(Math.round(change))}%</span>` : "<span></span>";
  const buy = i.order_qty > 0;
  return `<div class="order-item">
    <button class="order-row stock-row" type="button" aria-expanded="false" aria-controls="order-${i.item_id}">
      <span class="order-name">${esc(i.item)}<small>재고 ${qty(i.on_hand, i.unit)}</small></span>
      ${chip}
      <b>${buy ? qty(i.order_qty, i.unit) : "충분"}</b>
      <i class="order-arrow" aria-hidden="true"></i>
    </button>
    <div class="order-detail" id="order-${i.item_id}" hidden>
      <dl>
        <div><dt>내일 필요</dt><dd>${qty(i.need_target, i.unit)}</dd></div>
        <div><dt>재고</dt><dd>${qty(i.on_hand, i.unit)}</dd></div>
      </dl>
    </div>
  </div>`;
}

const setOpen = (b, open) => { b.setAttribute("aria-expanded", open); b.nextElementSibling.hidden = !open; };

// 메뉴를 누르면 지난 판매 그래프를 펼침
// 맨 위 버튼은 메뉴 전체를 펴고 접음
$("#menuForecast").onclick = (e) => {
  const rows = [...$("#menuForecast").querySelectorAll(".order-row")];
  const row = e.target.closest(".order-row");
  if (row) setOpen(row, row.getAttribute("aria-expanded") !== "true");
  else if (e.target.closest(".demand-all")) {
    const open = rows.some((b) => b.getAttribute("aria-expanded") !== "true");
    rows.forEach((b) => setOpen(b, open));
  } else return;
  $(".demand-all").textContent = rows.every((b) => b.getAttribute("aria-expanded") === "true") ? "모두 접기" : "근거 모두 보기";
};

// 재료를 누르면 계산 근거를 펼침 · 맨 위 버튼은 전체를 펴고 접음
$("#orderCard").onclick = (e) => {
  if (e.target.closest(".stock-edit")) { openStock(); return; }
  const rows = [...$("#orderCard").querySelectorAll(".order-row")];
  const row = e.target.closest(".order-row");
  if (row) setOpen(row, row.getAttribute("aria-expanded") !== "true");
  else if (e.target.closest(".stock-all")) {
    const open = rows.some((b) => b.getAttribute("aria-expanded") !== "true");
    rows.forEach((b) => setOpen(b, open));
  } else return;
  $(".stock-all").textContent = rows.every((b) => b.getAttribute("aria-expanded") === "true") ? "모두 접기" : "근거 모두 보기";
};

// 재고 입력 (/api/inventory): 재료마다 남은 양을 고쳐 저장 → 주문량 다시 계산
// kg · L · 모는 소수 한 자리 · 개는 정수. 영수증을 저장하면 산 만큼 자동으로 늘어남
const stockStep = (u) => (u === "개" ? "1" : "0.1");
async function openStock() {
  const modal = $("#stockModal"), box = $("#stockModalBody");
  box.innerHTML = `<div class="reading"><div class="spinner"></div><b>재고를 불러오는 중이에요</b></div>`;
  modal.hidden = false;
  let d;
  try { d = await getJSON("/api/inventory"); }
  catch (e) { box.innerHTML = `<p class="rc-warn">${esc(e.message)}</p>`; return; }
  const when = (s) => (s ? `${mmdd(s.slice(0, 10))} 고침` : "입력 전");
  box.innerHTML = `<h3>재고 입력</h3>
    <p class="muted small">지금 가게에 남은 양을 적어 주세요. 영수증을 저장하면 산 만큼 자동으로 늘어나요.</p>
    <form id="stockForm" novalidate>
      <ul class="sk-rows">${d.items.map((i) => `<li class="sk-row${i.in_menu ? "" : " off"}">
        <span class="sk-name">${esc(i.item)}<small>${when(i.updated_at)}${i.in_menu ? "" : " · 메뉴에 안 씀"}</small></span>
        <span class="mf-amount"><input type="number" inputmode="decimal" min="0" step="${stockStep(i.unit)}" data-id="${i.item_id}"
          data-was="${i.on_hand}" value="${+(+i.on_hand).toFixed(i.unit === "개" ? 0 : 1)}" aria-label="${esc(i.item)} 남은 양"><span class="mf-unit">${esc(i.unit)}</span></span>
      </li>`).join("")}</ul>
      <p class="rc-warn" id="skMsg" hidden></p>
      <div class="mf-actions"><button type="button" class="btn" id="skCancel">취소</button>
        <button type="submit" class="btn primary" id="skSave">저장</button></div>
    </form>`;
  $("#skCancel").onclick = closeStock;
  $("#stockForm").oninput = (e) => e.target.closest(".sk-row")?.classList.toggle("changed", +e.target.value !== +(+e.target.dataset.was).toFixed(3));
  $("#stockForm").onsubmit = async (e) => {
    e.preventDefault();
    const inputs = [...box.querySelectorAll("input[data-id]")];
    const bad = inputs.find((x) => x.value === "" || !(+x.value >= 0));
    const msg = $("#skMsg"), btn = $("#skSave");
    if (bad) { msg.textContent = "남은 양은 0 이상 숫자로 넣어 주세요"; msg.hidden = false; bad.focus(); return; }
    const items = inputs.filter((x) => x.closest(".sk-row").classList.contains("changed"))
      .map((x) => ({ item_id: +x.dataset.id, on_hand: +x.value }));
    if (!items.length) { closeStock(); return; }
    btn.disabled = true; btn.textContent = "저장하는 중"; msg.hidden = true;
    try {
      await sendJSON("/api/inventory", "PUT", { items });
      closeStock();
      loadDemand();   // 주문량 다시 계산
    } catch (err) { msg.textContent = err.message; msg.hidden = false; btn.disabled = false; btn.textContent = "저장"; }
  };
}
const closeStock = () => { $("#stockModal").hidden = true; };
$("#stockModalClose").onclick = closeStock;
$("#stockModal").onclick = (e) => { if (e.target.id === "stockModal") closeStock(); };

// ---------------------------------------------------------------
// 영수증으로 원가율 (사진 → 읽기 → 확인 · 수정 → 저장 → 원가율)
// ---------------------------------------------------------------
// 식봄 상품: 메인에는 보여 주지 않고 검색과 재료 페이지에서만 씀
let shop = {};             // 재료별 식봄 상품 (검색이 먼저 써도 오류 나지 않게 빈 값으로 시작)
let shopLoaded = false;
async function loadProducts() {
  try {
    shop = (await getJSON("/api/products")).items;
  } catch (e) {
    shop = {};
  }
  shopLoaded = true;
  if (ITEM) renderItemGoods();
}

function productCard({ item, g }) {
  const r = byItem(item) || { forecast: {} };
  const exp = expOf(r);
  const flag = exp >= 2 ? `<span class="flag" style="background:var(--up)">다음 주 오를 듯</span>`
    : exp <= -2 ? `<span class="flag" style="background:var(--down)">다음 주 떨어질 듯</span>` : "";
  const salpi = r.wholesale_change_pct == null ? ""
    : `<span class="salpi">살피: ${esc(item)} 도매 1주 <b class="${cls(r.wholesale_change_pct, 3)}">${pct(r.wholesale_change_pct)}</b></span>`;
  const sale = g.discount_rate && g.original_price > g.sale_price;
  return `
    <a class="product" href="${esc(g.url)}" target="_blank" rel="noopener">
      <div class="img">${g.image ? `<img src="${esc(g.image)}" alt="" loading="lazy">` : ""}${flag}</div>
      <span class="vendor">${esc(g.vendor || "")}</span>
      <span class="name">${esc(g.name)}</span>
      ${sale ? `<span class="orig">${won(g.original_price)}</span>` : ""}
      <span class="price">${sale ? `<span class="rate">${g.discount_rate}%</span>` : ""}${won(g.sale_price)}</span>
      ${g.price_per_kg ? `<span class="per">kg당 ${won(g.price_per_kg)}</span>` : ""}
      ${salpi}
    </a>`;
}

const DEMO_RECEIPTS = [
  ["receipt_1104_mart_up", "11/4 값 오른 마트 영수증"], ["receipt_1012_statement", "10/12 도매상 명세서"], ["receipt_1019_photo_tilted", "10/19 기울어진 사진"],
  ["receipt_1026_mart", "10/26 마트 영수증"], ["receipt_1102_handwritten", "11/2 손글씨 영수증"],
];
let receipt = null;
const supplierName = (s) => (s || "판매처 모름").replace(/\s*\(시연용\)/g, "");   // { image, mime, data(읽은 결과) }

async function sendJSON(url, method, body) {
  const r = await fetch(url, { method, headers: { "Content-Type": "application/json" }, body: body && JSON.stringify(body) });
  const out = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(out.detail || "잠시 뒤 다시 해 주세요");
  return out;
}

// 사진을 긴 쪽 1600px JPEG로 줄임 (요청 크기 제한 · 읽기 속도)
function shrink(blob) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, 1600 / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      const g = c.getContext("2d");
      g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
      g.drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(img.src);
      resolve(c.toDataURL("image/jpeg", 0.88));
    };
    img.onerror = () => reject(new Error("사진을 열지 못했어요"));
    img.src = URL.createObjectURL(blob);
  });
}

// PDF 영수증 · 명세서: 앞 3쪽까지 그림으로 그려 위아래로 이어 붙임 (pdf.js는 PDF를 고를 때만 불러옴)
const PDF_PAGES = 3;
let pdfLib = null;
function loadPdfLib() {
  if (pdfLib) return pdfLib;
  pdfLib = new Promise((resolve, reject) => {
    const sc = document.createElement("script");
    sc.src = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js";
    sc.onload = () => {
      window.pdfjsLib.GlobalWorkerOptions.workerSrc = "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
      resolve(window.pdfjsLib);
    };
    sc.onerror = () => { pdfLib = null; reject(new Error("PDF를 여는 도구를 불러오지 못했어요. 인터넷 연결을 확인해 주세요.")); };
    document.head.appendChild(sc);
  });
  return pdfLib;
}
const isPdf = (blob) => blob.type === "application/pdf" || /\.pdf$/i.test(blob.name || "");
async function pdfToImage(blob) {
  const lib = await loadPdfLib();
  let doc;
  try { doc = await lib.getDocument({ data: await blob.arrayBuffer() }).promise; }
  catch (e) { throw new Error(e.name === "PasswordException" ? "비밀번호가 걸린 PDF는 열 수 없어요" : "PDF를 열지 못했어요"); }
  const pages = [];
  for (let n = 1; n <= Math.min(doc.numPages, PDF_PAGES); n++) {
    const page = await doc.getPage(n);
    const base = page.getViewport({ scale: 1 });
    const vp = page.getViewport({ scale: Math.min(3, 1200 / base.width) });   // 한 쪽 너비 1200px
    const c = document.createElement("canvas");
    c.width = Math.round(vp.width); c.height = Math.round(vp.height);
    const g = c.getContext("2d");
    g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
    await page.render({ canvasContext: g, viewport: vp }).promise;
    pages.push(c);
  }
  return { image: stitch(pages), skipped: Math.max(0, doc.numPages - PDF_PAGES) };
}
// 그림 여러 장을 위아래로 이어 JPEG 한 장으로 (PDF 여러 쪽 · 카메라로 나눠 찍은 긴 영수증)
// 이은 높이가 6000px를 넘으면 전체를 줄임 (요청 크기 4.5MB 안으로 · 4장까지는 그대로)
const STITCH_MAX_H = 6000;
function stitch(pages) {
  const h = pages.reduce((s, c) => s + c.height, 0), k = Math.min(1, STITCH_MAX_H / h);
  const out = document.createElement("canvas");
  out.width = Math.round(Math.max(...pages.map((c) => c.width)) * k);
  out.height = Math.round(h * k);
  const g = out.getContext("2d");
  g.fillStyle = "#fff"; g.fillRect(0, 0, out.width, out.height);
  pages.reduce((y, c) => (g.drawImage(c, 0, y, c.width * k, c.height * k), y + c.height * k), 0);
  return out.toDataURL("image/jpeg", 0.85);
}

// blob: 사진 · PDF 파일, 또는 카메라로 찍은 사진(canvas) 목록 → 이어 붙여 한 장으로
async function readReceipt(blob) {
  const box = $("#receiptResult");
  $("#receiptStart").hidden = true;
  box.innerHTML = `<div class="reading"><div class="spinner"></div><b>살피가 영수증을 읽는 중이에요</b><p class="muted">10~30초쯤 걸려요</p></div>`;
  try {
    let image, skipped = 0;
    if (Array.isArray(blob)) image = stitch(blob);
    else if (isPdf(blob)) ({ image, skipped } = await pdfToImage(blob));
    else image = await shrink(blob);
    receipt = { image, mime: "image/jpeg" };
    // 로그인 표를 같이 보내면 서버가 무료 횟수를 셈 (다 썼으면 402 → 영수증 분석 칸을 가림)
    try { receipt.data = await authCall("/api/receipt/read", { token: readLogin()?.access_token, body: { image, mime: "image/jpeg" } }); }
    catch (e) { if (e.status === 402) { setTrial({ locked: true, left: 0 }); resetReceipt(); return; } throw e; }
    if (receipt.data.trial) setTrial(receipt.data.trial);
    receipt.data.skipped_pages = skipped;
    renderReceiptEdit();
  } catch (e) {
    box.innerHTML = `<p class="rc-warn">${esc(e.message)}</p><button class="btn" id="receiptAgain">다시 하기</button>`;
    $("#receiptAgain").onclick = resetReceipt;
  }
}

function resetReceipt() {
  receipt = null;
  $("#receiptResult").innerHTML = "";
  $("#receiptStart").hidden = false;
  $("#receiptFile").value = "";
}

// 확인 · 수정 표: 새로 읽은 영수증(아래 화면)과 저장한 영수증 고치기(팝업)가 같이 씀
// d = { date, supplier, items[{raw_name, item_id, base_unit, qty_base, amount, qty}], items_list, total_matches, ... }
function receiptEditor(box, d, { image, thumb = true, badge, saveLabel = "확인했어요, 저장", onSave, onCancel }) {
  const opts = (sel) => `<option value="">재료 아님</option>` + d.items_list.map((i) =>
    `<option value="${i.id}" ${i.id === sel ? "selected" : ""}>${esc(i.name)}</option>`).join("");
  const unitOf = (id) => d.items_list.find((i) => i.id === +id)?.base_unit || "";
  const row = (x, i) => `<tr data-i="${i}">
        <td><input class="rc-name" value="${esc(x.raw_name || "")}" aria-label="영수증 품목"></td>
        <td><select class="rc-item" aria-label="재료">${opts(x.item_id)}</select></td>
        <td class="qty-cell"><input class="rc-qty" type="number" step="0.1" min="0" value="${x.qty_base ?? ""}" aria-label="양"><span class="rc-unit">${esc(x.base_unit || "")}</span></td>
        <td><input class="rc-amount" type="number" min="0" value="${x.amount ?? ""}" aria-label="금액"></td>
        <td><button class="rc-del" type="button" title="이 줄 빼기">×</button></td></tr>`;
  box.innerHTML = `
    <div class="receipt-edit ${thumb ? "" : "no-thumb"}">
      ${thumb ? (image ? `<img class="receipt-thumb" src="${esc(image)}" alt="올린 영수증">` : `<div class="receipt-thumb no-photo">사진 없음</div>`) : ""}
      <div>
        <span class="badge">${badge || "살피가 읽은 내용 · 틀린 곳은 고쳐 주세요"}</span>
        <div class="receipt-meta">
          <label>날짜 <input type="date" class="rc-date" value="${esc(d.date || "")}"></label>
          <label>판매처 <input class="rc-supplier" value="${esc(d.supplier ? supplierName(d.supplier) : "")}"></label>
        </div>
        ${d.total_matches === false ? `<p class="rc-warn">줄 금액을 더하면 ${won(d.line_sum)}인데 합계는 ${won(d.total)}이에요. 빠진 줄이 없는지 봐 주세요.</p>` : ""}
        ${d.skipped_pages ? `<p class="rc-warn">PDF가 길어서 앞 ${PDF_PAGES}쪽만 읽었어요 (${d.skipped_pages}쪽 빠짐). 나머지 줄은 아래 '줄 더하기'로 넣어 주세요.</p>` : ""}
      </div>
    </div>
    <div class="table-scroll"><table class="price-table edit-table">
      <thead><tr><th>영수증 품목</th><th>재료</th><th>양</th><th>금액(원)</th><th></th></tr></thead>
      <tbody>${d.items.map(row).join("")}</tbody>
    </table></div>
    <button class="rc-add" type="button">+ 줄 더하기</button>
    <p class="muted small">양은 재료 기준 단위(kg · 모)로 바꾼 전체 양이에요. 예: 깐양파 15kg 1망 → 15</p>
    <div class="receipt-actions"><button class="btn rc-cancel" type="button">취소</button><button class="btn primary rc-save" type="button">${saveLabel}</button></div>`;
  const tb = box.querySelector("tbody");
  tb.onchange = (e) => {
    if (e.target.classList.contains("rc-item")) e.target.closest("tr").querySelector(".rc-unit").textContent = unitOf(e.target.value);
  };
  tb.onclick = (e) => { if (e.target.classList.contains("rc-del")) e.target.closest("tr").remove(); };
  box.querySelector(".rc-add").onclick = () => {
    tb.insertAdjacentHTML("beforeend", row({}, -1));
    tb.lastElementChild.querySelector(".rc-name").focus();
  };
  box.querySelector(".rc-cancel").onclick = onCancel;
  const btn = box.querySelector(".rc-save");
  btn.onclick = async () => {
    const items = [...tb.querySelectorAll("tr")].map((tr) => {
      const orig = d.items[+tr.dataset.i] || {};
      const itemId = tr.querySelector(".rc-item").value;
      return { raw_name: tr.querySelector(".rc-name").value.trim(), qty: orig.qty ?? null, item_id: itemId ? +itemId : null,
               qty_base: parseFloat(tr.querySelector(".rc-qty").value) || null, amount: parseFloat(tr.querySelector(".rc-amount").value) || null };
    });
    btn.disabled = true; btn.textContent = "저장하는 중";
    try {
      await onSave({ date: box.querySelector(".rc-date").value || null, supplier: box.querySelector(".rc-supplier").value || null, items });
    } catch (e) {
      btn.disabled = false; btn.textContent = saveLabel;
      alert(e.message);
    }
  };
}

function renderReceiptEdit() {
  receiptEditor($("#receiptResult"), receipt.data, {
    image: receipt.image, onCancel: resetReceipt,
    onSave: async (v) => {
      const r = await sendJSON("/api/receipt/save", "POST", { image: receipt.image, mime: receipt.mime, ...v });
      resetReceipt();
      $("#receiptResult").innerHTML = `<p class="ok">${mmdd(r.date)} 영수증 ${r.saved_items}줄을 저장했어요. 위 메뉴별 원가율이 새로 계산됐어요.</p>`;
      renderCosts(r, true);
      loadCosts(false);
      praiseIfSaved(r.purchase_id);
      // 이 영수증에서 찾은 '아낄 곳'(더 낸 돈)을 계정에 모아 둠 → 잠금 화면 '한 달 동안 n원 아낄 곳을 찾았어요'
      const token = readLogin()?.access_token;
      if (token && r.purchase_id) authCall("/api/receipt/trial/found", { token, body: { purchase_id: r.purchase_id } }).then(setTrial).catch(() => {});
    },
  });
}

// 칭찬 팝업: 새로 저장한 영수증에서 아낀 돈이 더 낸 돈보다 많을 때만 (나쁜 소식은 구매가 점검 칸에서만)
// 배지는 "장보기 고수!" 하나로 통일 · 5초 뒤 저절로 닫히고 × 로 바로 닫을 수도 있음
async function praiseIfSaved(id) {
  if (!id) return;
  let j;
  try { j = await getJSON(`/api/price-judge?purchase_id=${id}`); } catch { return; }
  praiseFrom(j);
}

// 구매가 점검 결과(j)로 아낀 돈 - 더 낸 돈을 계산해 이득이면 팝업 (새로 저장할 때 · 예전 영수증 열 때 둘 다)
function praiseFrom(j) {
  const net = (j.summary?.saved || 0) - (j.summary?.extra_paid || 0);
  if (net <= 0) return;
  const best = j.lines.filter((x) => x.saved > 0).sort((a, b) => b.saved - a.saved)[0];
  showPraise(net, best);
}

function showPraise(net, best) {
  document.querySelector(".praise-pop")?.remove();
  const pop = document.createElement("div");
  pop.className = "praise-pop";
  pop.innerHTML = `<div class="praise-box" role="dialog" aria-label="칭찬 배지">
    <button class="praise-x" type="button" aria-label="닫기">×</button>
    <img src="/static/img/salpi_thumbsup.png" alt="엄지 척 하는 살피">
    <span class="praise-badge">장보기 고수!</span>
    <p class="praise-msg">이번 영수증에서 <b>${won(net)}</b> 아꼈어요!</p>
    ${best ? `<p class="praise-best">가장 잘 산 품목 · ${esc(best.item)} <b>${won(best.saved)} 절약</b></p>` : ""}
    <i class="praise-timer"></i></div>`;
  document.body.append(pop);
  let timer;
  const close = () => { clearTimeout(timer); pop.classList.add("out"); setTimeout(() => pop.remove(), 200); };
  timer = setTimeout(close, 5000);
  pop.querySelector(".praise-x").onclick = close;
  pop.onclick = (e) => { if (e.target === pop) close(); };
}

const ratioCls = (v) => (v == null ? "" : v >= 40 ? "up" : "down");   // 원가율 40% 기준 (유저플로우 v2)

function renderCosts(r, withChange) {
  const T = r.target_ratio_pct;
  $("#costCard").innerHTML = `
    <p class="cost-guide"><b>원가율</b> = 판매가 중 <b>재료비 비율</b>. 보통 <b>${T}% 아래</b>면 괜찮아요.</p>
    <div class="cost-cards">${r.menus.map((m) => {
      const v = m.cost_ratio_pct;
      const ch = withChange && m.change_pt
        ? `<small class="cost-change ${m.change_pt > 0 ? "up" : "down"}">${m.change_pt > 0 ? "▲" : "▼"} ${Math.abs(m.change_pt)}%p</small>` : "";
      const tone = { up: "high", warnc: "tight", down: "ok" }[ratioCls(v)] || "";   // 높음 · 빠듯 · 충분
      // 한 줄에 숫자 넷: 원가율(크게 · 색) | 판매가 | 1인분 재료비 | 남는 금액
      return `<article class="cost-card ${tone}">
        <div class="cost-menu-row"><h3 class="cost-menu">${esc(m.menu)}</h3>
          <button class="btn cost-edit" type="button" data-mid="${m.menu_id}"><span class="pen-flip" aria-hidden="true">✎</span> 수정</button></div>
        <dl class="cost-stats">
          <div class="cost-main"><dt>원가율 <span class="cost-verdict">${esc(m.verdict)}</span></dt><dd>${v ?? "-"}<em>%</em>${ch}</dd></div>
          <div><dt>판매가</dt><dd>${won(m.price)}</dd></div>
          <div><dt>1인분 재료비</dt><dd>${won(m.cost_per_serving)}</dd></div>
          <div><dt>남는 금액</dt><dd>${won(m.margin)}</dd></div>
        </dl>
        ${m.next_ratio_pct != null && Math.abs(m.next_ratio_pct - v) >= 0.5 ? `<p class="cost-next">다음 주 예상 원가율 <b>${m.next_ratio_pct}%</b> (야채 시세 예측 반영)</p>` : ""}
        ${m.high ? costPlan(m) : ""}
        ${m.swap && !m.high ? `<div class="cost-swap">
          <b class="swap-title">대체 재료 제안</b>
          <div class="swap-body">
            <div class="swap-main">
              <p class="swap-pair"><span class="swap-from">${esc(m.swap.from)}</span><i aria-label="대신">→</i><span class="swap-to">${esc(m.swap.to)}</span></p>
              <p class="swap-reason">💡 ${esc(m.swap.reason)}</p>
            </div>
            <p class="swap-calc">${esc(m.swap.from)} ${m.swap.share_pct}%를 바꾸면 1인분 <b>${won(m.swap.saving_per_serving)}</b> 아껴요 · 원가율 ${m.cost_ratio_pct}% → <b>${m.swap.new_ratio_pct}%</b> · 남는 돈 ${won(m.margin)} → <b>${won(m.swap.new_margin)}</b></p>
            ${swapOrigin(m.swap)}${swapExtra(m.swap)}
          </div>
        </div>` : ""}
      </article>`;
    }).join("")}</div>
    <p class="muted small">레시피에 주재료만 들어 있어 실제보다 원가율이 조금 낮게 나와요.</p>`;
  fitCpWhat();
}

// 원가율 낮추는 방법 카드의 내용은 늘 한 줄: 칸보다 길면(예: 돼지고기 앞다리 50% → 수입 돼지고기 삼겹살) 글자를 칸에 맞을 때까지 조금씩 줄임
// → 세 카드 높이가 같아져 옆 카드에 빈 여백이 생기지 않음. 화면 폭이 바뀌면 다시 맞춤
function fitCpWhat() {
  document.querySelectorAll("#costCard .cp-what").forEach((el) => {
    el.style.fontSize = "";
    el.classList.remove("wrap");
    if (!el.clientWidth) return;   // 숨겨진 칸은 폭을 잴 수 없음
    let size = parseFloat(getComputedStyle(el).fontSize);
    while (el.scrollWidth > el.clientWidth + 1 && size > 13) { size -= 0.5; el.style.fontSize = `${size}px`; }
    // 13px로도 안 들어가는 좁은 화면(휴대폰 등)은 글자가 잘리지 않게 원래 크기로 두 줄
    if (el.scrollWidth > el.clientWidth + 1) { el.style.fontSize = ""; el.classList.add("wrap"); }
  });
}
let fitCpTimer;
addEventListener("resize", () => { clearTimeout(fitCpTimer); fitCpTimer = setTimeout(fitCpWhat, 150); });
document.fonts?.ready.then(fitCpWhat);   // 글꼴을 다 받은 뒤 폭이 달라지면 다시 맞춤

// 대체 재료 이름 바로 아래(구분선 위) 작게: 원산지 표시 변경 안내(고기). '원산지 표시 변경 필요'까지 한 줄, 설명은 다음 줄
const swapOrigin = (s) => {
  if (!s?.origin_notice) return "";
  const [head, ...rest] = s.origin_notice.split(":");
  return `<p class="swap-origin"><b>⚠ ${esc(head.trim())}</b>${rest.length ? `<span>${esc(rest.join(":").trim())}</span>` : ""}</p>`;
};
// 원가율 낮추는 방법 카드: '대체 재료' 칩 옆에 '⚠ 원산지 표시 변경 필요' 글자 → 마우스를 올리면(휴대폰은 누르면) 설명 말풍선 (카드 높이는 그대로)
let cpOriginSeq = 0;
const cpOrigin = (s) => {
  if (!s?.origin_notice) return "";
  const [head, ...rest] = s.origin_notice.split(":");
  const id = `cpOrigin${++cpOriginSeq}`;
  return `<span class="cp-origin-wrap"><button type="button" class="cp-origin"${rest.length ? ` aria-describedby="${id}"` : ""}>⚠ ${esc(head.trim())}</button>${rest.length
    ? `<span class="cp-tip" role="tooltip" id="${id}">${esc(rest.join(":").trim())}</span>` : ""}</span>`;
};
// 대체 재료 카드 맨 아래: 다른 후보(예: 수입 돼지고기)
const swapExtra = (s) => (s?.others || []).length
  ? `<p class="swap-others">다른 후보: ${s.others.map((o) => `${esc(o.to)} (1인분 ${won(o.saving_per_serving)} 절약 · 원가율 ${o.new_ratio_pct}%)`).join(" · ")}</p>` : "";

// 원가율 40% 이상(지금 또는 다음 주): 원가율 낮추는 방법(가격 · 재료 · 메뉴)을 함께 보여 줌 — 고르는 건 사장님 (유저플로우 v2)
// 방법마다 카드 하나: 종류 칩 · 바꾸는 것 · 원가율 · 남는 금액(또는 아끼는 돈) — 세 카드는 똑같이 (고르는 건 사장님)
function costPlan(m) {
  const p = m.price_up, s = m.swap, k = m.push_menu;
  const opts = [
    { kind: "price", label: "가격 조정", ratio: p?.new_ratio_pct, none: "계산할 수 없어요",
      what: p && `<s>${won(m.price)}</s><i aria-label="에서">→</i><b>${won(p.price)}</b>`,
      key: p?.basis === "다음 주 예상 원가" ? "남는 금액(다음 주 원가로 계산)" : "남는 금액", val: p && won(p.new_margin) },
    { kind: "swap", label: "대체 재료", ratio: s?.new_ratio_pct, none: "바꿀 만한 재료가 없어요",
      what: s && `${esc(s.from)} ${s.share_pct}%<i aria-label="대신">→</i><b>${esc(s.to)}</b>`,
      key: "1인분", val: s && `${won(s.saving_per_serving)} 절약` },
    { kind: "menu", label: "메뉴 제안", ratio: k?.cost_ratio_pct, none: "원가율이 괜찮은 다른 메뉴가 없어요",
      what: k && `<b>${esc(k.menu)} 판매 늘리기</b>`, key: "남는 금액", val: k && won(k.margin) },
  ];
  return `<div class="cost-plan">
    <b class="cp-title">원가율 낮추는 방법</b>
    <ol>${opts.map((o) => `<li class="cp-${o.kind}">
      <div class="cp-head"><span class="cp-chip">${o.label}</span>${o.kind === "swap" && o.ratio != null ? cpOrigin(s) : ""}${o.ratio == null ? "" : `<p class="cp-what">${o.what}</p>`}</div>
      ${o.ratio == null ? `<p class="cp-none">${o.none}</p>` : `<dl><dt>원가율</dt><dd class="cp-ratio">${o.ratio}%</dd><dt>${o.key}</dt><dd class="cp-money">${o.val}</dd></dl>`}
      ${o.kind === "swap" ? swapExtra(s) : ""}
    </li>`).join("")}</ol>
  </div>`;
}

// 최근 영수증: 사진 카드 한 줄 (맨 앞 = 새 영수증 올리기 칸) · 양옆 작은 화살표로 넘김
const RC_PIC = `<svg viewBox="0 0 48 40" aria-hidden="true"><rect x="2" y="2" width="44" height="36" rx="1.5"/><circle cx="11" cy="11" r="3.5"/><path d="M5 35l12-15 7 8 8-12 11 19z"/></svg>`;
// 사진이 없는 영수증: 품목 몇 줄 · 합계로 작은 영수증 모양을 그려 넣음 (올리기 칸과 헷갈리지 않게)
const rcMini = (p) => `<span class="rc-mini" aria-hidden="true">
  <b>${esc(supplierName(p.supplier))}</b><small>${mmdd(p.purchased_on)}</small>
  ${(p.names || []).slice(0, 3).map((n) => `<i>${esc(n)}</i>`).join("")}${p.items > 3 ? `<i class="more">외 ${p.items - 3}줄</i>` : ""}
  <em>합계 ${won(p.total_amount)}</em></span>`;
const RC_TRASH = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M9 7V4.5h6V7M6 7l1 13h10l1-13M10 11v6M14 11v6"/></svg>`;
function receiptList(list, all = false) {
  const cards = list.map((p) => `<li class="rc-card" data-id="${p.id}">
    <span class="rc-check" aria-hidden="true"></span>
    <button class="rc-open rc-thumb" data-rid="${p.id}" type="button" title="사진과 품목 보기">
      ${p.image_url ? `<img src="${esc(p.image_url)}" alt="${mmdd(p.purchased_on)} 영수증 사진" loading="lazy">` : rcMini(p)}
    </button>
    <div class="rc-meta"><span class="rc-date">${+p.purchased_on.slice(5, 7)}월 ${+p.purchased_on.slice(8, 10)}일</span>
      <b title="${esc(supplierName(p.supplier))}">${esc(supplierName(p.supplier))}</b><span class="rc-price">${won(p.total_amount)}</span></div></li>`).join("");
  return `<div class="rc-head"><h3 class="sub-h">최근 영수증</h3>
      ${list.length ? `<span class="rc-tools">
        <button class="rc-all" type="button" aria-expanded="${all}">${all ? "접기" : "전체 보기"}</button>
        <button class="rc-trash" type="button" title="여러 장 골라서 지우기" aria-label="여러 장 골라서 지우기">${RC_TRASH}</button>
        <span class="rc-sel-bar"><span class="rc-sel-count">지울 영수증을 골라 주세요</span>
          <button class="rc-remove rc-sel-del" type="button" disabled>지우기</button><button class="rc-sel-cancel" type="button">취소</button></span>
      </span>` : ""}</div>
    <div class="rc-strip-wrap">
      <button class="rc-arrow prev" type="button" aria-label="앞 영수증 보기" disabled><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M14.5 6l-6 6 6 6"/></svg></button>
      <ul class="rc-strip">
        <li class="rc-card"><button class="rc-thumb rc-add-tile" type="button" title="눌러서 영수증 사진 · PDF 올리기">
          <span class="rc-add-icon">${RC_PIC}<i aria-hidden="true">+</i></span><b>영수증 올리기</b><small>눌러서 사진 · PDF 선택</small></button></li>
        ${cards}
      </ul>
      <button class="rc-arrow next" type="button" aria-label="다음 영수증 보기" disabled><svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.5 6l6 6-6 6"/></svg></button>
    </div>`;
}
// 화살표: 더 넘길 게 없으면 흐리게 (자리는 그대로라 줄이 흔들리지 않음)
function rcArrows() {
  const s = $("#receiptList .rc-strip");
  if (!s) return;
  const max = s.scrollWidth - s.clientWidth - 2;
  $("#receiptList .rc-arrow.prev").disabled = s.scrollLeft <= 2;
  $("#receiptList .rc-arrow.next").disabled = s.scrollLeft >= max;
}
// all: [전체 보기]로 모든 날짜를 받아 사진 카드를 여러 줄로 펼침 · 접으면 마지막 최근 목록으로
let rcRecent = [];
function showReceiptList(list, all = false) {
  if (!all) rcRecent = list;
  $("#receiptList").classList.remove("selecting");
  $("#receiptList").classList.toggle("all", all);
  $("#receiptList").innerHTML = receiptList(list, all);
  rcArrows();
  document.querySelectorAll("#receiptList .rc-strip img").forEach((i) => i.addEventListener("load", rcArrows, { once: true }));
}
$("#receiptList").addEventListener("scroll", rcArrows, true);
addEventListener("resize", rcArrows);

async function loadCosts(full = true) {
  try {
    const r = await getJSON("/api/costs", { auth: true });
    if (r.locked) showSalesLock();
    else if (full) renderCosts(r, false);
    showReceiptList(r.receipts);
  } catch (e) {
    if (full) $("#costCard").innerHTML = `<p class="muted">원가율을 불러오지 못했어요. ${esc(e.message)}</p>`;
  }
}

// ---------------------------------------------------------------
// 메뉴 고치기 · 추가: 카드마다 [수정], 제목 옆 [+ 메뉴 추가] — 둘 다 같은 입력 창
// 저장하면 Supabase(팀 공용 데이터)에 바로 반영됨. 메뉴는 지우지 않고 '판매 중지'만 (판매 기록 보존)
// ---------------------------------------------------------------
let menuData = null;   // { items(재료 · 최근 영수증 단가), menus(레시피 포함), templates(자주 쓰는 메뉴) }
const menuItem = (id) => menuData.items.find((i) => i.id === +id);
// kg 재료는 g로 보여 주고 받음 (0.02kg보다 20g이 읽기 쉬움)
const qtyUnit = (it) => (!it ? "" : it.unit === "kg" ? "g" : it.unit);
const showQty = (it, q) => (it && it.unit === "kg" ? +(q * 1000).toFixed(1) : +(+q).toFixed(3));
const saveQty = (it, v) => (it && it.unit === "kg" ? v / 1000 : v);

async function openMenuEditor(menuId) {
  const modal = $("#menuModal"), box = $("#menuModalBody");
  box.innerHTML = `<div class="reading"><div class="spinner"></div><b>메뉴를 불러오는 중이에요</b></div>`;
  modal.hidden = false;
  try { menuData = await getJSON("/api/menus"); }
  catch (e) { box.innerHTML = `<p class="rc-warn">${esc(e.message)}</p>`; return; }
  menuForm(menuId ? menuData.menus.find((x) => x.id === +menuId) : null);
}

function itemOptions(sel) {
  const groups = {};
  for (const i of menuData.items) (groups[i.category] ||= []).push(i);
  return `<option value="">재료 선택</option>` + Object.entries(groups).map(([g, list]) => `<optgroup label="${esc(g)}">${
    list.map((i) => `<option value="${i.id}"${i.id === sel ? " selected" : ""}>${esc(i.name)}</option>`).join("")}</optgroup>`).join("");
}

const recipeRow = (r = {}) => `<li class="mf-row" data-loss="${r.loss || 0}">
  <select class="mf-item" aria-label="재료">${itemOptions(r.item_id)}</select>
  <span class="mf-amount"><input class="mf-qty" type="number" inputmode="decimal" min="0" step="any" aria-label="1인분 양"
    value="${r.qty != null ? showQty(menuItem(r.item_id), r.qty) : ""}"><span class="mf-unit"></span></span>
  <small class="mf-noprice" hidden>영수증 가격 없음</small>
  <button type="button" class="mf-del" aria-label="이 재료 빼기">✕</button></li>`;

function menuForm(m) {
  const add = !m;
  const onSale = new Set(menuData.menus.filter((x) => x.active).map((x) => x.name));
  const tpl = menuData.templates.filter((t) => !onSale.has(t.name));
  const box = $("#menuModalBody");
  box.innerHTML = `<h3>${add ? "메뉴 추가" : `${esc(m.name)} 고치기`}</h3>
    <p class="muted small">고치는 대로 아래에 원가율이 바로 계산돼요. [저장]을 눌러야 반영돼요.</p>
    ${add && tpl.length ? `<div class="mf-tpl"><b>자주 쓰는 메뉴에서 선택</b>
      <div>${tpl.map((t) => `<button type="button" class="btn" data-tpl="${esc(t.name)}">${esc(t.name)}</button>`).join("")}</div>
      <small>누르면 1인분 재료가 채워져요. 우리 가게에 맞게 양만 고쳐 주세요.</small></div>` : ""}
    <form class="menu-form" id="menuForm" novalidate>
      <label class="mf-field mf-price"><span>판매가</span><span><input id="mfPrice" type="number" inputmode="numeric" min="100" step="100"
        value="${m ? m.price : ""}" placeholder="예: 9000"> 원</span></label>
      <label class="mf-field"><span>메뉴 이름</span><input id="mfName" maxlength="30" value="${m ? esc(m.name) : ""}" placeholder="예: 김치찌개"></label>
      <div class="mf-field"><span>1인분 재료</span>
        <ul class="mf-rows" id="mfRows">${(m ? m.recipe : [{}]).map(recipeRow).join("")}</ul>
        <button type="button" class="btn mf-add" id="mfAddRow">+ 재료 추가</button></div>
      <div class="mf-preview" id="mfPreview" aria-live="polite"></div>
      <p class="rc-warn" id="mfMsg" hidden></p>
      <div class="mf-actions">
        ${add ? "" : `<button type="button" class="btn mf-stop" id="mfStop">판매 중지</button>`}
        <button type="button" class="btn" id="mfCancel">취소</button>
        <button type="submit" class="btn primary" id="mfSave">저장</button>
      </div>
    </form>`;
  const rows = $("#mfRows");
  menuCalc();
  box.querySelector(".mf-tpl")?.addEventListener("click", (e) => {
    const b = e.target.closest("[data-tpl]");
    if (!b) return;
    const t = menuData.templates.find((x) => x.name === b.dataset.tpl);
    $("#mfName").value = t.name;
    rows.innerHTML = t.recipe.map(recipeRow).join("");
    menuCalc();
    $("#mfPrice").focus();
  });
  $("#mfAddRow").onclick = () => { rows.insertAdjacentHTML("beforeend", recipeRow()); rows.lastElementChild.querySelector("select").focus(); menuCalc(); };
  rows.onclick = (e) => { if (e.target.closest(".mf-del")) { e.target.closest(".mf-row").remove(); menuCalc(); } };
  $("#menuForm").oninput = menuCalc;
  $("#mfCancel").onclick = closeMenu;
  if (!add) $("#mfStop").onclick = () => stopMenu(m);
  $("#menuForm").onsubmit = async (e) => {
    e.preventDefault();
    const recipe = [...rows.querySelectorAll(".mf-row")].map((li) => {
      const it = menuItem(li.querySelector(".mf-item").value), v = parseFloat(li.querySelector(".mf-qty").value);
      return it && v > 0 ? { item_id: it.id, qty: saveQty(it, v) } : null;
    }).filter(Boolean);
    const btn = $("#mfSave"), msg = $("#mfMsg");
    btn.disabled = true; btn.textContent = "저장하는 중"; msg.hidden = true;
    try {
      const r = await sendJSON(add ? "/api/menus" : `/api/menus/${m.id}`, add ? "POST" : "PUT",
        { name: $("#mfName").value.trim(), price: parseInt($("#mfPrice").value, 10) || null, recipe });
      closeMenu();
      afterMenuChange(r, add ? `'${r.name}' 메뉴를 추가했어요.` : `'${r.name}' 메뉴를 고쳤어요.`);
    } catch (err) {
      msg.textContent = err.message; msg.hidden = false;
      btn.disabled = false; btn.textContent = "저장";
    }
  };
}

// 원가율 미리 보기: 재료마다 최근 영수증 단가 × 1인분 양 (화면의 메뉴별 원가율과 같은 계산)
function menuCalc() {
  const price = parseInt($("#mfPrice").value, 10) || 0;
  let cost = 0, n = 0;
  const unknown = [];
  for (const li of $("#mfRows").querySelectorAll(".mf-row")) {
    const it = menuItem(li.querySelector(".mf-item").value), v = parseFloat(li.querySelector(".mf-qty").value);
    li.querySelector(".mf-unit").textContent = qtyUnit(it);
    li.querySelector(".mf-noprice").hidden = !it || it.price != null;
    if (!it || !(v > 0)) continue;
    if (it.price == null) { unknown.push(it.name); continue; }
    cost += saveQty(it, v) / (1 - +li.dataset.loss) * it.price;
    n++;
  }
  const ratio = price && n ? +(cost / price * 100).toFixed(1) : null;
  const tone = { up: "high", warnc: "tight", down: "ok" }[ratioCls(ratio)] || "";
  $("#mfPreview").className = `mf-preview ${tone}`;
  $("#mfPreview").innerHTML = ratio == null
    ? `<span class="muted">판매가와 재료를 넣으면 원가율이 계산돼요</span>`
    : `<span>원가율 <b class="mf-ratio">${ratio}%</b></span><span>1인분 재료비 <b>${won(cost)}</b></span><span>남는 금액 <b>${won(price - cost)}</b></span>
       ${unknown.length ? `<small>${unknown.map(esc).join(", ")}은(는) 영수증 가격이 없어 빠졌어요</small>` : ""}`;
}

async function stopMenu(m) {
  if (!confirm(`'${m.name}'을(를) 판매 중지할까요?\n\n원가율 · 내일 준비 목록에서 빠지고, 지금까지의 판매 기록은 그대로 남아요.\n나중에 같은 이름으로 추가하면 다시 판매돼요.`)) return;
  const btn = $("#mfStop");
  btn.disabled = true;
  try {
    const r = await sendJSON(`/api/menus/${m.id}/stop`, "POST");
    closeMenu();
    afterMenuChange(r, `'${r.name}' 메뉴를 판매 중지했어요. 판매 기록은 남아 있어요.`);
  } catch (err) {
    $("#mfMsg").textContent = err.message; $("#mfMsg").hidden = false;
    btn.disabled = false;
  }
}

function afterMenuChange(r, text) {
  renderCosts(r, false);
  $("#costCard").insertAdjacentHTML("afterbegin", `<p class="ok">${esc(text)}</p>`);
  showReceiptList(r.receipts);
  loadMyItems();
  loadDemand();
}

const closeMenu = () => { $("#menuModal").hidden = true; };
$("#menuModalClose").onclick = closeMenu;
$("#menuModal").onclick = (e) => { if (e.target.id === "menuModal") closeMenu(); };
$("#menuAddBtn").onclick = () => openMenuEditor(null);
$("#costCard").addEventListener("click", (e) => {
  const b = e.target.closest(".cost-edit");
  if (b) openMenuEditor(b.dataset.mid);
  // 원산지 안내 말풍선: 휴대폰처럼 마우스가 없으면 눌러서 열고 닫음 (다른 곳을 누르면 닫힘)
  const o = e.target.closest(".cp-origin-wrap");
  document.querySelectorAll("#costCard .cp-origin-wrap.open").forEach((w) => { if (w !== o) w.classList.remove("open"); });
  if (o) o.classList.toggle("open");
});

$("#demoReceipts").innerHTML = DEMO_RECEIPTS.map(([f, label]) =>
  `<button data-f="${f}"><img src="/receipts_demo/${f}.png" alt="" loading="lazy"><span>${label}</span></button>`).join("");
$("#demoReceipts").onclick = async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  readReceipt(await (await fetch(`/receipts_demo/${b.dataset.f}.png`)).blob());
};
$("#receiptFile").onchange = (e) => { if (e.target.files[0]) readReceipt(e.target.files[0]); };

// 영수증 분석 한 달 무료 (로그인한 사장님마다, 처음 읽은 날부터 30일 — 서버 account/trial.py)
// - 첫 화면 체험 버튼: 한 달 무료 → (시작 전) · 무료 D-n → · 끝나면 구독하기 →
// - 다 쓰면 나의 가게 영수증 분석 칸 전체를 흐리게 하고 안내 글을 띄움 (안의 버튼은 눌리지 않게)
function setTrial(t) {
  const locked = !!t?.locked;
  $("#receipt").classList.toggle("locked", locked);
  $("#receiptLock").hidden = !locked;
  ["#receiptStart", "#receiptResult", "#receiptList"].forEach((s) => { $(s).inert = locked; });
  // 잠금 화면 제목 밑 한 줄: 찾은 금액이 있으면 금액, 없으면 '원가율을 살펴봤어요'
  if (t) $("#receiptFound").innerHTML = t.found > 0
    ? `한 달 동안 <b>${won(t.found)}</b> 아낄 곳을 찾았어요`
    : "한 달 동안 영수증으로 원가율을 살펴봤어요";
  const go = $(".receipt-link .receipt-go");
  if (go && t) go.textContent = t.paid ? "→" : locked ? "구독하기 →" : t.since ? `무료 D-${t.left} →` : "한 달 무료 →";
  $(".receipt-link")?.classList.toggle("used-up", locked);   // 다 쓰면 카드는 회색, 구독하기 버튼만 노랑
}
if (SIGNED_IN) authCall("/api/receipt/trial", { method: "GET", token: readLogin()?.access_token }).then(setTrial).catch(() => {});
// 카메라로 찍기: 처음 한 번 브라우저가 카메라 권한을 물어봄 → 세로(2:3) 창에 맞춰 찍음
// 긴 영수증은 여러 번 나눠 찍기: 찍은 사진은 오른쪽 대기열에 작게 쌓이고(× 로 지우기) [다 찍었어요]를 누르면 위아래로 이어 읽음
// (폰은 뒤 카메라, 노트북은 앞 카메라. https 또는 내 컴퓨터 주소에서만 열림)
// shortcut: 여러 장을 한 장으로 이어 보냄(길면 stitch 가 줄임 · 요청 4.5MB), 팀원 feat/receipt-multi-photo(images 여러 장)가 dev에 합쳐지면 여러 장으로 보내기
const CAM_RATIO = 2 / 3;   // 영수증이 길어서 세로로 긴 2:3
let camStream = null, camShots = [], camSeen = null;   // camShots: [{ c: 자른 사진 canvas, url: 대기열 미리보기 }] · camSeen: 카메라 자리에 보고 있는 사진 번호
// 카메라 자리에 찍은 사진 보기 (i = null 이면 다시 카메라). 보고 있는 사진은 대기열에서 테두리로 표시
function camLook(i) {
  camSeen = i;
  const still = $("#camStill");
  if (i !== null) still.src = camShots[i].c.toDataURL("image/jpeg", 0.9);
  still.hidden = i === null;
  document.querySelectorAll("#camQueue .cam-thumb").forEach((b) => b.classList.toggle("on", +b.dataset.camView === i));
}
const CAM_GUIDE = `<ol class="cam-guide">
    <li><b>컴퓨터(크롬 · 엣지)</b>: 주소창 왼쪽 <b>자물쇠 · 설정 아이콘</b> → <b>카메라</b> → <b>허용</b> → 새로고침</li>
    <li><b>아이폰</b>: 설정 → Safari(또는 쓰는 브라우저) → <b>카메라</b> → <b>허용</b></li>
    <li><b>안드로이드</b>: 주소창 옆 <b>⋮</b> → 설정 → 사이트 설정 → <b>카메라</b> → 이 사이트 허용</li>
  </ol>`;
function camFail(msg, denied) {
  $("#cameraBody").innerHTML = `<p class="rc-warn">${msg}</p>
    ${denied ? `<p class="small">카메라를 쓰려면 권한을 켜 주세요.</p>${CAM_GUIDE}` : ""}
    <div class="camera-actions">
      <button class="btn" id="camRetry" type="button">다시 시도</button>
      <label class="btn primary" for="receiptFile" id="camGallery">사진첩에서 고르기</label>
    </div>`;
  $("#camRetry").onclick = openCamera;
  $("#camGallery").onclick = () => closeCamera();
}
async function askCamera() {
  return navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false });
}
async function openCamera() {
  $("#cameraModal").hidden = false;
  if (!navigator.mediaDevices?.getUserMedia) return camFail("이 브라우저에서는 카메라를 열 수 없어요. 사진첩에서 골라 주세요.");
  $("#cameraBody").innerHTML = `<div class="reading"><div class="spinner"></div><b>카메라를 여는 중이에요</b>
    <p class="muted small">'카메라 사용 허용' 창이 뜨면 <b>허용</b>을 눌러 주세요</p></div>`;
  try { camStream = await askCamera(); }
  catch (e) {
    const denied = e.name === "NotAllowedError" || e.name === "SecurityError";
    return camFail(denied ? "카메라 권한이 꺼져 있어요." : e.name === "NotFoundError" ? "연결된 카메라가 없어요." : "카메라를 열지 못했어요. 다른 앱이 카메라를 쓰고 있는지 확인해 주세요.", denied);
  }
  if ($("#cameraModal").hidden) return stopCamera();   // 여는 사이에 닫았으면
  camShots = [];
  $("#cameraBody").innerHTML = `<div class="cam-wrap">
      <div class="cam-view"><video id="camVideo" autoplay playsinline muted></video><i class="cam-frame" aria-hidden="true"></i>
        <img class="cam-still" id="camStill" alt="찍은 사진" hidden></div>
      <aside class="cam-queue" aria-label="찍은 사진"><p>찍은 사진 <b id="camCount">0</b>장</p><ul id="camQueue"></ul></aside>
    </div>
    <p class="muted small">영수증이 길면 위에서부터 나눠 찍어 주세요.</p>
    <div class="camera-actions"><button class="upload-btn" id="camShot" type="button">촬영</button>
      <button class="btn primary" id="camDone" type="button" hidden>완료</button></div>`;
  $("#camVideo").srcObject = camStream;
  $("#camShot").onclick = shootCamera;
  $("#camDone").onclick = () => { const pages = camShots.map((s) => s.c); closeCamera(); readReceipt(pages); };
  // 대기열: × = 그 사진 지우기, 사진 = 카메라 자리에 그 사진 보기 (같은 사진을 다시 누르면 카메라로)
  $("#camQueue").onclick = (e) => {
    const x = e.target.closest("[data-cam-del]");
    if (x) { camShots.splice(+x.dataset.camDel, 1); camLook(null); return camQueue(); }
    const v = e.target.closest("[data-cam-view]");
    if (v) camLook(+v.dataset.camView === camSeen ? null : +v.dataset.camView);
  };
}
// 대기열 다시 그리기: 찍은 순서대로 작은 사진 + × · 장수 · 버튼 켜고 끄기
function camQueue() {
  $("#camQueue").innerHTML = camShots.map((s, i) => `<li><button type="button" class="cam-thumb" data-cam-view="${i}" aria-label="${i + 1}번째 사진 크게 보기"><img src="${s.url}" alt=""></button>
    <button type="button" class="cam-x" data-cam-del="${i}" aria-label="${i + 1}번째 사진 지우기">×</button></li>`).join("");
  $("#camCount").textContent = camShots.length;
  $("#camDone").hidden = !camShots.length;   // 아무것도 안 찍었으면 [완료]는 숨김
  $("#camDone").textContent = `완료 (${camShots.length}장)`;
}
// 찍기: 화면에 보이는 세로(2:3) 가운데만 잘라 너비 1000px로
function shootCamera() {
  const v = $("#camVideo");
  if (camSeen !== null) return camLook(null);   // 찍은 사진을 보는 중이면 [촬영]은 카메라로 돌아가기
  if (!v.videoWidth) return;
  const vw = v.videoWidth, vh = v.videoHeight;
  const sw = vw / vh > CAM_RATIO ? vh * CAM_RATIO : vw, sh = sw / CAM_RATIO;
  const k = Math.min(1, 1000 / sw);
  const c = document.createElement("canvas");
  c.width = Math.round(sw * k); c.height = Math.round(sh * k);
  c.getContext("2d").drawImage(v, (vw - sw) / 2, (vh - sh) / 2, sw, sh, 0, 0, c.width, c.height);
  camShots.push({ c, url: c.toDataURL("image/jpeg", 0.5) });
  camQueue();
  $("#camQueue").lastElementChild?.scrollIntoView({ block: "nearest" });   // 4장이 넘으면 방금 찍은 사진이 보이게
}
function stopCamera() { camStream?.getTracks().forEach((t) => t.stop()); camStream = null; }
function closeCamera() { stopCamera(); camShots = []; camSeen = null; $("#cameraModal").hidden = true; }
// 찍은 사진을 보는 중이면 카메라로만 돌아감. 찍어 둔 사진이 있는데 카메라를 닫으려 하면 물어봄
const cancelCamera = () => {
  if (camSeen !== null) return camLook(null);
  if (!camShots.length || confirm(`찍은 사진 ${camShots.length}장을 버릴까요?`)) closeCamera();
};
$("#cameraBtn").onclick = openCamera;
$("#cameraClose").onclick = cancelCamera;
$("#cameraModal").onclick = (e) => { if (e.target.id === "cameraModal") cancelCamera(); };
// 휴지통 → 고르기 모드: 카드 오른쪽 위 체크 칸으로 여러 장 골라 한 번에 지우기
const rcPicked = () => [...document.querySelectorAll("#receiptList .rc-card.picked")].map((li) => li.dataset.id);
function rcSelectMode(on) {
  $("#receiptList").classList.toggle("selecting", on);
  document.querySelectorAll("#receiptList .rc-card.picked").forEach((li) => li.classList.remove("picked"));
  rcSelCount();
}
function rcSelCount() {
  const n = rcPicked().length;
  $("#receiptList .rc-sel-count").textContent = n ? `${n}장 골랐어요` : "지울 영수증을 골라 주세요";
  $("#receiptList .rc-sel-del").disabled = !n;
}
async function rcDeletePicked() {
  const ids = rcPicked();
  if (!ids.length || !confirm(`영수증 ${ids.length}장을 지울까요? 원가율이 다시 계산돼요.`)) return;
  $("#receiptList .rc-sel-del").disabled = true;
  const res = await Promise.allSettled(ids.map((id) => sendJSON(`/api/receipt/${id}`, "DELETE")));
  const fail = res.filter((x) => x.status === "rejected").length;
  if (fail) alert(`${ids.length}장 중 ${fail}장은 지우지 못했어요. 잠시 뒤 다시 해 주세요.`);
  loadCosts(true);   // 원가율 · 사진 줄을 한 번에 새로 (고르기 모드도 풀림)
}
$("#receiptList").onclick = async (e) => {
  if (e.target.closest(".rc-all")) {
    if ($("#receiptList").classList.contains("all")) return showReceiptList(rcRecent);
    try { return showReceiptList((await getJSON("/api/receipts")).receipts, true); } catch (err) { return alert(err.message); }
  }
  if (e.target.closest(".rc-trash")) return rcSelectMode(true);
  if (e.target.closest(".rc-sel-cancel")) return rcSelectMode(false);
  if (e.target.closest(".rc-sel-del")) return rcDeletePicked();
  const ar = e.target.closest(".rc-arrow");
  if (ar) { const s = $("#receiptList .rc-strip"); return s.scrollBy({ left: (ar.classList.contains("next") ? 1 : -1) * s.clientWidth * 0.8, behavior: "smooth" }); }
  if ($("#receiptList").classList.contains("selecting")) {   // 고르기 모드: 카드를 누르면 체크만
    const li = e.target.closest(".rc-card[data-id]");
    if (li) { li.classList.toggle("picked"); rcSelCount(); }
    return;
  }
  if (e.target.closest(".rc-add-tile")) return $("#receiptFile").click();   // 맨 앞 그림 칸 = 새 영수증 올리기
  const o = e.target.closest(".rc-open");
  if (o) return openReceipt(o.dataset.rid);   // 수정하기 · 지우기는 열린 창 안에
};

// ---------------------------------------------------------------
// 날씨 · 공휴일 · 행사
// ---------------------------------------------------------------
const WX_SUN = `<circle cx="16" cy="16" r="6.5" fill="#F5B02E"/><g stroke="#F5B02E" stroke-width="2.4" stroke-linecap="round"><path d="M16 3.5v3M16 25.5v3M3.5 16h3M25.5 16h3M7.2 7.2l2.1 2.1M22.7 22.7l2.1 2.1M7.2 24.8l2.1-2.1M22.7 9.3l2.1-2.1"/></g>`;
const WX_CLOUD = (fill) => `<path fill="${fill}" d="M9 24a5.5 5.5 0 0 1-.7-11 7.5 7.5 0 0 1 14.4 1.1A5 5 0 0 1 22.5 24Z"/>`;
const WX_ICONS = {
  "맑음": WX_SUN,
  "구름 많음": `<g transform="translate(5 -3) scale(.75)">${WX_SUN}</g><g transform="translate(-1 5) scale(.9)">${WX_CLOUD("#AEB8BF")}</g>`,
  "흐림": WX_CLOUD("#98A4AC"),
  "비": `<g transform="translate(0 -4)">${WX_CLOUD("#98A4AC")}</g><g stroke="#3F8FD8" stroke-width="2.4" stroke-linecap="round"><path d="M11 23.5l-1.5 4M17 23.5l-1.5 4M23 23.5l-1.5 4"/></g>`,
  "눈": `<g transform="translate(0 -4)">${WX_CLOUD("#98A4AC")}</g><g fill="#6FB1E6"><circle cx="10" cy="25.5" r="2"/><circle cx="16" cy="28" r="2"/><circle cx="22" cy="25.5" r="2"/></g>`,
};

// 기상청 하늘 상태 기준: 전운량 0~5 맑음, 6~8 구름 많음, 9~10 흐림. 비는 위 요약과 같이 1mm 이상부터
function sky(d) {
  if (d.snow_cm > 0) return "눈";
  if (d.rain_mm >= 1) return "비";
  if (d.cloud >= 9) return "흐림";
  if (d.cloud >= 6 || d.rain_mm > 0) return "구름 많음";
  return d.cloud == null ? "" : "맑음";
}

function wxIcon(d) { return skyIcon(sky(d)); }
// 예보 하늘 말(맑음 · 구름많음 · 흐림 · 흐리고 비 · 소나기 · 비/눈 …) → 아이콘 다섯 가지 중 하나
function fcSky(d) {
  const s = d.sky || "";
  if (/눈/.test(s)) return "눈";
  if (/비|소나기/.test(s)) return "비";
  if (/구름/.test(s)) return "구름 많음";
  if (/흐/.test(s)) return "흐림";
  return s ? "맑음" : "";
}
function skyIcon(s) {
  return `<svg class="wx-icon" viewBox="0 0 32 32" role="img" aria-label="${s}"><title>${s}</title>${WX_ICONS[s] || ""}</svg>`;
}

// ---------------------------------------------------------------
// 대형마트 판매가 (한국소비자원 참가격, 음식 재료만): 가장 싼 회사 · 보통 가격 · 2주 전 대비
// ---------------------------------------------------------------
const MART_FIRST = 12;   // 처음에 보여 줄 카드 수 (더보기마다 12개씩 더)
let mart = null, martCat = "전체", martPage = 1;

const martChange = (v) => (v == null ? "" : v > 0
  ? `<span class="mart-chg mart-up">2주 전보다 ▲${v.toFixed(1)}%</span>`
  : v < 0 ? `<span class="mart-chg mart-down">2주 전보다 ▼${Math.abs(v).toFixed(1)}%</span>`
  : `<span class="mart-chg">2주 전과 같아요</span>`);

// 최저가 회사의 온라인몰 검색 결과로 가는 바로가기 (그 회사에 몰이 없으면 몰 있는 회사 중 가장 싼 곳)
// 온라인몰 바로가기 버튼 (새 창)
const EXT_ICON = '<svg class="ext" viewBox="0 0 24 24" aria-hidden="true"><path d="M14 4h6v6"/><path d="M20 4l-9 9"/><path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>';
const martShop = (s) => (!s ? "" : `<div class="mart-shop-row"><a class="mart-shop" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer"
    title="${esc(s.mall)}로 가요 · ${esc(s.chain)} 매장가 기준이라 온라인몰 가격은 다를 수 있어요"><span class="mart-go">최저가 바로가기${EXT_ICON}</span></a></div>`);

// 품목 이름을 두 줄로: '쇠고기 등심' / '(1등급, 100g)' — 괄호가 없으면 한 줄
// 원래 자료에 무게가 없는 품목은 통째로 파는 단위를 적어 줌
const MART_UNIT = { "양배추": "(1통)", "애호박": "(1개)" };
function martName(name) {
  const m = name.match(/^(.+?)\s*(\(.*\))$/);
  const [base, spec] = m ? [m[1], m[2]] : [name, MART_UNIT[name]];
  return `<span class="mart-name">${esc(base)}</span>${spec ? `<small class="mart-spec">${esc(spec)}</small>` : ""}`;
}

function martCard(x) {
  const one = x.chains.length === 1;   // 한 회사에서만 조사된 재료는 비교 없이
  return `<article class="mart-item">
    <h3 title="${esc(x.name)}">${martName(x.name)}</h3>
    <p class="mart-low"><b>${won(x.low)}</b></p>
    ${martShop(x.shop)}
    ${one ? `<div class="mart-chains" aria-hidden="true"></div>` : `<details class="mart-chains"><summary>판매처별 가격</summary>
      <ul>${x.chains.map((c) => `<li${c.price === x.low ? ' class="mart-min"' : ""}><span>${esc(c.chain)}</span><b>${won(c.price)}</b></li>`).join("")}</ul>
    </details>`}
  </article>`;
}

function renderMart() {
  // 2주 새 오른 재료 → 내린 재료 → 그대로인 재료 순
  const rank = (x) => (x.change_pct > 0 ? 0 : x.change_pct < 0 ? 1 : 2);
  const list = mart.items.filter((x) => martCat === "전체" || x.category === martCat)
    .sort((a, b) => rank(a) - rank(b) || Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0) || a.name.localeCompare(b.name, "ko"));
  $("#martFilter").innerHTML = ["전체", ...mart.categories].map((c) =>
    `<button type="button" data-cat="${esc(c)}" class="${c === martCat ? "active" : ""}" aria-pressed="${c === martCat}">${esc(c)}</button>`).join("");
  const pages = Math.ceil(list.length / MART_FIRST);
  martPage = Math.min(martPage, pages || 1);
  $("#martGrid").innerHTML = list.length ? list.slice(0, martPage * MART_FIRST).map(martCard).join("")
    : `<p class="muted">이 종류는 이번 조사에 없어요</p>`;
  // 12개씩 더 보기: "더보기 지금 몇 번째 | 모두 몇 번" (끝까지 보면 처음으로 접기)
  const btn = $("#martAll");
  btn.hidden = pages <= 1;
  btn.innerHTML = martPage < pages ? `더보기 <b>${martPage}</b> | ${pages}` : "처음으로 접기";
  btn.setAttribute("aria-label", martPage < pages ? `12개 더 보기 (${pages}번 중 ${martPage}번째, ${list.length}개 중 ${martPage * MART_FIRST}개 보는 중)` : "처음 12개만 보기");
  fitMartNames();
}

// 이름이 한 줄에 안 들어가는 칸만 '긴 이름' 모양: 둘째 줄에 이름 나머지 + 바로 옆에 규격 (칸 높이는 그대로)
function fitMartNames() {
  $("#martGrid").querySelectorAll(".mart-item h3").forEach((h) => {
    h.classList.remove("long");
    const n = h.querySelector(".mart-name");
    if (n && n.scrollWidth > n.clientWidth + 1) h.classList.add("long");
  });
}
new ResizeObserver(() => fitMartNames()).observe($("#martGrid"));   // 화면 폭이 바뀌어 한 줄 칸 수가 달라질 때
document.fonts?.ready.then(fitMartNames);                            // 글꼴을 다 받은 뒤 다시 재기

async function loadMart() {
  try { mart = await getJSON("/api/mart"); }
  catch (e) { $("#martBasis").textContent = "대형마트 판매가를 불러오지 못했어요"; $("#martGrid").innerHTML = `<p class="muted">${esc(e.message)}</p>`; return; }
  $("#martBasis").textContent = "한국소비자원 참가격";
  renderMart();
}
$("#martFilter").onclick = (e) => {
  const b = e.target.closest("[data-cat]");
  if (b) { martCat = b.dataset.cat; martPage = 1; renderMart(); }
};
// 회사별 가격은 한 번에 하나만 펼침 (다른 카드를 펼치면 앞에 펼친 것은 접힘 — 겹쳐서 가려지지 않게)
$("#martGrid").addEventListener("toggle", (e) => {
  if (!e.target.open) return;
  $("#martGrid").querySelectorAll(".mart-chains[open]").forEach((d) => { if (d !== e.target) d.open = false; });
}, true);
$("#martAll").onclick = () => {
  const pages = Math.ceil(mart.items.filter((x) => martCat === "전체" || x.category === martCat).length / MART_FIRST);
  if (martPage < pages) { martPage += 1; renderMart(); return; }
  martPage = 1;
  renderMart();
  $("#mart").scrollIntoView({ block: "start" });
};

// ---------------------------------------------------------------
// 살피 예측률: 지난 7일 화면 예측을 7일 뒤 실제 시세와 비교해 맞춘 비율 (/api/forecast-score?weeks=1)
// 맞춤 = 오를지 · 비슷할지 · 내릴지(±2%) 방향을 맞힘. 품목은 예측 3번 이상만 (적으면 0% · 100%로 들쭉날쭉)
// ---------------------------------------------------------------
const SCORE_KINDS = ["과일", "야채", "육류", "수산물"];   // 탭 순서 (그 밖의 종류가 오면 뒤에 붙임)
const SCORE_MIN = 3;
let score = null, scoreKind = "전체", scoreOpen = true;   // 처음엔 펼친 채로, 다 본 뒤 접기
const scoreHits = (s) => Math.round((s.n * s.direction_hit_pct) / 100);
const scoreTier = (p) => (p >= 70 ? "good" : p >= 50 ? "mid" : "low");   // 사장님이 이 품목 예측을 얼마나 믿어도 되는지
const SCORE_GROUPS = [["good", "예측 정확", "70% 이상"], ["mid", "예측 안정", "50~70%"], ["low", "예측 성장 중", "50% 아래"]];
const scoreKinds = () => [...SCORE_KINDS, ...Object.keys(score.kinds).filter((k) => !SCORE_KINDS.includes(k))].filter((k) => score.kinds[k]?.n);
const scoreFold = new Set(["good", "mid", "low"]);   // 재료 목록을 접은 묶음 — 처음엔 카드만 보이고 누르면 재료 이름
// 펼치면: 묶음 카드 3개 나란히 (위 = 큰 묶음 이름 · 개수 · 기준, 누르면 그 아래 재료 목록 접기 · 펼치기)
function scoreDetail(few) {
  const shown = Object.entries(score.items).filter(([, v]) => (scoreKind === "전체" || v.kind === scoreKind) && v.n >= SCORE_MIN)
    .sort((a, b) => b[1].direction_hit_pct - a[1].direction_hit_pct || b[1].n - a[1].n || a[0].localeCompare(b[0], "ko"));
  const cards = SCORE_GROUPS.map(([tier, name, range]) => {
    const g = shown.filter(([, v]) => scoreTier(v.direction_hit_pct) === tier);
    const open = !scoreFold.has(tier);
    // 해당 재료가 없으면 제목만 흐리게 (누를 것 없음)
    if (!g.length) return `<div class="score-group ${tier} empty"><div class="score-group-head"><b>${name}</b><small>${range}</small></div></div>`;
    return `<div class="score-group ${tier}">
      <button type="button" class="score-group-head" data-sfold="${tier}" aria-expanded="${open}" aria-controls="scoreNames-${tier}">
        <b>${name}</b><span class="score-count">${g.length}개</span><small>${range}</small>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button>
      ${open ? `<div class="score-names" id="scoreNames-${tier}">${g.map(([item, v]) =>
        `<a href="/?item=${encodeURIComponent(item)}" title="예측률 ${v.direction_hit_pct}% (${v.n}번 예측해서 ${scoreHits(v)}번 맞혔어요)"><span>${esc(item)}</span></a>`).join("")}</div>` : ""}
    </div>`;
  }).join("");
  return `<div class="score-detail" id="scoreDetail">
    ${shown.length ? `<div class="score-groups">${cards}</div>` : `<p class="muted small">품목별로 보여 줄 만큼 채점한 예측이 아직 없어요</p>`}
    ${few ? `<p class="score-foot">예측 ${SCORE_MIN}번 미만 ${few}개는 채점 중</p>` : ""}
  </div>`;
}
function renderScore() {
  const a = score.all;
  if (!a?.n) { $("#scoreCard").innerHTML = `<p class="muted">아직 채점한 예측이 없어요. 예측하고 7일이 지나면 채점해요.</p>`; return; }
  const kinds = scoreKinds();
  if (scoreKind !== "전체" && !kinds.includes(scoreKind)) scoreKind = "전체";
  const s = scoreOpen && scoreKind !== "전체" ? score.kinds[scoreKind] : a;   // 큰 숫자 = 고른 탭의 예측률
  const label = scoreOpen && scoreKind !== "전체" ? scoreKind : "전체";
  const few = Object.values(score.items).filter((v) => (label === "전체" || v.kind === label) && v.n < SCORE_MIN).length;
  $("#scoreCard").innerHTML = `<div class="score-top">
      <p class="score-big"><b>${s.direction_hit_pct}%</b><span>${esc(label)} 예측률</span></p>
      <p class="score-sub">7일 뒤 가격 방향 적중률<br>${s.n}번 예측해서 ${scoreHits(s)}번 맞혔어요</p>
      ${scoreOpen ? `<div class="score-tabs" role="group" aria-label="재료 종류">${["전체", ...kinds].map((k) =>
        `<button type="button" data-skind="${esc(k)}" class="${k === scoreKind ? "active" : ""}" aria-pressed="${k === scoreKind}">${esc(k)}</button>`).join("")}</div>` : ""}
      <button type="button" class="score-more" data-smore aria-expanded="${scoreOpen}" aria-controls="scoreDetail">${scoreOpen ? "접기" : "상세보기"}
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg></button>
    </div>
    ${scoreOpen ? scoreDetail(few) : ""}`;
}
async function loadScore() {
  try { score = await getJSON("/api/forecast-score?weeks=1"); }
  catch (e) { $("#scoreCard").innerHTML = `<p class="muted">예측률을 불러오지 못했어요</p>`; return; }
  renderScore();
}
$("#scoreCard").onclick = (e) => {
  if (e.target.closest("[data-smore]")) { scoreOpen = !scoreOpen; renderScore(); return $("#scoreCard [data-smore]").focus(); }
  const k = e.target.closest("[data-skind]");
  if (k) { scoreKind = k.dataset.skind; renderScore(); $(`#scoreCard [data-skind="${CSS.escape(scoreKind)}"]`)?.focus(); }   // 다시 그려도 누른 탭에 그대로
  const f = e.target.closest("[data-sfold]");
  if (f) {
    const t = f.dataset.sfold;
    scoreFold.has(t) ? scoreFold.delete(t) : scoreFold.add(t);
    renderScore();
    $(`#scoreCard [data-sfold="${t}"]`)?.focus();
  }
};

async function loadContext() {
  let c;
  try { c = await getJSON("/api/context"); } catch (e) { return; }
  const fc = c.weather_forecast || [], w = c.weather;
  // 앞으로 7일 예보 (기상청 단기 · 중기). 예보를 못 받으면 지난 7일 관측으로 대신 보여 줌
  $("#weatherCard").innerHTML = fc.length ? (() => {
    const nums = (k) => fc.map((d) => d[k]).filter((v) => v != null);
    const rainy = fc.filter((d) => fcSky(d) === "비" || fcSky(d) === "눈").length;
    return `<h3>이번 주 대구 날씨</h3>
    <div class="wx-sum">
      <span class="${rainy ? "rain" : ""}">${rainy ? `비 · 눈 <b>${rainy}일</b>` : "비 예보 <b>없음</b>"}</span>
      <span class="lo">최저 <b>${Math.min(...nums("min"))}℃</b></span>
      <span class="hi">최고 <b>${Math.max(...nums("max"))}℃</b></span>
    </div>
    <div class="wx">${fc.map((d, i) => {
      const pop = Math.max(+d.rain_pct_am || 0, +d.rain_pct_pm || 0);
      return `<div><span class="wx-day">${mmdd(d.date)}<small>${"일월화수목금토"[new Date(`${d.date}T00:00:00`).getDay()]}</small></span>${skyIcon(fcSky(d))}<b>${d.max ?? "-"}°</b><span class="wx-min">${d.min ?? "-"}°</span>${pop ? `<span class="wx-pop">비 ${pop}%</span>` : "-"}</div>`;
    }).join("")}</div>`;
  })() : `<h3>대구 날씨 (지난 7일)</h3>
    <p class="muted" style="margin-bottom:10px">비 ${w.rain_total_mm}mm (${w.rain_days}일) · 최저 ${w.min_temp}℃ · 최고 ${w.max_temp}℃</p>
    <div class="wx">${(w.daily || []).map((d) => `<div>${mmdd(d.date)}${wxIcon(d)}<b>${Math.round(d.max_temp)}°</b>${d.rain_mm ? `비 ${d.rain_mm}` : "-"}</div>`).join("")}</div>`;
  const fmt = (s) => `${s.slice(4, 6)}.${s.slice(6, 8)}`;
  $("#holidayCard").innerHTML = `<h3>다가오는 공휴일 (30일)</h3>` + (c.holidays.length
    ? `<ul class="ctx-list">${c.holidays.map((x) => `<li>${fmt(x.date)} ${esc(x.name)}<small>도매시장 휴장 전 수요가 몰릴 수 있어요</small></li>`).join("")}</ul>`
    : `<p class="muted">30일 안에 공휴일이 없어요</p>`);
  $("#eventCard").innerHTML = `<h3>이달의 대구 행사 (${c.events.length}개)</h3>` + (c.events.length
    ? `<ul class="ctx-list event-list">${c.events.slice(0, 8).map((x) => {
        const inner = `<b>${esc(x.title)}</b><small>${fmt(x.start)} ~ ${fmt(x.end)} · ${esc((x.addr || "").replace("대구광역시 ", ""))}</small>`;
        return `<li>${x.content_id ? `<button type="button" class="event-link" data-event="${esc(x.content_id)}">${inner}<i aria-hidden="true">›</i></button>` : inner}</li>`;
      }).join("")}</ul>`
    : `<p class="muted">이달에 남은 행사가 없어요</p>`);
}

// ---------------------------------------------------------------
// 살피 챗봇
// ---------------------------------------------------------------
const chatEl = $("#chat"), body = $("#chatBody");
const history = [];   // 지난 대화 (서버가 기억하지 않으므로 화면이 보관해서 매번 보냄)
// 대화 기록용 묶음 번호: 이 창에서 나눈 대화끼리만 묶음 (가게 · 로그인 정보와 연결하지 않음, 새로 고침하면 바뀜)
const chatSession = (crypto.randomUUID && crypto.randomUUID()) || `${Date.now()}-${Math.random().toString(36).slice(2)}`;

function md(text) {
  // 굵게 · 목록 · 줄바꿈만 지원하는 간단한 변환
  const lines = esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").split(/\n/);
  let html = "", inList = false;
  for (const raw of lines) {
    const line = raw.trim();
    const item = line.match(/^(?:[*\-•]|\d+\.)\s+(.*)/);
    if (item) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${item[1]}</li>`; continue; }
    if (inList) { html += "</ul>"; inList = false; }
    if (line) html += `<p>${line}</p>`;
  }
  return html + (inList ? "</ul>" : "");
}

function addMsg(role, text) {
  const el = document.createElement("div");
  el.className = `msg ${role}`;
  el.innerHTML = role === "bot" ? md(text) : esc(text);
  body.appendChild(el);
  body.scrollTop = body.scrollHeight;
  return el;
}

function openChat() {
  chatEl.classList.add("open");
  chatEl.setAttribute("aria-hidden", "false");
  document.body.classList.add("chat-open");
  placeChat();
  if (!body.children.length) addMsg("bot", "사장님, 오늘 대구 시세 살펴왔어요.\n아래 버튼을 누르거나 편하게 물어보세요.");
  markAlertsRead();
  $("#chatText").focus();
}
function closeChat() {
  chatEl.classList.remove("open");
  chatEl.setAttribute("aria-hidden", "true");
  document.body.classList.remove("chat-open");
}
$("#chatClose").addEventListener("click", closeChat);

// 채팅창 크기: 가장자리 · 모서리에 마우스를 대면 화살표 커서로 바뀌고, 끌면 크기 조절
const EDGE = 8, CORNER = 22;   // 모서리는 둥글어서 끝점이 창 밖 → 가장자리 근처 22px까지 모서리로 봄
const CURSOR = { n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize",
                 ne: "nesw-resize", sw: "nesw-resize", nw: "nwse-resize", se: "nwse-resize" };
function edgeAt(e) {
  const r = chatEl.getBoundingClientRect();
  const near = (d) => (d < EDGE ? 2 : d < CORNER ? 1 : 0);   // 2: 가장자리 위, 1: 모서리 근처
  const t = near(e.clientY - r.top), b = near(r.bottom - e.clientY), l = near(e.clientX - r.left), rt = near(r.right - e.clientX);
  const v = t ? "n" : b ? "s" : "", h = l ? "w" : rt ? "e" : "";
  if (v && h && Math.max(t, b) + Math.max(l, rt) >= 3) return v + h;   // 모서리
  return (Math.max(t, b) === 2 ? v : "") + (Math.max(l, rt) === 2 ? h : "");
}
let rs = null;
chatEl.addEventListener("pointermove", (e) => {
  if (rs) {
    const dx = e.clientX - rs.x, dy = e.clientY - rs.y;
    let { left, top, width, height } = rs.box;
    if (rs.dir.includes("e")) width += dx;
    if (rs.dir.includes("s")) height += dy;
    if (rs.dir.includes("w")) { width -= dx; left += dx; }
    if (rs.dir.includes("n")) { height -= dy; top += dy; }
    const w = Math.max(320, Math.min(window.innerWidth - 16, width));
    const h = Math.max(360, Math.min(window.innerHeight - 16, height));
    if (rs.dir.includes("w")) left += width - w;   // 최소 크기에 걸리면 반대쪽이 밀리지 않게
    if (rs.dir.includes("n")) top += height - h;
    Object.assign(chatEl.style, { width: `${w}px`, height: `${h}px`, right: "auto", bottom: "auto",
      left: `${Math.max(0, Math.min(window.innerWidth - w, left))}px`, top: `${Math.max(0, Math.min(window.innerHeight - h, top))}px` });
    return;
  }
  chatEl.style.cursor = CURSOR[edgeAt(e)] || "";
});
chatEl.addEventListener("pointerdown", (e) => {
  const dir = edgeAt(e);
  if (!dir) return;
  const r = chatEl.getBoundingClientRect();
  rs = { dir, x: e.clientX, y: e.clientY, box: { left: r.left, top: r.top, width: r.width, height: r.height } };
  chatEl.setPointerCapture(e.pointerId);
  chatEl.classList.add("resizing");
  e.preventDefault();
}, true);
chatEl.addEventListener("pointerup", () => { if (rs) { rs = null; chatEl.classList.remove("resizing"); } });
chatEl.addEventListener("pointerleave", () => { if (!rs) chatEl.style.cursor = ""; });

// 살피 캐릭터 끌어서 옮기기 (살짝 누르면 채팅 열기 · 끌면 이동), 놓은 자리는 이 브라우저에 기억
const fab = $("#fab");
const FAB_KEY = "salpi_fab_pos";
function placeFab(x, y) {
  const w = fab.offsetWidth, h = fab.offsetHeight;
  x = Math.max(0, Math.min(window.innerWidth - w, x));
  y = Math.max(64, Math.min(window.innerHeight - h, y));
  Object.assign(fab.style, { left: `${x}px`, top: `${y}px`, right: "auto", bottom: "auto" });
  fab.classList.toggle("on-left", x + w / 2 < window.innerWidth / 2);   // 왼쪽에 있으면 말풍선을 오른쪽에
  placeChat();
}
function placeChat() {
  // 채팅창을 살피가 있는 쪽에 붙임 (넓은 화면만, 모바일은 아래에서 올라옴)
  if (window.innerWidth <= 700 || !fab.style.left) { chatEl.style.left = chatEl.style.right = chatEl.style.top = chatEl.style.bottom = ""; return; }
  const r = fab.getBoundingClientRect(), cw = chatEl.offsetWidth, ch = chatEl.offsetHeight;
  const left = r.left + r.width / 2 < window.innerWidth / 2 ? r.right + 8 : r.left - cw - 8;
  const top = Math.max(72, Math.min(window.innerHeight - ch - 12, r.bottom - ch));
  Object.assign(chatEl.style, { left: `${Math.max(8, Math.min(window.innerWidth - cw - 8, left))}px`, top: `${top}px`, right: "auto", bottom: "auto" });
}
try {
  const saved = JSON.parse(localStorage.getItem(FAB_KEY) || "null");
  if (saved) requestAnimationFrame(() => placeFab(saved.x * window.innerWidth, saved.y * window.innerHeight));
} catch (e) {}

let drag = null;
fab.addEventListener("pointerdown", (e) => {
  if (e.target.closest(".fab-x")) return;   // ×는 끌기 · 채팅 열기와 따로
  const r = fab.getBoundingClientRect();
  drag = { dx: e.clientX - r.left, dy: e.clientY - r.top, sx: e.clientX, sy: e.clientY, moved: false };
  fab.setPointerCapture(e.pointerId);
});
fab.addEventListener("pointermove", (e) => {
  if (!drag || fabHidden()) return;   // 작은 살피는 제자리 고정
  if (!drag.moved && Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) < 6) return;   // 손 떨림은 클릭으로 봄
  drag.moved = true;
  fab.classList.add("dragging");
  placeFab(e.clientX - drag.dx, e.clientY - drag.dy);
});
fab.addEventListener("pointerup", () => {
  if (!drag) return;
  fab.classList.remove("dragging");
  if (drag.moved) {
    const r = fab.getBoundingClientRect();
    try { localStorage.setItem(FAB_KEY, JSON.stringify({ x: r.left / window.innerWidth, y: r.top / window.innerHeight })); } catch (e) {}
  } else if (fabHidden()) {
    setFabHidden(false);
  } else {
    chatEl.classList.contains("open") ? closeChat() : openChat();
  }
  drag = null;
});
window.addEventListener("resize", () => { if (fab.style.left && !fabHidden()) placeFab(fab.offsetLeft, fab.offsetTop); });

// 살피 줄이기: 머리 위 ×를 누르면 문장 없이 작게 아래에 있고, 작은 살피를 누르면 돌아옴 (이 브라우저에 기억)
const FAB_HIDE_KEY = "salpi_fab_hidden";
const fabHidden = () => document.body.classList.contains("fab-hidden");
function setFabHidden(on, save = true) {
  document.body.classList.toggle("fab-hidden", on);
  $("#fabMain").setAttribute("aria-label", on ? "살피 다시 크게 보기" : "살피 챗봇 열기 (끌어서 옮길 수 있어요)");
  $("#fabMain").title = on ? "다시 크게 보기" : "누르면 대화, 끌면 이동";
  if (on) closeChat();
  if (save) try { localStorage.setItem(FAB_HIDE_KEY, on ? "1" : "0"); } catch (e) {}
}
$("#fabX").addEventListener("click", () => setFabHidden(true));
// 키보드로 누른 경우 (마우스 · 손가락은 위 pointerup에서 처리)
$("#fabMain").addEventListener("click", (e) => { if (e.detail === 0) fabHidden() ? setFabHidden(false) : openChat(); });
try { if (localStorage.getItem(FAB_HIDE_KEY) === "1") setFabHidden(true, false); } catch (e) {}

let busy = false;
async function send(text) {
  text = text.trim();
  if (!text || busy) return;
  busy = true;
  document.querySelectorAll("#quick button").forEach((b) => (b.disabled = true));
  addMsg("me", text);
  const typing = addMsg("bot", "살피가 살펴보는 중이에요…");
  typing.classList.add("typing");
  try {
    const r = await fetch("/api/chat/stream", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, history, session: chatSession }) });
    // 답이 한 줄(JSON)씩 옴: {s: 지금 하는 일} {t: 글자 조각} ... {done, reply}. 첫 조각이 오면 "살펴보는 중" 말풍선을 답으로 바꿔 채움
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "", shown = "", reply = null;
    const onLine = (line) => {
      if (!line.trim()) return;
      const m = JSON.parse(line);
      if (m.s && !shown) typing.textContent = m.s;   // 지금 하는 일 (답 글자가 나오기 전까지만)
      if (m.t) {
        shown += m.t;
        typing.classList.remove("typing");
        typing.innerHTML = md(shown);
        body.scrollTop = body.scrollHeight;
      }
      if (m.done) reply = m.reply;
    };
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop();
      lines.forEach(onLine);
    }
    onLine(buf);
    if (reply === null) throw new Error("끊김");
    typing.classList.remove("typing");
    typing.innerHTML = md(reply);   // 완성된 답으로 마무리 (섞인 질문 · 오류 문구는 여기서 처음 보임)
    body.scrollTop = body.scrollHeight;
    history.push({ role: "user", text }, { role: "bot", text: reply });
  } catch (e) {
    typing.remove();
    addMsg("bot", "연결이 끊겼어요. 잠시 뒤 다시 물어봐 주세요.");
  }
  busy = false;
  document.querySelectorAll("#quick button").forEach((b) => (b.disabled = false));
}
$("#quick").addEventListener("click", (e) => { const b = e.target.closest("button[data-q]"); if (b) send(b.dataset.q); });
$("#chatForm").addEventListener("submit", (e) => { e.preventDefault(); const t = $("#chatText"); send(t.value); t.value = ""; });

// ---------------------------------------------------------------
// 검색: 글자가 이름 어디에 들어 있든 찾음 ("토" → 토마토, 방울토마토 상품). 띄어쓰기와 대소문자는 무시
// ---------------------------------------------------------------
const squash = (s) => String(s ?? "").toLowerCase().replace(/\s/g, "");

function markHit(text, word) {
  const at = String(text).toLowerCase().indexOf(word.toLowerCase());
  if (at < 0) return esc(text);
  const end = at + word.length;
  return `${esc(text.slice(0, at))}<mark>${esc(text.slice(at, end))}</mark>${esc(text.slice(end))}`;
}

// 이름에 없지만 사장님이 흔히 쓰는 말 ("소고기" → 한우 등심, "달걀" → 계란)
const SEARCH_WORDS = {
  "한우 등심": "소고기", "한우 양지": "소고기 국거리", "돼지고기 앞다리": "돼지 제육 찌개용", "돼지고기 삼겹살": "돼지 오겹",
  "닭고기": "생닭 닭볶음탕", "계란": "달걀", "새우젓": "젓갈", "멸치액젓": "젓갈 액젓",
  "명태": "동태 생태", "새우": "흰다리",
};

function findAll(word) {
  const key = squash(word);
  const items = [
    ...overview.filter((r) => squash(r.item).includes(key))
      .map((r) => ({ name: r.item, note: r.wholesale_kg ? `${kindOf(r)} · 도매 kg당 ${won(r.wholesale_kg)}` : kindOf(r) })),
    ...extraList().filter((r) => r.price && squash(`${r.item} ${SEARCH_WORDS[r.item] || ""}`).includes(key))
      .map((r) => ({ name: r.item, note: `${r.group} · ${basisName(r)} ${won(r.price)}/${r.unit}` })),
  ];
  const seen = new Set();
  const goods = Object.values(shop).flat().filter((g) => {
    if (seen.has(g.url) || !squash(g.name).includes(key)) return false;
    seen.add(g.url);
    return true;
  }).map((g) => ({ name: g.name, note: won(g.sale_price), url: g.url }));
  return { items, goods };
}

// 검색창 하나를 연결: 위쪽 메뉴 검색창과 첫 화면 검색창이 같은 결과를 보여 줌
function setupSearch(searchInput, searchList, idp) {
  const box = searchInput.closest(".search");
  let searchHits = [], searchActive = -1;

  function closeSearch() {
    searchList.hidden = true;
    searchActive = -1;
    searchInput.setAttribute("aria-expanded", "false");
    searchInput.removeAttribute("aria-activedescendant");
  }

  function renderSearch() {
    const word = searchInput.value.trim();
    if (!squash(word)) { closeSearch(); return; }
    const { items, goods } = findAll(word);
    searchHits = [...items, ...goods];
    searchActive = -1;
    searchInput.removeAttribute("aria-activedescendant");
    const hit = (h, i) => `<a class="search-hit" id="${idp}${i}" role="option" aria-selected="false" href="${h.url ? esc(h.url) : `/?item=${encodeURIComponent(h.name)}`}"
      ${h.url ? 'target="_blank" rel="noopener"' : ""}><span>${markHit(h.name, word)}</span><small>${esc(h.note)}</small></a>`;
    searchList.innerHTML = searchHits.length
      ? (items.length ? `<p class="search-group">재료 시세 ${items.length}개</p>${items.map((h, i) => hit(h, i)).join("")}` : "")
        + (goods.length ? `<p class="search-group">식봄 상품 ${goods.length}개</p>${goods.map((h, i) => hit(h, items.length + i)).join("")}` : "")
      : `<p class="search-empty">${overview.length ? `'${esc(word)}'이(가) 들어간 재료나 상품이 없어요` : "시세를 불러오는 중이에요"}</p>`;
    searchList.hidden = false;
    searchInput.setAttribute("aria-expanded", "true");
  }

  function moveSearch(step) {
    if (!searchHits.length) return;
    $(`#${idp}${searchActive}`)?.classList.remove("active");
    $(`#${idp}${searchActive}`)?.setAttribute("aria-selected", "false");
    searchActive = (searchActive + step + searchHits.length) % searchHits.length;
    const el = $(`#${idp}${searchActive}`);
    el.classList.add("active");
    el.setAttribute("aria-selected", "true");
    el.scrollIntoView({ block: "nearest" });
    searchInput.setAttribute("aria-activedescendant", el.id);
  }

  // 검색 버튼: 고른(없으면 첫 번째) 결과로 이동. 결과가 없으면 목록 · 안내만 보여 줌
  function goFirst() {
    const keep = searchActive;
    renderSearch();
    if (searchHits.length) $(`#${idp}${Math.max(keep, 0)}`)?.click();
    else searchInput.focus();
  }

  searchInput.addEventListener("input", renderSearch);
  searchInput.addEventListener("focus", renderSearch);
  searchInput.addEventListener("keydown", (e) => {
    if (e.isComposing) return;   // 한글 조합 중에는 키 동작 없음
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); moveSearch(e.key === "ArrowDown" ? 1 : -1); }
    if (e.key === "Escape") closeSearch();
    if (e.key === "Enter" && searchHits.length && !searchList.hidden) {
      e.preventDefault();
      $(`#${idp}${Math.max(searchActive, 0)}`).click();
    }
  });
  searchList.addEventListener("click", (e) => { if (e.target.closest(".search-hit")) closeSearch(); });
  document.addEventListener("click", (e) => { if (!box.contains(e.target)) closeSearch(); });
  document.addEventListener("focusin", (e) => { if (!box.contains(e.target)) closeSearch(); });
  return { goFirst };
}

const topSearch = setupSearch($("#searchInput"), $("#searchList"), "hit");
$("#searchBtn").addEventListener("click", topSearch.goFirst);

// ---------------------------------------------------------------
// 알림톡 시연: 세그먼트별 메시지 (실제 발송 없음). 시세 문장은 오늘 값, 나머지는 예시 문장
// ---------------------------------------------------------------
function talkMessages() {
  const byExp = slideOrder();
  const rising = byExp.filter((r) => expOf(r) >= 2);
  const falling = byExp.at(-1);
  const top = rising[0];
  const live = "오늘 시세 기준";
  const sample = "가게 데이터가 쌓이면 실제 값으로 나가는 예시 문장";
  return {
    S1: { name: "S1 시세 민감", policy: "가격 알림을 먼저 보내요", title: "기다려도 좋은 재료",
      ...(falling && expOf(falling) <= -2
        ? { body: `${falling.item}, 다음 주에 떨어질 가능성이 있어요.\n급하지 않으면 며칠 기다려 보세요.`, basis: live }
        : { body: "양파, 오늘보다 다음 주가 쌀 가능성이 있어요.\n급하지 않으면 며칠 기다려 보세요.", basis: sample }) },
    S2: { name: "S2 루틴 고정", policy: "평소와 다를 때만 보내요", title: "평소와 달라요",
      body: "이번 주는 평소보다 돼지고기 3kg 더 필요해요.\n발주량을 확인해 보세요.", basis: sample },
    S3: { name: "S3 대량 계획", policy: "주 1회 요약 리포트로 보내요", title: "주간 가격 위험 요약",
      ...(rising.length
        ? { body: `다음 주 오를 가능성이 있는 재료 ${rising.length}개: ${rising.slice(0, 3).map((r) => r.item).join(", ")}\n식단을 확정하기 전에 살펴보세요.`, basis: live }
        : { body: "다음 주 식단 중 가격 위험 품목 2개가 있어요.\n식단을 확정하기 전에 살펴보세요.", basis: sample }) },
    S4: { name: "S4 급발주 위험", policy: "전날 오후에 미리 보내요", title: "미리 준비할 재료",
      body: "금요일 비 예보가 있어요.\n제육볶음 재료를 오늘 미리 살펴보세요.", basis: sample },
    S5: { name: "S5 이탈 위험", policy: "성과 요약을 1회만 보내고 다른 알림은 줄여요", title: "지난주 살피 성과",
      body: "지난주 김치찌개 예측이 얼마나 맞았는지 정리했어요.\n한 번 살펴보세요.", basis: sample },
    hold: { name: "판단 보류", policy: "기록이 적어 누구에게나 맞는 기본 안내만 보내요", title: "오늘의 시세",
      ...(top
        ? { body: `${top.item}, 다음 주에 오를 가능성이 있어요.\n필요한 양을 확인해 보세요.`, basis: live }
        : { body: "오늘 대구 도매 시세를 살펴왔어요.\n필요한 재료를 확인해 보세요.", basis: sample }) },
  };
}

let talkKind = "S1";
function renderTalk() {
  const all = talkMessages(), m = all[talkKind];
  $("#talkTabs").innerHTML = Object.entries(all).map(([key, v]) =>
    `<button data-kind="${key}" aria-pressed="${key === talkKind}">${esc(v.name)}</button>`).join("");
  $("#talkPolicy").textContent = m.policy;
  $("#talkRoom").innerHTML = `
    <p class="talk-time">오전 7:00</p>
    <div class="talk-msg">
      <img src="/static/img/salpi_face.png" alt="">
      <div>
        <p class="talk-from">살피</p>
        <div class="talk-card"><h3>${esc(m.title)}</h3><p>${esc(m.body)}</p><a href="/#dashboard" id="talkLink">시세 보러 가기</a></div>
      </div>
    </div>
    <p class="talk-basis">${esc(m.basis)}</p>`;
}
function openTalk() {
  renderTalk();
  $("#talk").hidden = false;
  $("#talkClose").focus();
}
function closeTalk() {
  $("#talk").hidden = true;
}
$("#talkClose").addEventListener("click", closeTalk);
$("#talk").addEventListener("click", (e) => {
  if (e.target.id === "talk" || e.target.id === "talkLink") closeTalk();
  const b = e.target.closest("button[data-kind]");
  if (b) { talkKind = b.dataset.kind; renderTalk(); $(`#talkTabs [data-kind="${talkKind}"]`).focus(); }
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#talk").hidden) closeTalk(); });

loadOverview();
loadExtra();   // 육류 · 수산물: 탭 · 검색 · 재료 페이지(/?item=삼겹살)에서 씀
loadProducts();
loadMyItems();
loadCostAlerts();
if (STORE_VIEW) {
  const storeReady = Promise.allSettled([loadSales(), loadDemand(), loadCosts()]);
  // 첫 화면 영수증 분석 체험 칸(/?page=store#receipt): 열자마자 영수증 분석 칸으로 이동하고,
  // 위 칸(내일 준비 · 원가율)이 늦게 채워져 길어지는 동안에도 그 자리에 머무름 (사용자가 직접 스크롤하면 멈춤)
  if (location.hash === "#receipt") {
    const toReceipt = () => $("#receipt").scrollIntoView({ block: "start" });
    let follow = true;
    const stop = () => { follow = false; };
    ["wheel", "touchstart", "keydown"].forEach((t) => addEventListener(t, stop, { once: true, passive: true }));
    toReceipt();
    const keep = new ResizeObserver(() => { if (follow) toReceipt(); });
    keep.observe($("#sales")); keep.observe($("#store")); keep.observe($("#costs"));
    storeReady.then(() => setTimeout(() => { follow = false; keep.disconnect(); }, 5000));   // 다 그려진 뒤 5초 동안 늦게 바뀌는 칸 크기도 따라감
  }
} else if (!ITEM && !AUTH_VIEW) {
  loadContext();
  loadMart();
  loadScore();
}
if (location.hash === "#chat") openChat();   // 주소 끝에 #chat 을 붙이면 채팅창이 열린 채로 시작
if (location.hash === "#talk") openTalk();   // 주소 끝에 #talk 을 붙이면 알림톡 시연이 열린 채로 시작
if (location.hash === "#rise") setTimeout(() => goSlide(1, "instant"), 4000);   // 시연용: 첫 야채 대시보드부터
if (location.hash === "#fruit") setBoardTab("과일");   // 시연용: 과일 탭이 열린 채로
if (location.hash === "#sea") setBoardTab("수산물");   // 시연용: 수산물 탭이 열린 채로
if (location.hash === "#meat") setBoardTab("육류");    // 시연용: 육류 탭이 열린 채로

// ---------------------------------------------------------------
// 영수증 한 장 자세히 (사진 + 품목) — '최근 영수증' 목록 · 마이페이지 '나의 영수증'에서 엶
// ---------------------------------------------------------------
async function openReceipt(id, editing = false) {
  const modal = $("#receiptModal"), box = $("#receiptModalBody");
  box.innerHTML = `<div class="reading"><div class="spinner"></div><b>영수증을 불러오는 중이에요</b></div>`;
  modal.hidden = false;
  let d;
  try { d = await getJSON(`/api/receipt/${id}`); }
  catch (e) { box.innerHTML = `<p class="rc-warn">${esc(e.message)}</p>`; return; }
  (editing ? editReceiptView : showReceiptView)(id, d);
}

const receiptPhoto = (d) => (d.image_url
  ? `<a href="${esc(d.image_url)}" target="_blank" rel="noopener" title="크게 보기"><img src="${esc(d.image_url)}" alt="영수증 사진"></a>`
  : `<div class="no-photo">사진이 없어요<br><small>품목만 고쳐도 돼요</small></div>`);

function showReceiptView(id, d) {
  const qtyTxt = (x) => (x.unit ? qty(x.qty_base, x.unit) : "-");
  $("#receiptModalBody").innerHTML = `
    <h3>${mmdd(d.purchased_on)} · ${esc(supplierName(d.supplier))}</h3>
    <p class="muted small">${d.source === "ocr" ? "영수증 읽기로 저장" : "기본 데이터"} · 합계 ${won(d.total_amount)}</p>
    <div class="receipt-view">
      ${receiptPhoto(d)}
      <div>
        <table class="price-table rc-table">
          <thead><tr><th>영수증 품목</th><th>재료</th><th>양</th><th>금액</th><th>kg·모당</th><th></th></tr></thead>
          <tbody>${d.items.map((x) => `<tr data-jk="${esc(judgeKey(x))}"><td>${esc(x.raw_name)}</td>
            <td>${esc(x.item || "재료 아님")}</td><td>${qtyTxt(x)}</td>
            <td class="price">${won(x.amount)}</td><td>${x.unit_price ? won(x.unit_price) : "-"}</td><td class="rc-judge-cell"><span class="rc-chip"></span></td></tr>`).join("")}</tbody>
          <!-- 맨 아래 한 줄: 합계 + 평소 가격과 비교한 결과 (구매가 점검을 표 안으로 합침) -->
          <tfoot><tr class="rc-total"><td colspan="6"><div><b>합계 ${won(d.total_amount)}</b>
            <span class="rc-judge-sum" id="rcJudgeSum">평소 가격과 비교하는 중이에요</span></div></td></tr></tfoot>
        </table>
      </div>
    </div>
    <div class="receipt-actions rc-view-btns"><button class="rc-edit" id="rcViewEdit" type="button">수정하기</button>
      <button class="rc-remove" id="rcViewDel" type="button">지우기</button></div>`;
  $("#rcViewEdit").onclick = () => editReceiptView(id, d);
  $("#rcViewDel").onclick = async () => {
    if (!confirm("이 영수증을 지울까요? 원가율이 다시 계산돼요.")) return;
    try { afterReceiptDelete(await sendJSON(`/api/receipt/${id}`, "DELETE")); closeReceipt(); }
    catch (err) { alert(err.message); }
  };
  loadJudge(id);
}
// 영수증을 지운 뒤: 나의 가게면 원가율 · 사진 줄, 마이페이지 '나의 영수증'이 열려 있으면 그 목록도 새로
function afterReceiptDelete(r) {
  if (STORE_VIEW) { renderCosts(r, false); loadCosts(false); }
  if ($("#mypage")?.classList.contains("open") && $("#mypageTitle").textContent === "나의 영수증") renderMypage("receipts");
}

// 싸게/비싸게 판정 (/api/price-judge): 표 맨 오른쪽 칸에 칩 하나씩 + 맨 아래 합계 줄에 더 낸 돈 · 아낀 돈
// 표 줄과 판정 줄은 '영수증 품목 · 재료 · 금액'으로 짝을 맞춤
const judgeKey = (x) => `${x.raw_name}|${x.item || ""}|${x.amount}`;
const JUDGE_CHIP = { "비싸게 샀어요": "up", "싸게 샀어요": "down", "시세가 올랐어요": "rise" };
function judgeChipText(x) {   // 판정 글자 그대로 (비슷해요 · 비교할 값 없음은 칩 없음)
  return JUDGE_CHIP[x.verdict] ? x.verdict : "";
}
async function loadJudge(id) {
  const sum = $("#rcJudgeSum");
  let j;
  try { j = await getJSON(`/api/price-judge?purchase_id=${id}`); }
  catch (e) { if (sum) sum.textContent = "평소 가격과 비교하지 못했어요"; return; }
  if (!sum?.isConnected) return;
  const rows = [...document.querySelectorAll(".rc-table tbody tr")];
  for (const x of j.lines) {
    const tr = rows.find((r) => r.dataset.jk === judgeKey(x) && !r.dataset.judged);
    const text = judgeChipText(x);
    if (!tr || !text) continue;
    tr.dataset.judged = "1";
    const why = x.why + (x.extra_paid ? ` · ${won(x.extra_paid)} 과지출` : x.saved ? ` · ${won(x.saved)} 절약` : "");
    // 칩 바로 옆에 같은 줄로 금액만 (빨강 = 더 낸 돈, 초록 = 아낀 돈 · '과지출 · 절약' 글자는 합계 줄에만)
    const money = x.extra_paid ? `<b class="up">${won(x.extra_paid)}</b>` : x.saved ? `<b class="down">${won(x.saved)}</b>` : "";
    // 비싸게 산 재료는 '더 싼 곳' 버튼 → 누르면 그 줄 아래에 판매처 목록 (/api/cheaper)
    const more = x.verdict === "비싸게 샀어요" && x.item
      ? `<button class="rc-cheaper-btn" type="button" data-item="${esc(x.item)}" data-paid="${x.unit_price || ""}" aria-expanded="false">더 싼 곳</button>` : "";
    tr.querySelector(".rc-chip").outerHTML = `<span class="demand-chip rc-chip ${JUDGE_CHIP[x.verdict] || ""}" title="${esc(why)}">${esc(text)}</span>`
      + (money ? `<span class="rc-why">${money}</span>` : "") + more;
  }
  document.querySelectorAll(".rc-cheaper-btn").forEach((b) => { b.onclick = () => toggleCheaper(b); });
  const extra = j.summary?.extra_paid || 0, saved = j.summary?.saved || 0;
  sum.innerHTML = [extra ? `<b class="up">${won(extra)} 과지출</b>` : "",
                   saved ? `<b class="down">${won(saved)} 절약</b>` : ""].filter(Boolean).join(" · ")
    || "모두 평소 값에 샀어요";
  praiseFrom(j);   // 예전 영수증을 열 때도 이득이면 칭찬 팝업
}

// 더 싼 판매처 (/api/cheaper): 산 값(kg·모당)보다 싼 곳만 싼 순서로. 제휴 · 소매가는 칩으로 표시
const sellerTags = (s) => [s.affiliate ? `<span class="cs-tag aff">제휴</span>` : "",
  s.retail ? `<span class="cs-tag retail">소매가</span>` : "",
  s.free_delivery ? `<span class="cs-tag">무료배송</span>` : ""].join("");
function cheaperHTML(c) {
  const u = c.unit || "kg";
  if (!c.sellers?.length) {
    const msg = c.message?.includes("지원하지") ? `${c.item}은(는) 아직 판매처 가격 비교를 못 해요 (야채 · 과일만 돼요)`
      : c.message || `지금은 ${u}당 ${won(c.paid_per_unit)}보다 싼 곳을 못 찾았어요`;
    return `<p class="cs-empty">${esc(msg)}</p>`;
  }
  return `<p class="cs-head">산 값 <b>${u}당 ${won(c.paid_per_unit)}</b>보다 싼 곳 ${c.sellers.length}곳
      ${c.data_date ? `<small>${mmdd(c.data_date)} 가격</small>` : ""}</p>
    <ul class="cs-list">${c.sellers.map((s) => `<li>
      <a href="${esc(s.url)}" target="_blank" rel="noopener sponsored">
        <span class="cs-name">${esc(s.name)}${sellerTags(s)}</span>
        <span class="cs-pack">${esc(s.pack)} ${won(s.pack_price)}</span>
        <span class="cs-price">${u}당 ${s.approx ? "약 " : ""}<b>${won(s.price_per_unit)}</b>
          <em>${s.saving_pct != null ? `−${Math.round(s.saving_pct)}%` : ""}</em></span>
      </a></li>`).join("")}</ul>`;
}
async function toggleCheaper(btn) {
  const tr = btn.closest("tr"), open = btn.getAttribute("aria-expanded") === "true";
  tr.nextElementSibling?.classList.contains("rc-cheaper") && tr.nextElementSibling.remove();
  btn.setAttribute("aria-expanded", String(!open));
  if (open) return;
  const row = document.createElement("tr");
  row.className = "rc-cheaper";
  row.innerHTML = `<td colspan="6"><div class="cs-box"><p class="cs-empty">판매처 가격을 찾는 중이에요</p></div></td>`;
  tr.after(row);
  const box = row.querySelector(".cs-box");
  try {
    const paid = btn.dataset.paid ? `&paid=${btn.dataset.paid}` : "";
    box.innerHTML = cheaperHTML(await getJSON(`/api/cheaper?item=${encodeURIComponent(btn.dataset.item)}${paid}`));
  } catch (e) { box.innerHTML = `<p class="cs-empty">판매처 가격을 불러오지 못했어요</p>`; }
}

// 저장한 영수증 고치기: 왼쪽에 사진(있으면)을 띄워 두고 오른쪽 표에서 바로 고침
function editReceiptView(id, d) {
  $("#receiptModalBody").innerHTML = `<h3>영수증 고치기</h3>
    <p class="muted small">${d.source === "ocr" ? "영수증 읽기로 저장" : "기본 데이터"} · 사진과 비교하면서 틀린 곳을 고쳐 주세요</p>
    <div class="receipt-view rc-edit-view">${receiptPhoto(d)}<div id="rcModalEditor"></div></div>`;
  const data = {
    date: d.purchased_on, supplier: d.supplier, items_list: d.items_list,
    items: d.items.map((x) => ({ raw_name: x.raw_name, item_id: x.item_id, base_unit: x.unit, qty_base: x.qty_base, amount: x.amount })),
  };
  receiptEditor($("#rcModalEditor"), data, {
    thumb: false, badge: "저장한 내용 · 고치고 저장하면 원가율을 다시 계산해요", saveLabel: "고친 내용 저장",
    onCancel: () => showReceiptView(id, d),
    onSave: async (v) => {
      const r = await sendJSON(`/api/receipt/${id}`, "PUT", v);
      closeReceipt();
      $("#receiptResult").innerHTML = `<p class="ok">영수증을 고쳤어요 (${r.saved_items}줄). 위 메뉴별 원가율이 새로 계산됐어요.</p>`;
      renderCosts(r, true);
      loadCosts(false);
    },
  });
}
const closeReceipt = () => { $("#receiptModal").hidden = true; };
$("#receiptModalClose").onclick = closeReceipt;
$("#receiptModal").onclick = (e) => { if (e.target.id === "receiptModal") closeReceipt(); };

// ---------------------------------------------------------------
// 마이페이지: 로그인한 사장님 정보(/api/auth/me) · 나의 영수증 · 설정(알림 · 권한) · 계정
// ---------------------------------------------------------------
// 제목: "<가게 이름> 사장님의 가게" — 가게 이름만 굵게 (가게 이름이 없으면 "나의 가게" 그대로)
if (STORE_VIEW && readLogin()?.store) $("#storeName").innerHTML = `<b>${esc(readLogin().store)}</b> 사장님의 가게`;
// 휴대폰 번호는 가운데를 가려서 보여 줌 (01012345678 → 010-****-5678)
const maskPhone = (p) => (p && p.length >= 10 ? `${p.slice(0, 3)}-****-${p.slice(-4)}` : "");
// 마이페이지는 기억해 둔 정보로 바로 그리고 → 서버(/api/auth/me) 답이 오면 기억을 고치고 다시 그림 (빈 화면으로 기다리지 않게)
function cachedProfile() {
  const u = readLogin();
  return u?.profile || { name: u?.name, store_name: u?.store, provider: u?.provider, login_id: u?.provider === "kakao" ? null : u?.id };
}
async function freshProfile() {
  const u = readLogin();
  const me = await authCall("/api/auth/me", { method: "GET", token: u?.access_token });
  try { saveLogin({ ...u, profile: me, name: me.name, store: me.store_name }, !!localStorage.getItem(LOGIN_KEY)); } catch (e) {}
  return me;
}

function openMypage(view = "home") {
  if (!SIGNED_IN) return goLogin();   // 마이페이지는 로그인한 사장님만
  $("#mypage").classList.add("open");
  $("#mypage").setAttribute("aria-hidden", "false");
  $("#backdrop").hidden = false;
  renderMypage(view);
}
function closeMypage() {
  $("#mypage").classList.remove("open");
  $("#mypage").setAttribute("aria-hidden", "true");
  $("#backdrop").hidden = true;
}

async function renderMypage(view) {
  const box = $("#mypageBody");
  $("#mypageBack").hidden = view === "home";
  $("#mypageTitle").textContent = { home: "마이페이지", receipts: "나의 영수증", settings: "알림 설정" }[view];
  if (view === "receipts") {
    box.innerHTML = `<p class="muted">불러오는 중이에요</p>`;
    try {
      const { receipts } = await getJSON("/api/receipts");
      box.innerHTML = receipts.length ? `<ul class="my-receipts">${receipts.map((p) => `<li><button data-rid="${p.id}">
        <b>${mmdd(p.purchased_on)} · ${esc(supplierName(p.supplier))}</b>
        <span>${p.items}줄 · ${won(p.total_amount)}${p.source === "ocr" ? " · 영수증 읽기" : " · 기본 데이터"}</span><i>›</i></button></li>`).join("")}</ul>`
        : `<p class="muted">아직 저장한 영수증이 없어요.</p>`;
    } catch (e) { box.innerHTML = `<p class="rc-warn">${esc(e.message)}</p>`; }
    return;
  }
  if (view === "settings") {
    // 설정: 알림 설정 · 권한 설정
    const prefs = alertPrefs();
    box.innerHTML = `
    <section class="my-card">
      <h4>알림 설정</h4>
      <p class="muted small">켜 둔 알림은 살피가 챗봇 창으로 보내 드려요.</p>
      <label class="toggle-row">
        <span><b>내 메뉴 재료만</b><small>${myItems
          ? `내 메뉴에 들어가는 재료${(n => n ? ` ${n}가지` : "")(overview.filter((r) => myItems.has(r.item)).length)}만 알려 드려요`
          : "메뉴를 불러오지 못해 모든 농산물을 알려 드려요"}</small></span>
        <input type="checkbox" class="switch" data-pref="mine" ${prefs.mine ? "checked" : ""}></label>
      ${ALERT_TYPES.map(([k, title, desc]) => `<label class="toggle-row">
        <span><b>${title}</b><small>${desc}</small></span>
        <input type="checkbox" class="switch" data-pref="${k}" ${prefs[k] ? "checked" : ""}></label>`).join("")}
    </section>
    <section class="my-card" id="appCard">
      <h4>살피 앱</h4>
      <div id="appBody"><p class="muted small">확인하는 중이에요</p></div>
    </section>
    <section class="my-card" id="kakaoCard">
      <h4>카카오톡 시세 알림</h4>
      <p class="muted small">매일 아침 내 카카오톡 '나와의 채팅'으로 보내 드려요.</p>
      <ul class="my-bullets"><li>내 메뉴 재료의 다음 주 시세</li><li>원가율 40% 넘은 메뉴</li></ul>
      <div id="kakaoBody"><p class="muted small">확인하는 중이에요</p></div>
    </section>
    <section class="my-card" id="permCard">
      <h4>권한 설정</h4>
      <p class="muted small">영수증 찍기와 시세 알림에 필요한 권한이에요.</p>
      <div class="toggle-row"><span><b>카메라</b><small id="camState">확인하는 중</small></span><span id="camAct"></span></div>
      <div class="toggle-row"><span><b>브라우저 알림</b><small id="notiState">확인하는 중</small></span><span id="notiAct"></span></div>
    </section>`;
    showCameraPerm();
    showNotiPerm();
    showAppPush();
    showKakao();
    return;
  }
  const draw = (me, offline) => { if ($("#mypage").classList.contains("open") && $("#mypageTitle").textContent === "마이페이지") box.innerHTML = myHome(me, offline); };
  const cached = cachedProfile();
  prof = null; costEdit = false; costAdding = false; addSec = "fixed"; storeDraft = null; storeErr = ""; costFold = new Set(["fixed", "sale", "delivery"]);   // 처음 들어오면 비용 칸은 모두 접힌 채로
  draw(cached);
  freshProfile().then((me) => { if (JSON.stringify(me) !== JSON.stringify(cached)) draw(me); syncCosts(me); }).catch(() => draw(cached, true));
  loadReceiptMaterial();
}

function myHome(me, offline) {
  // 이름 아래 한 줄: 이메일 → 아이디 → 카카오 로그인 순서로 있는 것
  const loginId = me.login_id || (me.provider !== "kakao" ? readLogin()?.id : null);
  const how = me.email || (loginId ? `아이디 ${loginId}` : me.provider === "kakao" ? "카카오 로그인" : "");
  costMe = me;
  return `
    <section class="my-card profile${prof ? " editing" : ""}" id="myProfile">${profileCard(me, how)}</section>
    ${offline ? `<p class="muted small my-offline">서버에 연결하지 못해 기억해 둔 정보만 보여 드려요.</p>` : ""}
    <section class="my-card mc" id="myCost">${costCard()}</section>
    <section class="my-card">
      <button class="my-link" type="button" data-view="settings"><span>알림 설정 <small>· 권한</small></span><i>›</i></button>
    </section>
    <section class="my-card my-account">
      <button class="my-link" type="button" data-account="logout"><span>로그아웃</span><i>›</i></button>
      <button class="my-link danger" type="button" data-account="leave"><span>회원탈퇴</span><i>›</i></button>
    </section>`;
}

// ---------------------------------------------------------------
// 프로필 수정: 사장님 이름 · 사진 (아이디 · 카카오 로그인 모두 같음, 서버 /api/auth/profile)
// 사진은 화면에서 가운데를 정사각으로 잘라 512px JPEG 로 줄여 보냄
// ---------------------------------------------------------------
const OWNER_FACE = "/static/img/owner_face.png";
const CAMERA = `<svg viewBox="0 0 24 24"><path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>`;
let prof = null;   // 수정 중일 때만: { name, photo(새 사진 data URL), reset(원래 사진으로), saving, err }
const profHow = (me) => {
  const loginId = me.login_id || (me.provider !== "kakao" ? readLogin()?.id : null);
  return me.email || (loginId ? `아이디 ${loginId}` : me.provider === "kakao" ? "카카오 로그인" : "");
};
function profileCard(me, how = profHow(me)) {
  const face = (src) => `<img src="${esc(src || OWNER_FACE)}" alt="" referrerpolicy="no-referrer" onerror="this.src='${OWNER_FACE}'">`;
  if (!prof) return `${face(me.avatar)}
    <div class="pf-text"><b>${me.name ? `${esc(me.name)} 사장님` : "사장님"}</b>${how ? `<small>${esc(how)}</small>` : ""}</div>
    <button type="button" class="pf-edit" data-prof="edit" aria-label="이름 · 사진 수정">${PEN}<span>수정</span></button>`;
  const shown = prof.photo || (prof.reset ? me.base_avatar : me.avatar);   // 되돌리기: 카카오 사진(없으면 기본 그림)
  return `<label class="pf-photo" title="사진 바꾸기">${face(shown)}<span class="pf-cam" aria-hidden="true">${CAMERA}</span>
      <input type="file" accept="image/jpeg,image/png,image/webp" data-prof-photo aria-label="사진 바꾸기" class="sr-only"></label>
    <div class="pf-form">
      <div class="pf-head"><label class="pf-label" for="pfName">이름</label>
        <div class="pf-btns"><button type="button" class="pf-cancel" data-prof="cancel">취소</button>
        <button type="button" class="pf-save" data-prof="save" ${prof.saving ? "disabled" : ""}>${prof.saving ? "저장하는 중" : "저장"}</button></div></div>
      <input type="text" id="pfName" class="pf-input" data-prof-name maxlength="20" value="${esc(prof.name)}" placeholder="이름" autocomplete="name">
      ${me.custom_photo && !prof.reset && !prof.photo ? `<button type="button" class="pf-reset" data-prof="reset">${me.provider === "kakao" ? "카카오 사진으로 되돌리기" : "기본 사진으로 되돌리기"}</button>` : ""}
      ${prof.err ? `<p class="pf-err">${esc(prof.err)}</p>` : ""}
    </div>`;
}
const drawProfile = (focus) => {
  const box = $("#myProfile");
  if (!box || !costMe) return;
  box.classList.toggle("editing", !!prof);
  box.innerHTML = profileCard(costMe);
  if (focus) box.querySelector(focus)?.focus();
};
// 사진 → 가운데 정사각 512px JPEG (data URL)
async function squarePhoto(file) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => bad(new Error("사진을 열지 못했어요. 다른 사진으로 해 주세요.")); i.src = url; });
    const s = Math.min(img.naturalWidth, img.naturalHeight), out = Math.min(512, s);
    const c = Object.assign(document.createElement("canvas"), { width: out, height: out });
    c.getContext("2d").drawImage(img, (img.naturalWidth - s) / 2, (img.naturalHeight - s) / 2, s, s, 0, 0, out, out);
    return c.toDataURL("image/jpeg", 0.85);
  } finally { URL.revokeObjectURL(url); }
}
async function saveProfile() {
  if (prof.saving) return;
  if (!prof.name.trim()) { prof.err = "이름을 입력해 주세요."; return drawProfile("[data-prof-name]"); }
  prof.saving = true; prof.err = ""; drawProfile();
  try {
    const u = readLogin();
    const me = await authCall("/api/auth/profile", { method: "PATCH", token: u?.access_token,
      body: { name: prof.name.trim(), photo: prof.photo || "", reset_photo: !!prof.reset } });
    costMe = me; prof = null;
    try { saveLogin({ ...u, profile: me, name: me.name, store: me.store_name }, !!localStorage.getItem(LOGIN_KEY)); } catch (e) {}
    drawProfile();
  } catch (e) { prof.saving = false; prof.err = e.message; drawProfile(); }
}
function profClick(e) {
  const b = e.target.closest("[data-prof]");
  if (!b) return false;
  const act = b.dataset.prof;
  if (act === "edit") { prof = { name: costMe?.name || "", photo: null, reset: false, saving: false, err: "" }; drawProfile("[data-prof-name]"); }
  else if (act === "cancel") { prof = null; drawProfile(); }
  else if (act === "reset") { prof.reset = true; prof.photo = null; drawProfile(); }
  else if (act === "save") saveProfile();
  return true;
}
async function profPhoto(input) {
  const f = input.files?.[0];
  if (!f || !prof) return;
  try { prof.photo = await squarePhoto(f); prof.reset = false; prof.err = ""; }
  catch (err) { prof.err = err.message; }
  drawProfile();
}

// ---------------------------------------------------------------
// 내 정보 · 가게 비용: 고정 비용 · 판매 비용 · 배달 비용을 넣으면 "하루 얼마 팔아야 본전인지" 알려 줌
// 금액은 모두 '만 원' 단위로, 이 브라우저에 사장님별로 기억 + 계정에도 저장 (/api/store/costs)
// ---------------------------------------------------------------
const COST_KEY = () => { const u = readLogin(); return `salpi_costs_${u?.profile?.id || u?.id || "me"}`; };
const WEEK = ["월", "화", "수", "목", "금", "토", "일"];
const BIZ = ["한식", "중식", "일식", "양식", "분식", "치킨", "카페", "기타"];
const FIXED_BASE = [["rent", "임대료"], ["manage", "관리비"], ["staff", "인건비"], ["power", "전기료"], ["gas", "가스비"], ["water", "수도세"]];
// 비용 추가: 넣을 칸 → 그 칸에 맞는 추천 항목 (추가한 비용은 extra[{name, v, sec}] 에 칸 이름과 함께 기억, sec 없으면 고정 비용)
const ADD_SECS = [["fixed", "고정 비용"], ["sale", "판매 비용"], ["deliv", "배달"]];
const EXTRA_SUGGEST = {
  fixed: ["4대보험", "광고비", "세무 기장료", "대출 이자", "음식물 쓰레기"],
  sale: ["일회용품", "주방 소모품", "주류 · 음료", "할인 · 포인트"],
  deliv: ["배달앱 광고", "할인 쿠폰", "배달 대행 기본료"],
};
const extraSec = (x) => x.sec || "fixed";
let addSec = "fixed";   // 비용 추가하기에서 고른 칸
const DELIV = [["fee", "중개 수수료", ""], ["ride", "배달비", "사장님 부담"], ["pack", "포장 용기", ""]];
const COST_DEFAULT = { seats: null, closed: ["일"], sales: null, fixed: {}, extra: [], material: null, card: null, tax: "general", delivery: false, deliv: {} };
const PEN = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16v4z"/><path d="M13.5 6.5l4 4"/></svg>`;
let costEdit = false, costAdding = false, costMe = null, receiptMaterial = null;   // costEdit: '수정'을 눌러 모든 칸이 입력칸인지
let costFold = new Set();
// 가게 이름 · 구: 서버(계정)에 저장 → '수정' 동안 고친 값을 들고 있다가 '완료'에서 바뀐 것만 보냄
const DAEGU_GU = ["중구", "동구", "서구", "남구", "북구", "수성구", "달서구", "달성군", "군위군"];
let storeDraft = null, storeErr = "", storeSaving = false;
const storeChanged = () => storeDraft && costMe && (storeDraft.store.trim() !== (costMe.store_name || "") || storeDraft.district !== (costMe.district || ""));
async function saveStore() {
  if (storeSaving) return;
  if (!storeDraft.store.trim()) { storeErr = "가게 이름을 입력해 주세요."; return drawCost(".mc-store"); }
  if (!storeDraft.district) { storeErr = "가게가 있는 구 · 군을 골라 주세요."; return drawCost('[data-sf="district"]'); }
  storeSaving = true;
  const btn = $("#myCost [data-cdone]");
  if (btn) { btn.disabled = true; btn.textContent = "저장하는 중"; }
  try {
    const u = readLogin();
    const me = await authCall("/api/auth/me", { method: "PATCH", token: u?.access_token, body: { store: storeDraft.store.trim(), district: storeDraft.district } });
    costMe = me; storeErr = "";
    try { saveLogin({ ...u, profile: me, name: me.name, store: me.store_name }, !!localStorage.getItem(LOGIN_KEY)); } catch (e) {}
    if ($("#storeName")) $("#storeName").innerHTML = `<b>${esc(me.store_name)}</b> 사장님의 가게`;
    storeSaving = false;
    if (btn) btn.disabled = false;   // 꺼진 버튼은 click()이 무시되므로 다시 켠 뒤 누름
    $("#myCost [data-cdone]")?.click();   // 저장됐으니 원래 '완료' 그대로 이어서
  } catch (e) {
    storeSaving = false; storeErr = e.message;
    drawCost(".mc-store");
  }
}

function costs() {
  const c = { ...COST_DEFAULT, ...load(COST_KEY(), {}) };
  return { ...c, fixed: { ...c.fixed }, deliv: { ...c.deliv }, extra: [...c.extra], closed: [...c.closed] };
}
// 이 브라우저에 바로 기억하고 → 0.8초 동안 더 안 바뀌면 서버(계정)에도 저장 (다른 기기 · 앱에서도 같은 값)
let costPush = null;
function saveCosts(c) {
  store(COST_KEY(), c);
  clearTimeout(costPush);
  costPush = setTimeout(() => pushCosts(c), 800);
}
async function pushCosts(c) {
  const u = readLogin();
  if (!u?.access_token) return;
  try { await authCall("/api/store/costs", { method: "PUT", token: u.access_token, body: { costs: c } }); }
  catch (e) { /* 저장 실패해도 이 브라우저에는 남아 있음 → 다음에 바꿀 때 다시 보냄 */ }
}
// 서버(계정)에 저장된 비용 → 이 브라우저 기억을 바꿈. 서버에 아직 없으면(예전 사장님) 이 브라우저 값을 올려 둠
function syncCosts(me) {
  if (!me) return;
  if (me.costs) {
    if (costEdit) return;   // 고치는 중이면 덮어쓰지 않음
    // 서버는 칸 순서를 바꿔 돌려줌 → 순서를 맞춰 비교 (같으면 다시 그리지 않음)
    const canon = (v) => JSON.stringify(v, (k, x) => (x && typeof x === "object" && !Array.isArray(x) ? Object.fromEntries(Object.entries(x).sort()) : x));
    if (canon({ ...COST_DEFAULT, ...load(COST_KEY(), {}) }) !== canon({ ...COST_DEFAULT, ...me.costs })) { store(COST_KEY(), me.costs); drawCost(); }
  } else if (load(COST_KEY(), null)) pushCosts(costs());
}
function setCost(path, raw) {
  const c = costs(), p = path.split(".");
  let o = c;
  for (const k of p.slice(0, -1)) o = o[k];
  o[p.at(-1)] = p.at(-1) === "name" ? raw : raw === "" ? null : Math.max(0, +raw);
  saveCosts(c);
}
// 만 원 → 보기 좋게 (100만 원 넘으면 소수점 없이, 1만 원 안 되면 원으로)
function man(v) {
  if (v == null || isNaN(v)) return "—";
  if (v > 0 && v < 1) return `${Math.round(v * 10000).toLocaleString("ko-KR")}원`;
  return `${(v >= 100 ? Math.round(v) : Math.round(v * 10) / 10).toLocaleString("ko-KR")}만 원`;
}

// 본전 계산: 넣은 비용을 모두 내고 남는 한 달 매출 S 를 거꾸로 구함 (매출은 묻지 않음)
//   S = 고정 + 재료비 + 배달 비용 + 카드 수수료(S) + 부가세(S)
//   카드 수수료 어림 = S × 1.2% (카드 결제 80% × 수수료 1.5%) — 직접 넣으면 그 금액
//   부가세 어림 = 일반 과세자 (S − 재료비) ÷ 11 · 간이 과세자 S × 1.5% (음식점 부가가치율 15% × 10%)
//   하루 본전 = S ÷ 한 달 영업일
function costCalc(c) {
  const n = (v) => +v || 0;
  const ex = (sec) => c.extra.filter((x) => extraSec(x) === sec).reduce((s, x) => s + n(x.v), 0);
  const fixed = FIXED_BASE.reduce((s, [k]) => s + n(c.fixed[k]), 0) + ex("fixed");
  const material = c.material == null ? n(receiptMaterial) : n(c.material);
  const saleEx = ex("sale");
  const deliv = c.delivery ? DELIV.reduce((s, [k]) => s + n(c.deliv[k]), 0) + ex("deliv") : 0;
  const cardRate = c.card == null ? 0.012 : 0;
  const base = fixed + material + saleEx + deliv + (c.card == null ? 0 : n(c.card));
  const S = !base ? 0 : c.tax === "simple" ? base / (1 - cardRate - 0.015) : (base - material / 11) / (1 - cardRate - 1 / 11);
  const card = c.card == null ? S * cardRate : n(c.card);
  const vat = c.tax === "simple" ? S * 0.015 : Math.max(0, S - material) / 11;
  const days = Math.round(30.4 * (7 - c.closed.length) / 7);
  return { fixed, material, card, vat, deliv, sale: material + saleEx + card + vat, days, monthly: S, be: days && S ? S / days : null };
}

function costBanner(k) {
  if (!k.days) return `<div class="mc-be loss"><b>쉬는 요일을 확인해 주세요</b><small>영업하는 날이 하루도 없어요</small></div>`;
  if (!k.be) return `<div class="mc-be empty"><b>비용을 넣어 주세요</b><small>하루에 얼마를 팔아야 본전인지 알려 드려요</small></div>`;
  return `<div class="mc-be"><b>하루 <em>${man(k.be)}</em> 넘게 팔면 본전이에요</b>
    <small>한 달 ${k.days}일 영업 기준</small></div>`;
}

const numIn = (path, v, label, ph = "0", unit = "만 원") => `<span class="mc-in"><input type="number" inputmode="decimal" min="0" step="any"
  data-k="${path}" value="${v ?? ""}" placeholder="${esc(ph)}" aria-label="${esc(label)}"><i>${unit}</i></span>`;
// 보기 화면: 금액을 넣은 줄만 진하게, 안 넣은 줄은 흐리게 (off)
const mcRow = (label, value, tag = "", off = false) => `<div class="mc-row${off ? " off" : ""}"><span class="mc-label">${label}${tag}</span>${value}</div>`;
const mcVal = (v, pre = "") => (v ? `<span class="v">${pre}${man(v)}</span>` : `<span class="v none">—</span>`);
// 보기 화면: 금액이 있는 줄만 보여 줌 (안 넣은 줄은 아예 숨김)
const mcShow = (label, v, tag = "", pre = "") => (v ? mcRow(label, mcVal(v, pre), tag) : "");
const mcTag = (t, auto) => `<em class="mc-tag${auto ? " auto" : ""}">${t}</em>`;
const CHEV = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 15l6-6 6 6"/></svg>`;
const PLUS = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>`;
const DELIV_LABEL = (label, sub) => `${label}${sub ? ` <small>(${sub})</small>` : ""}`;

// 칸에 보이는 줄(금액이 있는 줄)이 하나라도 있나 — 영수증 자동 재료비 · 어림값도 금액이 있으면 포함
function costFilled(c, key) {
  const k = costCalc(c);
  if (key === "fixed") return k.fixed > 0;
  if (key === "sale") return k.sale > 0;
  return c.delivery && (k.deliv > 0 || +c.deliv.sales > 0);
}

// 칸 하나 (제목 · 합계 · 접기 꺾쇠). 제목 줄 어디를 눌러도 접히고 펼쳐짐
// 넣은 금액이 없는 칸은 보기 화면에서 흐리게 (empty)
function mcSection(key, title, total, body, extra = "") {
  const open = !costFold.has(key);
  const empty = !costEdit && !costFilled(costs(), key);
  return `<div class="mc-sec${open ? "" : " folded"}${empty ? " empty" : ""}">
    <div class="mc-sec-head" data-fold="${key}">
      <h5>${title}</h5>${extra}
      ${total == null ? "" : `<span class="mc-total" data-total="${key}">${man(total)}</span>`}
      ${body ? `<button class="mc-chev" type="button" data-fold="${key}" aria-expanded="${open}" aria-label="${title} ${open ? "접기" : "펼치기"}">${CHEV}</button>` : ""}
    </div>
    ${body && open ? `<div class="mc-box">${body}</div>` : ""}
  </div>`;
}

function costCard() {
  const me = costMe || {}, c = costs(), k = costCalc(c), ed = costEdit;
  const place = ["대구", me.district, me.place].filter(Boolean).join(" ");
  const biz = c.biz || me.business_type;   // 고친 업종은 이 기기에 기억 (가입할 때 업종이 기본)
  const none = (t) => `<span class="none">${t}</span>`;

  const info = `<dl class="mc-info">
      <dt>가게 이름</dt><dd>${ed && storeDraft
        ? `<input class="mc-name mc-store" type="text" data-sf="store" maxlength="40" value="${esc(storeDraft.store)}" placeholder="예: 서문골 손칼국수" aria-label="가게 이름">`
        : esc(me.store_name || "아직 없어요")}</dd>
      <dt>지역</dt><dd>${ed && storeDraft
        ? `<span class="mc-gu"><span>대구</span><select class="mc-name" data-sf="district" aria-label="구 · 군">
            ${storeDraft.district ? "" : `<option value="">구 · 군 선택</option>`}
            ${DAEGU_GU.map((g) => `<option${g === storeDraft.district ? " selected" : ""}>${g}</option>`).join("")}</select></span>`
        : esc(place)}</dd>
      ${ed && storeErr ? `<dd class="mc-err" role="alert">${esc(storeErr)}</dd>` : ""}
      <dt>업종</dt><dd>${ed
        ? `<div class="mc-pick">${BIZ.map((b) => `<button type="button" data-biz="${b}" aria-pressed="${b === biz}">${b}</button>`).join("")}</div>`
        : biz ? esc(biz) : none("수정에서 골라 주세요")}</dd>
      <dt>좌석</dt><dd>${ed ? numIn("seats", c.seats, "좌석 수", "0", "석") : c.seats ? `${c.seats}석` : none("수정에서 넣어 주세요")}</dd>
      <dt>쉬는 요일</dt><dd>${ed
        ? `<div class="mc-days">${WEEK.map((d) => `<button type="button" data-day="${d}" aria-pressed="${c.closed.includes(d)}">${d}</button>`).join("")}</div>`
        : c.closed.length ? WEEK.filter((d) => c.closed.includes(d)).map((d) => `${d}요일`).join(", ") : "없어요"}</dd>
      ${me.phone ? `<dt>휴대폰</dt><dd>${esc(maskPhone(me.phone))}</dd>` : ""}
    </dl>`;

  // 추가한 비용 줄 (칸별로). i 는 extra 전체에서의 순서
  const extraRows = (sec) => c.extra.map((x, i) => [x, i]).filter(([x]) => extraSec(x) === sec).map(([x, i]) => ed
    ? `<div class="mc-row"><span class="mc-label"><input class="mc-name" type="text" data-k="extra.${i}.name" value="${esc(x.name)}" placeholder="비용 이름" aria-label="비용 이름"></span>
        <span class="mc-row-end">${numIn(`extra.${i}.v`, x.v, x.name || "비용")}<button class="mc-del" type="button" data-xdel="${i}" aria-label="${esc(x.name || "비용")} 지우기">×</button></span></div>`
    : mcShow(esc(x.name || "기타"), x.v)).join("");

  // 고정 비용
  const fixedRows = (ed
    ? FIXED_BASE.map(([key, label]) => mcRow(label, numIn(`fixed.${key}`, c.fixed[key], label))).join("")
    : FIXED_BASE.map(([key, label]) => mcShow(label, c.fixed[key])).join("")) + extraRows("fixed");

  // 판매 비용 (부가세 줄 안에 작은 일반 · 간이 전환)
  const matAuto = c.material == null && receiptMaterial != null;
  const taxSeg = `<span class="mc-seg" role="group" aria-label="과세 유형">
      <button type="button" data-tax="general" aria-pressed="${c.tax !== "simple"}">일반</button><button type="button" data-tax="simple" aria-pressed="${c.tax === "simple"}">간이</button></span>`;
  const saleRows = (ed
    ? mcRow("재료비", numIn("material", c.material, "재료비", receiptMaterial != null ? `자동 ${Math.round(receiptMaterial)}` : "0"))
      + mcRow("카드 수수료", numIn("card", c.card, "카드 수수료", k.card ? `어림 ${Math.round(k.card)}` : "0"))
    : mcShow("재료비", k.material, matAuto ? mcTag("자동", true) : "")
      + mcShow("카드 수수료", k.card, c.card == null ? mcTag("어림값") : ""))
    + (ed || k.vat ? mcRow("부가세", mcVal(k.vat, "약 "), taxSeg) : "") + extraRows("sale");

  // 배달
  const delivRows = c.delivery ? (ed
    ? mcRow("배달 매출", numIn("deliv.sales", c.deliv.sales, "배달 매출")) + DELIV.map(([key, label, sub]) => mcRow(DELIV_LABEL(label, sub), numIn(`deliv.${key}`, c.deliv[key], label))).join("")
    : mcShow("배달 매출", c.deliv.sales) + DELIV.map(([key, label, sub]) => mcShow(DELIV_LABEL(label, sub), c.deliv[key])).join("")) + extraRows("deliv") : "";
  const delivSwitch = `<span class="mc-switch${c.delivery ? " on" : ""}" role="group" aria-label="배달 여부">
    <button type="button" data-deliv="0" aria-pressed="${!c.delivery}">안 해요</button><button type="button" data-deliv="1" aria-pressed="${c.delivery}">해요</button></span>`;

  // 비용 추가하기: [고정 비용 | 판매 비용 | 배달] 중 넣을 칸 → 그 칸 추천 항목 + 직접 입력
  const added = new Set(c.extra.filter((x) => extraSec(x) === addSec).map((x) => x.name));
  const chips = EXTRA_SUGGEST[addSec].filter((n) => !added.has(n));
  const addBox = `<div class="mc-addbox">
      <div class="mc-addto"><span>어디에 넣을까요?</span>
        <span class="mc-seg" role="group" aria-label="비용을 넣을 칸">${ADD_SECS.map(([key, label]) =>
          `<button type="button" data-addsec="${key}" aria-pressed="${key === addSec}">${label}</button>`).join("")}</span></div>
      <div class="mc-chips">${chips.map((n) => `<button type="button" data-xadd="${esc(n)}">${esc(n)}</button>`).join("")}<button type="button" data-xadd="">직접 입력</button></div>    </div>`;

  return `
    <div class="mc-head"><h4>내 정보</h4>
      ${ed ? "" : `<button class="mc-edit" type="button" data-cedit>${PEN}<span>수정</span></button>`}</div>
    ${info}
    ${costBanner(k)}
    ${mcSection("fixed", "고정 비용", k.fixed, fixedRows)}
    ${mcSection("sale", "판매 비용", k.sale, saleRows)}
    ${mcSection("delivery", "배달", c.delivery ? k.deliv : null, delivRows, delivSwitch)}
    <button class="mc-add" type="button" data-cadd aria-expanded="${costAdding}">${PLUS}<span>비용 추가하기</span></button>
    ${costAdding ? addBox : ""}
    ${ed ? `<button class="mc-done wide" type="button" data-cdone>완료</button>` : ""}`;
}

function drawCost(focusSel) {
  const el = $("#myCost");
  if (!el) return;
  el.innerHTML = costCard();
  const f = focusSel && el.querySelector(focusSel);
  if (f) f.focus();
}

// 재료비 자동: 최근 30일 영수증 합계 (원 → 만 원)
async function loadReceiptMaterial() {
  try {
    const { receipts } = await getJSON("/api/receipts");
    const since = new Date(Date.now() - 30 * 864e5).toISOString().slice(0, 10);
    const recent = receipts.filter((p) => p.purchased_on >= since);
    receiptMaterial = recent.length ? recent.reduce((s, p) => s + (+p.total_amount || 0), 0) / 10000 : null;
  } catch (e) { receiptMaterial = null; }
  if (!costEdit) drawCost();
}

function costClick(e) {
  const t = e.target.closest("[data-cedit],[data-cdone],[data-day],[data-biz],[data-tax],[data-deliv],[data-cadd],[data-addsec],[data-xadd],[data-xdel],[data-fold]");
  if (!t || !t.closest("#myCost")) return false;
  const c = costs(), d = t.dataset;
  let focus;
  if ("cedit" in d) {
    costEdit = true; costFold.clear(); focus = '[data-k="seats"]';
    storeDraft = { store: costMe?.store_name || "", district: costMe?.district || "" }; storeErr = "";
  }
  else if ("cdone" in d) {
    if (storeChanged()) { saveStore(); return true; }   // 가게 이름 · 구가 바뀌었으면 서버에 먼저 저장
    costEdit = false; storeDraft = null; storeErr = "";
    c.extra = c.extra.filter((x) => x.name || x.v);   // 이름 · 금액 둘 다 빈 줄은 정리
    for (const key of ["fixed", "sale", "delivery"]) costFilled(c, key) ? costFold.delete(key) : costFold.add(key);   // 넣은 게 없는 칸은 접어 둠
    focus = "[data-cedit]";
  }
  else if (d.fold) { costFold.has(d.fold) ? costFold.delete(d.fold) : costFold.add(d.fold); focus = `.mc-chev[data-fold="${d.fold}"]`; }
  else if (d.biz) { c.biz = d.biz; focus = `[data-biz="${d.biz}"]`; }
  else if (d.day) { c.closed = c.closed.includes(d.day) ? c.closed.filter((x) => x !== d.day) : [...c.closed, d.day]; focus = `[data-day="${d.day}"]`; }
  else if (d.tax) { c.tax = d.tax; focus = `[data-tax="${d.tax}"]`; }
  else if (d.deliv) {
    c.delivery = d.deliv === "1";
    costFold.delete("delivery");
    if (c.delivery && !Object.values(c.deliv).some(Boolean)) { costEdit = true; focus = '[data-k="deliv.sales"]'; }   // 처음 켜면 바로 입력
    else focus = `[data-deliv="${d.deliv}"]`;
  }
  else if ("cadd" in d) { costAdding = !costAdding; focus = "[data-cadd]"; }
  else if (d.addsec) { addSec = d.addsec; focus = `[data-addsec="${d.addsec}"]`; }
  else if (d.xadd != null) {
    c.extra.push({ name: d.xadd, v: null, sec: addSec });
    if (addSec === "deliv") c.delivery = true;   // 배달 칸에 넣으면 배달을 켬
    costEdit = true; costAdding = false; costFold.delete({ fixed: "fixed", sale: "sale", deliv: "delivery" }[addSec]);
    const i = c.extra.length - 1;
    focus = d.xadd ? `[data-k="extra.${i}.v"]` : `[data-k="extra.${i}.name"]`;
  }
  else if (d.xdel) c.extra.splice(+d.xdel, 1);
  saveCosts(c);
  drawCost(focus);
  return true;
}

// ---------------------------------------------------------------
// 설치형 앱 (PWA): 백그라운드 작업 등록 · "앱 설치" 버튼 · 앱 알림 켜기
// ---------------------------------------------------------------
let installPrompt = null;
const IS_APP = matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;   // 홈 화면 앱으로 열었나
const IS_IOS = /iphone|ipad|ipod/i.test(navigator.userAgent);
if ("serviceWorker" in navigator) addEventListener("load", () => navigator.serviceWorker.register("/sw.js").catch(() => {}));
addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); installPrompt = e; if ($("#appBody")) showAppPush(); });
addEventListener("appinstalled", () => { installPrompt = null; if ($("#appBody")) showAppPush(); });

const b64ToBytes = (s) => {
  const raw = atob((s + "=".repeat((4 - (s.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
};
async function mySub() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) return null;
  const reg = await navigator.serviceWorker.getRegistration("/");
  return reg ? reg.pushManager.getSubscription() : null;
}

// 마이페이지 › 설정 › "살피 앱 · 알림"
async function showAppPush() {
  const box = $("#appBody"), token = readLogin()?.access_token;
  if (!box) return;
  const install = IS_APP ? `<div class="toggle-row"><span><b>살피 앱</b><small>홈 화면 앱으로 쓰고 있어요</small></span><span class="perm-on">설치됨</span></div>`
    : installPrompt ? `<div class="toggle-row"><span><b>앱 설치</b><small>살피를 휴대폰에 앱으로 설치해요</small></span>
        <button class="btn primary" id="appInstall" type="button">앱 설치</button></div>`
    : IS_IOS ? `<div class="toggle-row"><span><b>앱 설치 (아이폰)</b><small>Safari 아래 공유 버튼 → "홈 화면에 추가" → 그 앱에서 알림을 켜 주세요</small></span></div>`
    : `<div class="toggle-row"><span><b>앱 설치</b><small>크롬 메뉴(⋮) → "앱 설치" 또는 "홈 화면에 추가"</small></span></div>`;
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
    box.innerHTML = install + `<p class="muted small">${IS_IOS && !IS_APP ? "아이폰은 홈 화면에 추가한 살피 앱에서만 알림을 켤 수 있어요." : "이 브라우저는 앱 알림을 쓸 수 없어요."}</p>`;
    return;
  }
  let st;
  try { st = await authCall("/api/push/status", { method: "GET", token }); }
  catch (e) { box.innerHTML = install + `<p class="muted small">${esc(e.message)}</p>`; return; }
  const sub = await mySub().catch(() => null);
  const on = !!sub && Notification.permission === "granted";
  box.innerHTML = install + (on ? `
    <div class="toggle-row"><span><b>앱 알림 켜짐</b><small>${st.last_sent ? `마지막 알림 ${esc(st.last_sent.replace("T", " "))}` : "매일 아침 시세 알림이 이 기기로 와요"}${st.devices > 1 ? ` · 기기 ${st.devices}대` : ""}</small></span>
      <button class="btn" id="pushOff" type="button">끄기</button></div>
    <div class="toggle-row"><span><b>지금 보내 보기</b><small id="pushMsg">이 계정의 기기로 지금 알림을 보내요</small></span>
      <button class="btn" id="pushTest" type="button">보내기</button></div>`
    : Notification.permission === "denied"
      ? `<p class="rc-warn">알림이 막혀 있어요. 휴대폰 설정 → 앱(또는 크롬) → 살피 → 알림을 허용해 주세요.</p>`
      : `<div class="toggle-row"><span><b>앱 알림</b><small>매일 아침 시세 알림을 휴대폰 알림으로 받아요.</small></span>
          <button class="btn primary" id="pushOn" type="button" ${st.ready ? "" : "disabled"}>알림 켜기</button></div>`);
  if ($("#appInstall")) $("#appInstall").onclick = async () => { installPrompt.prompt(); await installPrompt.userChoice; installPrompt = null; showAppPush(); };
  if ($("#pushOn")) $("#pushOn").onclick = async () => {
    try {
      if ((await Notification.requestPermission()) !== "granted") return showAppPush();
      const reg = await navigator.serviceWorker.register("/sw.js");
      await navigator.serviceWorker.ready;
      const s = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToBytes(st.public_key) });
      await authCall("/api/push/subscribe", { token, body: s.toJSON() });
      showAppPush();
    } catch (e) { box.insertAdjacentHTML("beforeend", `<p class="rc-warn">앱 알림을 켜지 못했어요: ${esc(e.message)}</p>`); }
  };
  if ($("#pushOff")) $("#pushOff").onclick = async () => {
    try { await authCall("/api/push/unsubscribe", { token, body: { endpoint: sub.endpoint } }); await sub.unsubscribe(); } catch (e) {}
    showAppPush();
  };
  if ($("#pushTest")) $("#pushTest").onclick = async () => {
    const msg = $("#pushMsg");
    msg.textContent = "보내는 중이에요";
    try { const r = await authCall("/api/push/test", { token }); msg.textContent = `보냈어요 (기기 ${r.sent}대). 휴대폰 알림을 확인해 주세요`; }
    catch (e) { msg.textContent = e.message; }
  };
}

// 카카오톡 시세 알림: 카카오 로그인 + '카카오톡 메시지 전송' 동의가 있으면 켜기 · 끄기 · 지금 보내 보기
async function showKakao() {
  const box = $("#kakaoBody"), token = readLogin()?.access_token;
  if (!box) return;
  let st;
  try { st = await authCall("/api/kakao/status", { method: "GET", token }); }
  catch (e) { box.innerHTML = `<p class="muted small">${esc(e.message)}</p>`; return; }
  // 카카오에서 돌아온 결과 (/api/kakao/callback → ?kakao=ok · kakao_err=이유) — 한 번만 보여 줌
  let done = "", err = "";
  try { done = sessionStorage.getItem("salpi_kakao_ok") || ""; err = sessionStorage.getItem("salpi_kakao_err") || "";
        sessionStorage.removeItem("salpi_kakao_ok"); sessionStorage.removeItem("salpi_kakao_err"); } catch (e) {}
  if (!st.connected) {
    // 아이디로 가입한 사장님도 됨: 살피 로그인은 그대로, 카카오톡 권한만 붙임
    box.innerHTML = `<div class="toggle-row"><span><b>아직 연결 전</b><small>카카오톡 연결 후 동의하면 받아요.</small></span>
      <button class="btn primary" id="kakaoLink" type="button" ${st.ready ? "" : "disabled"}>카카오톡 연결</button></div>
      ${err ? `<p class="rc-warn">연결하지 못했어요: ${esc(err)}</p>` : ""}`;
    $("#kakaoLink").onclick = async () => {
      try { location.assign((await authCall("/api/kakao/link", { token })).url); }
      catch (e) { box.insertAdjacentHTML("beforeend", `<p class="rc-warn">${esc(e.message)}</p>`); }
    };
    return;
  }
  box.innerHTML = `${done ? `<p class="ok">카카오톡과 연결했어요. '지금 보내 보기'로 확인해 보세요</p>` : ""}
    <label class="toggle-row"><span><b>매일 아침 받기</b><small>${st.last_sent ? `마지막으로 보낸 때 ${esc(st.last_sent.replace("T", " "))}` : "아직 보낸 적 없어요"}${st.last_error ? ` · 지난번 실패: ${esc(st.last_error)}` : ""}</small></span>
      <input type="checkbox" class="switch" id="kakaoOn" ${st.on ? "checked" : ""}></label>
    <div class="toggle-row"><span><b>지금 보내 보기</b><small id="kakaoTestMsg">내 카톡으로 지금 시세 알림을 보내요</small></span>
      <button class="btn" id="kakaoTest" type="button" ${st.ready ? "" : "disabled"}>보내기</button></div>
    <div class="toggle-row"><span><b>연결 끊기</b><small>카카오톡 알림을 그만 받고 저장한 카카오 권한을 지워요</small></span>
      <button class="btn" id="kakaoUnlink" type="button">끊기</button></div>`;
  $("#kakaoOn").onchange = async (e) => {
    try { await authCall("/api/kakao/on", { token, body: { on: e.target.checked } }); } catch (err) { e.target.checked = !e.target.checked; }
  };
  $("#kakaoTest").onclick = async () => {
    const msg = $("#kakaoTestMsg");
    msg.textContent = "보내는 중이에요";
    try { await authCall("/api/kakao/test", { token }); await showKakao(); $("#kakaoTestMsg").textContent = "보냈어요. 카카오톡 '나와의 채팅'을 확인해 주세요 (카톡 정책상 알림은 울리지 않아요)"; }
    catch (e) { msg.textContent = e.message; }
  };
  $("#kakaoUnlink").onclick = async () => {
    try { await authCall("/api/kakao/unlink", { token }); showKakao(); } catch (e) { $("#kakaoTestMsg").textContent = e.message; }
  };
}

// 브라우저 알림 권한: 허용하면 새 시세 알림을 화면 밖(작업 표시줄 · 휴대폰 알림)으로도 띄움
function showNotiPerm() {
  if (!$("#notiState")) return;
  const state = "Notification" in window ? Notification.permission : "none";   // granted · denied · default
  $("#notiState").textContent = { granted: "허용됨 · 새 시세 알림을 바로 띄워 드려요", denied: "꺼져 있어요 · 브라우저 주소창 왼쪽 자물쇠에서 켜 주세요",
    default: "아직 허용하지 않았어요", none: "이 브라우저는 알림을 쓸 수 없어요" }[state];
  $("#notiAct").innerHTML = state === "granted" ? `<span class="perm-on">허용됨</span>`
    : state === "default" ? `<button class="btn primary" id="notiAllow" type="button">허용하기</button>` : "";
  const b = $("#notiAllow");
  if (b) b.onclick = async () => { await Notification.requestPermission(); showNotiPerm(); notifyAlerts(); };
}

// 카메라 권한 상태: 허용됨 · 꺼짐 · 아직 안 물어봄 (브라우저가 알려 주지 않으면 '허용하기'로 직접 물어봄)
async function cameraPerm() {
  try { return (await navigator.permissions.query({ name: "camera" })).state; } catch (e) { return "prompt"; }
}
async function showCameraPerm() {
  const state = navigator.mediaDevices?.getUserMedia ? await cameraPerm() : "none";
  if (!$("#camState")) return;
  $("#camState").textContent = { granted: "허용됨 · 영수증을 바로 찍을 수 있어요", denied: "꺼져 있어요 · 아래 방법으로 켜 주세요",
    prompt: "아직 허용하지 않았어요", none: "이 브라우저는 카메라를 쓸 수 없어요" }[state];
  $("#camAct").innerHTML = state === "granted" ? `<span class="perm-on">허용됨</span>`
    : state === "prompt" ? `<button class="btn primary" id="camAllow" type="button">허용하기</button>` : "";
  $("#permCard .cam-guide")?.remove();
  if (state === "denied") $("#permCard").insertAdjacentHTML("beforeend", CAM_GUIDE);
  const b = $("#camAllow");
  if (b) b.onclick = async () => {
    try { (await askCamera()).getTracks().forEach((t) => t.stop()); } catch (e) {}
    showCameraPerm();
  };
}

$("#meBtn").onclick = () => openMypage();
$("#mypageClose").onclick = closeMypage;
$("#mypageBack").onclick = () => renderMypage("home");
$("#backdrop").onclick = closeMypage;
$("#mypageBody").onclick = (e) => {
  if (profClick(e)) return;
  if (costClick(e)) return;
  const acc = e.target.closest("[data-account]");
  if (acc?.dataset.account === "logout") return logout();
  if (acc?.dataset.account === "leave") return openLeave();
  const v = e.target.closest("[data-view]");
  if (v) return renderMypage(v.dataset.view);
  const r = e.target.closest("[data-rid]");
  if (r) openReceipt(r.dataset.rid);
};
// 비용 칸: 치는 대로 기억하고, 본전 요약 · 칸별 합계만 바로 고침 (입력칸은 다시 그리지 않아 커서가 그대로)
$("#mypageBody").oninput = (e) => {
  if (e.target.matches("[data-prof-name]") && prof) { prof.name = e.target.value; return; }
  const sf = e.target.dataset.sf;
  if (sf && storeDraft) { storeDraft[sf] = e.target.value; return; }   // 가게 이름 · 구는 '완료' 때 서버에 저장
  const p = e.target.dataset.k;
  if (!p) return;
  setCost(p, e.target.value);
  const k = costCalc(costs()), be = $("#myCost .mc-be");
  if (be) be.outerHTML = costBanner(k);
  for (const [key, v] of [["fixed", k.fixed], ["sale", k.sale], ["delivery", k.deliv]]) { const t = $(`#myCost [data-total="${key}"]`); if (t) t.textContent = man(v); }
};
$("#mypageBody").addEventListener("keydown", (e) => {   // 비용 칸에서 Enter = 다 했어요
  if (e.key === "Enter" && e.target.matches("[data-prof-name]")) { e.preventDefault(); return saveProfile(); }   // 이름 칸 Enter = 저장
  if (e.key === "Enter" && (e.target.dataset.k || e.target.dataset.sf === "store")) { e.preventDefault(); $("#myCost [data-cdone]")?.click(); }
});
$("#mypageBody").onchange = (e) => {
  if (e.target.matches("[data-prof-photo]")) return profPhoto(e.target);
  const k = e.target.dataset.pref;
  if (!k) return;
  const prefs = alertPrefs();
  prefs[k] = e.target.checked;
  store(ALERT_PREFS_KEY, prefs);
  deliverAlerts();
};
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (!$("#leaveModal").hidden) return closeLeave();   // 탈퇴 팝업만 닫고 마이페이지는 그대로
  closeReceipt(); closeMypage(); closeEvent(); closeCamera(); closeStock();
});

// 회원탈퇴: 한 번 더 묻는 팝업 → '안내를 확인했어요'에 체크해야 [탈퇴하기]가 눌림
// 탈퇴하면 서버에서 계정 · 가게 · 메뉴 · 영수증(사진 포함)을 지우고, 이 브라우저의 로그인 상태 · 알림 설정도 지우고 첫 화면으로
function openLeave() {
  $("#leaveAgree").checked = false;
  $("#leaveOk").disabled = true;
  $("#leaveModal").hidden = false;
  $("#leaveCancel").focus();
}
function closeLeave() { $("#leaveModal").hidden = true; }
$("#leaveAgree").onchange = () => { $("#leaveOk").disabled = !$("#leaveAgree").checked; };
$("#leaveCancel").onclick = closeLeave;
$("#leaveModal").onclick = (e) => { if (e.target === e.currentTarget) closeLeave(); };   // 바깥을 누르면 취소
$("#leaveOk").onclick = async () => {
  const btn = $("#leaveOk"), label = btn.textContent;
  btn.disabled = true;
  try {
    await authCall("/api/auth/me", { method: "DELETE", token: readLogin()?.access_token });
  } catch (err) {
    btn.textContent = "탈퇴하지 못했어요 · 다시 누르기";
    btn.disabled = false;
    return;
  }
  try {
    [ALERT_PREFS_KEY, ALERT_READ_KEY].forEach((k) => localStorage.removeItem(k));
    sessionStorage.setItem(BYE_KEY, "1");   // 첫 화면에서 인사 한 번
  } catch (err) {}
  btn.textContent = label;
  clearLogin();
  location.replace("/");
};

// ---------------------------------------------------------------
// 시세 알림: 켜 둔 종류만 살피 말투로 챗봇 창에 보냄 (규칙으로 만든 문장, 숫자는 대시보드 시세 그대로)
// 읽음 여부 · 설정은 이 브라우저에 기억 (로그인이 생기면 Supabase로 옮김)
// ---------------------------------------------------------------
const ALERT_PREFS_KEY = "salpi_alert_prefs", ALERT_READ_KEY = "salpi_alert_read";
const ALERT_TYPES = [
  ["all", "모든 시세가 오르고 내릴 때", "지난주보다 3% 넘게 움직인 농산물을 알려 드려요"],
  ["up", "값이 오를 때만", "지난주보다 10% 넘게 오른 농산물"],
  ["down", "값이 내렸을 때만", "지난주보다 10% 넘게 내린 농산물"],
  ["unusual", "평소랑 다를 때만", "하루 사이에 평소보다 크게 움직인 농산물"],
  ["weekly", "주 1회 대시보드 리포트", "한 주 시세를 한 번에 정리해 드려요"],
];
const DEFAULT_PREFS = { mine: true, all: false, up: true, down: false, unusual: true, weekly: true };
// 내 메뉴 재료: { 재료: [메뉴, ...] } — 못 불러오면 null (그때는 '내 메뉴 재료만'을 켜도 모든 야채로 알림)
let myItems = null, myMenus = [];
async function loadMyItems() {
  if (!SIGNED_IN) return;
  try {
    const r = await getJSON("/api/my-items");
    myItems = new Map(Object.entries(r.items));
    myMenus = r.menus;
  } catch (e) { myItems = null; }
  if (overview.length) deliverAlerts();
}
// 원가율 알림 (서버 store/cost_alert.py, GET /api/cost-alerts): 시세가 바뀌어 다시 계산한 원가율이 40%를 넘거나 넘을 예정 · 오름 · 내려옴
// → 시세 알림과 같은 종 · 챗봇 · 크롬 알림 목록에 섞어 보여 줌, 누르면 메뉴별 원가율
let costAlerts = [];
async function loadCostAlerts() {
  if (!SIGNED_IN) return;
  try {
    const r = await getJSON("/api/cost-alerts", { auth: true });
    // day = 한국 날짜 (06:00 알림은 UTC로 전날)
    costAlerts = r.alerts.map((a) => ({ id: `cost|${a.id}`, kind: "원가율", text: `사장님, ${a.message}`,
      title: a.message.split(". ")[0], item: null, day: new Date(Date.parse(a.sent_at) + 9 * 36e5).toISOString().slice(0, 10), href: "/?page=store#costs" }));
  } catch (e) { costAlerts = []; }
  deliverAlerts();
}
const menusOf = (item) => myItems?.get(item) || [];
// 알림 문장 뒤에 붙임: (김치찌개 · 된장찌개에 들어가요)
const inMenus = (item) => { const m = menusOf(item); return m.length ? ` (${m.join(" · ")}에 들어가요)` : ""; };
const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } };
function store(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
const alertPrefs = () => ({ ...DEFAULT_PREFS, ...load(ALERT_PREFS_KEY, {}) });
const josa = (w, a, b) => { const c = w.charCodeAt(w.length - 1); return w + (c >= 0xac00 && c <= 0xd7a3 && (c - 0xac00) % 28 ? a : b); };
let delivered = [];   // 지금 챗봇 창에 있는 알림 [{id, text}]

function buildAlerts() {
  if (!overview.length) return [];
  const prefs = alertPrefs();
  const day = overview.map((r) => r.wholesale_date).filter(Boolean).sort().at(-1) || "";
  // '내 메뉴 재료만'을 켜면 우리 가게 메뉴에 들어가는 야채만 알림
  const mine = prefs.mine && myItems;
  // 야채 · 과일 중 요즘 거래되는 것만 (제철이 아니라 거래가 드문 과일은 알림에서 뺌)
  const live = overview.filter((r) => r.wholesale_kg && (r.history || []).length >= 8);
  const pool = mine ? live.filter((r) => myItems.has(r.item)) : live;
  const tag = mmdd(day);
  const out = [], seen = new Set();
  const push = (id, text, title, item) => { if (!seen.has(id)) { seen.add(id); out.push({ id: `${day}|${id}`, text, title, item, day }); } };
  const moveTitle = (r) => `${josa(r.item, "이", "가")} 지난주보다 ${pct(ch(r))} ${ch(r) > 0 ? "올랐어요" : "내렸어요"}`;
  const ch = (r) => r.wholesale_change_pct ?? 0;
  const move = (r) => {
    const f = expOf(r);
    if (ch(r) > 0) return `사장님, **${josa(r.item, "이", "가")} 지난주보다 ${pct(ch(r))} 올랐어요** (${tag} 도매 kg당 ${won(r.wholesale_kg)})${inMenus(r.item)}.\n`
      + (f >= 2 ? "다음 주에도 오를 수 있어요. 필요한 만큼은 미리 사 두세요." : f <= -2 ? "다음 주엔 내릴 수 있어요. 급하지 않으면 조금 기다려 보세요." : "다음 주엔 비슷할 것 같아요. 필요한 만큼만 사 두세요.");
    return `사장님, **${josa(r.item, "이", "가")} 지난주보다 ${pct(ch(r))} 내렸어요** (${tag} 도매 kg당 ${won(r.wholesale_kg)})${inMenus(r.item)}.\n`
      + (f >= 2 ? "다음 주엔 다시 오를 수 있어요. 지금 사 두면 좋아요." : "지금 사기 좋은 때예요.");
  };
  const byAbs = (a, b) => Math.abs(ch(b)) - Math.abs(ch(a));
  const pushMove = (r) => push(`move|${r.item}`, move(r), moveTitle(r), r.item);
  if (prefs.all) pool.filter((r) => Math.abs(ch(r)) >= 3).sort(byAbs).slice(0, 6).forEach(pushMove);
  if (prefs.up) pool.filter((r) => ch(r) >= 10).sort(byAbs).slice(0, 3).forEach(pushMove);
  if (prefs.down) pool.filter((r) => ch(r) <= -10).sort(byAbs).slice(0, 3).forEach(pushMove);
  if (prefs.unusual) {
    pool.map((r) => {
      const h = (r.history || []).map((x) => x.kg_price).filter((v) => v > 0);
      const d = h.slice(1).map((v, i) => (v / h[i] - 1) * 100);
      if (d.length < 6) return null;
      const last = d.at(-1), usual = d.slice(0, -1).reduce((s, v) => s + Math.abs(v), 0) / (d.length - 1);
      return Math.abs(last) >= Math.max(10, usual * 2.5) ? { r, last, usual } : null;
    }).filter(Boolean).sort((a, b) => Math.abs(b.last) - Math.abs(a.last)).slice(0, 3).forEach(({ r, last, usual }) =>
      push(`unusual|${r.item}`, `사장님, **${josa(r.item, "이", "가")} 평소와 달라요.** 직전 거래일보다 ${pct(last)} ${last > 0 ? "올랐는데" : "내렸는데"}, `
        + `보통은 하루 ${usual.toFixed(0)}% 안팎으로 움직여요${inMenus(r.item)}.\n${last > 0 ? "주문 전에 가격을 한 번 더 확인해 보세요." : "필요하면 지금 사 두는 것도 좋아요."}`,
        `${josa(r.item, "이", "가")} 평소와 달라요 (하루 ${pct(last)})`, r.item));
  }
  if (prefs.weekly && day) {
    const d = new Date(day), monday = new Date(d - ((d.getDay() + 6) % 7) * 864e5).toISOString().slice(0, 10);
    const ups = live.filter((r) => ch(r) >= 3), downs = live.filter((r) => ch(r) <= -3), rise = live.filter((r) => expOf(r) >= 2);
    const top = [...live].sort((a, b) => ch(b) - ch(a));
    out.push({ id: `week|${monday}`, title: `이번 주 살피 리포트 (${mmdd(monday)} 주)`, item: null, day,
      text: `사장님, **이번 주 살피 리포트**예요 (${mmdd(monday)} 주).\n`
      + `- 지난주보다 오른 농산물 ${ups.length}개 · 내린 농산물 ${downs.length}개\n`
      + `- 가장 많이 오른 농산물: ${top[0].item} ${pct(ch(top[0]))}\n`
      + `- 가장 많이 내린 농산물: ${top.at(-1).item} ${pct(ch(top.at(-1)))}\n`
      + `- 다음 주 오를 가능성: ${rise.length}개${rise.length ? ` (${rise.sort((a, b) => expOf(b) - expOf(a)).slice(0, 3).map((r) => r.item).join(", ")} 등)` : ""}\n`
      + (mine && pool.length ? `- 내 메뉴 재료: ${pool.map((r) => `${r.item} ${pct(ch(r))}`).join(", ")}\n` : "")
      + "자세한 건 위의 시세 대시보드에서 보세요." });
  }
  return out;
}

function deliverAlerts() {
  const list = [...costAlerts, ...buildAlerts()];
  document.querySelectorAll("#chatBody .msg.alert").forEach((el) => el.remove());
  if (list.length && !body.children.length) addMsg("bot", "사장님, 오늘 대구 시세 살펴왔어요.\n아래 버튼을 누르거나 편하게 물어보세요.");
  const read = new Set(load(ALERT_READ_KEY, []));
  for (const a of list) {
    const el = addMsg("bot", a.text);
    el.classList.add("alert");
    el.dataset.alertId = a.id;
    el.insertAdjacentHTML("afterbegin", `<span class="alert-tag">${a.kind || "시세"} 알림${read.has(a.id) ? "" : " · 새 알림"}</span>`);
    el.insertAdjacentHTML("beforeend", `<span class="alert-more">${a.href ? "메뉴별 원가율 보기" : a.item ? `${esc(a.item)} 시세 자세히 보기` : "시세 대시보드 보기"} ›</span>`);
    el.title = a.href ? "누르면 메뉴별 원가율로 넘어가요" : "누르면 자세한 시세로 넘어가요";
  }
  delivered = list;
  if (chatEl.classList.contains("open")) markAlertsRead();
  updateBadges();
  renderBell();
  notifyAlerts();
}

// 브라우저 알림을 허용했으면 아직 읽지 않은 새 알림을 한 번씩 띄움 (최대 3개)
const ALERT_NOTIFIED_KEY = "salpi_alert_notified";
function notifyAlerts() {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const read = new Set(load(ALERT_READ_KEY, [])), shown = new Set(load(ALERT_NOTIFIED_KEY, []));
  const fresh = delivered.filter((a) => !read.has(a.id) && !shown.has(a.id)).slice(0, 3);
  for (const a of fresh) {
    try { new Notification(`살피 ${a.kind || "시세"} 알림`, { body: a.text.split("\n")[0], icon: "/static/img/salpi_face.png", tag: a.id }); } catch (e) {}
    shown.add(a.id);
  }
  if (fresh.length) store(ALERT_NOTIFIED_KEY, [...shown].slice(-200));
}

function unreadCount() {
  const read = new Set(load(ALERT_READ_KEY, []));
  return delivered.filter((a) => !read.has(a.id)).length;
}
function markAlertsRead(ids = delivered.map((a) => a.id)) {
  const read = new Set(load(ALERT_READ_KEY, []));
  ids.forEach((id) => read.add(id));
  store(ALERT_READ_KEY, [...read].slice(-300));
  updateBadges();
}
function updateBadges() {
  const n = unreadCount();
  for (const el of [$("#fabCount"), $("#bellCount")]) { el.hidden = !n; el.textContent = n > 99 ? "99+" : n; }
  $("#fabBubble").textContent = n ? "새 알림이 있어요" : "살피 챗봇에게 물어보세요";
  $("#fab").classList.toggle("has-alert", n > 0);
  renderBell();
}

// 위쪽 종: 알림만 모아 보기. 누르면 그 알림의 자세한 시세로 넘어감
function renderBell() {
  const read = new Set(load(ALERT_READ_KEY, []));
  $("#bellList").innerHTML = delivered.length ? delivered.map((a) => `<li><button data-aid="${esc(a.id)}" class="${read.has(a.id) ? "" : "unread"}">
      <img src="/static/img/salpi_face.png" alt=""><span><b>${esc(a.title)}</b><small>${mmdd(a.day)} ${a.kind || "시세"} · ${a.href ? "누르면 메뉴별 원가율" : a.item ? "누르면 재료 페이지" : "누르면 대시보드"}</small></span></button></li>`).join("")
    : `<li class="empty">새 알림이 없어요.<br><button data-open-settings>설정에서 알림 종류 켜기 ›</button></li>`;
}
function toggleBell(open = $("#bellPanel").hidden) {
  $("#bellPanel").hidden = !open;
  $("#bellBtn").setAttribute("aria-expanded", String(open));
}
$("#bellBtn").onclick = (e) => { e.stopPropagation(); toggleBell(); };
$("#bellPanel").onclick = (e) => {
  e.stopPropagation();
  const a = e.target.closest("[data-aid]");
  if (a) { toggleBell(false); return goToAlert(a.dataset.aid); }
  if (e.target.closest("[data-open-settings]")) { toggleBell(false); openMypage("settings"); }
};
$("#bellReadAll").onclick = () => markAlertsRead();
document.addEventListener("click", () => toggleBell(false));

// 알림 → 자세한 시세: 재료 알림은 그 재료 페이지(/?item=재료), 리포트는 첫 화면 전체 대시보드
function goToAlert(id) {
  const a = delivered.find((x) => x.id === id);
  if (!a) return;
  markAlertsRead([id]);
  if (a.href) { location.href = a.href; return; }
  if (a.item) { location.href = `/?item=${encodeURIComponent(a.item)}`; return; }
  closeChat();
  if (ITEM) { location.href = "/#dashboard"; return; }
  goSlide(0, "auto");
  setPaused(true);   // 보는 동안 다른 야채로 넘어가지 않게 (일시정지 버튼으로 다시 자동)
  $("#dashboard").scrollIntoView({ behavior: "smooth" });
  const s = slides()[0];
  s?.classList.remove("flash"); void s?.offsetWidth; s?.classList.add("flash");
}
body.addEventListener("click", (e) => {
  const m = e.target.closest(".msg.alert");
  if (m) goToAlert(m.dataset.alertId);
});

// ---------------------------------------------------------------
// 행사 정보 창: '시세 영향 정보'의 행사를 누르면 한국관광공사 행사 정보를 보여 줌
// ---------------------------------------------------------------
async function openEvent(id) {
  const box = $("#eventModalBody");
  box.innerHTML = `<div class="reading"><div class="spinner"></div><b>행사 정보를 불러오는 중이에요</b></div>`;
  $("#eventModal").hidden = false;
  let d;
  try { d = await getJSON(`/api/event/${encodeURIComponent(id)}`); }
  catch (e) { box.innerHTML = `<p class="rc-warn">${esc(e.message)}</p>`; return; }
  const day = (s) => (s ? `${s.slice(0, 4)}.${s.slice(4, 6)}.${s.slice(6, 8)}` : "");
  const row = (k, v) => (v ? `<div><dt>${k}</dt><dd>${esc(v)}</dd></div>` : "");
  const map = `https://map.kakao.com/link/search/${encodeURIComponent(d.addr || d.title)}`;
  box.innerHTML = `
    <div class="event-top ${d.image ? "" : "no-img"}">
      ${d.image ? `<a class="event-poster" href="${esc(d.image)}" target="_blank" rel="noopener" title="포스터 크게 보기">
        <img src="${esc(d.image)}" alt="${esc(d.title)} 포스터"></a>` : ""}
      <div class="event-head">
        <h3>${esc(d.title)}</h3>
        <dl class="event-info">
          ${row("기간", d.start ? `${day(d.start)} ~ ${day(d.end)}` : "")}${row("장소", d.place || d.addr)}${row("주소", d.place ? d.addr : "")}
          ${row("시간", d.playtime)}${row("요금", d.fee)}${row("문의", d.tel)}${row("주최", d.sponsor)}
        </dl>
        ${d.overview ? `<p class="event-overview">${esc(d.overview)}</p>` : ""}
      </div>
    </div>
    <div class="event-body">
      <div class="event-links">
        ${(d.homepages || []).map((u, i) => `<a href="${esc(u)}" target="_blank" rel="noopener">${i ? "관련 사이트" : "공식 홈페이지"} →</a>`).join("")}
        <a href="${map}" target="_blank" rel="noopener">지도에서 보기 →</a>
      </div>
      <p class="muted small">출처: 한국관광공사 국문 관광정보</p>
    </div>`;
}
function closeEvent() { $("#eventModal").hidden = true; }
$("#eventModalClose").onclick = closeEvent;
$("#eventModal").onclick = (e) => { if (e.target.id === "eventModal") closeEvent(); };
$("#eventCard").onclick = (e) => {
  const b = e.target.closest("[data-event]");
  if (b) openEvent(b.dataset.event);
};

// 시연용 주소: 마이페이지 코드 · 알림 설정 값이 모두 읽힌 뒤에 열어야 해서 파일 맨 끝에 둠
if (location.hash === "#my") openMypage();               // 시연용: 마이페이지가 열린 채로
if (location.hash === "#settings") openMypage("settings");   // 시연용: 마이페이지 › 설정(알림 · 권한)이 열린 채로
try { if (sessionStorage.getItem("salpi_kakao_show")) { sessionStorage.removeItem("salpi_kakao_show"); if (SIGNED_IN) openMypage("settings"); } } catch (e) {}   // 카카오톡 연결 결과를 바로 보여 줌
