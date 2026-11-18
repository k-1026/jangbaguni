// 아래 네비게이션 탭 전환 (#/home · #/mart · #/store · #/my)
// 메모리 아끼기: 한 번에 한 화면만 붙여 둠. 다른 탭으로 가면 그 화면을 dispose 해서 DOM · 구독 · 그림을 모두 풂
// (ViewModel 은 작은 데이터만 들고 있어서 남겨 둠 → 돌아오면 다시 받지 않고 바로 그림)

export function createRouter(outlet, routes, { onChange } = {}) {
  let current = null, currentName = null;

  async function show() {
    const [name, ...rest] = (location.hash.replace(/^#\/?/, "") || "home").split("/");
    const route = routes[name] ? name : "home";
    if (route === currentName && current?.update) { current.update(rest); return; }
    current?.dispose?.();
    outlet.replaceChildren();
    currentName = route;
    onChange?.(route);
    const mod = await routes[route]();      // 화면 코드는 처음 열 때만 받음 (첫 실행이 가벼움)
    if (currentName !== route) return;       // 받는 사이 다른 탭을 눌렀으면 버림
    current = mod.mount(outlet, rest);
    outlet.scrollTop = 0;
    window.scrollTo(0, 0);
  }

  addEventListener("hashchange", show);
  return { start: show, go: (path) => { location.hash = `#/${path}`; } };
}
