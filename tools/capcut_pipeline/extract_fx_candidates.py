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
import hashlib
import json
import re
import sys
from pathlib import Path


# ----- Local BGM library (path-mode skeleton) ------------------------------
# fx_patcher가 audios.json preset 대신 로컬 mp3 파일을 직접 주입하는 path 모드 지원.
# Skeleton의 BGM은 LLM이 Step 5 자가 검증에서 영상 톤에 맞게 교체하는 게 원칙.
BGM_LIBRARY = [
    'BGM/After The Pause.mp3',   # 잔잔·여운
    'BGM/Midnight Receipt.mp3',  # 차분·지적·도시 야경
    'BGM/Shibuya Ledger.mp3',    # 도시감·트렌디·세련
    'BGM/Sunlit Cup.mp3',        # 밝음·따뜻·아침
    'BGM/window.mp3',            # 미니멀·잔잔·여백
]
BGM_DEFAULT_VOLUME_DB = -25  # MEMORY: feedback_capcut_bgm_local_path_minus25


def _pick_bgm_skeleton(seed: str = '') -> dict:
    """기본 BGM 1곡(-25dB)을 고른다. **결정론적** — 같은 영상 이름이면 항상 같은 곡.

    2026-06-11: random.choice → SHA1(seed) 기반으로 변경. 같은 드래프트를 다시
    돌려도 BGM이 바뀌지 않아 idempotent(fx_patcher no-op 철학)와 일치한다.
    이 값은 **폴백**일 뿐 — LLM이 Step 5에서 영상 톤에 맞춰 `path`를 덮어쓰는 게 원칙.
    """
    if seed:
        idx = int(hashlib.sha1(seed.encode('utf-8')).hexdigest(), 16) % len(BGM_LIBRARY)
    else:
        idx = 0
    pick = BGM_LIBRARY[idx]
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


def get_subtitle_cue_bounds(draft: dict) -> list[float]:
    """자막 트랙(가장 segment 많은 text 트랙)의 cue 시작·끝 시각 목록 = 자막이 바뀌는 경계.

    lens_zoom 시작/끝을 여기에 스냅해 '자막 바뀌는 타이밍에 끊기게' 한다. 드래프트 좌표계
    (offset 적용 후)라 emphasis pick과 동일 좌표.
    """
    text_tracks = [tr for tr in draft.get('tracks', []) if tr.get('type') == 'text']
    if not text_tracks:
        return []
    sub = max(text_tracks, key=lambda tr: len(tr.get('segments', [])))
    bounds: set[float] = set()
    for s in sub.get('segments', []):
        r = s.get('target_timerange', {})
        st = r.get('start', 0) / 1e6
        du = r.get('duration', 0) / 1e6
        bounds.add(round(st, 3))
        bounds.add(round(st + du, 3))
    return sorted(bounds)


def get_broll_overlay_windows(draft: dict) -> list[tuple[float, float]]:
    """B-roll 모션 overlay 세그먼트의 [start, end] 윈도우 목록.

    lens_zoom(scene effect)이 이 구간과 겹치면 overlay까지 줌이 걸려 어색하므로, 이 윈도우와
    겹치는 zoom은 배치하지 않는다(사용자 피드백 2026-06-11). 드래프트 좌표계.
    """
    vids = {m['id']: m for m in draft.get('materials', {}).get('videos', [])}
    wins: list[tuple[float, float]] = []
    for tr in draft.get('tracks', []):
        if tr.get('type') != 'video':
            continue
        for s in tr.get('segments', []):
            m = vids.get(s.get('material_id'), {})
            p = str(m.get('path', '') or '').lower()
            if 'motion' in p or 'broll' in p:
                r = s.get('target_timerange', {})
                st = r.get('start', 0) / 1e6
                du = r.get('duration', 0) / 1e6
                wins.append((st, st + du))
    return wins


