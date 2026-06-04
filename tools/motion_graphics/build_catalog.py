"""
Build sample_catalog.json — SoT for which motion templates are available
for LLM-driven B-roll planning.

Pipeline:
  1. Scan templates/*.html for available HTML+GSAP motion templates.
  2. Match each template stem to a sample MOV under out/ using:
       a. Direct: out/sample_<stem>.mov
       b. Alias dict (smoke_*, regression_*, sample_<short>_*)
  3. Extract 3 thumbnail PNGs from each matched MOV at t=0.5s / mid / end
     into out/thumbs/<stem>_t<*>.png — LLM Read these to visually verify
     a motion before selecting it in _claude_broll_plan.json.
  4. Parse params_schema from `window.__params || { ... }` in each HTML.
  5. Mark templates without sample MOV as `user_approved: false`
     (= deprecated, sample was deleted by user → "별로" → use forbidden).
  6. Write sample_catalog.json.

The catalog is read by scene_designer.py context to inject sample paths
into broll_designer_context.md so the LLM picks motions only from the
user-approved set, and verifies each pick by Read-ing the thumbnails.

Run:
    PYTHONIOENCODING=utf-8 python tools/motion_graphics/build_catalog.py

When to rebuild:
  - When you add a new motion template (templates/*.html)
  - When you render a new sample MOV (out/sample_*.mov, out/smoke_*.mov)
  - When you delete a sample MOV (user-curation: "this template is too generic/boring")
  - Before each /capcut Step 3-A (idempotent; cheap if no changes)

Companion files:
  - tools/motion_graphics/sample_catalog.json — SoT output
  - tools/motion_graphics/out/thumbs/<stem>__{early,mid,end}.png — 3 thumbs/template
  - tools/capcut_pipeline/scene_designer.py — reads catalog in build_context + ingest

CHANGELOG:
  2026-05-13: Initial — user feedback "맨날 똑같은 것만 써. 샘플 확인하고 있는거 맞아?"
              → catalog forces LLM to Read thumbs before picking. forbidden ingest reject.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
TEMPLATES_DIR = HERE / "templates"
OUT_DIR = HERE / "out"
THUMBS_DIR = OUT_DIR / "thumbs"
CATALOG_PATH = HERE / "sample_catalog.json"

# Alias map: sample filename stem (no .mov) → template stem.
# Used when sample file name diverges from the template HTML file name.
# Keep additions here when new naming conventions appear in out/.
SAMPLE_ALIAS = {
    # smoke_* (smoke test renders for newer templates)
    "smoke_aurora_16x9": "text_hero_aurora_16x9",
    "smoke_beam_16x9": "animated_beam_16x9",
    "smoke_bar_chart_16x9": "bar_chart_16x9",
    "smoke_marquee_16x9": "logo_marquee_16x9",
    "smoke_orbit_1x1": "orbiting_circles_1x1",
    "smoke_text_sparkles_1x1": "text_hero_sparkles_1x1",
    "smoke_toast_9x16": "toast_notification_9x16",
    "smoke_code_editor_16x9": "ui_evidence_code_editor_16x9",
    # regression_* (regression tests pin known-good renders)
    "regression_kt_9x16": "ui_evidence_kakaotalk_9x16",
    "regression_stat_16x9": "stat_card_16x9",
    # sample_* with shortened stem (ui_evidence_ prefix dropped)
    "sample_claude_code_16x9": "ui_evidence_claude_code_16x9",
    "sample_claude_code_welcome_16x9": "ui_evidence_claude_code_welcome_16x9",
    "sample_discord_16x9": "ui_evidence_discord_16x9",
    "sample_discord_9x16": "ui_evidence_discord_9x16",
    "sample_finder_16x9": "ui_evidence_finder_16x9",
    "sample_instagram_dm_9x16": "ui_evidence_instagram_dm_9x16",
    "sample_notion_16x9": "ui_evidence_notion_16x9",
    "sample_slack_16x9": "ui_evidence_slack_16x9",
    "sample_slack_9x16": "ui_evidence_slack_9x16",
    "sample_terminal_16x9": "ui_evidence_terminal_16x9",
    "sample_youtube_comment_16x9": "ui_evidence_youtube_comment_16x9",
    "sample_youtube_comment_9x16": "ui_evidence_youtube_comment_9x16",
    # sample_* with file_ (no ui_evidence prefix on icon_*)
    "sample_file_1x1": "icon_file_1x1",
}

# Scenario hints per template (from capcut-broll SKILL.md cheat sheet).
# These guide the LLM at plan-time: "what kind of narration matches this motion?"
SCENARIO_HINTS = {
    "text_hero_aurora_16x9": ["결정적 한 줄 강조", "감정 톤 결론", "6색 aurora gradient sweep"],
    "text_hero_sparkles_1x1": ["결정적 한 단어", "성공·축하·결정", "파티클 twinkle"],
    "animated_beam_16x9": ["A → B 데이터 흐름", "API 통합", "두 노드 연결 + glowing dot"],
    "logo_marquee_16x9": ["여러 도구·플랫폼 무한 스크롤", "지원 플랫폼 strip"],
    "orbiting_circles_1x1": ["에코시스템", "통합 도구 군집", "중앙 hub + 위성 회전"],
    "bar_chart_16x9": ["카테고리 비교", "월별·분기별·항목별 막대"],
    "line_chart_16x9": ["매출·성장·추세 (시간축)", "SVG line draw + 카운트업"],
    "stat_card_16x9": ["숫자 before→after 가로 bar"],
    "stat_card_1x1": ["숫자 before→after 정사각 카드"],
    "stat_card_9x16": ["숫자 before→after 세로 풀스크린"],
    "metric_ring_1x1": ["퍼센트·진행률·달성률 원형 게이지"],
    "graphic_insight_16x9": ["체크리스트 (3-4 item) 가로 다이어그램", "보라 체크박스 순차 체크"],
    "graphic_insight_1x1": ["체크리스트 정사각 (3-4 item)"],
    "avatar_group_1x1": ["N명 사용 중 군집 + 카운트업"],
    "toast_notification_9x16": ["시스템 OS-level 토스트 (앱 메시지 X)"],
    "ai_chat_bubble_16x9": ["일반 AI 챗 UI (ChatGPT/Claude 챗)"],
    "icon_hero_1x1": ["브랜드 로고 단독 언급 hero"],
    "icon_claude_1x1": ["Anthropic Claude starburst 로고"],
    "icon_file_1x1": ["파일·PDF·문서 (확장자 강조)"],
    "dual_icon_1x1": ["두 브랜드 vs 비교 (텍스트 심볼)"],
    "dual_brand_1x1": ["두 브랜드 진짜 SVG 로고 비교"],
    "pricing_card_1x1": ["Pricing tier ('Pro 플랜에선')"],
    "message_object_16x9": ["빈 말풍선 심볼 (카톡/DM 왔어요)"],
    "message_object_9x16": ["빈 말풍선 심볼 세로"],
    "ui_evidence_kakaotalk_16x9": ["카톡 (16:9 특수)"],
    "ui_evidence_kakaotalk_9x16": ["카톡 모바일 native (9:16)"],
    "ui_evidence_youtube_comment_16x9": ["YouTube 댓글 + CTA (데스크톱)"],
    "ui_evidence_youtube_comment_9x16": ["YouTube 댓글 + CTA (모바일)"],
    "ui_evidence_instagram_dm_9x16": ["Instagram DM 모바일"],
    "ui_evidence_notion_16x9": ["Notion 문서 / 회의록"],
    "ui_evidence_terminal_16x9": ["Terminal / CLI 명령어 시연"],
    "ui_evidence_finder_16x9": ["Finder / 파일 탐색기"],
    "ui_evidence_slack_16x9": ["Slack 워크스페이스 (데스크톱)"],
    "ui_evidence_slack_9x16": ["Slack 모바일"],
    "ui_evidence_discord_16x9": ["Discord 서버 (다크 테마)"],
    "ui_evidence_discord_9x16": ["Discord 모바일"],
    "ui_evidence_claude_code_16x9": ["Claude Code 작업 세션 (Thinking + tool calls)"],
    "ui_evidence_claude_code_welcome_16x9": ["Claude Code 시작 화면"],
    "ui_evidence_code_editor_16x9": ["VSCode/Cursor IDE 코드 시연"],
    "ui_evidence_tweet_1x1": ["X (Twitter) testimonial / 인용"],
}


def parse_aspect_from_stem(stem: str) -> tuple[str, tuple[int, int]]:
    """`text_hero_aurora_16x9` → ('16:9', (1920, 1080))."""
    if stem.endswith("_16x9"):
        return "16:9", (1920, 1080)
    if stem.endswith("_9x16"):
        return "9:16", (1080, 1920)
    if stem.endswith("_1x1"):
        return "1:1", (1080, 1080)
    return "unknown", (1920, 1080)


PARAM_KEY_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*:', re.MULTILINE)


def parse_params_schema(html_path: Path) -> list[str]:
    """Heuristic: pull top-level keys out of `window.__params || { ... }`.

    Not a real JS parser — just finds top-level `key: ...` lines inside the
    first `||\\s*{ ... };` block. Good enough for our templates.
    """
    raw = html_path.read_text(encoding="utf-8")
    m = re.search(r"window\.__params\s*\|\|\s*\{(.*?)\};", raw, flags=re.DOTALL)
    if not m:
        return []
    block = m.group(1)
    # Only keep top-level keys (not nested inside arrays/objects)
    keys: list[str] = []
    depth = 0
    cur_line = ""
    for ch in block:
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth = max(0, depth - 1)
        if ch == "\n":
            if depth == 0:
                mk = PARAM_KEY_RE.match(cur_line)
                if mk:
                    keys.append(mk.group(1))
            cur_line = ""
        else:
            cur_line += ch
    # also check last buffered line
    if cur_line and depth == 0:
        mk = PARAM_KEY_RE.match(cur_line)
        if mk:
            keys.append(mk.group(1))
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out


def probe_mov_duration(mov_path: Path) -> float | None:
    """ffprobe duration in seconds. None on failure."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(mov_path),
            ],
            capture_output=True, text=True, check=True,
        )
        return float(r.stdout.strip())
    except (subprocess.CalledProcessError, ValueError):
        return None


