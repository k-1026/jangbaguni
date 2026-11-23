// 품목 하나의 시세 카드 (홈 대시보드의 슬라이드 · 검색 상세 화면이 같이 씀)
import { esc, won, pct, tone, arrow } from "../core/dom.js";
import { buyButton } from "./BuyPicker.js";

export const itemBody = (r, { shop = true } = {}) => `
  <div class="m-dash-head">
    <h3>${esc(r.name)}</h3>
    <span class="m-week ${tone(r.week)}">${arrow(r.week)} ${pct(r.week)} <small>1주</small></span>
  </div>
  <p class="m-price"><b>${won(r.price)}</b><small>/${esc(r.unit)} · ${esc(r.basis)}</small></p>
  <canvas class="m-chart" aria-label="${esc(r.name)} 최근 시세와 다음 7일 예상"></canvas>
  ${r.exp == null ? `<p class="m-note">예측 자료가 없어요</p>` : `
  <div class="m-fc ${tone(r.exp, 1.9)}">
    <b>${esc(r.direction || "")}</b>
    <span>다음 7일 ${pct(r.exp)}${r.price ? ` · ${won(Math.round((r.price * (1 + r.exp / 100)) / 10) * 10)} 안팎` : ""}</span>
    <small>${esc(r.tip || "")}${r.reason?.length ? ` · ${esc(r.reason.join(", "))} 영향` : ""}</small>
  </div>`}
  ${shop && r.shop ? buyButton(r.name, r.shop, `${esc(r.name)} 사러 가기 <i aria-hidden="true">›</i>`) : ""}`;
