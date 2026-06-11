"""
gen_opacity_classification.py — B-roll 모션 템플릿 투명/불투명 분류 HTML 생성기 (2026-06-11)
----------------------------------------------------------------------------------------
sample_catalog.json(현재 등록 템플릿) + scene_designer._default_card_opacity(실제 분류 로직)를
읽어 self-contained 분류 리포트 HTML(repo root/broll_opacity_classification.html)을 생성한다.
썸네일은 out/thumbs/<stem>__mid.png를 base64 임베드(상대경로 깨짐 방지).

재생성: PYTHONIOENCODING=utf-8 python tools/motion_graphics/gen_opacity_classification.py
"""
from __future__ import annotations

import base64
import html
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CATALOG = HERE / "sample_catalog.json"
THUMBS = HERE / "out" / "thumbs"
TEMPLATES = HERE / "templates"
OUT = REPO / "broll_opacity_classification.html"

sys.path.insert(0, str(REPO / "tools" / "capcut_pipeline"))
from scene_designer import _default_card_opacity  # noqa: E402

# 2026-06-11 신규 archetype (video-edit-skill 차용).
NEW_STEMS = {"split_reveal_9x16", "ratio_dots_9x16", "vertical_timeline_9x16"}


def _thumb_b64(stem: str) -> str | None:
    for suf in ("__mid", "__end", "__early", ""):
        p = THUMBS / f"{stem}{suf}.png"
        if p.exists():
            return base64.b64encode(p.read_bytes()).decode("ascii")
    return None


def _is_self_bg(stem: str) -> bool:
    """템플릿이 .card를 안 쓰면(자체 panel 배경) card_opacity override가 no-op."""
    p = TEMPLATES / f"{stem}.html"
    if not p.exists():
        return False
    txt = p.read_text(encoding="utf-8", errors="ignore")
    return ('class="card"' not in txt) and ("class='card'" not in txt)


def _aspect_cls(aspect: str) -> str:
    return {"9:16": "a916", "16:9": "a169", "1:1": "a11"}.get(aspect, "a916")


