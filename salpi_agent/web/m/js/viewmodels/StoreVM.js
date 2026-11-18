// 나의 가게 화면 상태: 영수증 분석(사진 → 읽기 → 확인 → 저장) · 메뉴별 원가율 · 내일 준비
import { observable, resource } from "../core/observable.js";
import { Api, login } from "../core/api.js";

// 사진을 긴 쪽 1600px JPEG 로 줄임 (서버 4.5MB 제한 · 휴대폰 메모리 아끼기). 다 쓰면 원본 주소를 바로 풂
export function shrink(file) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, 1600 / Math.max(img.width, img.height));
      const c = document.createElement("canvas");
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      const g = c.getContext("2d");
      g.fillStyle = "#fff"; g.fillRect(0, 0, c.width, c.height);
      g.drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(img.src);
      const out = c.toDataURL("image/jpeg", 0.86);
      c.width = c.height = 0;   // 그림 메모리 비움
      resolve(out);
    };
    img.onerror = () => { URL.revokeObjectURL(img.src); reject(new Error("사진을 열지 못했어요")); };
    img.src = URL.createObjectURL(file);
  });
}

export function createStoreVM() {
  const costs = resource(Api.costs);
  const demand = resource(Api.demand);
  // 영수증: step = idle · reading · edit · saving · done
  const receipt = observable({ step: "idle", image: null, data: null, error: null, saved: null });

  return {
    costs, demand, receipt,
    signedIn: () => !!login(),
    load() { return Promise.all([costs.load(), demand.load()]); },
    async read(file) {
      receipt.set({ step: "reading", image: null, data: null, error: null, saved: null });
      try {
        const image = await shrink(file);
        const data = await Api.receiptRead(image);
        receipt.set({ step: "edit", image, data, error: null, saved: null });
      } catch (e) { receipt.set({ step: "idle", image: null, data: null, error: e.message, saved: null }); }
    },
    // 고친 칸 값만 바꿈 (화면을 다시 그리지 않음 — 입력 중 커서 · 바로 누른 저장 버튼이 사라지지 않게)
    setLine(i, field, value) {
      const line = receipt.get().data?.items?.[i];
      if (line) line[field] = value;
    },
    async save() {
      const r = receipt.get();
      receipt.set({ ...r, step: "saving", error: null });
      try {
        const items = r.data.items.filter((x) => x.raw_name && x.amount).map((x) => ({
          raw_name: x.raw_name, item_id: x.item_id || null, qty: x.qty, qty_base: x.qty_base, amount: x.amount }));
        const saved = await Api.receiptSave({ image: r.image, mime: "image/jpeg", date: r.data.date, supplier: r.data.supplier, items });
        receipt.set({ step: "done", image: null, data: null, error: null, saved });   // 사진은 저장했으니 메모리에서 뺌
        costs.load(true); demand.load(true);
      } catch (e) { receipt.set({ ...r, step: "edit", error: e.message }); }
    },
    reset() { receipt.set({ step: "idle", image: null, data: null, error: null, saved: null }); },
  };
}

let vm;
export const storeVM = () => (vm ||= createStoreVM());
