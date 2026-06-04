"""
B-roll 프롬프트 체계 — 6 types + text_only decision.

**실사 사진 전면 금지** (2026-04-21 개편):
  과거 `symbol_moment` / `number_hero` 제거. 실사 photograph/Kinfolk editorial
  setup이 "말도 안되는 배경" (책상 + A4 + 손글씨 + 볼펜)을 반복 생성하여
  시청 경험을 저해함. 모든 비주얼은 flat editorial graphic 또는 actual
  screenshot(`ui_evidence`)로만 표현.

  - `symbol_moment` 제거 → 감정/분위기 씬은 `text_only`로 emphasis만
  - `number_hero` 제거 → 숫자 강조는 `text_only` + emphasis로 대체
    (숫자 비교는 `stat_card`, 개념 시각화는 `graphic_insight`)

**split_stack 제거** (2026-04-21 추가):
  "텍스트만 나열된 이미지 = emphasis 오버레이로 충분"이 원칙.
  3-item 수직 리스트는 emphasis 텍스트 오버레이로 더 타이트하고 통제 가능.
  B-roll 이미지는 "시각 자산으로만 전달 가능한 순간"에만 써야 함.
  → `split_stack` 신규 plan에 등장 시 `build_prompt`가 ValueError.

**블루 크로마 파이프라인** (2026-04-21 확립):
  Gemini가 배경을 flat chroma blue #0000FF로 채우도록 지시 → 생성 후
  chroma_remove.py가 블루 픽셀을 alpha=0으로 변환. CapCut 오버레이 시
  메인 영상이 투명 영역으로 비침. 체커보드 / "transparent background"
  같은 문구는 Gemini가 실제 체커보드 픽셀을 렌더링하도록 유도하므로 금지.

text_only는 타입이 아니라 decision-level 옵션:
  broll_plan.json의 scene decision에서 "text_only"를 쓰면 이미지 생성을
  생략하고 emphasis 텍스트 오버레이만 넣는다.

사용:
  from broll_prompts import build_prompt, validate_prompt, load_brand_registry
  prompt = build_prompt('icon_hero', src_hint='Notion 로고', brand_key='notion')
"""

from pathlib import Path
import json

HERE = Path(__file__).parent
BRAND_REGISTRY_PATH = HERE / 'templates' / 'brand_registry.json'

# 공통 prefix (모든 타입에 prepend)
#
# BACKGROUND RULE (블루 크로마): 배경을 flat #0000FF로 채우라고 Gemini에게
# 지시. 후처리에서 블루 픽셀 → alpha=0. "transparent background" /
# "PNG alpha channel" / "checkerboard" 같은 문구는 Gemini가 실제
# 체커보드 픽셀을 렌더하도록 유도하므로 절대 쓰지 말 것.
COMMON_PREFIX = """Editorial minimalist design. Apple keynote slide aesthetic.
One subject only. 60%+ negative space. Pretendard Korean typography if any text.
No drop shadows >20px, no bevels, no 3D, no glass-morphism, no textures,
no people in scene, no UI mockup, no multiple widgets.
Flat editorial design or actual screenshot ONLY. NO photography, NO natural light, NO paper texture, NO desk scenes.

BACKGROUND RULE (CHROMA KEY): Fill ALL empty area outside the main UI/graphic element with PURE DIGITAL ELECTRIC BLUE — hex #0000FF, RGB (0, 0, 255). This is the MAXIMUM-saturation chroma-key blue used on blue screens, NOT sky blue, NOT pale blue, NOT cornflower, NOT navy, NOT cerulean, NOT any decorative/aesthetic blue. The blue must be flat, uniform, single-tone — NO gradient, NO texture, NO noise, NO cloud pattern, NO vignette, NO pattern, NO checkerboard. This blue will be keyed out to transparency in post-processing, so any softer/lighter/darker blue will fail the keying. The UI/graphic element keeps its native colors and native background (e.g. Instagram white, Terminal black, Finder grey). Only the empty area AROUND the element is pure electric #0000FF."""

