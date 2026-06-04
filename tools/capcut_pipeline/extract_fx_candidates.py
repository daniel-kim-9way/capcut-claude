"""
extract_fx_candidates.py — CapCut draft analyzer that emits a ready-to-paste
fx_plan.json skeleton with sensible timings for `/capcut` Step 5.

Goal: remove the manual "eyeball emphasis timings" burden. Reads a draft,
finds the emphasis text track, scores each segment heuristically, picks the
top-K punches, and assembles a plan skeleton matching the 6-category schema
enforced by `capcut_fx_patcher.py` (filter/bgm/title_animation/outro_animation/
sfx/scene_effects).

The output is a STARTING POINT — operators can tweak timings/durations before
running `--verify-completeness`.

Usage:
  PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/extract_fx_candidates.py \
    --draft "$LOCALAPPDATA/CapCut/User Data/Projects/com.lveditor.draft/<name>/draft_content.json" \
    --top-k 6 \
    [--out temp/<name>/fx_plan.json]

Stdlib-only. ~300 LOC.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path


# ----- Local BGM library (path-mode skeleton) ------------------------------
# fx_patcher가 audios.json preset 대신 로컬 mp3 파일을 직접 주입하는 path 모드 지원.
# Skeleton은 5개 중 랜덤 픽 — LLM이 Step 5 자가 검증에서 영상 톤에 맞게 교체.
BGM_LIBRARY = [
    'BGM/After The Pause.mp3',   # 잔잔·여운
    'BGM/Midnight Receipt.mp3',  # 차분·지적·도시 야경
    'BGM/Shibuya Ledger.mp3',    # 도시감·트렌디·세련
    'BGM/Sunlit Cup.mp3',        # 밝음·따뜻·아침
    'BGM/window.mp3',            # 미니멀·잔잔·여백
]
BGM_DEFAULT_VOLUME_DB = -25  # MEMORY: feedback_capcut_bgm_local_path_minus25


def _pick_bgm_skeleton() -> dict:
    """Pick a random BGM from the local library at default -25dB.

    Skeleton fallback only — LLM should review and override `path` based on
    video tone using the cheat sheet in `.claude/commands/capcut.md` Step 5.
    """
    pick = random.choice(BGM_LIBRARY)
    return {
        'path': pick,
        'display_name': Path(pick).stem,
        'volume_db': BGM_DEFAULT_VOLUME_DB,
    }


# ----- Scoring heuristics --------------------------------------------------

# Digits including Korean-style numeric expressions. We also look for %, "배",
# and common "N만/억/천" quantifiers.
RE_DIGIT = re.compile(r'\d')
RE_NUM_KR = re.compile(r'(\d[\d,\.]*)\s*(배|%|퍼센트|만|억|천|개|원|건|년|월|일|명|시간|분|초)')
RE_COMPARISON = re.compile(r'(vs|VS|대비|반면|반대|차이|보다|↑|↓|↗|↘|→|←)')
RE_LIST_STARTER = re.compile(r'(\d+가지|\d+개(?:\s|의)|\d+단계|\d+번째|첫째|둘째|셋째)')
RE_CTA = re.compile(r'(댓글|남겨주|보내드|구독|좋아요|팔로우|알림|링크|DM|이메일로|이메일 주)')
RE_FILLER = re.compile(r'^(근데|그래서|그리고|그러니까|자|음|어|아|네)$')


def score_segment(text: str, start_sec: float, scene_boundaries: list[float]) -> tuple[int, list[str]]:
    """Score a single emphasis text segment. Returns (score, reasons)."""
    score = 0
    reasons: list[str] = []

    stripped = text.strip()

    # Digits / numbers / percent / 배
    if RE_NUM_KR.search(stripped):
        score += 5
        reasons.append('digits')
    elif RE_DIGIT.search(stripped):
        score += 3
        reasons.append('has-digits')

    # vs / comparison
    if RE_COMPARISON.search(stripped):
        score += 3
        reasons.append('comparison')

    # Scene boundary proximity (within 1.5s of any scene boundary)
    for b in scene_boundaries:
        if abs(b - start_sec) <= 1.5:
            score += 3
            reasons.append('scene-boundary')
            break

    # List starters
    if RE_LIST_STARTER.search(stripped):
        score += 2
        reasons.append('list-starter')

    # CTA keywords
    if RE_CTA.search(stripped):
        score += 4
        reasons.append('cta')

    # Filler / too short penalty
    if len(stripped) < 5:
        score -= 2
        reasons.append('short')
    if RE_FILLER.match(stripped):
        score -= 2
        reasons.append('filler')

    return score, reasons


# ----- Draft parsing -------------------------------------------------------

def _extract_text_content(material_text: dict) -> str:
    """CapCut stores text materials' visible text inside a JSON-encoded `content`."""
    raw = material_text.get('content', '')
    if not raw:
        return ''
    try:
        parsed = json.loads(raw)
        return parsed.get('text', '') or ''
    except Exception:
        return raw[:80]


