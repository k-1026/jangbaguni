// 나의 가게: 영수증 분석 → 메뉴별 원가율(40% 이상이면 마진 지키는 방법 3가지) → 내일 준비
import { disposer } from "../core/observable.js";
import { esc, won, mmdd } from "../core/dom.js";
import { card, loading, errorBox, empty, loginGate, toast } from "../components/index.js";
import { storeVM } from "../viewmodels/StoreVM.js";

function receiptBody(r) {
  if (r.step === "reading") return loading("살피가 영수증을 읽는 중이에요 (10~30초)");
  if (r.step === "saving") return loading("저장하고 원가율을 다시 계산하는 중이에요");
  if (r.step === "edit") {
    const opts = (r.data.items_list || []).map((i) => `<option value="${i.id}">${esc(i.name)} (${esc(i.base_unit)})</option>`).join("");
    return `<p class="m-note">${esc(r.data.date || "날짜 모름")} · ${esc(r.data.supplier || "판매처 모름")} · 읽은 내용이 맞는지 확인해 주세요</p>
      ${r.data.total_matches === false ? `<p class="m-warn">줄 금액 합(${won(r.data.line_sum)})이 합계(${won(r.data.total)})와 달라요. 금액을 다시 봐 주세요</p>` : ""}
      <ul class="m-lines">${r.data.items.map((x, i) => `<li data-line="${i}">
        <b>${esc(x.raw_name)}</b>
        <select data-f="item_id" aria-label="재료"><option value="">재료 아님</option>${opts.replace(`value="${x.item_id}"`, `value="${x.item_id}" selected`)}</select>
        <label>양<input data-f="qty_base" inputmode="decimal" value="${x.qty_base ?? ""}" aria-label="기준 단위 양"></label>
        <label>금액<input data-f="amount" inputmode="numeric" value="${x.amount ?? ""}" aria-label="금액"></label></li>`).join("")}</ul>
      ${r.error ? `<p class="m-warn">${esc(r.error)}</p>` : ""}
      <div class="m-row"><button type="button" class="m-btn" data-cancel>다시 찍기</button><button type="button" class="m-btn primary" data-save>확인했어요, 저장</button></div>`;
  }
  return `${r.step === "done" ? `<p class="m-ok">${mmdd(r.saved.date)} 영수증 ${r.saved.saved_items}줄을 저장했어요. 아래 원가율이 새로 계산됐어요</p>` : ""}
    ${r.error ? `<p class="m-warn">${esc(r.error)}</p>` : ""}
    <div class="m-row">
      <label class="m-btn primary">카메라로 찍기<input type="file" accept="image/*" capture="environment" hidden data-file></label>
      <label class="m-btn">사진 고르기<input type="file" accept="image/*" hidden data-file></label>
    </div>`;
}

function costCard(m, T) {
  const plan = m.high ? `<div class="m-plan"><b>마진 지키는 방법 3가지</b><ol>
      <li><b>가격 조정</b> ${m.price_up ? `${won(m.price)} → <b>${won(m.price_up.price)}</b> · 원가율 ${m.price_up.new_ratio_pct}%` : "계산할 수 없어요"}</li>
      <li><b>대체 재료</b> ${m.swap ? `${esc(m.swap.from)} 절반을 ${esc(m.swap.to)}(으)로 · 1인분 ${won(m.swap.saving_per_serving)} 아낌` : "지금은 바꿀 만한 재료가 없어요"}</li>
      <li><b>메뉴 제안</b> ${m.push_menu ? `${esc(m.push_menu.menu)} 밀기 · 한 그릇 ${won(m.push_menu.margin)} 남음` : "원가율이 괜찮은 다른 메뉴가 없어요"}</li></ol></div>` : "";
  return `<li class="m-cost ${m.high ? "high" : "ok"}">
    <div class="m-cost-top"><b>${esc(m.menu)}</b><span class="m-ratio">${m.cost_ratio_pct ?? "-"}<small>%</small></span></div>
    <p class="m-note">${esc(m.verdict)} · 판매가 ${won(m.price)} · 재료비 ${won(m.cost_per_serving)} · 남는 돈 ${won(m.margin)}${
      m.next_ratio_pct != null && Math.abs(m.next_ratio_pct - m.cost_ratio_pct) >= 0.5 ? ` · 다음 주 ${m.next_ratio_pct}%` : ""}</p>${plan}</li>`;
}