# 타입별 prompt 템플릿 (6 types — 실사 사진 금지, split_stack 제거)
TYPES = {
    'icon_hero': {
        'use_case': 'G1 브랜드/앱 단일 언급',
        'aspect_ratio': '16:9',
        'spec_template': """Single brand logo (symbol mark only, NO wordmark text),
official brand color, centered on SOLID FLAT CHROMA BLUE #0000FF background,
20-25% of frame width. NO glow, NO halo (would contaminate chroma key).
Refer to src_hint below for WHICH brand and exact color.
70% negative space of pure chroma blue. Apple keynote hero slide aesthetic.""",
        'negative': 'NO app interface, NO phone frame, NO menu bar, NO multiple icons, ONE icon only, centered.',
        'example_narration': ['노션에서 정리하면', '카톡으로 보내'],
        'example_hint': 'Notion N logo, centered',
    },
    'stat_card': {
        'use_case': 'G6 숫자 비교 (before→after / vs)',
        'aspect_ratio': '16:9',
        'spec_template': """Two Korean numbers vertically stacked on centerline.
Top number in grey #6B6B70 (smaller). Small arrow '↓' between them.
Bottom number in white #FFFFFF (larger, bolder).
Refer to src_hint below for the exact before/after numbers and unit label.
SOLID FLAT CHROMA BLUE #0000FF background. Symmetric centered. 65% negative space.""",
        'negative': 'NO bars, NO columns, NO pie chart, NO axis labels, TWO numbers stacked only with arrow.',
        'example_narration': ['5,500 → 6,900', '1시간 → 10분'],
        'example_hint': '5,500 ↓ 6,900 | 만원',
    },
    'message_object': {
        'use_case': 'G1 메시지/알림 맥락 (구체 content 없이 상징)',
        'aspect_ratio': '16:9',
        'spec_template': """Single messaging platform speech bubble icon in the platform's official color
(refer to src_hint below for which platform — KakaoTalk yellow, iMessage blue, etc.),
centered on SOLID FLAT CHROMA BLUE #0000FF background, rounded corners,
empty interior (NO text inside), ~30% of frame width.
Apple keynote aesthetic. 65% negative space of pure chroma blue.""",
        'negative': 'NO chat list, NO contact names, NO timestamp, NO phone frame, ONE bubble only, empty interior.',
        'example_narration': ['카톡 왔어요', 'DM이 도착', '메시지 받았는데'],
        'example_hint': 'KakaoTalk yellow bubble, empty',
    },
    'dual_icon': {
        'use_case': 'G6 양쪽 브랜드 비교',
        'aspect_ratio': '1:1',
        'spec_template': """Two brand icons side-by-side on SOLID FLAT CHROMA BLUE #0000FF background.
Left: first brand logo (official color). Right: second brand logo (official color).
Small grey 'vs' between them in Pretendard Light #6B6B70.
Both icons 18% frame width, centered vertically.
Refer to src_hint below for WHICH two brands and their hex colors.
70% negative space of pure chroma blue.""",
        'negative': 'NO device frames, NO UI around icons, TWO logos only with separator symbol.',
        'example_narration': ['아이폰 vs 갤럭시', '노션 vs 옵시디언'],
        'example_hint': 'Notion N vs Obsidian purple gem',
    },
    'ui_evidence': {
        'use_case': '특정 플랫폼 + 특정 데이터 증빙 (실제 스크린샷 수준)',
        'aspect_ratio': '16:9',
        'spec_template': """Screenshot of a specific platform's native interface.
Refer to src_hint below for WHICH platform (Instagram/Finder/Terminal/Notion/etc.),
WHICH specific target (account name, filename, command), and
what visible data elements should appear (truthful-looking, specific — not generic).
The UI element itself keeps its native background (Instagram white, Terminal black,
Finder grey, etc.) and native colors — do NOT tint the UI.
Any empty area AROUND the UI screenshot (padding/margin to fill the 16:9 frame)
must be SOLID FLAT CHROMA BLUE #0000FF for post-processing keying.
NO generic SaaS layout, NO made-up company names.
Native platform aesthetic exactly as seen in real app.
Platform UI elements only — no extra widgets or decoration.""",
        'negative': 'NO generic SaaS mockup, NO fake analytics dashboard, NO imaginary Korean enterprise app.',
        'example_narration': [
            '@유니약사 팔로워 278명',
            '터미널에 이렇게 뜨면',
            'Finder에서 이 폴더 열어보면',
        ],
        'example_hint': 'Instagram mobile profile @yuni__yaksa | 45게시물/278팔로워/98팔로잉',
    },
    'graphic_insight': {
        'use_case': '개념/상태/진행도/추상 관계를 flat editorial graphic으로 시각화',
        'aspect_ratio': '16:9',
        'spec_template': """Flat editorial infographic. Single concept visualization —
checkbox / progress bar / simple geometric shape with labels / minimal diagram.
SOLID FLAT CHROMA BLUE #0000FF background with white/accent color graphic elements
(white checkboxes, cream yellow #FFE15C accents, grey #6B6B70 labels).
NO photograph, NO paper texture, NO desk, NO ambient light. Pure digital design.
Pretendard Korean typography if any text. Max 3 elements on screen.
Refer to src_hint below for the specific concept to visualize.""",
        'negative': 'NO photograph, NO paper texture, NO desk, NO wood grain, NO natural light, NO handwriting, NO pen, NO notebook, NO Kinfolk aesthetic, NO Monocle aesthetic, NO shallow depth of field, NO beige tones, NO ambient warm tone. Flat digital design ONLY.',
        'example_narration': ['자이가르닉 효과', '뇌는 4개만 기억', '진행 중인 할 일이 많아서'],
        'example_hint': '6개 체크박스 중 2개만 체크됨 — 나머지는 열린 상태 (미완성 일감 상징), flat vector design',
    },
}

