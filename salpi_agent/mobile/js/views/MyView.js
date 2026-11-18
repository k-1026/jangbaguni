// 마이페이지: 내 정보 · 시세 알림 설정 · 카카오톡 알림 · (웹) 앱 알림 · 로그아웃
import { disposer } from "../core/observable.js";
import { esc } from "../core/dom.js";
import { IS_NATIVE, siteUrl } from "../core/api.js";
import { card, loading, loginGate, toast } from "../components/index.js";
import { myVM, ALERT_TYPES } from "../viewmodels/MyVM.js";

function profile(me) {
  const how = me.provider === "kakao" ? "카카오 로그인" : me.login_id ? `아이디 ${me.login_id}` : "";
  return `<div class="m-profile">
    <img src="${esc(me.avatar || "/static/img/owner_face.png")}" alt="" width="56" height="56" referrerpolicy="no-referrer" onerror="this.src='/static/img/owner_face.png'">
    <div><b>${esc(me.name || "사장님")} 사장님</b><small>${esc(how)}</small></div></div>
    <dl class="m-dl"><dt>가게</dt><dd>${esc(me.store_name || "아직 없어요")}</dd>
      <dt>지역</dt><dd>${esc(["대구", me.district, me.place].filter(Boolean).join(" "))}</dd></dl>`;
}

const toggle = (key, title, desc, on) => `<label class="m-li m-tg"><span><b>${esc(title)}</b><small>${esc(desc)}</small></span>
  <input type="checkbox" class="m-switch" data-pref="${key}" ${on ? "checked" : ""}></label>`;

function prefsBody(p) {
  return toggle("mine", "내 메뉴 재료만", "내 메뉴에 들어가는 재료의 시세만 알려 드려요", p.mine)
    + ALERT_TYPES.map(([k, t, d]) => toggle(k, t, d, p[k])).join("");
}

function kakaoBody(k) {
  if (k.loading) return loading("확인하는 중이에요");
  if (k.error || !k.data) return `<p class="m-warn">${esc(k.error || "상태를 불러오지 못했어요")}</p>`;
  const s = k.data;
  if (!s.connected) return `<div class="m-li"><span><b>아직 연결 전</b><small>카카오 계정으로 '카카오톡 메시지 전송'에 동의하면 받아요</small></span>
    <button type="button" class="m-btn primary" data-kconnect ${s.ready ? "" : "disabled"}>연결</button></div>`;
  return `<label class="m-li m-tg"><span><b>매일 아침 받기</b><small>${s.last_sent ? `마지막으로 보낸 때 ${esc(String(s.last_sent).replace("T", " "))}` : "아직 보낸 적 없어요"}${s.last_error ? ` · 지난번 실패: ${esc(s.last_error)}` : ""}</small></span>
      <input type="checkbox" class="m-switch" data-kon ${s.on ? "checked" : ""}></label>
    <div class="m-li"><span><b>지금 보내 보기</b><small>내 카톡 '나와의 채팅'으로 지금 시세 알림</small></span><button type="button" class="m-btn" data-ktest>보내기</button></div>
    <div class="m-li"><span><b>연결 끊기</b><small>카카오톡 알림을 그만 받아요</small></span><button type="button" class="m-btn" data-kunlink>끊기</button></div>`;
}

function appBody(vm, p) {
  if (IS_NATIVE) return `<div class="m-li"><b>살피 앱</b><span class="m-on">설치됨</span></div>
    <p class="m-note">휴대폰 알림(푸시)은 카카오톡 알림으로 먼저 받을 수 있어요. 앱 자체 푸시는 준비 중이에요.</p>`;
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
  if (!vm.signedIn()) { outlet.innerHTML = `<div class="m-page"><h1 class="m-title">마이페이지</h1>${loginGate("마이페이지", "my")}</div>`; return { dispose() {} }; }
  outlet.innerHTML = `<div class="m-page my">
    <h1 class="m-title">마이페이지</h1>
    ${card("", `<div id="me">${loading()}</div>`)}
    ${card("알림 설정", `<p class="m-note">켜 둔 종류의 시세 알림을 받아요 (이 기기에 저장)</p><div id="prefs"></div>`)}
    ${card("카카오톡 시세 알림", `<p class="m-note">매일 아침 내 메뉴 재료의 다음 주 시세 · 원가율 40% 넘은 메뉴를 카카오톡으로 보내 드려요</p><div id="kakao">${loading()}</div>`)}
    ${card("살피 앱 · 알림", `<div id="app"></div>`)}
    ${card("", `<a class="m-link" href="${esc(siteUrl("/?page=store"))}" target="_blank" rel="noopener">웹에서 더 보기 (메뉴 수정 · 영수증 목록)<i>›</i></a>
      <button type="button" class="m-link danger" data-logout>로그아웃<i>›</i></button>`)}
  </div>`;
  const me = outlet.querySelector("#me"), app = outlet.querySelector("#app"), prefs = outlet.querySelector("#prefs"), kakao = outlet.querySelector("#kakao");
  const drawApp = () => { app.innerHTML = appBody(vm, vm.push.get()); };

  d.add(vm.me.state.subscribe((st) => {
    me.innerHTML = st.data ? profile(st.data) : st.error ? `<p class="m-warn">${esc(st.error.message)}</p>` : loading();
  }));
  d.add(vm.prefs.subscribe((p) => { prefs.innerHTML = prefsBody(p); }));
  d.add(vm.kakao.subscribe((k) => { kakao.innerHTML = kakaoBody(k); }));
  d.add(vm.push.subscribe(drawApp));
  d.add(vm.installPrompt.subscribe(drawApp, false));

  d.on(outlet, "change", async (e) => {
    const p = e.target.closest("[data-pref]");
    if (p) { vm.setPref(p.dataset.pref, p.checked); return; }
    if (e.target.closest("[data-kon]")) {
      const box = e.target;
      try { await vm.kakaoOn(box.checked); } catch (err) { box.checked = !box.checked; toast(err.message, 4000); }
    }
  });
  d.on(outlet, "click", async (e) => {
    if (e.target.closest("[data-install]")) vm.install();
    if (e.target.closest("[data-on]")) vm.enablePush();
    if (e.target.closest("[data-off]")) vm.disablePush();
    if (e.target.closest("[data-test]")) {
      try { const r = await vm.testPush(); toast(`보냈어요 (기기 ${r.sent}대)`); } catch (err) { toast(err.message, 4000); }
    }
    if (e.target.closest("[data-kconnect]")) {
      try { window.open(await vm.kakaoConnect(), "_blank"); toast("카카오 동의 화면이 열려요. 끝나면 앱으로 돌아와 주세요", 4000); } catch (err) { toast(err.message, 4000); }
    }
    if (e.target.closest("[data-ktest]")) {
      try { await vm.kakaoTest(); toast("카카오톡으로 보냈어요"); } catch (err) { toast(err.message, 4000); }
    }
    if (e.target.closest("[data-kunlink]")) {
      try { await vm.kakaoUnlink(); toast("연결을 끊었어요"); } catch (err) { toast(err.message, 4000); }
    }
    if (e.target.closest("[data-logout]")) { vm.logout(); location.hash = "#/home"; }
  });
  vm.load();
  vm.refreshPush();
  vm.refreshKakao();
  return { dispose: d.run };
}