def _snap_zoom_to_cues(anchor: float, cue_bounds: list[float],
                       min_dur: float, max_dur: float) -> tuple[float, float]:
    """zoom 시작을 anchor 직전 cue 경계로, 끝을 (시작+min_dur) 이상인 첫 cue 경계로 스냅.

    반환 (start_sec, duration_sec). 자막 cue가 없으면 anchor + min_dur로 폴백.
    duration은 항상 ≥ min_dur (1.2배속 후 ≥1.5s 보장하도록 min_dur=1.8 권장).
    """
    if not cue_bounds:
        return round(max(0.0, anchor), 2), round(min_dur, 2)
    befores = [c for c in cue_bounds if c <= anchor + 0.15]
    z_start = befores[-1] if befores else anchor
    afters = [c for c in cue_bounds if c >= z_start + min_dur]
    if afters and afters[0] <= z_start + max_dur + 0.6:
        z_end = afters[0]
    else:
        z_end = z_start + min_dur
    return round(max(0.0, z_start), 2), round(z_end - z_start, 2)


def build_fx_plan(
    draft_path: Path,
    emphasis_picks: list[dict],
    scene_timings: list[tuple[float, float]],
    total_duration_sec: float,
    cue_bounds: list[float] | None = None,
    broll_windows: list[tuple[float, float]] | None = None,
) -> dict:
    """Assemble a complete fx_plan.json that passes --verify-completeness."""
    cue_bounds = cue_bounds or []
    broll_windows = broll_windows or []
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

    # closer-suppression (2026-06-11): 마지막 emphasis(보통 CTA "댓글에 X")는 SFX sting 없이
    #   조용히 닫는다 — 닫는 순간의 여운. 시각 강조(lens_zoom scene_effect)는 그대로 유지.
    closer_sec = emphasis_starts[-1] if emphasis_starts else None
    if closer_sec is not None:
        sfx_list = [s for s in sfx_list if abs(s['start_sec'] - closer_sec) > 0.01]

    # de-dup (2026-06-11): 0.05s 이내 SFX 중복 제거 (같은 시점이 인트로/타이틀/emphasis로
    #   동시 유발될 때 '띡띡' 겹침 방지). 시간순 정렬 후 앞엣것 유지.
    sfx_list.sort(key=lambda x: x['start_sec'])
    _deduped: list[dict] = []
    for s in sfx_list:
        if _deduped and abs(s['start_sec'] - _deduped[-1]['start_sec']) < 0.05:
            continue
        _deduped.append(s)
    sfx_list = _deduped

    # 2026-06-08 사용자 결정: 시작 '미지근한 플래시(flash_warm)' 제거. 오프닝 강조는
    # intro_video_animation(첫 클립 사이드 슬라이드)이 담당. scene_effects는 lens_zoom 중심.
    #
    # lens_zoom 배치 규칙 (2026-06-11 사용자 피드백 반영):
    #   ① 모든 lens_zoom은 **자막 cue 경계에 스냅** → 자막 바뀌는 타이밍에 시작·끝(끊김 자연스러움).
    #   ② 최소 길이 1.8s clean = **1.2배속 후 ≥1.5s** (과거 seam 0.6s→0.5s 어색 해소).
    #   ③ **겹침 금지** — emphasis zoom(우선) 먼저 배치 후, 컷 seam zoom(cover-the-cut)은
    #      이미 놓인 zoom/math_rush 구간과 안 겹칠 때만 추가. 과거 SEAM_GUARD가 시작거리만 봐서
    #      긴 emphasis zoom 구간 안에 짧은 seam이 박히던 중복 버그 해소.
    MIN_ZOOM = 1.8   # clean (1.2배속 후 1.5s)
    MAX_ZOOM = 4.0   # clean — 너무 긴 zoom 방지
    ZOOM_GAP = 1.5   # lens_zoom 사이 최소 간격(clean) — 인접/연속 줌 방지(사용자 피드백 2026-06-11)

    scene_fx_list: list[dict] = [
        {'preset': 'math_rush', 'start_sec': title_reveal_sec, 'duration_sec': 3.00},
    ]
    # placed: 하드 겹침 검사용(math_rush 포함). placed_zooms: lens_zoom끼리 GAP 검사용(연속 방지).
    placed: list[tuple[float, float]] = [(title_reveal_sec, title_reveal_sec + 3.0)]
    placed_zooms: list[tuple[float, float]] = []
    # emphasis zoom 우선, 그다음 컷 seam(cover-the-cut). 첫 씬(0)은 intro 애니가 담당 → 제외.
    emphasis_anchors = [first_emphasis_sec] + list(remaining_emphasis)
    seam_anchors = sorted(round(s, 2) for s, _ in scene_timings[1:])

    # ⭐ 영상 cut(씬 경계) > 자막 cue (사용자 우선순위 2026-06-11): 줌이 영상 컷을 넘으면 안 된다.
    #   줌을 anchor가 속한 씬 [sc_s, sc_e] 안에 가둔다 — 컷을 넘으면 그 컷에서 줌 종료, 컷 이전으로
    #   시작 못 함. 컷에 막혀 너무 짧아지면(< MIN_ZOOM_AT_CUT) skip.
    MIN_ZOOM_AT_CUT = 1.2  # clean. 컷에 막혀 이보다 짧으면 제대로 된 줌 불가 → 배치 안 함.

    def _scene_of(a: float) -> tuple[float, float]:
        for s, d in scene_timings:
            if s - 0.01 <= a < s + d:
                return s, s + d
        s, d = scene_timings[-1]
        return s, s + d

    for kind, anchors in (('emphasis', emphasis_anchors), ('seam', seam_anchors)):
        for anchor in anchors:
            sc_s, sc_e = _scene_of(anchor)
            zs, zd = _snap_zoom_to_cues(anchor, cue_bounds, MIN_ZOOM, MAX_ZOOM)
            zs = max(zs, round(sc_s, 2))          # 씬 시작(앞 컷) 이전으로 못 감
            ze = min(zs + zd, round(sc_e, 2))     # 씬 끝(다음 컷) 넘으면 거기서 종료
            zd = round(ze - zs, 2)
            if zd < MIN_ZOOM_AT_CUT:
                continue  # 컷이 너무 가까워 제대로 된 줌 불가
            if any(zs < pe and ze > ps for ps, pe in placed):
                continue  # 하드 겹침(math_rush 등)과 충돌
            # 다른 lens_zoom과 GAP 미만으로 인접하면 skip — 줌이 딱 붙어 연속으로 보이는 것 방지.
            if any(zs < pe + ZOOM_GAP and ze > ps - ZOOM_GAP for ps, pe in placed_zooms):
                continue
            # B-roll overlay 구간(±0.3s)과 겹치면 skip — overlay까지 줌이 걸려 어색한 것 방지.
            if any(zs < we + 0.3 and ze > ws - 0.3 for ws, we in broll_windows):
                continue
            scene_fx_list.append({'preset': 'lens_zoom', 'start_sec': zs, 'duration_sec': zd})
            placed.append((zs, ze))
            placed_zooms.append((zs, ze))
    scene_fx_list.sort(key=lambda x: x['start_sec'])

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
        'bgm': _pick_bgm_skeleton(draft_path.parent.name),  # 결정론 폴백(영상명 기반). LLM이 톤으로 덮어씀
        # ⭐ 사용자 결정: 시작 타자기(title_animation typewriter) 제거 → 첫 클립 in-animation으로
        #    대체. 2026-06-11 사용자 결정: '줌1'(zoom_in) 대신 '사이드 슬라이드'(side_slide).
        #    첫 클립(scene 0)에만 적용. title/outro_animation은 기본 미사용.
        'intro_video_animation': {'scene_idx': 0, 'preset': 'side_slide', 'duration_us': 400_000},
        'sfx': sfx_list,
        'scene_effects': scene_fx_list,
        # ⭐ 전역 배속 (사용자 결정 2026-06-08, 기존 1.15 → 1.2): CapCut '전체 선택 → 1.2배속'
        #    자동 재현. fx_patcher가 마지막에 모든 트랙(영상·자막·B-roll·SFX·BGM)을 1/speed로
        #    압축. 배속 원치 않으면 1.0으로 변경.
        'speed': 1.2,
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

    cue_bounds = get_subtitle_cue_bounds(draft)
    broll_windows = get_broll_overlay_windows(draft)
    print(f'[analysis] subtitle cue bounds: {len(cue_bounds)} (lens_zoom 스냅용), '
          f'b-roll overlay windows: {len(broll_windows)} (zoom 회피)', file=sys.stderr)
    plan = build_fx_plan(draft_path, picks, scene_timings, total_duration_sec,
                         cue_bounds, broll_windows)
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