# Type별 negative prompt 조합
NEGATIVE_PER_TYPE = {k: v['negative'] for k, v in TYPES.items()}

# Legacy 타입 → migration 힌트 (build_prompt에서 ValueError 발생 시 메시지)
LEGACY_HINTS = {
    'symbol_moment': (
        "'symbol_moment' REMOVED (2026-04-21, 실사 photo 금지). "
        "감정/분위기 씬은 decision: text_only 로, "
        "추상 개념 시각화는 type: graphic_insight 로 변경하세요."
    ),
    'number_hero': (
        "'number_hero' REMOVED (2026-04-21). "
        "단일 숫자 강조는 decision: text_only + emphasis 로 처리하세요. "
        "(숫자 비교는 stat_card, 개념은 graphic_insight)"
    ),
    'split_stack': (
        "'split_stack' REMOVED (2026-04-21). "
        "텍스트만 나열된 이미지는 emphasis 오버레이로 충분합니다. "
        "3-item 수직 리스트는 decision: text_only + emphasis 조합 "
        "(또는 여러 씬에 걸쳐 emphasis 순차 배치)으로 바꾸세요. "
        "B-roll 이미지는 '시각 자산으로만 전달 가능한 순간'에만 사용."
    ),
}

# 금지 문구 — Gemini를 SaaS mockup / 실사 photo setup / 체커보드로 유도하는 패턴
BANNED_PHRASES = [
    # Legacy — SaaS mockup 유도
    'Rich visual density', 'multiple widgets', 'data points visible',
    'Korean SaaS analytics dashboard', 'left sidebar menu', 'main content area',
    'highlighted summary metric card', 'Clean modern interface',
    'Realistic modern Korean SaaS', 'Full-bleed desktop web browser',
    'List 5+ Korean sender names', '가상 한국 데이터 풍부',
    '체크박스 3개', '20개 이상 표시',
    'multiple labeled rows', 'sidebar + main content',
    'stat cards', 'dashboard layout',
    # 실사 photo setup 유도 (2026-04-21)
    'wooden desk', 'on a desk', 'handwritten', 'blue pen', 'ballpoint pen',
    'window light', 'shallow depth of field', 'editorial photograph',
    'Kinfolk', 'Monocle', 'warm tone', 'natural light',
    'beige background', 'paper texture', 'notebook',
    '책상', '메모장', '손글씨', '종이 질감', '창문빛',
    # 체커보드 / 투명 PNG 유도 (2026-04-21 추가) — Gemini가 실제 체커보드 픽셀 렌더링
    'transparent background', 'transparent bg', 'PNG alpha channel',
    'alpha channel', 'checkerboard', 'checker pattern', 'checkered pattern',
    'transparency grid',
    # 세로 방향 강제 금지 (2026-04-21 추가) — overlay는 landscape 기본
    'vertical 9:16', 'portrait orientation', 'vertical portrait',
    '9:16 portrait',
]


