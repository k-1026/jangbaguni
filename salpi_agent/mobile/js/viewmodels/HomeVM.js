// 홈(시세) 화면 상태: 품목 묶음(야채 · 과일 · 수산물 · 육류) · 대시보드 카드 · 요약 · 보기 방식(전체/오른/내린/다음 주 오를)
import { observable, resource } from "../core/observable.js";
import { Api } from "../core/api.js";
import { mmdd } from "../core/dom.js";

export const KINDS = [{ key: "야채", label: "야채" }, { key: "과일", label: "과일" }, { key: "수산물", label: "수산물" }, { key: "육류", label: "육류" }];
export const MODES = {
  all: "전체", up: "오른 품목", down: "내린 품목", rising: "다음 주 오를 품목",
};
const PRODUCE = (k) => k === "야채" || k === "과일";
const SHOP = "https://www.foodspring.co.kr";

// 서버 두 곳(농산물 · 수산물 육류)의 모양을 화면 하나의 모양으로 맞춤
function fromProduce(r) {
  const f = r.forecast || {};
  return { name: r.item, kind: r.kind || "야채", price: r.wholesale_kg, unit: "kg", week: r.wholesale_change_pct, basis: "대구 북부도매 kg당",
    points: (r.history || []).filter((h) => h.kg_price).map((h) => [mmdd(h.date), h.kg_price]),
    exp: f.expected_change_pct, range: f.expected_kg_price_range, direction: f.direction, tip: f.suggestion,
    // '품목 특성'은 AI 계산의 기본값이라 이유로 보여 주지 않음 (웹 app.js isReason 과 같음)
    reason: (f.factors || []).filter((x) => !x.factor.startsWith("품목 특성") && Math.abs(x.effect_pct) >= 1).slice(0, 2).map((x) => x.factor),
    shop: r.foodspring_url || SHOP };
}
function fromExtra(r) {
  const f = r.forecast || {};
  return { name: r.item, kind: r.group, price: r.price, unit: r.unit, week: r.week_change_pct, basis: r.basis_label || "대구 조사가",
    points: (r.history || []).filter((h) => h.price).map((h) => [mmdd(h.date), h.price]),
    exp: f.expected_change_pct, range: f.expected_price_range, direction: f.direction, tip: f.suggestion, reason: [],
    shop: r.foodspring_url || SHOP };
}

export function createHomeVM() {
  const kind = observable("야채");
  const mode = observable("all");
  const produce = resource(Api.overview);
  const extra = resource(Api.extra);

  // 지금 묶음 전체 (오를 가능성 높은 순 — 데스크톱과 같은 순서)
  function baseRows() {
    const k = kind.get();
    if (PRODUCE(k)) {
      const d = produce.state.get().data || [];
      return d.filter((r) => (r.kind || "야채") === k && r.wholesale_kg && (r.history || []).length >= 8).map(fromProduce)
        .sort((a, b) => (b.exp ?? -99) - (a.exp ?? -99));
    }
    const d = extra.state.get().data || [];
    return d.filter((r) => r.group === k && r.price).map(fromExtra).sort((a, b) => Math.abs(b.week ?? 0) - Math.abs(a.week ?? 0));
  }
  // 요약 숫자를 눌러 고른 보기 방식에 맞게 걸러 냄
  function rows() {
    const rs = baseRows(), m = mode.get();
    if (m === "up") return rs.filter((r) => r.week > 0).sort((a, b) => b.week - a.week);
    if (m === "down") return rs.filter((r) => r.week < 0).sort((a, b) => a.week - b.week);
    if (m === "rising") return rs.filter((r) => r.exp >= 2).sort((a, b) => b.exp - a.exp);
    return rs;
  }
  const summary = (rs) => ({
    up: rs.filter((r) => r.week > 0).length, down: rs.filter((r) => r.week < 0).length,
    rising: rs.filter((r) => r.exp >= 2).length, top: rs.slice().sort((a, b) => (b.week ?? 0) - (a.week ?? 0))[0],
  });

  // 이름으로 품목 하나 찾기 (검색 · 상세 화면): 야채 · 과일 · 수산물 · 육류 모두에서
  function all() {
    const p = (produce.state.get().data || []).filter((r) => r.wholesale_kg).map(fromProduce);
    const e = (extra.state.get().data || []).filter((r) => r.price).map(fromExtra);
    return [...p, ...e];
  }

  return {
    kind, mode, produce, extra, rows, baseRows, summary, all,
    find: (name) => all().find((r) => r.name === name),
    load() { return PRODUCE(kind.get()) ? produce.load() : extra.load(); },
    loadAll() { return Promise.all([produce.load(), extra.load()]); },
    pick(k) { mode.set("all"); kind.set(k); return this.load(); },
    setMode(m) { mode.set(mode.get() === m ? "all" : m); },
    state: () => (PRODUCE(kind.get()) ? produce : extra).state,
  };
}

// 앱 전체에서 하나만 (탭을 오가도 데이터 유지)
let vm;
export const homeVM = () => (vm ||= createHomeVM());
