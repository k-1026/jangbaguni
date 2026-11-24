import json
import sys
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
    # ---- 11/24 추가: OCR 정확도 20장 시험용 (재료 이름 맞추기 · 묶음 단위 · 재료 아닌 줄 · 흐린 사진까지) ----
    "1005": ("2026-10-05", [("쌀 20kg", "포", 2, 118000), ("계란 1판(30구)", "판", 3, 22500), ("식용유 18L", "통", 1, 52000),
             ("사각어묵 1kg", "봉", 5, 27500), ("당근 10kg", "박스", 1, 21000)]),
    "1022": ("2026-10-22", [("깐양파 15kg", "망", 1, 24000), ("돈앞다리 1kg", "kg", 10, 125000), ("국산두부 1모", "모", 40, 48000),
             ("양배추 8kg(3통)", "망", 1, 13500), ("깻잎 1kg", "kg", 1, 15500), ("건고추 1kg", "봉", 1, 19000)]),
    "1109": ("2026-11-09", [("쌀 20kg", "포", 2, 120000), ("계란 1판(30구)", "판", 4, 30800), ("배추김치 10kg", "박스", 2, 78000),
             ("재래된장 2kg", "통", 2, 28000), ("태양초고추장 3kg", "통", 1, 21500), ("배달비", "회", 1, 5000)]),
    "1116": ("2026-11-16", [("깐양파 15kg", "망", 1, 26000), ("돈앞다리 1kg", "kg", 12, 152400), ("국산두부 1모", "모", 45, 54000),
             ("포기김치 10kg", "박스", 2, 78000), ("대파 1kg", "kg", 4, 11600), ("청양고추 1kg", "kg", 1, 8800),
             ("애호박 1개", "개", 12, 19200), ("감자 10kg", "박스", 1, 24000), ("깐마늘 1kg", "봉", 2, 22000),
             ("고춧가루(국산) 1kg", "봉", 1, 32000), ("양배추 8kg(3통)", "망", 1, 12500), ("당근 10kg", "박스", 1, 20500),
             ("사각어묵 1kg", "봉", 3, 16500), ("식용유 18L", "통", 1, 53000), ("계란 1판(30구)", "판", 3, 23400),
             ("쌀 20kg", "포", 1, 61000)]),
    "1123": ("2026-11-23", [("양배추 8kg(3통)", "망", 1, 12000), ("대파 1단", "단", 5, 14500), ("건고추 1kg", "봉", 1, 19500),
             ("깻잎 1kg", "kg", 1, 16000), ("배달비", "회", 1, 5000)]),
    "1029": ("2026-10-29", [("국산콩두부300G", "", 10, 18900), ("청양고추500G", "", 2, 6980), ("깐마늘1K", "", 1, 11900),
             ("애호박(개)", "", 6, 8940), ("종량제봉투20L", "", 1, 2600)]),
    "1111": ("2026-11-11", [("햇양파3K", "", 2, 9960), ("감자2K", "", 2, 8980), ("세척당근1K", "", 3, 7470),
             ("대파(단)", "", 2, 5980), ("생수2L*6", "", 1, 4980)]),
    "1118": ("2026-11-18", [("계란30구(특)", "", 2, 15980), ("어묵사각1K", "", 2, 11980), ("식용유1.8L", "", 2, 9960),
             ("깐마늘500G", "", 2, 9980)]),
    "1120": ("2026-11-20", [("돈앞다리(냉장)1K", "", 5, 64500), ("국산두부300G", "", 20, 24000), ("양배추(통)", "", 2, 7980)]),
    "1107": ("2026-11-07", [("양파 20k", "1망", 1, 31000), ("감자", "1박스", 1, 25000), ("대파", "3단", 3, 9900)]),
    "1114": ("2026-11-14", [("돼지 앞다리", "10kg", 10, 128000), ("두부", "30모", 30, 36000), ("청양", "1kg", 1, 9000),
             ("깻잎", "1kg", 1, 16500)]),
    "1121": ("2026-11-21", [("배추김치", "10kg", 1, 39000), ("애호박", "10개", 10, 16000), ("당근", "5kg", 5, 11000)]),
    "1025": ("2026-10-25", [("고춧가루", "1kg", 1, 30000), ("마늘(깐것)", "2kg", 2, 22000), ("생강", "500g", 1, 6000)]),
    "1101": ("2026-11-01", [("깐양파 15kg", "망", 1, 25000), ("돈앞다리 1kg", "kg", 8, 100000), ("어묵(부산) 1kg", "봉", 4, 23200),
             ("깐마늘 1kg", "봉", 1, 11500), ("봉투", "장", 2, 200)]),
}