def load_brand_registry() -> dict:
    """brand_registry.json 로드."""
    if not BRAND_REGISTRY_PATH.exists():
        return {'brands': {}}
    return json.loads(BRAND_REGISTRY_PATH.read_text(encoding='utf-8'))


def _detect_brand(src_hint: str, registry: dict) -> dict | None:
    """src_hint에서 브랜드 추정 — canonical name과 display 이름 매칭."""
    hint_lower = src_hint.lower()
    for key, brand in registry.get('brands', {}).items():
        if key in hint_lower:
            return brand
        if brand['display'].lower() in hint_lower:
            return brand
    return None


def build_prompt(type_name: str, src_hint: str, *, brand_key: str = None) -> str:
    """
    타입 + src_hint + (선택) 브랜드 → Gemini 최종 prompt 생성.

    src_hint는 Claude가 작성한 구체 지시문. type_name은 DECISION_TREE가 결정.
    """
    if type_name not in TYPES:
        # Legacy types — clear migration hint
        if type_name in LEGACY_HINTS:
            raise ValueError(
                f"type '{type_name}' has been REMOVED. {LEGACY_HINTS[type_name]}"
            )
        raise ValueError(f"unknown type: {type_name}. Valid: {list(TYPES.keys())}")

    tp = TYPES[type_name]
    registry = load_brand_registry()

    # src_hint를 spec_template에 녹여넣기 (간단한 접미사 방식)
    core = f"""{tp['spec_template']}

Src hint (Claude's specific instruction for this scene):
{src_hint}
"""
    # Brand enrichment if detected
    brand = None
    if brand_key:
        brand = registry.get('brands', {}).get(brand_key)
    if not brand:
        brand = _detect_brand(src_hint, registry)
    if brand:
        core += f"""
Brand detail: {brand['display']} ({brand['hex']}) — {brand.get('symbol_desc', '')}
"""

    # 조립
    prompt = f"""{COMMON_PREFIX}

=== Type: {type_name} ({tp['use_case']}) ===
Aspect ratio: {tp['aspect_ratio']}

{core}

STRICT EXCLUSIONS: {tp['negative']}
"""
    return prompt.strip()


_NEGATION_PREFIXES = ('no ', 'not ', 'never ', 'avoid ', 'without ', 'exclude ', 'excluding ')


def validate_prompt(prompt: str) -> list:
    """프롬프트에 금지 문구가 있는지 검사. 빈 리스트면 통과.

    부정문 맥락(no X / not X / avoid X)에 있는 문구는 유효한 exclusion이므로 허용.
    금지 대상은 '긍정적 지시'로 등장하는 경우뿐 (Gemini를 mockup으로 유도).
    """
    violations = []
    lower = prompt.lower()
    for phrase in BANNED_PHRASES:
        p = phrase.lower()
        idx = 0
        while True:
            hit = lower.find(p, idx)
            if hit == -1:
                break
            # Check preceding ~12 chars for negation prefix
            window_start = max(0, hit - 12)
            preceding = lower[window_start:hit]
            if not any(neg in preceding for neg in _NEGATION_PREFIXES):
                violations.append(phrase)
                break
            idx = hit + len(p)
    return violations


if __name__ == '__main__':
    # Self-test
    print(f'=== Self-test: {len(TYPES)} types (실사 사진 금지, split_stack 제거) ===')
    for t, spec in TYPES.items():
        prompt = build_prompt(t, spec['example_hint'])
        violations = validate_prompt(prompt)
        status = 'OK' if not violations else f'WARN {violations}'
        aspect = spec['aspect_ratio']
        print(f'\n[{t}] aspect={aspect} {status}\n{prompt[:400]}...\n')

    # Migration test — legacy types must raise clear errors
    print('=== Legacy type migration check ===')
    for legacy in ('symbol_moment', 'number_hero', 'split_stack'):
        try:
            build_prompt(legacy, 'test')
            print(f'[{legacy}] FAIL: should have raised')
        except ValueError as e:
            print(f'[{legacy}] OK -- {str(e)[:120]}')