def pick_emphasis_track(draft: dict) -> tuple[int, dict]:
    """Pick the track most likely to be the emphasis text track.

    Heuristic preference:
      1. text track with name == 'emphasis_text'
      2. text track with fewest segments (but >= 3)
      3. otherwise last text track
    Returns (track_index, track).
    """
    text_tracks = [(i, tr) for i, tr in enumerate(draft['tracks']) if tr.get('type') == 'text']
    if not text_tracks:
        raise ValueError('no text track found in draft')

    # Named match
    for i, tr in text_tracks:
        if tr.get('name') == 'emphasis_text':
            return i, tr

    # Fewest segs with >= 3
    candidates = [(i, tr) for i, tr in text_tracks if len(tr.get('segments', [])) >= 3]
    if candidates:
        candidates.sort(key=lambda it: len(it[1].get('segments', [])))
        return candidates[0]

    # Fallback: last text track (warn)
    return text_tracks[-1]


def load_scene_info(draft: dict) -> tuple[list[tuple[float, float]], float]:
    """Return (scene_timings, total_duration_sec) for main_video track (first video)."""
    for tr in draft['tracks']:
        if tr.get('type') == 'video':
            segs = tr.get('segments', [])
            out: list[tuple[float, float]] = []
            end = 0.0
            for s in segs:
                r = s.get('target_timerange', {})
                start = r.get('start', 0) / 1e6
                dur = r.get('duration', 0) / 1e6
                out.append((start, dur))
                end = max(end, start + dur)
            return out, end
    raise ValueError('no video track found')


# ----- Pick + skeleton -----------------------------------------------------

def pick_emphasis_segments(
    segs: list[dict],
    material_texts: dict,
    scene_boundaries: list[float],
    top_k: int,
    min_gap_sec: float,
) -> list[dict]:
    """Score, drop filler/neighbors, take top-K."""
    scored: list[dict] = []
    for seg in segs:
        r = seg.get('target_timerange', {})
        start_s = r.get('start', 0) / 1e6
        dur_s = r.get('duration', 0) / 1e6
        mat = material_texts.get(seg.get('material_id'), {})
        text = _extract_text_content(mat)
        if not text.strip():
            continue
        score, reasons = score_segment(text, start_s, scene_boundaries)
        scored.append({
            'start_sec': round(start_s, 3),
            'duration_sec': round(dur_s, 3),
            'text': text,
            'score': score,
            'reasons': reasons,
        })

    # Rank by score desc, tie-break by earlier start
    scored.sort(key=lambda x: (-x['score'], x['start_sec']))

    picked: list[dict] = []
    for cand in scored:
        if any(abs(cand['start_sec'] - p['start_sec']) < min_gap_sec for p in picked):
            continue
        picked.append(cand)
        if len(picked) >= top_k:
            break

    picked.sort(key=lambda x: x['start_sec'])
    return picked


