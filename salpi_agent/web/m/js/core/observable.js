// MVVM 의 바인딩: ViewModel 이 값을 바꾸면 구독한 View 가 다시 그림.
// 구독을 풀면(dispose) 참조가 끊겨 화면을 떠난 View 가 메모리에 남지 않음.

export function observable(value) {
  const subs = new Set();
  return {
    get: () => value,
    set(next) {
      if (Object.is(next, value)) return;
      value = next;
      subs.forEach((fn) => fn(value));
    },
    update(fn) { this.set(fn(value)); },
    subscribe(fn, now = true) {
      subs.add(fn);
      if (now) fn(value);
      return () => subs.delete(fn);
    },
  };
}

// 여러 구독 · 이벤트를 한 번에 풀기 위한 묶음 (View 마다 하나)
export function disposer() {
  const fns = [];
  return {
    add(fn) { if (typeof fn === "function") fns.push(fn); return fn; },
    on(el, type, fn, opt) { el.addEventListener(type, fn, opt); fns.push(() => el.removeEventListener(type, fn, opt)); },
    run() { while (fns.length) { try { fns.pop()(); } catch (e) { /* 이미 풀림 */ } } },
  };
}

// 상태 묶음: { loading, error, data } — ViewModel 이 서버를 부를 때 공통으로 씀
export function resource(loader) {
  const state = observable({ loading: false, error: null, data: null });
  let pending = null;
  return {
    state,
    async load(force = false) {
      if (pending) return pending;
      if (state.get().data && !force) return state.get().data;
      state.set({ ...state.get(), loading: true, error: null });
      pending = loader()
        .then((data) => { state.set({ loading: false, error: null, data }); return data; })
        .catch((error) => { state.set({ loading: false, error, data: state.get().data }); return null; })
        .finally(() => { pending = null; });
      return pending;
    },
  };
}
