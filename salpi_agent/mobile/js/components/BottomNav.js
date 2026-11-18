// 아래 네비게이션: 홈 · 대형마트 · 나의 가게 · 마이페이지 (상단 헤더 없음)
const ICON = {
  home: '<path d="M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  mart: '<path d="M4 4h2l2.2 10.2a1 1 0 0 0 1 .8h8.6a1 1 0 0 0 1-.8L20.5 8H7"/><circle cx="10" cy="19" r="1.5"/><circle cx="17" cy="19" r="1.5"/>',
  store: '<path d="M4 9 5.5 4h13L20 9M4 9h16v11H4zM4 9a2.7 2.7 0 0 0 5.3 0 2.7 2.7 0 0 0 5.4 0A2.7 2.7 0 0 0 20 9M10 20v-5h4v5"/>',
  my: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
};
export const TABS = [
  { key: "home", label: "홈" },
  { key: "mart", label: "대형마트" },
  { key: "store", label: "나의 가게" },
  { key: "my", label: "마이페이지" },
];

export function bottomNav(el) {
  el.innerHTML = TABS.map((t) => `<a href="#/${t.key}" class="m-nav-item" data-tab="${t.key}" aria-label="${t.label}">
    <svg viewBox="0 0 24 24" width="24" height="24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICON[t.key]}</svg>
    <span>${t.label}</span></a>`).join("");
  return {
    select(key) {
      el.querySelectorAll(".m-nav-item").forEach((a) => {
        const on = a.dataset.tab === key;
        a.classList.toggle("on", on);
        if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
      });
    },
  };
}