function demandBody(dm) {
  return `<p class="m-note">내일 ${mmdd(dm.target_date)}(${esc(dm.target_weekday)}) · ${dm.is_open ? `모두 ${dm.total_predicted}그릇` : "쉬는 날"}${dm.model ? " · 학습 모델(가상 판매 기록)" : ""}</p>
    <ul class="m-list">${dm.menus.map((m) => `<li class="m-li"><b>${esc(m.menu)}</b><span>${m.predicted}그릇 <small>${m.range[0]}~${m.range[1]}</small></span></li>`).join("")}</ul>
    <h3 class="m-sub">오늘 주문 (${dm.next_delivery_date ? `${mmdd(dm.next_delivery_date)} 입고까지` : "다음 입고까지"})</h3>
    <ul class="m-list">${dm.items.filter((i) => i.order_qty > 0).slice(0, 8).map((i) =>
      `<li class="m-li"><b>${esc(i.item)}</b><span>${i.order_qty}${esc(i.unit)} <small>${esc(i.decision)}</small></span></li>`).join("") || "<li class='m-li'>재고로 충분해요</li>"}</ul>`;
}

export function mount(outlet, rest = []) {
  const vm = storeVM(), d = disposer();
  if (!vm.signedIn()) { outlet.innerHTML = `<div class="m-page"><h1 class="m-title">나의 가게</h1>${loginGate("나의 가게", "store")}</div>`; return { dispose() {} }; }
  outlet.innerHTML = `<div class="m-page store">
    <h1 class="m-title">나의 가게</h1>
    ${card("영수증 분석", `<div id="rc"></div>`, { cls: "receipt" })}
    ${card("메뉴별 원가율", `<div id="costs">${loading()}</div>`)}
    ${card("내일 준비", `<div id="demand">${loading()}</div>`)}
  </div>`;
  const rc = outlet.querySelector("#rc"), costs = outlet.querySelector("#costs"), demand = outlet.querySelector("#demand");

  d.add(vm.receipt.subscribe((r) => { rc.innerHTML = receiptBody(r); }));
  d.add(vm.costs.state.subscribe((st) => {
    if (st.error && !st.data) costs.innerHTML = errorBox(st.error);
    else if (st.data) costs.innerHTML = `<p class="m-note">원가율 ${st.data.target_ratio_pct}% 아래면 괜찮아요 · 영수증 단가 기준</p>
      <ul class="m-costs">${st.data.menus.map((m) => costCard(m, st.data.target_ratio_pct)).join("")}</ul>`;
  }));
  d.add(vm.demand.state.subscribe((st) => {
    if (st.error && !st.data) demand.innerHTML = errorBox(st.error);
    else if (st.data) demand.innerHTML = st.data.error ? empty(st.data.error) : demandBody(st.data);
  }));

  d.on(rc, "change", (e) => {
    const f = e.target.closest("[data-file]");
    if (f?.files?.[0]) { vm.read(f.files[0]); f.value = ""; return; }
    const li = e.target.closest("[data-line]");
    if (li && e.target.dataset.f) {
      const v = e.target.value, field = e.target.dataset.f;
      vm.setLine(+li.dataset.line, field, field === "item_id" ? (v ? +v : null) : (v === "" ? null : Number(v)));
    }
  });
  d.on(rc, "click", (e) => {
    if (e.target.closest("[data-save]")) vm.save().then(() => { if (vm.receipt.get().step === "done") toast("저장했어요"); });
    if (e.target.closest("[data-cancel]")) vm.reset();
  });
  d.on(outlet, "click", (e) => { if (e.target.closest("[data-retry]")) vm.load(); });

  vm.load();
  if (rest[0] === "receipt") requestAnimationFrame(() => outlet.querySelector(".receipt")?.scrollIntoView({ block: "start" }));
  return { dispose: d.run, update: (r) => { if (r[0] === "receipt") outlet.querySelector(".receipt")?.scrollIntoView({ block: "start" }); } };
}
