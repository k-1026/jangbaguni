// 손가락으로 넘기는 카드 (CSS scroll-snap — 따로 애니메이션 계산을 하지 않아 가볍고 부드러움)
// 메모리 아끼기: 화면에 보이는 카드와 양옆 카드만 그림(onShow), 멀어진 카드는 그림을 지움(onHide)
import { esc } from "../core/dom.js";

export function swiper(el, items, { render, onShow, onHide, onChange, label = "" }) {
  el.innerHTML = `<div class="m-swiper" tabindex="0" aria-roledescription="carousel" aria-label="${esc(label)}">
      ${items.map((it, i) => `<article class="m-slide" data-i="${i}" aria-roledescription="slide" aria-label="${i + 1} / ${items.length}">${render(it, i)}</article>`).join("")}
    </div>
    <div class="m-swiper-foot"><span class="m-count"><b>1</b> / ${items.length}</span><span class="m-hint">옆으로 넘겨 보세요</span></div>`;
  const track = el.querySelector(".m-swiper"), count = el.querySelector(".m-count b");
  const slides = [...track.children];
  const drawn = new Set();
  let index = 0;

  const near = (i) => [i - 1, i, i + 1].filter((k) => k >= 0 && k < slides.length);
  function refresh(i) {
    const keep = new Set(near(i));
    for (const k of keep) if (!drawn.has(k)) { drawn.add(k); onShow?.(slides[k], items[k], k); }
    for (const k of [...drawn]) if (!keep.has(k) && Math.abs(k - i) > 2) { drawn.delete(k); onHide?.(slides[k], items[k], k); }
  }
  let raf = 0;
  const onScroll = () => {
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(() => {
      const i = Math.round(track.scrollLeft / Math.max(1, track.clientWidth));
      if (i !== index) { index = i; count.textContent = i + 1; refresh(i); onChange?.(i); }
    });
  };
  track.addEventListener("scroll", onScroll, { passive: true });
  refresh(0);
  return {
    go(i, smooth = true) { track.scrollTo({ left: i * track.clientWidth, behavior: smooth ? "smooth" : "auto" }); },
    dispose() {
      track.removeEventListener("scroll", onScroll);
      cancelAnimationFrame(raf);
      drawn.forEach((k) => onHide?.(slides[k], items[k], k));
      el.replaceChildren();
    },
  };
}
