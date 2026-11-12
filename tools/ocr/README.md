# 캡처 · 문서 → 글 파일(.md) 바꾸기

Claude에게 PDF · 이미지를 그대로 주면 **페이지마다 사진으로 읽어서 사용량이 많이 나갑니다.**
글만 필요하면 먼저 글 파일(.md)로 바꿔서 주세요. 두 도구 모두 무료이고 내 컴퓨터에서만 돌아갑니다.

| 바꿀 것 | 도구 | 비고 |
|---|---|---|
| **캡처 이미지** (png · jpg …) | `tools/ocr/voc_ocr.ps1` (윈도우 기본 한국어 글자 인식) | 폴더 하나 → `폴더이름.md` 한 파일. 작은 글씨는 3배로 키워 읽음 |
| **PDF · 워드 · 엑셀 · PPT** | MarkItDown (마이크로소프트) | 이미지 속 글자는 못 읽음 → 캡처는 위 도구로 |

## 1. 캡처 이미지 → 글

```
powershell -ExecutionPolicy Bypass -File tools\ocr\voc_ocr.ps1 -Folder "캡처 폴더 경로"
```
- 하위 폴더까지 읽고, 파일마다 `## 파일 이름` 아래에 글이 붙습니다
- 한국어 글자 인식이 없다고 나오면: 설정 → 시간 및 언어 → 언어 → 한국어 → 옵션 → **광학 문자 인식** 설치
- 가끔 한두 글자가 틀립니다 (예: "엑셀작업" → "엑셀직업"). 분류 · 요약에는 충분합니다

## 2. PDF · 워드 · 엑셀 · PPT → 글 (MarkItDown)

처음 한 번 설치 (저장소 밖 내 폴더에):
```
py -m venv %USERPROFILE%\tools\markitdown
%USERPROFILE%\tools\markitdown\Scripts\python -m pip install "markitdown[pdf,docx,xlsx,pptx]"
```
바꾸기:
```
%USERPROFILE%\tools\markitdown\Scripts\markitdown "바꿀파일.pdf" -o "결과.md"
```
- "FontBBox" 경고가 많이 떠도 무시해도 됩니다

## ⚠️ 개인정보
- 카페 캡처에는 닉네임 등 개인정보가 있습니다. **캡처 · 결과 .md 파일은 저장소(GitHub) 밖**(예: 바탕화면)에 두고 올리지 마세요