def build_fx_plan(
    draft_path: Path,
    emphasis_picks: list[dict],
    scene_timings: list[tuple[float, float]],
    total_duration_sec: float,
) -> dict:
    """Assemble a complete fx_plan.json that passes --verify-completeness."""
    last_scene_idx = len(scene_timings) - 1

    # title_reveal moment: end of scene 0 (which is usually the short intro hook)
    # Fallback: 2.5s if scene 0 is unusually long.
    if scene_timings:
        scene_0_end = scene_timings[0][0] + scene_timings[0][1]
        title_reveal_sec = round(min(scene_0_end, 3.0), 2) if scene_0_end > 1.0 else 2.5
    else:
        title_reveal_sec = 2.5

    # Emphasis starts (rounded to hundredths)
    emphasis_starts = [round(p['start_sec'], 2) for p in emphasis_picks]

    # First emphasis = ui_notify (not tick), subsequent = tick
    # If the first pick IS the title (at 0.00s), use the SECOND as ui_notify anchor
    if emphasis_starts and emphasis_starts[0] < 0.5:
        intro_included = True
        first_emphasis_idx = 1 if len(emphasis_starts) > 1 else 0
    else:
        intro_included = False
        first_emphasis_idx = 0

    first_emphasis_sec = (
        emphasis_starts[first_emphasis_idx]
        if first_emphasis_idx < len(emphasis_starts)
        else round(title_reveal_sec + 5.0, 2)
    )
    remaining_emphasis = emphasis_starts[first_emphasis_idx + 1:]

    sfx_list: list[dict] = [
        {'preset': 'keyboard_typing', 'start_sec': 0.00, 'duration_sec': 1.87},
        {'preset': 'mouse_click',     'start_sec': title_reveal_sec, 'duration_sec': 0.77},
        {'preset': 'ui_notify',       'start_sec': first_emphasis_sec, 'duration_sec': 1.77},
    ]
    for s in remaining_emphasis:
        sfx_list.append({'preset': 'tick', 'start_sec': s, 'duration_sec': 0.87})

    scene_fx_list: list[dict] = [
        {'preset': 'flash_warm', 'start_sec': 0.00, 'duration_sec': 1.87},
        {'preset': 'math_rush',  'start_sec': title_reveal_sec, 'duration_sec': 3.00},
        {'preset': 'lens_zoom',  'start_sec': first_emphasis_sec, 'duration_sec': 5.63},
    ]
    for s in remaining_emphasis:
        scene_fx_list.append({'preset': 'lens_zoom', 'start_sec': s, 'duration_sec': 5.63})

    summary_items = []
    for p in emphasis_picks:
        reason_tag = p['reasons'][0] if p['reasons'] else 'misc'
        summary_items.append(f"{p['start_sec']:.2f}s {p['text'][:20]} ({reason_tag},sc:{p['score']})")

    plan: dict = {
        '_generated_by': 'extract_fx_candidates.py',
        '_draft': str(draft_path),
        '_draft_duration': f'{total_duration_sec:.2f}s ({len(scene_timings)} scenes)',
        '_emphasis_picks': summary_items,
        '_note': 'Skeleton — review timings and run --verify-completeness before patching.',
        'filter': {'preset': 'natural_ii', 'intensity': 0.3},
        'bgm': _pick_bgm_skeleton(),
        'title_animation': {'scene_idx': 0, 'preset': 'typewriter', 'duration_us': 1_400_000},
        'outro_animation': {'scene_idx': last_scene_idx, 'preset': 'typewriter'},
        'sfx': sfx_list,
        'scene_effects': scene_fx_list,
    }
    return plan


# ----- Main ----------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description='Analyze a CapCut draft and emit a ready-to-paste fx_plan.json skeleton.'
    )
    ap.add_argument('--draft', required=True, help='path to draft_content.json')
    ap.add_argument('--top-k', type=int, default=6, help='max emphasis picks (default 6)')
    ap.add_argument('--min-gap', type=float, default=5.0,
                    help='min seconds between picks to avoid clustering (default 5.0)')
    ap.add_argument('--out', help='output path for fx_plan.json; stdout if omitted')
    args = ap.parse_args()

    draft_path = Path(args.draft)
    if not draft_path.exists():
        print(f'[err] draft not found: {draft_path}', file=sys.stderr)
        return 2

    draft = json.loads(draft_path.read_text(encoding='utf-8'))

    scene_timings, total_duration_sec = load_scene_info(draft)
    scene_boundaries = [s for s, _ in scene_timings] + [
        scene_timings[-1][0] + scene_timings[-1][1]
    ] if scene_timings else []

    print(f'[analysis] {len(scene_timings)} scenes, {total_duration_sec:.2f}s duration',
          file=sys.stderr)

    track_idx, track = pick_emphasis_track(draft)
    segs = track.get('segments', [])
    print(f'[analysis] emphasis track: track[{track_idx}] '
          f'({len(segs)} segs, name={track.get("name","")!r})', file=sys.stderr)

    if track.get('name') != 'emphasis_text':
        print(f'[warn] track named {track.get("name","")!r} — not strictly emphasis_text. '
              'Review picks carefully.', file=sys.stderr)

    # Build material_id -> text material map (fast lookup)
    material_texts = {m['id']: m for m in draft['materials'].get('texts', [])}

    picks = pick_emphasis_segments(
        segs, material_texts, scene_boundaries,
        top_k=args.top_k, min_gap_sec=args.min_gap,
    )

    print(f'[picks] top {len(picks)}:', file=sys.stderr)
    for p in picks:
        reason_str = ','.join(p['reasons']) if p['reasons'] else '-'
        print(f"  {p['start_sec']:7.2f}s  {p['text'][:40]!r:42}  (score:{p['score']} - {reason_str})",
              file=sys.stderr)

    plan = build_fx_plan(draft_path, picks, scene_timings, total_duration_sec)
    plan_json = json.dumps(plan, ensure_ascii=False, indent=2)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(plan_json, encoding='utf-8')
        print(f'[written] {out_path}', file=sys.stderr)
        print('[next] run:', file=sys.stderr)
        print(f'  PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/capcut_fx_patcher.py '
              f'--plan {out_path} --verify-completeness', file=sys.stderr)
    else:
        print(plan_json)

    return 0


if __name__ == '__main__':
    sys.exit(main())
