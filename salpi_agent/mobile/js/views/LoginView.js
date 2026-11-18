// 로그인: 아이디(또는 휴대폰 번호) + 비밀번호. 회원가입 · 카카오 로그인은 웹 화면으로 열어 줌
import { disposer } from "../core/observable.js";
import { esc } from "../core/dom.js";
import { Api, siteUrl, IS_NATIVE, kakaoLoginStart } from "../core/api.js";
import { card, toast } from "../components/index.js";

export function mount(outlet, rest = []) {
  const d = disposer();
  const back = /^(home|mart|store|my)$/.test(rest[0] || "") ? rest[0] : "my";
  outlet.innerHTML = `<div class="m-page login">
    <h1 class="m-title">로그인</h1>
    ${card("", `<form id="f" class="m-form" autocomplete="on">
      <label>아이디 또는 휴대폰 번호<input name="id" autocomplete="username" autocapitalize="off" required></label>
      <label>비밀번호<input name="pw" type="password" autocomplete="current-password" required></label>
      <label class="m-check"><input name="keep" type="checkbox" checked> 로그인 상태 유지</label>
      <p class="m-warn" id="msg" hidden></p>
      <button type="submit" class="m-btn primary wide">로그인</button>
    </form>`)}
    ${IS_NATIVE ? card("", `<button type="button" id="kakao" class="m-btn wide">카카오로 로그인</button>`) : ""}
    ${card("", `<a class="m-link" href="${esc(siteUrl("/?page=login"))}" target="_blank" rel="noopener">${IS_NATIVE ? "회원가입 (웹에서 열려요)" : "회원가입 · 카카오로 로그인 (웹에서 열려요)"}<i>›</i></a>`)}
  </div>`;
  const kakao = outlet.querySelector("#kakao");
  if (kakao) d.on(kakao, "click", () => kakaoLoginStart().catch((err) => toast(err.message, 4000)));
  const f = outlet.querySelector("#f"), msg = outlet.querySelector("#msg"), submit = f.querySelector("[type=submit]");
  d.on(f, "submit", async (e) => {
    e.preventDefault();
    msg.hidden = true;
    submit.disabled = true;
    try {
      const x = f.elements;   // f.id 는 폼 자신의 id 라서 elements 로 읽음
      await Api.signIn(x.id.value.trim(), x.pw.value, x.keep.checked);
      toast("로그인했어요");
      location.hash = `#/${back}`;
    } catch (err) {
      msg.textContent = err.message;
      msg.hidden = false;
    } finally { submit.disabled = false; }
  });
  return { dispose: d.run };
}