def main() -> int:
    cat = json.loads(CATALOG.read_text(encoding="utf-8"))
    templates = cat["templates"]

    opaque, translucent = [], []
    for stem in sorted(templates):
        entry = templates[stem]
        op = _default_card_opacity(stem)
        rec = {
            "stem": stem,
            "aspect": entry.get("aspect", "9:16"),
            "opacity": op,
            "b64": _thumb_b64(stem),
            "new": stem in NEW_STEMS,
            "self_bg": _is_self_bg(stem),
            "hints": entry.get("scenario_hints", []),
        }
        (opaque if op >= 1.0 else translucent).append(rec)

    def card_html(r: dict) -> str:
        img = (f"<img src='data:image/png;base64,{r['b64']}'>" if r["b64"]
               else "<div class='noimg'>썸네일 없음</div>")
        badges = f"<span class='asp'>{r['aspect']}</span>"
        if r["new"]:
            badges += "<span class='new'>NEW</span>"
        note = ""
        if r["self_bg"] and r["opacity"] < 1.0:
            note = "<div class='note'>자체 배경 · card_opacity 무관</div>"
        hint = html.escape(r["hints"][0]) if r["hints"] else ""
        return (
            f"<div class='card{' newc' if r['new'] else ''}'>"
            f"<div class='thumb {_aspect_cls(r['aspect'])}'>{img}</div>"
            f"<div class='name'>{html.escape(r['stem'])}</div>"
            f"<div class='meta'>{badges}</div>"
            f"{note}"
            f"<div class='hint'>{hint}</div>"
            f"</div>"
        )

    op_cards = "".join(card_html(r) for r in opaque)
    tr_cards = "".join(card_html(r) for r in translucent)

    css = """
:root{--bg:#0e0e13;--panel:#17171f;--line:#2a2a36;--txt:#ececf2;--mut:#9b9bab;
--op:#5fb0ff;--tr:#B366FF;--new:#2af598;}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--txt);
font-family:"Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;line-height:1.55}
.wrap{max-width:1200px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:27px;margin:0 0 6px;letter-spacing:-.02em}
.sub{color:var(--mut);font-size:15px;margin:0 0 18px}
.principle{background:var(--panel);border:1px solid var(--line);border-radius:14px;
padding:15px 18px;font-size:14.5px;color:#d6d6e2;margin-bottom:26px}
.principle b{color:#fff}.legend{color:var(--mut);font-size:12.5px;margin-top:8px}
section{margin:30px 0}.sechead{display:flex;align-items:center;gap:10px;margin-bottom:14px;flex-wrap:wrap}
.sechead h2{font-size:20px;margin:0}.dot{width:13px;height:13px;border-radius:50%}
.dot.op{background:var(--op)}.dot.tr{background:var(--tr)}
.sechead .n{font-size:13px;color:#0e0e13;background:#cfcfe0;border-radius:99px;padding:2px 11px;font-weight:700}
.sechead .desc{color:var(--mut);font-size:13.5px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:13px;overflow:hidden;
display:flex;flex-direction:column}
.card.newc{border-color:var(--new)}
.thumb{position:relative;background-image:linear-gradient(45deg,#23232c 25%,transparent 25%),
linear-gradient(-45deg,#23232c 25%,transparent 25%),linear-gradient(45deg,transparent 75%,#23232c 75%),
linear-gradient(-45deg,transparent 75%,#23232c 75%);background-size:22px 22px;
background-position:0 0,0 11px,11px -11px,-11px 0;display:flex;align-items:center;justify-content:center}
.thumb img{max-width:100%;max-height:100%;display:block}
.thumb.a916 img{height:230px}.thumb.a169 img{width:100%}.thumb.a11 img{height:200px}
.thumb.a916,.thumb.a11{height:230px}.thumb.a169{height:150px}
.noimg{color:var(--mut);font-size:12px;padding:40px}
.name{font-size:13px;font-weight:700;padding:10px 12px 4px;word-break:break-all}
.meta{padding:0 12px;display:flex;gap:6px;flex-wrap:wrap}
.meta .asp{font-size:11px;background:#262633;color:#b9b9cc;border-radius:6px;padding:1px 8px}
.meta .new{font-size:11px;background:var(--new);color:#0e0e13;border-radius:6px;padding:1px 8px;font-weight:700}
.note{font-size:11.5px;color:#9af0cf;padding:4px 12px 0}
.hint{font-size:12px;color:var(--mut);padding:6px 12px 12px;min-height:14px}
""".strip()

    doc = (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>B-roll 모션 템플릿 투명/불투명 구분</title>"
        f"<style>{css}</style></head><body><div class='wrap'>"
        "<h1>B-roll 모션 템플릿 — 투명 / 불투명 구분</h1>"
        f"<p class='sub'>사용 가능 {len(templates)}개 · 불투명 {len(opaque)} · 반투명 {len(translucent)} · "
        f"신규 3종(split_reveal · ratio_dots · vertical_timeline) 추가 (2026-06-11)</p>"
        "<div class='principle'><b>원칙.</b> 실제 UI <b>화면</b>/디바이스/다이얼로그/알림 = "
        "<b style='color:var(--op)'>불투명(card_opacity 1.0)</b> — 화면은 실물 surface라 인물·배경이 비치면 깨져 보임. · "
        "영상 위에 띄우는 <b>장식·데이터·텍스트 카드/심볼</b> = <b style='color:var(--tr)'>반투명(0.62)</b> — 영상이 비쳐 레이어드. · "
        "B-roll은 <b>1:1(compact)</b> 또는 <b>9:16 풀프레임(리스트·비교·전환)</b> 선호, 16:9는 화면 native만."
        "<div class='legend'>※ 썸네일=템플릿 외형(기본 params), 체크무늬=투명영역. "
        "<b style='color:#9af0cf'>자체 배경</b> 표시 템플릿(신규 3종 등)은 .card 미사용이라 card_opacity override가 무관(자체 panel 배경대로 렌더). 모두 approved.</div></div>"
        "<section class='op'><div class='sechead'><span class='dot op'></span><h2>불투명 1.0</h2>"
        f"<span class='n'>{len(opaque)}개</span><span class='desc'>실제 앱/기기 <b>화면</b> · 디바이스 목업 · 댓글 모달 · OS 토스트</span></div>"
        f"<div class='grid'>{op_cards}</div></section>"
        "<section class='tr'><div class='sechead'><span class='dot tr'></span><h2>반투명 0.62</h2>"
        f"<span class='n'>{len(translucent)}개</span><span class='desc'>장식 · 데이터 · 텍스트/전환/비율 카드 · 심볼 (영상 위 레이어)</span></div>"
        f"<div class='grid'>{tr_cards}</div></section>"
        "</div></body></html>"
    )

    OUT.write_text(doc, encoding="utf-8")
    print(f"[done] {OUT}  (불투명 {len(opaque)} / 반투명 {len(translucent)} / 총 {len(templates)})")
    print(f"  신규 표시: {sorted(NEW_STEMS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
