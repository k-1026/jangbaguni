// 스플래시: 흰 바탕에 살피 로고. 첫 데이터가 오거나 최대 2.5초 뒤 사라지고 DOM 에서 지움 (메모리 남기지 않음)
export function splash(root = document.body) {
  const el = document.getElementById("m-splash");
  const shownAt = Date.now();
  let gone = false;
  const hide = () => {
    if (gone || !el) return;
    gone = true;
    const wait = Math.max(0, 700 - (Date.now() - shownAt));   // 너무 깜빡이지 않게 최소 0.7초
    setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 350); }, wait);
  };
  setTimeout(hide, 2500);
  return { hide };
}
