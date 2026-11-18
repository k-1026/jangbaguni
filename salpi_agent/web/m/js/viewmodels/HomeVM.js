// 홈(시세) 화면 상태: 품목 묶음(야채 · 과일 · 수산물 · 육류) · 대시보드 카드 · 요약
import { observable, resource } from "../core/observable.js";
import { Api } from "../core/api.js";
import { mmdd } from "../core/dom.js";

export const KINDS = [{ key: "야채", label: "야채" }, { key: "과일", label: "과일" }, { key: "수산물", label: "수산물" }, { key: "육류", label: "육류" }];
const PRODUCE = (k) => k === "야채" || k === "과일";

// 서버 두 곳(농산물 · 수산물 육류)의 모양을 화면 하나의 모양으로 맞춤
function fromProduce(r) {
  const f = r.forecast || {};
  return { name: r.item, price: r.wholesale_kg, unit: "kg", week: r.wholesale_change_pct, basis: "대구 북부도매 kg당",
    points: (r.history || []).filter((h) => h.kg_price).map((h) => [mmdd(h.date), h.kg_price]),
    exp: f.expected_change_pct, range: f.expected_kg_price_range, direction: f.direction, tip: f.suggestion,
    reason: (f.factors || []).filter((x) => Math.abs(x.effect_pct) >= 1).slice(0, 2).map((x) => x.factor) };
}
function fromExtra(r) {
  const f = r.forecast || {};
  return { name: r.item, price: r.price, unit: r.unit, week: r.week_change_pct, basis: r.basis_label || "대구 조사가",
    points: (r.history || []).filter((h) => h.price).map((h) => [mmdd(h.date), h.price]),
    exp: f.expected_change_pct, range: f.expected_price_range, direction: f.direction, tip: f.suggestion, reason: [] };
}

export function createHomeVM() {
  const kind = observable("야채");
  const produce = resource(Api.overview);
  const extra = resource(Api.extra);

  // 지금 묶음의 대시보드 카드 (오를 가능성 높은 순 — 데스크톱과 같은 순서)
  function rows() {
    const k = kind.get();
    if (PRODUCE(k)) {
      const d = produce.state.get().data || [];
      return d.filter((r) => (r.kind || "야채") === k && r.wholesale_kg && (r.history || []).length >= 8).map(fromProduce)
        .sort((a, b) => (b.exp ?? -99) - (a.exp ?? -99));
    }
    const d = extra.state.get().data || [];
    return d.filter((r) => r.group === k && r.price).map(fromExtra).sort((a, b) => Math.abs(b.week ?? 0) - Math.abs(a.week ?? 0));
  }
  const summary = (rs) => ({
    up: rs.filter((r) => r.week > 0).length, down: rs.filter((r) => r.week < 0).length,
    rising: rs.filter((r) => r.exp >= 2).length, top: rs.slice().sort((a, b) => (b.week ?? 0) - (a.week ?? 0))[0],
  });

  return {
    kind, produce, extra, rows, summary,
    load() { return PRODUCE(kind.get()) ? produce.load() : extra.load(); },
    pick(k) { kind.set(k); return this.load(); },
    state: () => (PRODUCE(kind.get()) ? produce : extra).state,
  };
}

// 앱 전체에서 하나만 (탭을 오가도 데이터 유지)
let vm;
export const homeVM = () => (vm ||= createHomeVM());
