// 대형마트 판매가 화면 상태: 종류 · 검색 · 몇 개까지 보일지 (한 번에 30개씩 — 260여 개를 다 그리지 않음)
import { observable, resource } from "../core/observable.js";
import { Api } from "../core/api.js";

const PAGE = 30;

export function createMartVM() {
  const data = resource(Api.mart);
  const category = observable("전체"), query = observable(""), shown = observable(PAGE);

  function list() {
    const d = data.state.get().data;
    if (!d) return [];
    const q = query.get().replace(/\s/g, "").toLowerCase(), c = category.get();
    return (d.items || [])
      .filter((x) => (c === "전체" || x.category === c) && (!q || x.name.replace(/\s/g, "").toLowerCase().includes(q)))
      .sort((a, b) => (b.change_pct ?? 0) - (a.change_pct ?? 0));   // 2주 새 오른 것부터 (데스크톱과 같음)
  }
  const categories = () => ["전체", ...((data.state.get().data?.categories) || [])].map((c) => ({ key: c, label: c }));

  return {
    data, category, query, shown, list, categories,
    load: () => data.load(),
    pick(c) { category.set(c); shown.set(PAGE); },
    search(q) { query.set(q); shown.set(PAGE); },
    more() { shown.update((n) => n + PAGE); },
  };
}

let vm;
export const martVM = () => (vm ||= createMartVM());
