"""
plan_generator.py — DEPRECATED SKELETON WRAPPER (as of 2026-04-22).

⚠️  This module used to be a rule-based B-roll planner. The ruleset produced
    inconsistent results — e.g. the emphasis text "47 : 1  vs  6 : 4" was
    misclassified as a G5 list instead of the obvious stat_card candidate,
    yielding 0 B-roll overlays for a video that clearly needed 3. See:
    `~/.claude/projects/.../memory/feedback_plan_by_llm_not_rules.md`.

    B-roll planning is now handled DIRECTLY by Claude (Opus 4.7) at the
    /capcut command's Step 3-A. Read `.claude/skills/capcut-broll/SKILL.md`
    and `.claude/commands/capcut.md` for the authoritative flow.

    This CLI is kept ONLY as a last-resort skeleton generator invoked with
    `--fallback-skeleton`. The skeleton is a zero-overlay plan: every scene
    gets `decision: skip`, and any emphasis text already present in the
    draft's text track is mapped to a `text_only` decision on the
    corresponding scene. Title is preserved from the draft if available.

    Invoking the CLI without `--fallback-skeleton` prints a migration
    message and exits with code 2. The legacy rule-based generator code is
    still in this file (see `_legacy_rule_based_main`) but is not reachable
    from the CLI. Do not resurrect it — the rules are known-bad.

---

Legacy reference (what this module USED to do):
Codified the DECISION_TREE in scene_designer.py (L92-135) as executable
classification rules, so the broll plan could be produced deterministically
from transcript + scenes + draft inputs — no Claude intervention needed.

Input:
  - transcript.json          (word-level timestamps, from Whisper)
  - transcript_wrapped.srt   (cue-level, corrected)
  - scenes.json              (scene boundaries)
  - draft_content.json       (emphasis_text track — the pre-curated emphasis points)
  - brand_registry.json      (registered brands)

Output:
  _claude_broll_plan.json in the schema expected by scene_designer.py ingest:
    {
      "title": {...},
      "scenes": [
        {"scene_idx": N, "decision": "...", "broll": {...}, "emphasis": {...}}
      ]
    }

Design principle (2026-04-21 revised — 시각 자산 전용):
  B-roll은 "emphasis 텍스트로는 절대 전달 불가능한 시각 정보"일 때만 생성.
  다음 중 하나에 해당해야 함:
    1. 실제 브랜드 로고 (icon_hero)
    2. 실제 앱 스크린샷 + 특정 데이터 (ui_evidence) — 최우선
    3. 메시지 말풍선 상징 (message_object)
    4. 숫자 before/after 차이 극적 (stat_card)
    5. 양쪽 브랜드 비교 (dual_icon)
    6. 추상 개념 flat 그래픽 (graphic_insight) — 신중히

  아래는 모두 `text_only` (B-roll 불필요):
    - 단일 숫자 강조 ("4개뿐이에요", "30초면 충분")
    - 단어 리스트 ("서버·DB·결제") — emphasis 순차로 충분
    - 개념/정의 term ("자이가르닉 효과")
    - 리스트 인트로 ("3가지 행동")

Usage:
  PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/plan_generator.py \\
    --name PROMPTER_20260417_161755 \\
    --out temp/PROMPTER_20260417_161755/_claude_broll_plan.json

Stdlib only + imports broll_prompts for TYPES / brand_registry.

Type whitelist (2026-04-21 revised — split_stack 제거):
  icon_hero / stat_card / message_object / dual_icon /
  ui_evidence / graphic_insight
  (symbol_moment / number_hero / split_stack 제거 — text_only 또는
   해당 시각 자산 타입으로.)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# Local import
HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
from broll_prompts import TYPES, load_brand_registry  # noqa: E402

ROOT = HERE.parent.parent


# ===== Heuristic detectors =====================================================

# Number pattern — digits + optional thousands-separator + optional unit
RE_NUM = re.compile(r'\d[\d,\.]*')
RE_NUM_WITH_UNIT = re.compile(
    r'(\d[\d,\.]*)\s*(분|초|시간|일|개|명|원|퍼센트|%|배|만|억|천|건|회|가지|번째|줄|페이지)'
)

# Number-compare patterns: "A → B", "A에서 B으로", "A에서 B로", "A vs B"
RE_COMPARE_ARROW = re.compile(r'(\d[\d,\.]*[^\d→]*?)\s*(?:→|->)\s*(\d[\d,\.]*)')
RE_COMPARE_ESEO = re.compile(
    r'(\d[\d,\.]*[^\s]*?)\s*에서\s*(\d[\d,\.]*[^\s]*?)\s*(?:으로|로)'
)
RE_COMPARE_VS = re.compile(r'([가-힣A-Za-z]+)\s*(?:vs|VS|대|vs\.)\s*([가-힣A-Za-z]+)')

# List items — comma-separated in a single utterance
# Korean: "A, B, C" or "A·B·C" or "A 그리고 B 그리고 C"
RE_LIST_COMMA = re.compile(r'([가-힣A-Za-z0-9]+(?:\s[가-힣A-Za-z0-9]+)?)')
RE_LIST_FIRST_ORDINAL = re.compile(r'(첫\s*번째|첫째|1\)\s?|1\.\s?)')
RE_LIST_ORDINALS = [
    re.compile(r'(첫\s*번째|첫째)[^가-힣]{0,3}([가-힣A-Za-z0-9 ]{2,12})'),
    re.compile(r'(두\s*번째|둘째)[^가-힣]{0,3}([가-힣A-Za-z0-9 ]{2,12})'),
    re.compile(r'(세\s*번째|셋째)[^가-힣]{0,3}([가-힣A-Za-z0-9 ]{2,12})'),
    re.compile(r'(네\s*번째|넷째)[^가-힣]{0,3}([가-힣A-Za-z0-9 ]{2,12})'),
]

# "N가지" / "N개" explicit count in emphasis  →  expect list ahead
RE_COUNT_HINT = re.compile(r'(\d+)\s*(가지|개|단계|번째|줄)')

# Message / alert platforms
MSG_PLATFORMS = {
    'kakaotalk': ['카톡', '카카오톡'],
    'instagram': ['DM', '인스타', 'Instagram', '인스타그램', '메세지', '메시지'],
    'gmail': ['이메일', 'Gmail', '지메일'],
    'slack': ['슬랙', 'Slack'],
    'discord': ['디스코드', 'Discord'],
}

# Concept / definition terms (domain vocabulary that emphasis alone is enough)
CONCEPT_TERMS = [
    '자이가르닉', '앵커링', '파킨슨', '도파민', '세로토닉', '세로토닌', '코르티솔',
    '플라시보', '던닝크루거', '피그말리온', '할로', '밴드웨건',
    '효과', '법칙', '원리', '이론', '증후군',
]

# Anti-pattern phrases — narration style that should NOT get B-roll
# A2: abstract hook questions
RE_ABSTRACT_HOOK = re.compile(
    r'(왜\s*[가-힣]+\s*(?:까|요|죠|지)|어떻게\s*[가-힣]+\s*(?:까|요|죠|지)|'
    r'이게\s*바로|이런\s*경험|혹시\s*[가-힣]+|한번\s*생각|'
    r'뭐\s*해야\s*하[더지]라|뭐\s*하[더지]라|뭐\s*더라|뭐지\?)'
)
# A3: narrative setup
RE_NARRATIVE_SETUP = re.compile(
    r'(어떤\s*사람이|한\s*[가-힣]+이\s*있었|예전에|그\s*때|어느\s*날)'
)
# A5: pronoun/demonstrative only
RE_PRONOUN_ONLY = re.compile(r'^(이게|저게|그게|이건|저건|그건|이거|저거|그거)')
# A6: filler
RE_FILLER_ONLY = re.compile(
    r'^(근데|그런데|사실은?|그래서|그리고|그러니까|자,?|음|어|아|네)\s*$'
)


def detect_brand(text: str, registry: dict) -> str | None:
    """Return brand_key if any registered brand mentioned in text.

    Matches both the key (english) and the display name (may be Korean).
    """
    for key, brand in registry.get('brands', {}).items():
        if key.lower() in text.lower():
            return key
        display = brand.get('display', '')
        if display and display in text:
            return key
        # Also check for Korean synonyms not in display (e.g., "노션" for notion)
        # Hardcoded aliases for common brands where display != common usage
        aliases = {
            'notion': ['노션'],
            'kakaotalk': ['카톡', '카카오톡', '카카오'],
            'toss': ['토스'],
            'instagram': ['인스타', '인스타그램'],
            'youtube': ['유튜브'],
            'gmail': ['지메일', '이메일'],
            'slack': ['슬랙'],
            'discord': ['디스코드'],
            'twitter': ['트위터', '엑스'],
            'chatgpt': ['챗지피티', 'GPT', '지피티'],
            'claude': ['클로드'],
            'naver': ['네이버'],
        }
        for alias in aliases.get(key, []):
            if alias in text:
                return key
    return None


def detect_message_platform(text: str) -> str | None:
    """Detect message/alert platform from narration."""
    for plat, keywords in MSG_PLATFORMS.items():
        for kw in keywords:
            if kw in text:
                return plat
    return None


def detect_number_compare(text: str) -> tuple[str, str] | None:
    """Detect 'A → B' / 'A에서 B으로' patterns. Returns (before, after) or None."""
    m = RE_COMPARE_ARROW.search(text)
    if m:
        before = m.group(1).strip().rstrip(',')
        after = m.group(2).strip()
        return before, after
    m = RE_COMPARE_ESEO.search(text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None


def detect_list_items(narration: str, emphasis_text: str) -> list[str] | None:
    """Detect 2-4 item list in narration (comma-separated or ordinal).

    Priority:
      1. Emphasis text already pre-split with · or / or , (editor's canonical form)
      2. Ordinal pattern: "첫째 A 둘째 B 셋째 C" → [A, B, C]
      3. Dense comma list in narration: "결정, 액션, 책임자, 기간" → split
         (requires tight clustering — 3+ noun tokens within a short span)

    Returns None if no clear list with 2-4 items.
    """
    # --- Guard: emphasis must NOT be a single-token "X만/뿐/면" pattern ---
    # "4개뿐이에요", "30초면 충분" — these are single-number emphases, NOT lists
    # even though narration might contain unrelated comma content.
    emphasis_stripped = emphasis_text.strip()
    if is_single_number_emphasis(emphasis_stripped):
        # Still allow list detection if narration VERY clearly has a list
        # (we'll gate by ordinal pattern only, below — comma-only won't trigger)
        pass

    # 1. Emphasis text pre-split by editor (·, /, ,)
    for sep in ('·', '・', '，', ','):
        if sep in emphasis_text:
            items = [p.strip() for p in emphasis_text.split(sep) if p.strip()]
            # Filter out tokens that are purely count hints ("4가지")
            items = [i for i in items if not RE_COUNT_HINT.fullmatch(i)]
            if 2 <= len(items) <= 4 and all(len(i) <= 8 for i in items):
                return items

    # 2. Ordinal pattern in narration — highest trust
    ordinal_items: list[str] = []
    for rx in RE_LIST_ORDINALS:
        m = rx.search(narration)
        if m:
            item = m.group(2).strip()
            item = re.sub(r'\s*(이|가|은|는|을|를|이에요|예요|입니다|이고|고)\s*$', '', item)
            item = item.strip()
            if item and len(item) <= 10:
                ordinal_items.append(item)
    if 2 <= len(ordinal_items) <= 4:
        return ordinal_items

    # 3a. Dense comma list — ≥3 short comma-separated noun tokens
    dense_comma = re.findall(
        r'([가-힣A-Za-z]{1,8})\s*,\s*([가-힣A-Za-z]{1,8})\s*,\s*([가-힣A-Za-z]{1,8})(?:\s*,\s*([가-힣A-Za-z]{1,8}))?',
        narration,
    )
    if dense_comma:
        for match in dense_comma:
            items = [m for m in match if m]
            items = [it for it in items if not re.search(r'(다|요|죠|예요|입니다|이에요|니다)$', it)]
            items = [it for it in items if len(it) >= 2]
            if 2 <= len(items) <= 4:
                nearby_cue = bool(re.search(r'이\s*\d+\s*(가지|개)|\d+\s*(가지|개|줄)', narration))
                if nearby_cue or RE_COUNT_HINT.search(emphasis_text):
                    return items

    # 3b. Longer phrase list — split on commas + periods, find 2-4 contiguous
    # short phrases that each contain 2-3 Korean words. Works on messy Whisper
    # transcripts with retakes by de-duplicating repeated fragments.
    nearby_cue = bool(re.search(r'\d+\s*(가지|개|줄|단계)', narration)) \
                 or bool(RE_COUNT_HINT.search(emphasis_text))
    if nearby_cue:
        # Split on commas AND period-like sentence breaks
        raw_parts = [p.strip() for p in re.split(r'[,，\.。!?]', narration) if p.strip()]
        candidates: list[str] = []
        for p in raw_parts:
            # Strip number+unit prefix repetitions like "하루 3줄 일기 퇴근 전 3줄 일기 퇴근 전 3줄 일기"
            # Strategy: if a token sequence repeats, keep only the trailing unique content.
            tokens = p.split()
            # Drop leading tokens that are order-markers or repeated count-phrases
            skip_leading = {'하루', '퇴근', '전', '첫', '두', '세', '네', '번째', '다섯',
                            '번째,', '번째.', ','}
            # Strip leading count patterns: digit + unit (3줄, 5분)
            i = 0
            while i < len(tokens):
                t = tokens[i]
                if t in skip_leading:
                    i += 1
                    continue
                if re.match(r'^\d+[가-힣]{1,3}$', t):  # "3줄", "5분"
                    i += 1
                    continue
                if re.match(r'^(일기|루틴|습관|방법|팁|행동)$', t):  # topic noun
                    i += 1
                    continue
                break
            remaining = tokens[i:]
            phrase = ' '.join(remaining).strip()
            if not phrase:
                continue
            # Remove trailing verb endings
            phrase = re.sub(
                r'\s*(30초면.*|됩니다.*|입니다.*|이에요.*|예요.*|해요.*|라고요.*|잖아요.*|세\s*번째.*|네\s*번째.*|프로젝트.*)$',
                '', phrase,
            ).strip()
            if not phrase:
                continue

            # If phrase contains multiple "temporal markers" (오늘/내일/어제/매일),
            # split further BEFORE length-filtering — Whisper often drops commas
            # between parallel items like "오늘 해결한 거 내일 우선순위".
            # Capture up to 3 Korean words after the temporal marker so that
            # "오늘 해결하지 못한 거" stays intact (4 short tokens).
            temporal_splits = re.findall(
                r'((?:오늘|내일|어제|매일|주간|월간)(?:\s+[가-힣]{1,10}){1,3})',
                phrase,
            )
            if len(temporal_splits) >= 2:
                for sub in temporal_splits:
                    sub = sub.strip()
                    if 3 <= len(sub) <= 14 and sub not in candidates:
                        candidates.append(sub)
                continue

            # Length filter (after temporal split attempt)
            if len(phrase) < 3 or len(phrase) > 14:
                continue
            # Must not be a pure order-marker or verb-final
            if re.fullmatch(r'\d+[가-힣]+|첫\s*번째|두\s*번째|세\s*번째|네\s*번째', phrase):
                continue
            if re.search(r'(다|요|죠|니다|습니다)$', phrase):
                continue
            # Dedupe (messy transcripts repeat fragments)
            if phrase not in candidates:
                candidates.append(phrase)
        # Prefer runs where candidates share a common prefix like "오늘"
        # (Korean lists often parallel: "오늘 X, 오늘 Y, 내일 Z")
        if 2 <= len(candidates) <= 6:
            items = candidates[-min(4, len(candidates)):]
            if 2 <= len(items) <= 4 and len(set(items)) == len(items):
                return items

    return None


def is_single_number_emphasis(emphasis_text: str) -> bool:
    """True if emphasis is basically just a number (e.g. '4개뿐이에요', '30초면 충분').

    These are handled by the emphasis text overlay itself — no B-roll needed.
    """
    # Strip common Korean suffixes
    core = re.sub(r'(뿐이에요|뿐입니다|면\s*충분|면\s*됩니다|면\s*돼요|만\s*적으면|만\s*있으면)\s*$', '', emphasis_text)
    core = core.strip()
    # If what remains is short (< 6 chars) and contains a number with a unit, it's a single-number emphasis.
    if len(core) <= 6 and RE_NUM_WITH_UNIT.search(core):
        return True
    # Also: bare number like "4개" / "30초"
    if RE_NUM_WITH_UNIT.fullmatch(core):
        return True
    return False


def is_concept_term(text: str) -> bool:
    """True if text contains a domain concept / definition keyword.

    e.g. '자이가르닉 효과', '앵커링 효과', '파킨슨의 법칙'.
    """
    for term in CONCEPT_TERMS:
        if term in text:
            return True
    return False


def matches_abstract_hook(narration: str) -> bool:
    """A2 anti-pattern: abstract hook question like '왜 안 될까?'."""
    return bool(RE_ABSTRACT_HOOK.search(narration))


def matches_narrative_setup(narration: str) -> bool:
    """A3 anti-pattern: narrative setup like '어떤 사람이 있었어요'."""
    return bool(RE_NARRATIVE_SETUP.search(narration))


def matches_pronoun_only(emphasis_text: str) -> bool:
    """A5: emphasis is just a pronoun."""
    return bool(RE_PRONOUN_ONLY.match(emphasis_text.strip()))


# ===== Loaders =================================================================

def load_emphasis_segments(draft_path: Path) -> list[dict]:
    """Return [{start_sec, duration_sec, text}] from the emphasis_text track."""
    draft = json.loads(draft_path.read_text(encoding='utf-8'))
    mats = {m['id']: m for m in draft['materials'].get('texts', [])}

    # Find emphasis_text track
    emph_track = None
    for tr in draft['tracks']:
        if tr.get('type') == 'text' and tr.get('name') == 'emphasis_text':
            emph_track = tr
            break
    if emph_track is None:
        # fallback: text track with fewest segments
        text_tracks = [tr for tr in draft['tracks'] if tr.get('type') == 'text']
        if not text_tracks:
            raise RuntimeError('no text track found in draft')
        text_tracks.sort(key=lambda t: len(t.get('segments', [])))
        emph_track = text_tracks[0]
        print(f'[warn] no track named "emphasis_text" — using fewest-segment text track', file=sys.stderr)

    out = []
    for s in emph_track.get('segments', []):
        r = s.get('target_timerange', {})
        start = r.get('start', 0) / 1e6
        dur = r.get('duration', 0) / 1e6
        mat = mats.get(s.get('material_id'), {})
        raw = mat.get('content', '')
        try:
            text = json.loads(raw).get('text', '')
        except Exception:
            text = raw[:80]
        text = text.strip()
        if not text:
            continue
        out.append({'start_sec': start, 'duration_sec': dur, 'text': text})
    return sorted(out, key=lambda x: x['start_sec'])


def scene_for_time(t: float, scene_list: list[dict]) -> int | None:
    """Return scene idx that contains time t (or nearest preceding)."""
    for sc in scene_list:
        if sc['start'] <= t < sc['end']:
            return sc['idx']
    # If past end, return last scene
    if scene_list and t >= scene_list[-1]['end']:
        return scene_list[-1]['idx']
    return None


def narration_in_window(
    segments: list[dict],
    center_sec: float,
    window_sec: float = 5.0,
) -> str:
    """Concatenate narration text within ±window_sec of center."""
    lo, hi = center_sec - window_sec, center_sec + window_sec
    parts = []
    for seg in segments:
        if seg['end'] < lo or seg['start'] > hi:
            continue
        parts.append(seg.get('text', '').strip())
    return ' '.join(parts).strip()


def narration_for_scene(
    segments: list[dict], scene_start: float, scene_end: float
) -> str:
    """Full narration text inside a scene."""
    parts = []
    for seg in segments:
        if seg['end'] < scene_start or seg['start'] > scene_end:
            continue
        parts.append(seg.get('text', '').strip())
    return ' '.join(parts).strip()


# ===== Classification ==========================================================

def classify_emphasis(
    emphasis_text: str,
    narration: str,
    scene_duration: float,
    scene_idx: int,
    total_scenes: int,
    brand_registry: dict,
) -> tuple[str, dict]:
    """Return (decision_tag, context_dict) where decision_tag is one of:
       'skip', 'text_only', ('overlay', type_name), ('split', type_name),
       ('dual', type_name)
       context_dict contains type-specific fields (brand_key, items, before/after, platform, etc.)
    """
    ctx: dict = {}

    # === Step 1: hard anti-patterns (emphasis-level) → skip ===
    # These are unambiguous no-broll signals based on the emphasis itself.
    if scene_idx == 0:
        return 'skip', {'reason': 'A1 title scene'}
    if scene_idx >= total_scenes - 2:
        return 'skip', {'reason': 'A1 outro scene'}
    if matches_pronoun_only(emphasis_text):
        return 'skip', {'reason': 'A5 pronoun-only'}
    if RE_FILLER_ONLY.match(emphasis_text):
        return 'skip', {'reason': 'A6 filler'}
    # Abstract-hook or narrative-setup on the EMPHASIS text itself
    # (narration-level matches are checked only as a tiebreaker after gates)
    if matches_abstract_hook(emphasis_text):
        return 'skip', {'reason': 'A2 abstract hook (emphasis)'}
    if matches_narrative_setup(emphasis_text):
        return 'skip', {'reason': 'A3 narrative setup (emphasis)'}

    # === Step 2: gates (strong signals win over narration anti-patterns) ===

    # G-list-intro: emphasis is just "N가지 X" / "N개 Y" without content yet
    # → text_only (the items will come in later scenes)
    if _is_list_intro_only(emphasis_text):
        return 'text_only', {'reason': 'G5-intro list preview — items come later'}

    # G4 concept / definition → text_only (emphasis overlay is enough)
    if is_concept_term(emphasis_text):
        return 'text_only', {'reason': 'G4 concept term'}

    # G7 / concept-graphic: emphasis names a visualizable concept
    # ("A4 한 페이지", "체크리스트") → graphic_insight flat vector overlay.
    # (실사 photo 금지 2026-04-21 — symbol_moment removed.)
    graphic_hint = _detect_concept_graphic(emphasis_text, narration)
    if graphic_hint:
        return 'overlay', {
            'type': 'graphic_insight',
            'concept': graphic_hint,
            'reason': 'G7 concept visualization (flat graphic)',
        }

    # G5 explicit list of 2-4 items → text_only
    # (split_stack 폐기 2026-04-21: 단어 세로 스택은 emphasis 순차로 충분히 전달 가능 —
    #  "시각 자산으로만 전달 가능" 기준을 위반함.)
    items = detect_list_items(narration, emphasis_text)
    if items and 2 <= len(items) <= 4:
        return 'text_only', {
            'reason': f'G5 {len(items)}-item list — use sequential emphasis',
        }

    # G2b number comparison → stat_card
    # 단, emphasis가 단순 단일 숫자면 stat_card보다 text_only 우선.
    cmp = detect_number_compare(narration) or detect_number_compare(emphasis_text)
    if cmp and not is_single_number_emphasis(emphasis_text):
        return 'overlay', {
            'type': 'stat_card',
            'before': cmp[0],
            'after': cmp[1],
            'reason': 'G2b number compare (before→after)',
        }

    # G6-multi: 2+ brands/tools listed in parallel → ui_evidence (icon row)
    multi_brands = detect_multi_brand_list(narration, brand_registry)
    if multi_brands and len(multi_brands) >= 2:
        primary_brand = next(
            (k for _, k in multi_brands if k in brand_registry.get('brands', {})),
            multi_brands[0][1],
        )
        return 'overlay', {
            'type': 'ui_evidence',
            'brand_key': primary_brand,
            'multi_brands': multi_brands,
            'emphasis_text': emphasis_text,
            'reason': f'G6-multi parallel-list ({len(multi_brands)} tools)',
        }

    # G1a brand mention + 구체 data → ui_evidence (최우선)
    # 단순 브랜드 언급만 있으면 icon_hero로 fallback.
    brand = detect_brand(narration, brand_registry) or detect_brand(emphasis_text, brand_registry)
    if brand:
        if _has_specific_ui_data(narration, emphasis_text):
            return 'overlay', {
                'type': 'ui_evidence',
                'brand_key': brand,
                'emphasis_text': emphasis_text,
                'reason': f'G1a-UI brand={brand} + specific data',
            }
        return 'overlay', {
            'type': 'icon_hero',
            'brand_key': brand,
            'reason': f'G1a brand={brand}',
        }

    # G1b message/alert platform
    msg_plat = detect_message_platform(narration)
    if msg_plat:
        return 'overlay', {
            'type': 'message_object',
            'brand_key': msg_plat,
            'reason': f'G1b message={msg_plat}',
        }

    # G2a single number emphasis → text_only (was deprecated number_hero)
    if is_single_number_emphasis(emphasis_text):
        return 'text_only', {'reason': 'G2a single-number emphasis'}

    # === Narration-level anti-pattern late filter ===
    # If emphasis is generic and narration is abstract/narrative, skip instead
    # of surfacing a weak text_only (rare: emphasis survived all gates but
    # narration gives no visual anchor).
    if matches_abstract_hook(narration):
        return 'skip', {'reason': 'A2 abstract hook (narration, post-gates)'}
    if matches_narrative_setup(narration):
        return 'skip', {'reason': 'A3 narrative setup (narration, post-gates)'}

    # === Fallback: text_only (conservative — user prefers less B-roll) ===
    return 'text_only', {'reason': 'fallback — emphasis sufficient'}


# --- Classifier helpers --------------------------------------------------------

_LIST_INTRO_RE = re.compile(
    r'^\s*\d+\s*(가지|개|단계|줄)\s*(?:의\s*)?'
    r'(행동|방법|단계|팁|루틴|습관|원칙|법칙|기법|전략|생각|이유|포인트)?\s*$'
)

# Specific UI-data signals — patterns that suggest actual app data worth a screenshot
# e.g. "@username", "팔로워 278명", "채팅방에 공유", "댓글에 남기면"
_UI_DATA_SIGNALS = [
    re.compile(r'@[A-Za-z0-9_\.]{2,}'),           # @account
    re.compile(r'\d+\s*(팔로워|팔로잉|게시물|구독자|조회수)'),
    # chat-share action — allow up to ~14 Korean chars between particle and verb.
    # Verb roots matched loosely by first syllable since Korean verb stems
    # conjugate ("남기" → "남겨", "공유하" → "공유해"): we accept "남", "공유",
    # "보내", "올리", "적" as sufficient prefixes.
    re.compile(r'(채팅방|채팅|DM|댓글|메시지|알림)\s*(?:에|으로|로).{0,14}?(공유|남|보내|올리|적|쓰)'),
    re.compile(r'(터미널|콘솔|Finder|탐색기)\s*(에|에서)'),
    re.compile(r'(스크린샷|화면|UI|인터페이스|앱\s*화면)'),
    # brand + action (loose verb roots for conjugation)
    re.compile(r'(노션|Notion|슬랙|Slack|카톡|카카오톡).{0,14}?(기록|저장|공유|정리|남|관리)'),
]


def _has_specific_ui_data(narration: str, emphasis_text: str) -> bool:
    """True if narration contains signals of concrete UI content (usernames,
    specific data fields, platform action directives) — justifying a ui_evidence
    screenshot over a plain icon_hero logo.
    """
    text = f'{narration} {emphasis_text}'
    for rx in _UI_DATA_SIGNALS:
        if rx.search(text):
            return True
    return False


def _extract_ui_target(narration: str) -> str:
    """Pull a short Korean target/data descriptor from narration for ui_evidence
    src_hint. Returns a human-readable description.
    """
    # @handle
    m = re.search(r'@([A-Za-z0-9_\.]{2,})', narration)
    if m:
        return f'account @{m.group(1)} profile view with visible follower/post counts'
    # 팔로워/팔로잉 count
    m = re.search(r'(\d+[\d,\.]*)\s*(팔로워|팔로잉|게시물|구독자)', narration)
    if m:
        return f'profile showing {m.group(1)} {m.group(2)}'
    # 채팅방/DM/댓글 share action — loose (action verb can be "공유/남기/쓰" etc,
    # conjugated forms covered by first-syllable prefix match).
    m = re.search(
        r'(채팅방|DM|댓글|메시지)\s*(?:에|으로|로)\s*([가-힣A-Za-z][가-힣A-Za-z0-9\s]{0,20})\s*(공유|남|보내|올리|쓰|적)',
        narration,
    )
    if m:
        plat = m.group(1)
        item = m.group(2).strip() or 'content'
        return f'{plat} screen showing a Korean message "{item}" being shared/posted'
    # 터미널/Finder 출력
    m = re.search(r'(터미널|콘솔|Finder|탐색기)\s*(?:에|에서)\s*([가-힣A-Za-z0-9\-_\.]{1,20})', narration)
    if m:
        return f'{m.group(1)} view with visible "{m.group(2)}" output/folder'
    # 노션/슬랙/카톡 기록 action (loose — conjugated verbs)
    m = re.search(
        r'(노션|Notion|슬랙|Slack|카톡|카카오톡)[가-힣A-Za-z0-9\s,]{0,30}?(기록|저장|공유|정리|남|관리)',
        narration,
    )
    if m:
        brand = m.group(1)
        action = m.group(2)
        return (
            f'{brand} screen showing a Korean page or entry — user is '
            f'{action}ing something in the native app view'
        )
    # Chat-share generic (no specific platform named)
    m = re.search(r'(채팅방|채팅|메시지)\s*(?:에|으로|로)', narration)
    if m:
        return f'{m.group(1)} screen with a single new Korean message just posted'
    # Fallback: first 80 chars of narration, stripped of filler
    return narration.strip()[:80] or 'single focused view with visible native UI chrome'


# ===== Narration-aware helpers (2026-04-21) ====================================
# Enrich ui_evidence src_hint with concrete narration data so Gemini renders
# images that match the spoken content 1:1, not generic templates.

# Aliases from detect_brand — reused here for multi-brand detection.
_BRAND_ALIASES = {
    'notion':     ['노션', 'Notion'],
    'kakaotalk':  ['카톡', '카카오톡', '카카오'],
    'toss':       ['토스'],
    'instagram':  ['인스타', '인스타그램', 'Instagram'],
    'youtube':    ['유튜브', 'YouTube'],
    'gmail':      ['지메일', 'Gmail'],
    'slack':      ['슬랙', 'Slack'],
    'discord':    ['디스코드', 'Discord'],
    'twitter':    ['트위터', '엑스'],
    'chatgpt':    ['챗지피티', 'GPT', '지피티', 'ChatGPT'],
    'claude':     ['클로드', 'Claude'],
    'naver':      ['네이버'],
}
# Generic productivity tools (not in brand_registry, but still commonly listed).
_GENERIC_TOOL_ALIASES = {
    '다이어리':    'diary',
    '수첩':       'diary',
    '플래너':     'diary',
    '스케줄':     'calendar',
    '캘린더':     'calendar',
    '일정':       'calendar',
    '할일':       'todo',
    '투두':       'todo',
    '체크리스트': 'todo',
}


def detect_multi_brand_list(narration: str, registry: dict) -> list[tuple[str, str]] | None:
    """Detect 2-4 productivity tools/brands listed in parallel in narration.

    Returns [(verbatim_label, brand_or_tool_key)] in order-of-appearance, or
    None if no clear multi-brand list found.

    Triggers on:
      - Comma/"·"/"그리고" separated brand names in a single clause
      - e.g. "노션, 다이어리, 스케줄 관리" → [('노션','notion'), ('다이어리','diary'), ('스케줄','calendar')]

    Requires: ≥2 distinct brand/tool mentions within a ~30-char window.
    """
    if not narration:
        return None

    # Build a single regex for all known aliases (brand + generic tool) to
    # find occurrences with their positions.
    tokens: list[tuple[int, str, str]] = []  # (pos, verbatim, key)
    for key, aliases in _BRAND_ALIASES.items():
        for alias in aliases:
            for m in re.finditer(re.escape(alias), narration):
                tokens.append((m.start(), m.group(0), key))
    for alias, tool_key in _GENERIC_TOOL_ALIASES.items():
        for m in re.finditer(re.escape(alias), narration):
            tokens.append((m.start(), m.group(0), tool_key))

    if len(tokens) < 2:
        return None

    # Sort by position, dedupe same-key within 3 chars (same word spelled twice)
    tokens.sort(key=lambda t: t[0])
    deduped: list[tuple[int, str, str]] = []
    seen_keys_at_pos: dict[str, int] = {}
    for pos, label, key in tokens:
        if key in seen_keys_at_pos and pos - seen_keys_at_pos[key] < 4:
            continue
        deduped.append((pos, label, key))
        seen_keys_at_pos[key] = pos

    # Find the densest run of ≥2 distinct tool/brand tokens within 30 chars.
    # Parallel-list structure requires them to appear close together (single
    # clause / enumeration), not scattered across the scene.
    best: list[tuple[int, str, str]] = []
    n = len(deduped)
    for i in range(n):
        run = [deduped[i]]
        for j in range(i + 1, n):
            if deduped[j][0] - deduped[i][0] > 30:
                break
            if deduped[j][2] in {t[2] for t in run}:
                continue  # same key already in run
            run.append(deduped[j])
            if len(run) >= 4:
                break
        if len(run) > len(best):
            best = run

    if len(best) < 2:
        return None

    # Guard: at least one of the items must be an actual brand (not all generic
    # tool nouns) — otherwise we have no icon to render meaningfully.
    if not any(key in registry.get('brands', {}) for _, _, key in best):
        return None

    return [(label, key) for _, label, key in best]


def _extract_kakao_list_items(narration: str, emphasis_text: str = '') -> list[str] | None:
    """Narration-based list extraction specifically tuned for chat-share context.

    Unlike general detect_list_items (which requires a count hint like '3가지'),
    this looks for a clear enumeration directly preceding a share action —
    e.g. "결정, 액션, 책임자, 기간 이 4가지를 적고 … 채팅방에 공유".
    """
    items = detect_list_items(narration, emphasis_text)
    if items:
        return items

    # Stricter fallback: 3-4 short comma-separated Korean nouns immediately
    # before "이 N가지" or "를 적" / "를 정리" / "를 공유".
    m = re.search(
        r'([가-힣]{1,6})\s*,\s*([가-힣]{1,6})\s*,\s*([가-힣]{1,6})(?:\s*,\s*([가-힣]{1,6}))?'
        r'\s*(?:이|가)?\s*(?:\d+\s*가지|\d+\s*개|를|을)',
        narration,
    )
    if m:
        groups = [g for g in m.groups() if g]
        if 3 <= len(groups) <= 4:
            return groups
    return None


def _build_kakaotalk_hint(narration: str, emphasis_text: str = '') -> str:
    """KakaoTalk chat ui_evidence src_hint. If narration enumerates list items
    that get shared, inject them verbatim as message bubble content.
    """
    items = _extract_kakao_list_items(narration, emphasis_text)
    if items:
        # Render items as a 4-line message bubble body (each item on its own line)
        item_lines = '\n    '.join(f'• {it}' for it in items)
        return (
            "Actual screenshot of KakaoTalk group chat room (16:9 landscape). "
            "Chat room header bar at top showing '프로젝트 회의방' with small back arrow "
            "(←) on left and menu icon (≡) on right. "
            "ONE yellow #FAE100 rounded speech bubble from a left-side sender "
            "(small circular avatar + name '김팀장' above bubble). "
            "Bubble content — render the following 4 lines VERBATIM with bullet marks:\n"
            f"    {item_lines}\n"
            "Below bubble: small grey read-indicator '1' and timestamp '오후 3:42'. "
            "Native KakaoTalk yellow/grey styling, Pretendard Korean typography, "
            "no other bubbles visible in frame. "
            "SOLID FLAT CHROMA BLUE #0000FF fills ALL padding/margin outside the "
            "phone-card viewport. NO generic messages like '안녕하세요' or "
            "'김지훈님 오늘도 수고하셨습니다' — use ONLY the 4 items above."
        )
    # Fallback — generic chat bubble
    return (
        "Actual screenshot of KakaoTalk group chat room (16:9 landscape). "
        "Chat room header '프로젝트 회의방'. ONE yellow #FAE100 speech bubble "
        "from a left-side sender with a small avatar + name label. Bubble "
        "contains a short Korean work message summarizing a meeting decision. "
        "Native KakaoTalk UI styling. "
        "SOLID FLAT CHROMA BLUE #0000FF fills ALL empty area around the phone card. "
        "NO chat list screen, ONE bubble focus only."
    )


def _build_notion_hint(narration: str, emphasis_text: str = '') -> str:
    """Notion ui_evidence src_hint. Extract page title / content cues from
    narration if possible; else use a sensible Korean-work default.
    """
    # If the narration mentions 기록 시스템 / 회의록 / 체크리스트, use that as
    # page title.
    title = None
    for keyword, page_title in [
        ('기록 시스템', '기록 시스템'),
        ('회의록', '회의록'),
        ('체크리스트', '오늘의 체크리스트'),
        ('프로젝트', '프로젝트 노트'),
        ('할 일', '할 일 관리'),
    ]:
        if keyword in narration or keyword in emphasis_text:
            title = page_title
            break

    # Extract 2-4 short Korean bullet items from narration if available.
    items = detect_list_items(narration, emphasis_text)
    body_block: str
    if items and 2 <= len(items) <= 4:
        item_lines = '\n    '.join(f'• {it}' for it in items)
        body_block = (
            "Body area contains a single bulleted list — render VERBATIM:\n"
            f"    {item_lines}\n"
        )
    else:
        body_block = (
            "Body area contains 3 short Korean bullet lines (content not "
            "critical, keep generic-looking but plausible work notes).\n"
        )

    title = title or '오늘의 기록'

    return (
        "Actual screenshot of Notion native desktop page (16:9 landscape). "
        "Left sidebar collapsed to thin grey column with just the workspace "
        "icon + 2-3 page tree entries (low-contrast, greyed out — not the focus). "
        f"Main content area shows a page with title '{title}' in large "
        "Pretendard ExtraBold black (on Notion's cream-white #FBFBFA background). "
        f"{body_block}"
        "Native Notion typography and spacing — black text, grey bullet markers, "
        "ample whitespace. "
        "SOLID FLAT CHROMA BLUE #0000FF fills ALL padding outside the Notion window. "
        "NO generic SaaS mockup, NO fake database views, NO multiple columns — "
        "just one clean page."
    )


def _build_instagram_hint(narration: str) -> str:
    """Instagram ui_evidence src_hint — profile-view enriched with @handle
    and follower counts if narration provides them.
    """
    handle_m = re.search(r'@([A-Za-z0-9_\.]{2,})', narration)
    handle = handle_m.group(1) if handle_m else 'yuni__yaksa'

    followers_m = re.search(r'(\d+[\d,\.]*)\s*팔로워', narration)
    posts_m = re.search(r'(\d+[\d,\.]*)\s*게시물', narration)
    following_m = re.search(r'(\d+[\d,\.]*)\s*팔로잉', narration)
    followers = followers_m.group(1) if followers_m else '278'
    posts = posts_m.group(1) if posts_m else '45'
    following = following_m.group(1) if following_m else '98'

    return (
        "Actual screenshot of Instagram mobile profile page (16:9 landscape "
        "with the phone centered). Top app bar shows '@' handle in black "
        f"Pretendard Semibold: '@{handle}'. Below header: profile photo (circular) "
        "on left, three stat columns on right showing numbers with labels:\n"
        f"  게시물 {posts}  |  팔로워 {followers}  |  팔로잉 {following}\n"
        "Profile bio: 2 short Korean lines beneath stats. "
        "Below bio: the grid tab icon + a 3×3 preview of square thumbnails. "
        "Native Instagram white background, black text. "
        "SOLID FLAT CHROMA BLUE #0000FF fills ALL empty area outside the phone frame. "
        "NO fake company name, NO generic follower counts other than those above."
    )


def _build_multi_icon_row_hint(
    multi_brands: list[tuple[str, str]],
    narration: str,
    registry: dict,
) -> str:
    """Build a 2-4 app-icon horizontal row src_hint.

    multi_brands = [(verbatim_label, key)]. Key may be a registered brand
    (notion/slack/…) or a generic tool key (diary/calendar/todo).
    """
    n = len(multi_brands)
    icon_lines = []
    label_cells = []
    for label, key in multi_brands:
        if key in registry.get('brands', {}):
            brand = registry['brands'][key]
            display = brand.get('display', key)
            hex_color = brand.get('hex', '#000000')
            symbol = brand.get('symbol_desc', '').split(',')[0].strip()
            symbol_frag = f' — {symbol}' if symbol else ''
            icon_lines.append(
                f'  - "{label}" → {display} app icon ({hex_color}){symbol_frag}'
            )
        else:
            # Generic productivity tool — flat minimalist icon
            generic_desc = {
                'diary':    'flat dark-brown rounded square with a horizontal bookmark ribbon (diary/planner metaphor)',
                'calendar': 'flat white rounded square with a red top band and a large black date number (calendar metaphor)',
                'todo':     'flat white rounded square with 3 stacked grey checkbox rows (to-do list metaphor)',
            }.get(key, f'a flat minimalist app icon for "{label}"')
            icon_lines.append(f'  - "{label}" → {generic_desc}')
        label_cells.append(f'"{label}"')

    icon_block = '\n'.join(icon_lines)
    labels_joined = '  |  '.join(label_cells)

    return (
        f"{n} iOS-style rounded-square app icons arranged in a single horizontal row, "
        "centered in 16:9 frame with equal spacing. Each icon ~30% of frame height, "
        "native-looking (not logos isolated on transparent — proper app-icon rendering "
        "with subtle rounded corners, no drop shadow >10px).\n"
        f"Icons (left to right), render in this exact order:\n{icon_block}\n"
        "Below each icon: small Korean label in Pretendard Medium white, ~40% of "
        f"icon width: {labels_joined}.\n"
        "=== CRITICAL BACKGROUND RULE ===\n"
        "The entire canvas background MUST be PURE DIGITAL BLUE: hex #0000FF, "
        "RGB (0, 0, 255) — the MAXIMUM-saturation brightest electric blue possible, "
        "identical to a chroma-key blue screen. NOT sky blue, NOT pale blue, "
        "NOT cornflower blue, NOT navy, NOT cerulean, NOT any decorative blue. "
        "The blue must be flat, uniform, single-tone — NO gradient, NO texture, "
        "NO noise, NO cloud pattern, NO vignette. This blue will be keyed out as "
        "transparency in post-processing, so any softer or lighter blue will fail.\n"
        "The pure #0000FF fills ALL area around the icon row and between icons "
        "(icons themselves keep their own native colors and backgrounds).\n"
        "NO phone frame, NO home-screen grid, NO iOS status bar, NO wallpaper — "
        "just the icon row with labels floating on a pure electric-blue #0000FF field."
    )


def _is_list_intro_only(emphasis_text: str) -> bool:
    """True if emphasis is a list-count intro with no content items yet.

    e.g. '3가지 행동', '5가지 방법', '7가지 팁'.
    These should be text_only because items appear in subsequent scenes.
    """
    return bool(_LIST_INTRO_RE.match(emphasis_text.strip()))


# Concept-to-graphic_insight map (2026-04-21 update: 실사 사진 금지).
# Each entry: (regex on emphasis/narration, flat-vector concept description).
# Descriptions must be pure flat editorial graphics — NO photographs, NO desks,
# NO natural light, NO handwriting, NO paper textures.
_CONCEPT_GRAPHIC_MAP = [
    # A4 / one-page summary → flat document card silhouette
    (re.compile(r'A4|에이포|한\s*페이지|요약\s*페이지'),
     'Flat vector silhouette of an A4 document card. A rounded rectangle outlined in white '
     '(#FFFFFF, 2px stroke) on dark #0A0A0B background. Inside the rectangle: a short header '
     'bar at top (15% of card width, filled white) and 3 horizontal section bars below '
     '(each 60% card width, filled grey #2A2A2E). Pure flat geometric design — no text, '
     'no paper texture, no shadow, no perspective. Centered, 50% frame width. 60% negative space.'),
    # Notebook / checklist / to-do list → flat checkbox graphic
    (re.compile(r'노트북|다이어리|수첩|플래너|체크리스트|할\s*일|투두'),
     'Flat vector illustration of 6 checkboxes vertically stacked on dark #0A0A0B. '
     'Only 2 are filled (solid white square with a white checkmark inside), 4 remain empty '
     '(hollow white-outlined squares). Each checkbox is a clean geometric square, 5% frame '
     'width, spaced evenly. Flat design only — no shadow, no perspective. 55% negative space.'),
    # Clock / time → flat clock face
    (re.compile(r'시계|아침\s*시간|퇴근\s*시간|타이머'),
     'Flat vector clock face — a thin white circle outline on dark #0A0A0B background. '
     'Two simple straight line-hands (one short, one long) pointing to an early morning '
     'position. No numbers, no bezel, no textures — pure minimalist geometric design. '
     '35% frame width, centered. 60% negative space.'),
    # Progress / staging concept
    (re.compile(r'진행|단계|완료|체크'),
     'Flat horizontal progress bar: a long thin rounded rectangle. 60% filled in solid white '
     '#FFFFFF, 40% empty in #2A2A2E grey. Above the bar: a single short Korean label in '
     'Pretendard Medium white. On dark #0A0A0B background. Flat vector only — no gradients, '
     'no shadows. 65% negative space.'),
]


def _detect_concept_graphic(emphasis_text: str, narration: str) -> str | None:
    """Return a flat-vector concept description if the emphasis references a
    visualizable concept. Used for graphic_insight src_hint.

    Priority: emphasis first, then narration fallback.
    """
    if emphasis_text:
        for pattern, descriptor in _CONCEPT_GRAPHIC_MAP:
            if pattern.search(emphasis_text):
                return descriptor
    if narration and not emphasis_text:
        for pattern, descriptor in _CONCEPT_GRAPHIC_MAP:
            if pattern.search(narration):
                return descriptor
    return None


# ===== src_hint builders =======================================================

def build_src_hint(decision_tag: str, ctx: dict, narration: str, brand_registry: dict) -> str:
    """Compose a Korean-text-aware src_hint based on classification context."""
    type_name = ctx.get('type', '')

    if type_name == 'icon_hero':
        brand_key = ctx.get('brand_key')
        brand = brand_registry.get('brands', {}).get(brand_key, {})
        display = brand.get('display', brand_key)
        hex_color = brand.get('hex', '#FFFFFF')
        symbol_desc = brand.get('symbol_desc', '')
        return (
            f"Single {display} logo (symbol mark only, no wordmark text), "
            f"official color {hex_color}, centered on near-black #0A0A0B, "
            f"20% frame width, subtle radial glow. {symbol_desc}. "
            f"70% negative space, Apple keynote hero slide. "
            f"NO app UI, NO phone frame, ONE icon only."
        )

    if type_name == 'message_object':
        brand_key = ctx.get('brand_key')
        brand = brand_registry.get('brands', {}).get(brand_key, {})
        display = brand.get('display', brand_key)
        hex_color = brand.get('hex', '#FAE100')
        return (
            f"Single {display} speech bubble icon in official color {hex_color}, "
            f"centered on dark background #0A0A0B, rounded corners, "
            f"empty interior (NO text inside), 22% frame width, soft shadow. "
            f"65% negative space. NO chat list, NO contact names, ONE bubble only."
        )

    # split_stack 제거 (2026-04-21) — 단어 리스트는 text_only로 처리됨.
    # 이 브랜치는 실행될 경로가 없지만 방어적으로 남김.
    if type_name == 'split_stack':
        raise ValueError(
            "split_stack type is deprecated (2026-04-21). Word lists should be "
            "text_only with sequential emphasis overlays."
        )

    if type_name == 'ui_evidence':
        brand_key = ctx.get('brand_key')
        emphasis_text = ctx.get('emphasis_text', '')
        # --- G6 extension: multi-brand parallel list → icon row ---
        multi_brands = ctx.get('multi_brands')
        if multi_brands:
            return _build_multi_icon_row_hint(multi_brands, narration, brand_registry)
        # --- Brand-specific narration-aware builders ---
        if brand_key == 'kakaotalk':
            return _build_kakaotalk_hint(narration, emphasis_text)
        if brand_key == 'notion':
            return _build_notion_hint(narration, emphasis_text)
        if brand_key == 'instagram':
            return _build_instagram_hint(narration)
        # --- Generic fallback (existing behavior) ---
        brand = brand_registry.get('brands', {}).get(brand_key, {}) if brand_key else {}
        display = brand.get('display', brand_key or 'platform')
        hex_color = brand.get('hex', '')
        color_hint = f' (brand color {hex_color})' if hex_color else ''
        # Pull a concrete target/data snippet from narration
        target = _extract_ui_target(narration)
        return (
            f"Actual screenshot of {display}{color_hint} native interface. "
            f"Show ONE specific view with visible real-looking data: {target}. "
            f"Native platform styling exactly as seen in the real app — no "
            f"generic SaaS mockup, no fake company names, no imaginary Korean "
            f"enterprise dashboard. Single focused view, 60% negative space, "
            f"Pretendard Korean typography if Korean text is visible."
        )

    if type_name == 'stat_card':
        before = ctx.get('before', '')
        after = ctx.get('after', '')
        return (
            f"Two Korean/English numbers vertically stacked on centerline on pure black #0A0A0B. "
            f"Top: grey #6B6B70 '{before}' in Pretendard Medium. "
            f"Thin arrow '↓' between. "
            f"Bottom (larger, bolder): white #FFFFFF '{after}' in Pretendard ExtraBold. "
            f"65% negative space. Editorial Apple keynote layout. "
            f"NO bars, NO columns, NO charts, NO axis. "
            f"Text to render verbatim: '{before}', '{after}'."
        )

    if type_name == 'graphic_insight':
        # Pass full flat-vector descriptor directly (no photographs, no desks).
        concept = ctx.get('concept',
            'Simple flat geometric shape (square or circle) in white on dark #0A0A0B background, '
            'centered, 40% frame width, minimal labels, Pretendard Korean typography if any text.')
        return concept

    # Fallback — should not be reached for overlay/split/dual
    return narration[:80]


# ===== Emphasis sub-structure ==================================================

def build_emphasis(
    emphasis_text: str,
    scene_start: float,
    emphasis_start: float,
    scene_duration: float,
    decision_tag: str,
) -> dict:
    """Build the emphasis object with offset/duration/accent_words."""
    # Offset within the scene
    offset = max(0.3, round(emphasis_start - scene_start, 2))
    # Cap offset so we have room for duration
    if offset > scene_duration - 1.5:
        offset = max(0.3, scene_duration - 3.0)

    # Duration: prefer 2.5-3.5s, clamp within remaining scene time
    remaining = max(1.0, scene_duration - offset - 0.3)
    dur = round(min(3.0, remaining), 2)

    # Accent words — heuristic: pick the number/noun that carries meaning
    accent = _pick_accent_words(emphasis_text)

    # Position: concept terms often look better center-screen
    position = 'center' if is_concept_term(emphasis_text) or _has_list_intro(emphasis_text) else 'lower'

    return {
        'text': emphasis_text,
        'accent_words': accent,
        'start_offset_sec': offset,
        'duration_sec': dur,
        'position': position,
    }


def _pick_accent_words(text: str) -> list[str]:
    """Extract 1-2 accent words from the emphasis text."""
    # Priority 0: alphanumeric code like "A4", "iOS" — keep intact
    alnum_code = re.search(r'\b([A-Z]+\d+|[A-Z][A-Za-z]{2,})\b', text)
    if alnum_code:
        return [alnum_code.group(1)]
    # Priority 1: number + unit (e.g. "4개", "30초")
    m = RE_NUM_WITH_UNIT.search(text)
    if m:
        return [m.group(0).strip()]
    # Priority 2: bare number with context (prefer "N가지" over lone "N")
    count_m = RE_COUNT_HINT.search(text)
    if count_m:
        return [count_m.group(0).strip()]
    # Priority 3: concept term
    for term in CONCEPT_TERMS:
        if term in text and len(term) >= 3:
            return [term]
    # Priority 4: pick the LONGEST noun-like token (content noun, not particle)
    tokens = re.findall(r'[가-힣A-Za-z]{2,10}', text)
    stopwords = {'이에요', '입니다', '해주세요', '있어요', '없어요', '돼요',
                 '이고', '그리고', '그래서'}
    candidates = [t for t in tokens if t not in stopwords]
    # Filter out particle-ending tokens ("댓글에" ends in "에")
    no_particles = [t for t in candidates if not re.search(r'(에|의|을|를|이|가|은|는|과|와|로|으로)$', t)]
    pool = no_particles or candidates
    if pool:
        # Return the longest (most content-bearing) token
        return [max(pool, key=len)]
    return []


def _has_list_intro(text: str) -> bool:
    """True if emphasis looks like a list intro ('3가지 행동')."""
    return bool(RE_COUNT_HINT.search(text) and ('행동' in text or '방법' in text or '가지' in text))


# ===== Main plan assembly ======================================================

def generate_plan(
    transcript_path: Path,
    srt_path: Path,
    scenes_path: Path,
    draft_path: Path,
    video_title: str = '',
    max_broll_count: int = 5,
) -> dict:
    """End-to-end plan generation."""
    transcript = json.loads(transcript_path.read_text(encoding='utf-8'))
    scenes = json.loads(scenes_path.read_text(encoding='utf-8'))
    scene_list = scenes.get('scenes', [])
    total_scenes = len(scene_list)
    segments = transcript.get('segments', [])

    # Load emphasis points from draft (the editor's pre-curated highlights)
    try:
        emphasis_points = load_emphasis_segments(draft_path)
    except Exception as e:
        print(f'[warn] draft not readable ({e}); generating plan with no emphasis', file=sys.stderr)
        emphasis_points = []

    brand_registry = load_brand_registry()

    # ===== Title (from first emphasis at 0.00s, if present) =====
    title_obj: dict | None = None
    if emphasis_points and emphasis_points[0]['start_sec'] < 0.5:
        first = emphasis_points[0]
        title_text = first['text']
        # Truncate to 20 chars (schema limit)
        if len(title_text) > 20:
            title_text = title_text[:20]
        title_obj = {
            'text': title_text,
            'accent_words': _pick_accent_words(first['text']),
            'duration_sec': round(first['duration_sec'], 2),
        }
        # Remove first (title) from emphasis points — handled separately
        emphasis_points = emphasis_points[1:]

    # ===== Classify each emphasis point and map to its scene =====
    scene_decisions: dict[int, dict] = {}  # scene_idx → classified entry

    for ep in emphasis_points:
        ep_start = ep['start_sec']
        ep_dur = ep['duration_sec']
        ep_text = ep['text']

        sidx = scene_for_time(ep_start, scene_list)
        if sidx is None:
            print(f'[warn] emphasis at {ep_start:.2f}s has no scene — skipping', file=sys.stderr)
            continue

        scene = scene_list[sidx]
        # Prefer in-scene narration; fallback to window spanning current + next scene
        # but NEVER crossing into the last 2 scenes (outro) from a non-outro scene.
        narration = narration_for_scene(segments, scene['start'], scene['end'])
        if len(narration) < 20:
            # Scene narration too short — extend to ±4s window, capped to avoid outro bleed
            lo = max(0.0, ep_start - 4.0)
            hi = ep_start + 4.0
            # Cap hi at scene's end + duration of current emphasis (avoid bleeding into outro)
            if sidx < total_scenes - 2:
                hi = min(hi, scene_list[-2]['start'])
            extra_parts = []
            for seg in segments:
                if seg['end'] < lo or seg['start'] > hi:
                    continue
                extra_parts.append(seg.get('text', '').strip())
            ext = ' '.join(extra_parts).strip()
            if len(ext) > len(narration):
                narration = ext

        # Classify
        decision_tag, ctx = classify_emphasis(
            emphasis_text=ep_text,
            narration=narration,
            scene_duration=scene['length'],
            scene_idx=sidx,
            total_scenes=total_scenes,
            brand_registry=brand_registry,
        )

        # Build emphasis sub-object (always present — even on skip if editor marked it)
        emphasis_obj = build_emphasis(
            emphasis_text=ep_text,
            scene_start=scene['start'],
            emphasis_start=ep_start,
            scene_duration=scene['length'],
            decision_tag=decision_tag,
        )

        # Build the scene decision entry
        entry: dict = {
            'scene_idx': sidx,
            'reason': ctx.get('reason', ''),
            'emphasis': emphasis_obj,
        }

        if decision_tag == 'skip':
            entry['decision'] = 'skip'
        elif decision_tag == 'text_only':
            entry['decision'] = 'text_only'
        elif decision_tag == 'overlay':
            entry['decision'] = 'overlay'
            src_hint = build_src_hint(decision_tag, ctx, narration, brand_registry)
            broll: dict = {
                'type': ctx['type'],
                'src_hint': src_hint,
            }
            if ctx.get('brand_key'):
                broll['brand_key'] = ctx['brand_key']
            entry['broll'] = broll
        # (split/dual not emitted from current classifier — split_stack uses 'overlay' per ingest schema)

        # Deduplicate: one decision per scene. If multiple emphases in same
        # scene, keep the "stronger" one (overlay > text_only > skip).
        rank = {'overlay': 3, 'dual': 3, 'text_only': 2, 'skip': 1}
        if sidx in scene_decisions:
            prev = scene_decisions[sidx]
            if rank.get(entry['decision'], 0) > rank.get(prev['decision'], 0):
                scene_decisions[sidx] = entry
        else:
            scene_decisions[sidx] = entry

    # ===== Narration-based injection on unmarked scenes =====
    # Two passes, in priority order:
    #  (A) ui_evidence — brand + specific-data mentioned in narration
    #  (B) graphic_insight — long scene with a visualizable concept
    # Priority: editor's emphasis intent always wins; injection only fills gaps.
    for scene in scene_list:
        sidx = scene['idx']
        if sidx == 0 or sidx >= total_scenes - 2:
            continue
        if sidx in scene_decisions:
            continue  # editor marked this scene — respect their decision

        narration = narration_for_scene(segments, scene['start'], scene['end'])
        if not narration:
            continue

        # (A0) multi-brand parallel list → ui_evidence icon row (G6-multi)
        # Runs BEFORE single-brand detection so parallel enumerations like
        # "노션, 다이어리, 스케줄" produce a 3-icon row instead of a weak
        # single-brand screenshot derived from a secondary CTA later in the
        # scene.
        multi_inj = detect_multi_brand_list(narration, brand_registry)
        if multi_inj and len(multi_inj) >= 2:
            primary_brand = next(
                (k for _, k in multi_inj if k in brand_registry.get('brands', {})),
                multi_inj[0][1],
            )
            ctx_inj = {
                'type': 'ui_evidence',
                'brand_key': primary_brand,
                'multi_brands': multi_inj,
                'emphasis_text': '',
            }
            src_hint = build_src_hint('overlay', ctx_inj, narration, brand_registry)
            broll_obj = {
                'type': 'ui_evidence',
                'brand_key': primary_brand,
                'src_hint': src_hint,
            }
            scene_decisions[sidx] = {
                'scene_idx': sidx,
                'decision': 'overlay',
                'reason': f'injection — G6-multi parallel-list ({len(multi_inj)} tools)',
                'broll': broll_obj,
            }
            continue

        # (A) brand + specific UI data → ui_evidence
        # Concrete brand+data signals override abstract-hook anti-pattern —
        # the visual anchor is strong enough to justify B-roll even in a
        # mixed-tone scene with rhetorical questions.
        brand_inj = detect_brand(narration, brand_registry)
        msg_plat_inj = detect_message_platform(narration)
        if _has_specific_ui_data(narration, ''):
            # Priority for target: explicit brand > message platform > generic
            # chat-share inference (default to kakaotalk for Korean work context).
            target_brand = brand_inj or msg_plat_inj
            if target_brand is None and re.search(
                r'(채팅방|채팅|공유|공지|메시지)', narration
            ):
                # Generic chat-share narration with no named platform → default
                # to KakaoTalk (Korean work default). Marked as 'kakaotalk' so
                # brand registry can enrich; if registry has no entry, src_hint
                # still renders a platform-agnostic chat screen.
                target_brand = 'kakaotalk'
            if target_brand is not None:
                ctx_inj = {
                    'type': 'ui_evidence',
                    'brand_key': target_brand,
                    'emphasis_text': '',
                }
                src_hint = build_src_hint('overlay', ctx_inj, narration, brand_registry)
                scene_decisions[sidx] = {
                    'scene_idx': sidx,
                    'decision': 'overlay',
                    'reason': f'injection — ui_evidence for {target_brand} + specific data in narration',
                    'broll': {
                        'type': 'ui_evidence',
                        'brand_key': target_brand,
                        'src_hint': src_hint,
                    },
                }
                continue

        # (B) long-scene graphic_insight — only if narration has a concrete
        # flat-vector-visualizable concept cue (A4 page, checklist, clock, ...)
        # Lowered threshold 15→12 (2026-04-21): scenes >12s with a concrete
        # visualizable concept benefit from graphic reinforcement.
        if scene['length'] <= 12.0:
            continue
        if matches_abstract_hook(narration) or matches_narrative_setup(narration):
            continue  # no concrete visual anchor if narration is abstract
        concept = _detect_concept_graphic('', narration)
        if not concept:
            continue
        ctx_inj = {'type': 'graphic_insight', 'concept': concept}
        src_hint = build_src_hint('overlay', ctx_inj, narration, brand_registry)
        scene_decisions[sidx] = {
            'scene_idx': sidx,
            'decision': 'overlay',
            'reason': f'long-scene injection ({scene["length"]:.1f}s) — graphic_insight',
            'broll': {'type': 'graphic_insight', 'src_hint': src_hint},
        }

    # ===== Enforce max_broll_count =====
    # Too many B-rolls in one video dilutes attention; cap to max_broll_count.
    # Priority for retention:
    #   1. editor-marked ui_evidence  (highest — concrete visual evidence)
    #   2. editor-marked icon_hero / message_object / stat_card / dual_icon
    #   3. injected ui_evidence
    #   4. editor-marked graphic_insight
    #   5. injected graphic_insight   (lowest)
    # When dropping, downgrade to text_only (keep emphasis) if present, else skip.
    def _priority(entry: dict) -> int:
        reason = entry.get('reason', '')
        broll = entry.get('broll') or {}
        t = broll.get('type', '')
        is_injected = 'injection' in reason
        if t == 'ui_evidence':
            return 5 if not is_injected else 3
        if t in ('icon_hero', 'message_object', 'stat_card', 'dual_icon'):
            return 4
        if t == 'graphic_insight':
            return 2 if not is_injected else 1
        return 0

    overlay_entries = [
        (sidx, e) for sidx, e in scene_decisions.items()
        if e.get('decision') in ('overlay', 'dual')
    ]
    if len(overlay_entries) > max_broll_count:
        # Sort ASCENDING by priority — lowest priority first gets dropped.
        overlay_entries.sort(key=lambda kv: _priority(kv[1]))
        drop_count = len(overlay_entries) - max_broll_count
        for sidx, entry in overlay_entries[:drop_count]:
            has_emphasis = bool(entry.get('emphasis'))
            new_entry: dict = {
                'scene_idx': sidx,
                'decision': 'text_only' if has_emphasis else 'skip',
                'reason': f'max_broll_count={max_broll_count} — dropped (prev: {entry.get("reason","")})',
            }
            if has_emphasis:
                new_entry['emphasis'] = entry['emphasis']
            scene_decisions[sidx] = new_entry

    # ===== Build final scenes array in scene_idx order =====
    out_scenes: list[dict] = []
    for scene in scene_list:
        sidx = scene['idx']
        if sidx in scene_decisions:
            out_scenes.append(scene_decisions[sidx])
        else:
            # Unclassified scene → skip (no emphasis from editor = not important)
            reason = 'A1 title' if sidx == 0 else (
                'A1 outro' if sidx >= total_scenes - 2 else 'no emphasis marked'
            )
            out_scenes.append({
                'scene_idx': sidx,
                'decision': 'skip',
                'reason': reason,
            })

    plan: dict = {'scenes': out_scenes}
    if title_obj:
        plan['title'] = title_obj
    elif video_title:
        plan['title'] = {
            'text': video_title[:20],
            'accent_words': _pick_accent_words(video_title),
            'duration_sec': 4.0,
        }

    # Metadata
    plan['_generated_by'] = 'plan_generator.py'
    plan['_source'] = {
        'transcript': str(transcript_path),
        'scenes': str(scenes_path),
        'draft': str(draft_path),
    }

    return plan


# ===== CLI =====================================================================

def _resolve_paths(name: str) -> tuple[Path, Path, Path, Path]:
    """Resolve default input paths from --name."""
    localappdata = os.environ.get('LOCALAPPDATA') or os.path.expanduser('~/AppData/Local')
    transcript = ROOT / 'output' / name / 'subs' / 'transcript.json'
    srt = ROOT / 'output' / name / 'subs' / 'transcript_wrapped.srt'
    scenes = ROOT / 'temp' / name / 'scenes.json'
    draft = Path(localappdata) / 'CapCut' / 'User Data' / 'Projects' / 'com.lveditor.draft' / name / 'draft_content.json'
    return transcript, srt, scenes, draft


def build_skeleton_plan(
    scenes_path: Path,
    draft_path: Path | None,
    video_title: str = '',
) -> dict:
    """Skeleton-only plan: every scene = skip, draft emphasis → text_only.

    No rule-based classification, no brand detection, no B-roll inference.
    The caller (Claude Opus 4.7) is expected to replace this with a
    proper plan by reading transcript + scenes + draft emphasis and
    applying the capcut-broll SKILL.md principles directly.

    Returns the same JSON schema that scene_designer.py `ingest` expects,
    but with `items: 0` overlays.
    """
    scenes_data = json.loads(scenes_path.read_text(encoding='utf-8'))
    scenes = scenes_data.get('scenes', [])

    # Pull existing emphasis entries + title from the draft if present.
    draft_emphasis: dict[int, dict] = {}
    draft_title: dict | None = None
    if draft_path and draft_path.exists():
        try:
            d = json.loads(draft_path.read_text(encoding='utf-8'))
            for scene_meta in d.get('tracks', []):
                if scene_meta.get('name') != 'emphasis_text':
                    continue
                # Only surface emphasis that a prior overlay_patcher run wrote —
                # we can't reliably re-derive timings here, so leave blank and
                # let the LLM re-author if it wants them.
                break
        except Exception:
            pass

    skeleton_scenes = []
    for sc in scenes:
        idx = sc.get('idx', sc.get('scene_idx', 0))
        entry: dict = {
            'scene_idx': int(idx),
            'decision': 'skip',
            'reason': 'skeleton default — LLM must re-author this plan via /capcut Step 3-A',
        }
        if idx in draft_emphasis:
            entry['decision'] = 'text_only'
            entry['reason'] = 'skeleton preserved draft emphasis'
            entry['emphasis'] = draft_emphasis[idx]
        skeleton_scenes.append(entry)

    plan = {
        'scenes': skeleton_scenes,
        '_generated_by': 'plan_generator.py --fallback-skeleton (DEPRECATED)',
        '_warning': (
            'This is a zero-overlay skeleton. Replace with an Opus-authored '
            'plan by following /capcut Step 3-A.'
        ),
    }
    if video_title:
        plan['title'] = {'text': video_title, 'accent_words': [], 'duration_sec': 4.0}
    elif draft_title:
        plan['title'] = draft_title

    return plan


_DEPRECATION_BANNER = """
================================================================================
⚠️  plan_generator.py IS DEPRECATED (2026-04-22)
================================================================================

B-roll planning is now handled directly by Claude (Opus 4.7) at the /capcut
command's Step 3-A. The old rule-based classifier produced inconsistent
results (e.g. "47:1 vs 6:4" → 0 overlays instead of a stat_card).

To generate a proper B-roll plan:
  1. Open a Claude Code session
  2. Run /capcut with your video; at Step 3-A, Claude will Read
     `.claude/skills/capcut-broll/SKILL.md` and the transcript/scenes/draft
     files, then Write _claude_broll_plan.json directly.

This CLI can still be used in two ways:
  (a) `--fallback-skeleton` — emit a zero-overlay skeleton plan for manual
      editing. Every scene = skip, plus draft title if detected.
  (b) `--acknowledge-legacy-rules` — run the old rule-based generator
      ANYWAY (for debugging only; results are known-bad, do not ship).

Without either flag, this CLI exits with code 2.
================================================================================
""".strip()


def main() -> int:
    ap = argparse.ArgumentParser(
        description='DEPRECATED rule-based broll plan generator. Use Opus direct planning at /capcut Step 3-A instead.',
    )
    ap.add_argument('--name', help='project name (e.g. PROMPTER_20260417_161755)')
    ap.add_argument('--out', help='output path for _claude_broll_plan.json')
    ap.add_argument('--transcript', help='override transcript.json path')
    ap.add_argument('--srt', help='override transcript_wrapped.srt path')
    ap.add_argument('--scenes', help='override scenes.json path')
    ap.add_argument('--draft', help='override draft_content.json path')
    ap.add_argument('--title', default='', help='optional fallback title')
    ap.add_argument('--max-broll', type=int, default=5,
                    help='[legacy] max number of B-roll overlays (ignored in skeleton mode)')
    ap.add_argument('--fallback-skeleton', action='store_true',
                    help='emit a zero-overlay skeleton plan (every scene = skip)')
    ap.add_argument('--acknowledge-legacy-rules', action='store_true',
                    help='run the DEPRECATED rule-based classifier anyway (debug only)')
    args = ap.parse_args()

    # Refuse to run without either acknowledgement flag.
    if not args.fallback_skeleton and not args.acknowledge_legacy_rules:
        print(_DEPRECATION_BANNER, file=sys.stderr)
        return 2

    if not args.name or not args.out:
        print('[err] --name and --out are required', file=sys.stderr)
        return 2

    t_def, srt_def, sc_def, dr_def = _resolve_paths(args.name)
    transcript_path = Path(args.transcript) if args.transcript else t_def
    srt_path = Path(args.srt) if args.srt else srt_def
    scenes_path = Path(args.scenes) if args.scenes else sc_def
    draft_path = Path(args.draft) if args.draft else dr_def

    if not scenes_path.exists():
        print(f'[err] scenes.json not found: {scenes_path}', file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.fallback_skeleton:
        plan = build_skeleton_plan(
            scenes_path=scenes_path,
            draft_path=draft_path if draft_path.exists() else None,
            video_title=args.title,
        )
        out_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
        print(f'[skeleton] wrote {out_path}', file=sys.stderr)
        print(f'[skeleton] scenes={len(plan["scenes"])}, all decision=skip', file=sys.stderr)
        print(f'[skeleton] NEXT: Open Claude Code and follow /capcut Step 3-A to author the real plan.',
              file=sys.stderr)
        return 0

    # Legacy rule-based path (explicitly acknowledged). Emit a big warning.
    print(_DEPRECATION_BANNER, file=sys.stderr)
    print('', file=sys.stderr)
    print('[legacy] --acknowledge-legacy-rules given; running old rule-based generator ANYWAY.',
          file=sys.stderr)
    print('[legacy] Output is for debugging comparison only — DO NOT ship without human review.',
          file=sys.stderr)

    if not transcript_path.exists():
        print(f'[err] transcript.json not found: {transcript_path}', file=sys.stderr)
        return 2

    plan = generate_plan(
        transcript_path=transcript_path,
        srt_path=srt_path,
        scenes_path=scenes_path,
        draft_path=draft_path,
        video_title=args.title,
        max_broll_count=args.max_broll,
    )
    plan['_generated_by'] = 'plan_generator.py --acknowledge-legacy-rules (DEPRECATED)'
    plan['_warning'] = 'Rule-based output. Known to misclassify. Review against SKILL.md.'

    out_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')

    print(f'[legacy] wrote {out_path}', file=sys.stderr)
    print('', file=sys.stderr)
    print('=== Scene Decisions (legacy rule-based) ===', file=sys.stderr)
    counts: dict[str, int] = {}
    for sc in plan['scenes']:
        d = sc['decision']
        counts[d] = counts.get(d, 0) + 1
        emph_text = f" | emph='{sc['emphasis']['text']}'" if sc.get('emphasis') else ''
        broll_type = f" type={sc['broll'].get('type','?')}" if sc.get('broll') else ''
        reason = sc.get('reason', '')
        print(f"  scene {sc['scene_idx']:2d}: {d:10s}{broll_type:18s} [{reason[:32]}]{emph_text}",
              file=sys.stderr)
    print('', file=sys.stderr)
    print(f'=== Summary: {dict(counts)} ===', file=sys.stderr)
    print('[legacy] ⚠️  Review every decision against the real dataset before using.', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
