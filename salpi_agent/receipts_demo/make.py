import json
from pathlib import Path

OUT = Path(__file__).resolve().parent
NOTE = "※ 살피 시연용 가상 영수증 (실제 거래 아님)"

# seed.sql 의 영수증 4장과 같은 품목 · 금액 (원문 이름은 영수증마다 다르게: OCR이 재료 이름 맞추기까지 하는지 시험)
R = {
    "1012": ("2026-10-12", [("깐양파 15kg", "망", 1, 19500), ("돈앞다리 1kg", "kg", 12, 138000), ("국산두부 1모", "모", 45, 54000),
             ("포기김치 10kg", "박스", 2, 76000), ("대파 1kg", "kg", 3, 9000), ("청양고추 1kg", "kg", 1, 9500),
             ("애호박 1개", "개", 10, 15000), ("감자 10kg", "박스", 1, 26000), ("재래된장 2kg", "통", 1, 14000),
             ("태양초고추장 3kg", "통", 1, 21000), ("고춧가루(중국) 1kg", "봉", 1, 14000), ("깐마늘 1kg", "봉", 1, 11000)]),
    "1019": ("2026-10-19", [("깐양파 15kg", "망", 1, 22500), ("돈앞다리 1kg", "kg", 12, 144000), ("국산두부 1모", "모", 45, 54000),
             ("대파 1kg", "kg", 3, 9600)]),
    "1026": ("2026-10-26", [("깐양파15K", "", 1, 25500), ("돈앞다리(냉장)1K", "", 12, 150000), ("국산두부300G", "", 45, 54000),
             ("포기김치10K", "", 2, 76000)]),
    "1102": ("2026-11-02", [("양파 1망", "1", 1, 28500), ("돼지 앞다리", "12kg", 12, 153600), ("대파", "3kg", 3, 10500)]),
    # 시연용: 값이 오른 오늘 영수증 → 저장하면 원가율이 오르는 걸 보여 줌
    "1104": ("2026-11-04", [("깐양파15K", "", 1, 34500), ("돈앞다리(냉장)1K", "", 12, 168000), ("대파1단", "", 3, 11400)]),
}


def won(v):
    return f"{v:,}"


CSS = """<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;700;900&family=Nanum+Gothic+Coding&family=Nanum+Pen+Script&display=swap" rel="stylesheet">
<style>*{box-sizing:border-box}body{margin:0;background:#9a948a;display:flex;justify-content:center;align-items:flex-start;padding:30px;min-height:100vh}</style>"""


def statement(key):
    d, rows = R[key]
    total = sum(r[3] for r in rows)
    trs = "".join(f"<tr><td>{i + 1}</td><td class=l>{n}</td><td>{u}</td><td>{c}</td><td>{won(a // c)}</td><td>{won(a)}</td></tr>"
                  for i, (n, u, c, a) in enumerate(rows))
    trs += "<tr><td>&nbsp;</td><td></td><td></td><td></td><td></td><td></td></tr>" * max(0, 14 - len(rows))
    html = f"""<!doctype html><html><head><meta charset=utf-8>{CSS}<style>
.p{{width:760px;background:#fffdf8;padding:28px 30px;font-family:'Noto Sans KR';color:#222;box-shadow:0 6px 20px rgba(0,0,0,.3)}}
h1{{text-align:center;letter-spacing:12px;font-size:28px;margin:0 0 4px;color:#1d3c8f}} .sub{{text-align:center;color:#1d3c8f;font-size:12px;margin-bottom:14px}}
table{{width:100%;border-collapse:collapse;font-size:13px}} td,th{{border:1px solid #1d3c8f;padding:5px 6px;text-align:right}} th{{background:#e9eefb;color:#1d3c8f;text-align:center}}
td.l{{text-align:left}} .info td{{text-align:left;vertical-align:top}} .tot td{{font-weight:900;font-size:15px}} .note{{font-size:11px;color:#888;margin-top:10px;text-align:center}}
.stamp{{position:relative}} .stamp span{{position:absolute;right:8px;top:6px;width:46px;height:46px;border:3px solid #d33;border-radius:50%;color:#d33;font-weight:900;font-size:12px;display:flex;align-items:center;justify-content:center;transform:rotate(-12deg);opacity:.8}}
</style></head><body><div class=p>
<h1>거래명세서</h1><div class=sub>(공급받는자 보관용)</div>
<table class=info><tr><td style="width:50%">일자: {d[:4]}년 {int(d[5:7])}월 {int(d[8:])}일<br>공급받는자: 살피 시연 한식당 귀하<br>합계금액: <b>일금 {won(total)}원정</b></td>
<td class=stamp>상호: 살피상회 (시연용)<br>등록번호: 000-00-00000<br>주소: 대구광역시 북구 (가상)<br>대표: 홍길동 <span>(인)</span></td></tr></table><br>
<table><tr><th>No</th><th>품목</th><th>단위</th><th>수량</th><th>단가</th><th>금액</th></tr>{trs}
<tr class=tot><td colspan=5 style="text-align:center">합 계</td><td>{won(total)}</td></tr></table>
<div class=note>{NOTE}</div></div></body></html>"""
    return html, 820, 860