# 정답 재료 · 줄 수량 1당 기준 단위 양 (OCR 이 재료 이름 · 양까지 맞혔는지 채점). None = 재료 아님 / 양을 알 수 없음
EXPECT = {
    "깐양파 15kg": ("양파", 15), "돈앞다리 1kg": ("돼지고기 앞다리", 1), "국산두부 1모": ("두부", 1), "포기김치 10kg": ("배추김치", 10),
    "대파 1kg": ("대파", 1), "청양고추 1kg": ("청양고추", 1), "애호박 1개": ("애호박", 0.3), "감자 10kg": ("감자", 10),
    "재래된장 2kg": ("된장", 2), "태양초고추장 3kg": ("고추장", 3), "고춧가루(중국) 1kg": ("고춧가루", 1), "깐마늘 1kg": ("깐마늘", 1),
    "깐양파15K": ("양파", 15), "돈앞다리(냉장)1K": ("돼지고기 앞다리", 1), "국산두부300G": ("두부", 1), "포기김치10K": ("배추김치", 10),
    "양파 1망": ("양파", None), "돼지 앞다리": ("돼지고기 앞다리", 1), "대파": ("대파", 1), "대파1단": ("대파", 1),
    "쌀 20kg": ("쌀", 20), "계란 1판(30구)": ("계란", 30), "식용유 18L": ("식용유", 18), "사각어묵 1kg": ("어묵", 1),
    "당근 10kg": ("당근", 10), "양배추 8kg(3통)": ("양배추", 8), "깻잎 1kg": ("깻잎", 1), "건고추 1kg": ("건고추", 1),
    "배추김치 10kg": ("배추김치", 10), "배달비": (None, None), "고춧가루(국산) 1kg": ("고춧가루", 1), "대파 1단": ("대파", 1),
    "국산콩두부300G": ("두부", 1), "청양고추500G": ("청양고추", 0.5), "깐마늘1K": ("깐마늘", 1), "애호박(개)": ("애호박", 0.25),
    "종량제봉투20L": (None, None), "햇양파3K": ("양파", 3), "감자2K": ("감자", 2), "세척당근1K": ("당근", 1),
    "대파(단)": ("대파", 1), "생수2L*6": (None, None), "계란30구(특)": ("계란", 30), "어묵사각1K": ("어묵", 1),
    "식용유1.8L": ("식용유", 1.8), "깐마늘500G": ("깐마늘", 0.5), "양배추(통)": ("양배추", 2.5),
    "양파 20k": ("양파", 20), "감자": ("감자", None), "두부": ("두부", 1), "청양": ("청양고추", 1), "깻잎": ("깻잎", 1),
    "배추김치": ("배추김치", 10), "애호박": ("애호박", 0.25), "당근": ("당근", 1), "고춧가루": ("고춧가루", 1),
    "마늘(깐것)": ("깐마늘", 1), "생강": (None, None), "어묵(부산) 1kg": ("어묵", 1), "봉투": (None, None),
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
    return html, 820, 620 + 28 * max(14, len(rows))


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
    return html, 480, 380 + 48 * len(rows)


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
    return html, 520, 440 + 44 * (len(rows) + 4)


pages = {"receipt_1012_statement": statement("1012"), "receipt_1019_statement": statement("1019"),
         "receipt_1026_mart": mart("1026"), "receipt_1102_handwritten": hand("1102"), "receipt_1104_mart_up": mart("1104")}
# 사진처럼: 1019 명세서를 기울이고 흐리게 + 그림자
html, w, h = statement("1019")
html = html.replace("<div class=p>", '<div class=p style="transform:rotate(-4deg) translateY(30px);filter:blur(.7px) brightness(.93) contrast(.95);box-shadow:30px 30px 60px rgba(0,0,0,.45)">')
html = html.replace("background:#9a948a", "background:linear-gradient(120deg,#6b5f52,#a59985 60%,#857865)")
pages["receipt_1019_photo_tilted"] = (html, w + 60, h + 100)


def photo(page, angle=-4, blur=.7, dark=False):
    """종이를 기울여 흐리게 찍은 사진처럼 (dark=True 면 어두운 가게 안에서 찍은 것처럼 더 어둡고 흐리게)."""
    html, w, h = page
    look = (f"transform:rotate({angle}deg) translateY(30px);filter:blur({blur}px) brightness({.72 if dark else .93}) "
            f"contrast({.8 if dark else .95});box-shadow:30px 30px 60px rgba(0,0,0,.45)")
    for cls in ("p", "r", "h"):
        html = html.replace(f"<div class={cls}>", f'<div class={cls} style="{look}">', 1)
    html = html.replace("background:#9a948a", "background:linear-gradient(120deg,#6b5f52,#a59985 60%,#857865)")
    return html, w + 60, h + 100


# 11/24 추가 14장 (거래명세서 6 · 마트 4 · 손글씨 4 · 16줄 긴 명세서 포함, 기울임 · 어두운 사진 섞음)
pages.update({
    "receipt_1005_statement": statement("1005"), "receipt_1022_statement_dark": photo(statement("1022"), 3, 1.0, dark=True),
    "receipt_1109_statement": statement("1109"), "receipt_1116_statement_long": statement("1116"),
    "receipt_1123_statement_tilted": photo(statement("1123"), -6, .9),
    "receipt_1029_mart": mart("1029"), "receipt_1111_mart": mart("1111"), "receipt_1118_mart_tilted": photo(mart("1118"), 5, .8),
    "receipt_1120_mart_dark": photo(mart("1120"), -2, 1.1, dark=True),
    "receipt_1107_handwritten": hand("1107"), "receipt_1114_handwritten": hand("1114"),
    "receipt_1121_handwritten_tilted": photo(hand("1121"), 4, .8), "receipt_1025_handwritten_dark": photo(hand("1025"), -3, 1.0, dark=True),
    "receipt_1101_statement_tilted": photo(statement("1101"), 8, 1.2),
})
for name, (html, w, h) in pages.items():
    (OUT / f"{name}.html").write_text(html, encoding="utf-8")
    print(name, w, h)

# 정답지: OCR이 이렇게 읽어야 맞음 (정확도 시험용)
keys = {name: name.split("_")[1] for name in pages}   # receipt_1012_statement → 1012


def _line(n, c, a):
    item, per = EXPECT[n]
    return {"raw_name": n, "qty": c, "amount": a, "item": item, "qty_base": round(per * c, 3) if per is not None else None}


ans = {name: {"date": R[k][0], "items": [_line(n, c, a) for n, u, c, a in R[k][1]],
              "total": sum(r[3] for r in R[k][1])} for name, k in keys.items()}
(OUT / "answers.json").write_text(json.dumps(ans, ensure_ascii=False, indent=1), encoding="utf-8")

# 그림 뜨기: 크롬으로 캡처 — python make.py --png [이름 …]  (이름 없이 --png 만 주면 아직 그림이 없는 것만)
CHROMES = [r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
           "/usr/bin/google-chrome", "/usr/bin/chromium"]
if "--png" in sys.argv:
    import subprocess
    chrome = next(c for c in CHROMES if Path(c).exists())
    want = sys.argv[sys.argv.index("--png") + 1:] or [n for n in pages if not (OUT / f"{n}.png").exists()]
    for name in want:
        html, w, h = pages[name]
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--virtual-time-budget=5000",
                        f"--window-size={w},{h}", f"--screenshot={OUT / f'{name}.png'}", (OUT / f"{name}.html").as_uri()],
                       check=True, capture_output=True)
        print("그림", name)