def extract_thumb(mov_path: Path, ts: float, out_png: Path) -> bool:
    """ffmpeg: extract 1 frame at ts seconds. Returns True on success."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-ss", f"{ts:.3f}",
                "-i", str(mov_path),
                "-frames:v", "1",
                "-q:v", "2",
                str(out_png),
            ],
            check=True, capture_output=True,
        )
        return out_png.exists() and out_png.stat().st_size > 0
    except subprocess.CalledProcessError:
        return False


def discover_samples() -> dict[str, dict]:
    """Walk out/ and map each motion sample file → its template stem.

    Returns: { template_stem: {"mov": Path|None, "mp4": Path|None, "src_stem": str} }
    """
    result: dict[str, dict] = {}
    if not OUT_DIR.exists():
        return result

    # Collect both .mov and .mp4 per source stem
    mov_files = {p.stem: p for p in OUT_DIR.glob("*.mov")}
    mp4_files = {p.stem: p for p in OUT_DIR.glob("*.mp4")}

    all_stems = set(mov_files.keys()) | set(mp4_files.keys())
    for src_stem in sorted(all_stems):
        # 1) explicit alias
        tpl_stem = SAMPLE_ALIAS.get(src_stem)
        if tpl_stem is None:
            # 2) direct: `sample_<stem>` → strip `sample_`
            if src_stem.startswith("sample_"):
                candidate = src_stem[len("sample_") :]
                if (TEMPLATES_DIR / f"{candidate}.html").exists():
                    tpl_stem = candidate
            # 3) `scene_*` is a per-video render, not a generic sample → skip
            elif src_stem.startswith("scene_"):
                continue
        if tpl_stem is None:
            # Unknown sample file; skip (don't error — user may add new patterns)
            continue
        # First sample wins; later samples for same template are ignored
        if tpl_stem in result:
            continue
        result[tpl_stem] = {
            "mov": mov_files.get(src_stem),
            "mp4": mp4_files.get(src_stem),
            "src_stem": src_stem,
        }
    return result


def main() -> int:
    if not TEMPLATES_DIR.exists():
        print(f"[error] templates dir not found: {TEMPLATES_DIR}")
        return 2
    THUMBS_DIR.mkdir(parents=True, exist_ok=True)

    templates = sorted(p.stem for p in TEMPLATES_DIR.glob("*.html"))
    samples = discover_samples()

    print(f"[scan] templates: {len(templates)}")
    print(f"[scan] sample-mapped templates: {len(samples)}")

    catalog: dict = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "thumbs_dir": str(THUMBS_DIR.relative_to(HERE.parent.parent).as_posix()),
        "templates": {},
        "deprecated": [],
        "no_sample_yet": [],
    }

    for stem in templates:
        aspect, (w, h) = parse_aspect_from_stem(stem)
        html_path = TEMPLATES_DIR / f"{stem}.html"
        params = parse_params_schema(html_path)
        hints = SCENARIO_HINTS.get(stem, [])

        entry: dict = {
            "template_path": str(html_path.relative_to(HERE.parent.parent).as_posix()),
            "aspect": aspect,
            "viewport": [w, h],
            "scenario_hints": hints,
            "params_schema": params,
            "user_approved": False,
            "sample_mov": None,
            "sample_mp4": None,
            "frame_thumbs": [],
        }

        sample = samples.get(stem)
        if sample:
            entry["user_approved"] = True
            if sample["mov"]:
                entry["sample_mov"] = str(sample["mov"].relative_to(HERE.parent.parent).as_posix())
            if sample["mp4"]:
                entry["sample_mp4"] = str(sample["mp4"].relative_to(HERE.parent.parent).as_posix())

            # Thumb extraction: prefer mp4 (no alpha key needed, faster decode)
            src = sample["mp4"] or sample["mov"]
            duration = probe_mov_duration(src) or 5.0
            stops = {
                "early": min(0.5, duration * 0.1),
                "mid":   duration * 0.5,
                "end":   max(0.0, duration - 0.3),
            }
            thumbs: list[str] = []
            for label, ts in stops.items():
                thumb_path = THUMBS_DIR / f"{stem}__{label}.png"
                ok = extract_thumb(src, ts, thumb_path)
                if ok:
                    thumbs.append(str(thumb_path.relative_to(HERE.parent.parent).as_posix()))
                    print(f"  [thumb] {stem} @{ts:.2f}s → {thumb_path.name}")
                else:
                    print(f"  [warn] thumb extract failed: {stem} @{ts:.2f}s")
            entry["frame_thumbs"] = thumbs
            catalog["templates"][stem] = entry
        else:
            # No sample MOV → either user deleted it (deprecated) or never made yet.
            # We can't distinguish here, but we mark as "no_sample_yet" and let
            # the LLM treat both equally: forbidden until sample exists.
            entry["user_approved"] = False
            catalog["templates"][stem] = entry
            catalog["no_sample_yet"].append(stem)

    # deprecated list = templates without sample but with scenario hints
    # (heuristic: these are templates that "exist on paper" but unverified)
    catalog["deprecated"] = [s for s in catalog["no_sample_yet"] if s in SCENARIO_HINTS]

    CATALOG_PATH.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    approved = sum(1 for v in catalog["templates"].values() if v["user_approved"])
    print()
    print(f"[done] catalog written: {CATALOG_PATH}")
    print(f"  total templates: {len(catalog['templates'])}")
    print(f"  user_approved (sample exists): {approved}")
    print(f"  no_sample_yet (forbidden until sample built): {len(catalog['no_sample_yet'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