def mart(key):
    d, rows = R[key]
    total = sum(r[3] for r in rows)
    lines = "".join(f"<div class=it>{n}</div><div class=row><span>{won(a // c)}</span><span>{c}</span><span>{won(a)}</span></div>"
                    for n, u, c, a in rows)
    vat = round(total / 11)
    html = f"""<!doctype html><html><head><meta charset=utf-8>{CSS}<style>
.r{{width:380px;background:#fff;padding:22px 20px 30px;font-family:'Nanum Gothic Coding',monospace;font-size:14px;color:#222;box-shadow:0 6px 20px rgba(0,0,0,.3)}}
.c{{text-align:center}} h2{{margin:0;font-size:22px}} hr{{border:0;border-top:1px dashed #555;margin:8px 0}}
.row{{display:grid;grid-template-columns:1fr 50px 100px;text-align:right}} .row.h{{font-weight:700}} .it{{margin-top:4px}}
.sum{{display:flex;justify-content:space-between}} .big{{font-size:18px;font-weight:700}} .note{{font-size:11px;color:#888;margin-top:12px;text-align:center}}
.bar{{height:44px;margin:12px 20px 0;background:repeating-linear-gradient(90deg,#222 0 2px,#fff 2px 4px,#222 4px 5px,#fff 5px 8px)}}
</style></head><body><div class=r>
<div class=c><h2>살피마트 (시연용)</h2>대구 달서구 (가상) · 000-00-00000<br>[등록] {d} 10:42:17 POS:02</div><hr>
<div class="row h"><span>단가</span><span>수량</span><span>금액</span></div><hr>{lines}<hr>
<div class=sum><span>과세물품가액</span><span>{won(total - vat)}</span></div><div class=sum><span>부가세</span><span>{won(vat)}</span></div>
<div class="sum big"><span>합  계</span><span>{won(total)}</span></div><hr>
<div class=sum><span>카드결제(****-****-****-0000)</span><span>{won(total)}</span></div><div class=bar></div>
<div class=note>{NOTE}</div></div></body></html>"""
    return html, 480, 560


def hand(key):
    d, rows = R[key]
    total = sum(r[3] for r in rows)
    trs = "".join(f"<tr><td>{n}</td><td>{u}</td><td>{won(a)}</td></tr>" for n, u, c, a in rows)
    trs += "<tr><td></td><td></td><td></td></tr>" * 4
    html = f"""<!doctype html><html><head><meta charset=utf-8>{CSS}<style>
.h{{width:460px;background:#fbf6e9;padding:20px 22px;font-family:'Noto Sans KR';color:#333;box-shadow:0 6px 20px rgba(0,0,0,.3)}}
h1{{text-align:center;font-size:22px;margin:0 0 8px;letter-spacing:6px}} table{{width:100%;border-collapse:collapse}}
td,th{{border:1px solid #777;padding:4px 8px;height:38px;font-size:13px}} td{{font-family:'Nanum Pen Script';font-size:28px;color:#1a2f8a}}
td:last-child{{text-align:right}} .w{{font-family:'Nanum Pen Script';font-size:26px;color:#1a2f8a}} .note{{font-size:11px;color:#888;margin-top:10px;text-align:center}}
</style></head><body><div class=h><h1>영 수 증</h1>
<div>살피 시연 한식당 귀하 &nbsp; <span class=w>{int(d[5:7])}/{int(d[8:])}</span></div>
<div>공급자: 매천시장 살피네 (시연용)</div><br>
<table><tr><th>품명</th><th>수량</th><th>금액</th></tr>{trs}
<tr><th>합계</th><td></td><td>{won(total)}</td></tr></table>
<div class=note>{NOTE}</div></div></body></html>"""
    return html, 520, 640


pages = {"receipt_1012_statement": statement("1012"), "receipt_1019_statement": statement("1019"),
         "receipt_1026_mart": mart("1026"), "receipt_1102_handwritten": hand("1102"), "receipt_1104_mart_up": mart("1104")}
# 사진처럼: 1019 명세서를 기울이고 흐리게 + 그림자
html, w, h = statement("1019")
html = html.replace("<div class=p>", '<div class=p style="transform:rotate(-4deg) translateY(30px);filter:blur(.7px) brightness(.93) contrast(.95);box-shadow:30px 30px 60px rgba(0,0,0,.45)">')
html = html.replace("background:#9a948a", "background:linear-gradient(120deg,#6b5f52,#a59985 60%,#857865)")
pages["receipt_1019_photo_tilted"] = (html, w + 60, h + 100)
for name, (html, w, h) in pages.items():
    (OUT / f"{name}.html").write_text(html, encoding="utf-8")
    print(name, w, h)

# 정답지: OCR이 이렇게 읽어야 맞음 (정확도 시험용)
keys = {"receipt_1012_statement": "1012", "receipt_1019_statement": "1019", "receipt_1026_mart": "1026",
        "receipt_1102_handwritten": "1102", "receipt_1019_photo_tilted": "1019", "receipt_1104_mart_up": "1104"}
ans = {name: {"date": R[k][0], "items": [{"raw_name": n, "qty": c, "amount": a} for n, u, c, a in R[k][1]],
              "total": sum(r[3] for r in R[k][1])} for name, k in keys.items()}
(OUT / "answers.json").write_text(json.dumps(ans, ensure_ascii=False, indent=1), encoding="utf-8")
