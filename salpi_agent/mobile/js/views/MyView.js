// 마이페이지: 내 정보 · 살피 앱 설치 · 앱 알림 · 로그아웃 (자세한 설정은 웹 마이페이지로)
import { disposer } from "../core/observable.js";
import { esc } from "../core/dom.js";
import { card, loading, loginGate, toast } from "../components/index.js";
import { myVM } from "../viewmodels/MyVM.js";

function profile(me) {
  const how = me.provider === "kakao" ? "카카오 로그인" : me.login_id ? `아이디 ${me.login_id}` : "";
  return `<div class="m-profile">
    <img src="${esc(me.avatar || "/static/img/owner_face.png")}" alt="" width="56" height="56" referrerpolicy="no-referrer" onerror="this.src='/static/img/owner_face.png'">
    <div><b>${esc(me.name || "사장님")} 사장님</b><small>${esc(how)}</small></div></div>
    <dl class="m-dl"><dt>가게</dt><dd>${esc(me.store_name || "아직 없어요")}</dd>
      <dt>지역</dt><dd>${esc(["대구", me.district, me.place].filter(Boolean).join(" "))}</dd></dl>`;
}

function appBody(vm, p) {
  const install = vm.isApp() ? `<div class="m-li"><b>살피 앱</b><span class="m-on">설치됨</span></div>`
    : vm.installPrompt.get() ? `<div class="m-li"><span><b>살피 앱 설치</b><small>홈 화면에 아이콘이 생겨요</small></span><button type="button" class="m-btn primary" data-install>설치</button></div>`
    : vm.isIOS ? `<p class="m-note">아이폰: Safari 아래 공유 버튼 → "홈 화면에 추가" → 그 앱에서 알림을 켜 주세요</p>`
    : `<p class="m-note">크롬 메뉴(⋮) → "앱 설치" 또는 "홈 화면에 추가"</p>`;
  if (!vm.canPush()) return install + `<p class="m-note">${vm.isIOS ? "아이폰은 홈 화면에 추가한 살피 앱에서만 알림을 켤 수 있어요" : "이 브라우저는 앱 알림을 쓸 수 없어요"}</p>`;
  if (p.loading) return install + loading("알림 상태를 확인하는 중이에요");
  const push = p.on
    ? `<div class="m-li"><span><b>앱 알림 켜짐</b><small>${p.last ? `마지막 알림 ${esc(p.last.replace("T", " "))}` : "매일 아침 시세 알림이 와요"}</small></span><button type="button" class="m-btn" data-off>끄기</button></div>
       <div class="m-li"><span><b>지금 보내 보기</b><small>이 계정의 기기로 지금 알림</small></span><button type="button" class="m-btn" data-test>보내기</button></div>`
    : p.denied ? `<p class="m-warn">알림이 막혀 있어요. 휴대폰 설정 → 앱 → 살피(또는 크롬) → 알림 허용</p>`
    : `<div class="m-li"><span><b>앱 알림</b><small>${p.ready ? "매일 아침 내 메뉴 재료 시세 · 원가율" : "서버에 앱 알림 열쇠가 아직 없어요"}</small></span>
        <button type="button" class="m-btn primary" data-on ${p.ready ? "" : "disabled"}>켜기</button></div>`;
  return install + push + (p.error ? `<p class="m-warn">${esc(p.error)}</p>` : "");
}

export function mount(outlet) {
  const vm = myVM(), d = disposer();
  if (!vm.signedIn()) { outlet.innerHTML = `<div class="m-page"><h1 class="m-title">마이페이지</h1>${loginGate("마이페이지", "/m/#/my")}</div>`; return { dispose() {} }; }
  outlet.innerHTML = `<div class="m-page my">
    <h1 class="m-title">마이페이지</h1>
    ${card("", `<div id="me">${loading()}</div>`)}
    ${card("살피 앱 · 알림", `<div id="app"></div>`)}
    ${card("", `<a class="m-link" href="/?page=store&from=app">웹에서 더 보기 (메뉴 수정 · 영수증 목록 · 카카오톡 알림)<i>›</i></a>
      <button type="button" class="m-link danger" data-logout>로그아웃<i>›</i></button>`)}
  </div>`;
  const me = outlet.querySelector("#me"), app = outlet.querySelector("#app");
  const drawApp = () => { app.innerHTML = appBody(vm, vm.push.get()); };

  d.add(vm.me.state.subscribe((st) => {
    me.innerHTML = st.data ? profile(st.data) : st.error ? `<p class="m-warn">${esc(st.error.message)}</p>` : loading();
  }));
  d.add(vm.push.subscribe(drawApp));
  d.add(vm.installPrompt.subscribe(drawApp, false));
  d.on(outlet, "click", async (e) => {
    if (e.target.closest("[data-install]")) vm.install();
    if (e.target.closest("[data-on]")) vm.enablePush();
    if (e.target.closest("[data-off]")) vm.disablePush();
    if (e.target.closest("[data-test]")) {
      try { const r = await vm.testPush(); toast(`보냈어요 (기기 ${r.sent}대)`); } catch (err) { toast(err.message, 4000); }
    }
    if (e.target.closest("[data-logout]")) { vm.logout(); location.hash = "#/home"; }
  });
  vm.load();
  vm.refreshPush();
  return { dispose: d.run };
}
