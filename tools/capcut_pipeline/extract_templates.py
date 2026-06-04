"""
Extract reusable JSON templates from a hand-edited CapCut draft.

사용자가 수동으로 추가한 애니메이션, SFX, 비디오 효과의 material JSON을
뽑아서 tools/capcut_pipeline/templates/ 하위에 재사용 가능한 preset으로 저장.

이후 overlay_patcher.py가 이 템플릿을 복사해 UUID만 새로 만들어 주입.

또한 이 스크립트는 모든 프리셋 이름의 **single source of truth** 역할을
하는 `_registry.json`을 함께 생성합니다. 드리프트 방지용 — 스킬 문서와
patcher의 REQUIRED_FX_KEYS 가 이 파일을 참조.
"""
import json
import os
from datetime import datetime
from pathlib import Path


SOURCE_DRAFT_NAME = 'PROMPTER_20260417_160404'
SOURCE_DRAFT = Path(os.environ['LOCALAPPDATA']) / (
    f'CapCut/User Data/Projects/com.lveditor.draft/'
    f'{SOURCE_DRAFT_NAME}/draft_content.json'
)
OUT_DIR = Path(__file__).parent / 'templates'
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# Single source of truth — REQUIRED FX key spec & category hints.
# extract_templates.py writes this to templates/_registry.json; both
# capcut_fx_patcher.py 와 check_registry_drift.py 가 이 파일을 읽는다.
# ============================================================

REQUIRED_FX_KEYS_SPEC = {
    'title_animation': {'type': 'dict',
                        'rationale': '160404 edit: typewriter on title'},
    'outro_animation': {'type': 'dict',
                        'rationale': '160404 edit: typewriter on CTA'},
    'sfx':             {'type': 'list', 'min_count': 3,
                        'rationale': 'intro + title_reveal + ticks'},
    'scene_effects':   {'type': 'list', 'min_count': 3,
                        'rationale': 'flash + math_rush + lens_zoom×n'},
    'bgm':             {'type': 'dict',
                        'rationale': '전구간 배경음'},
    'filter':          {'type': 'dict',
                        'rationale': '인물 톤 보정 (color grading)'},
}

CATEGORY_HINTS = {
    'sfx_candidates':     ['keyboard_typing', 'mouse_click', 'ui_notify', 'tick'],
    'bgm_candidates':     ['bgm_good_mood'],
    'intro_sfx':          'keyboard_typing',
    'title_reveal_sfx':   'mouse_click',
    'first_emphasis_sfx': 'ui_notify',
    'punch_sfx':          'tick',
}


ANIM_PRESET_MAP = {
    '타자기 iv': 'typewriter',
}

AUDIO_PRESET_MAP = {
    'Keyboard Typing 01': 'keyboard_typing',
    '鼠标单击1': 'mouse_click',
    'UI提示-976714': 'ui_notify',
    '滴答-95172': 'tick',
    'Good Mood': 'bgm_good_mood',
}

FX_PRESET_MAP = {
    '미지근한 플래시': 'flash_warm',
    '수학 폭주': 'math_rush',
    '렌즈 줌': 'lens_zoom',
}

FILTER_PRESET_MAP = {
    '천연 ll': 'natural_ii',
}


def main():
    d = json.loads(SOURCE_DRAFT.read_text(encoding='utf-8'))
    m = d['materials']

    # ===== 1. Animations (material_animations) =====
    anim_templates = {}
    for ma in m['material_animations']:
        if not ma.get('animations'):
            continue
        anim = ma['animations'][0]
        name = anim.get('name', '')
        key = ANIM_PRESET_MAP.get(name, name.lower().replace(' ', '_'))
        anim_templates[key] = {
            'display_name': name,
            'animation_entry': anim,  # material_animations[x].animations[0]
            'default_duration_us': anim.get('duration', 1400000),
        }
    (OUT_DIR / 'animations.json').write_text(
        json.dumps(anim_templates, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f'[ok] animations.json — {len(anim_templates)} presets: {list(anim_templates.keys())}')

    # ===== 2. Audios =====
    audio_templates = {}
    seen_names = set()
    for a in m['audios']:
        name = a.get('name', '')
        if name in seen_names:
            continue
        seen_names.add(name)
        key = AUDIO_PRESET_MAP.get(name, name.lower().replace(' ', '_'))
        full = dict(a)
        full['wave_points'] = []  # CapCut이 재생성
        audio_templates[key] = {
            'display_name': name,
            'material': full,
            'is_bgm': 'BGM' in (a.get('category_name') or ''),
        }
    (OUT_DIR / 'audios.json').write_text(
        json.dumps(audio_templates, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f'[ok] audios.json — {len(audio_templates)} presets: {list(audio_templates.keys())}')

    # ===== 3. Video Effects =====
    fx_templates = {}
    seen_ids = set()
    for e in m['video_effects']:
        eid = e.get('effect_id', '')
        if eid in seen_ids:
            continue
        seen_ids.add(eid)
        name = e.get('name', '')
        key = FX_PRESET_MAP.get(name, name.lower().replace(' ', '_'))
        fx_templates[key] = {
            'display_name': name,
            'material': dict(e),
        }
    (OUT_DIR / 'video_effects.json').write_text(
        json.dumps(fx_templates, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f'[ok] video_effects.json — {len(fx_templates)} presets: {list(fx_templates.keys())}')

    # ===== 3-B. Filters (materials.effects with type=filter) =====
    # Filter는 video_effects가 아니라 materials.effects[] 에 저장됨. type == 'filter' 인 것만.
    filter_templates = {}
    seen_filter_ids = set()
    for e in m.get('effects', []):
        if e.get('type') != 'filter':
            continue
        eid = e.get('effect_id', '')
        if eid in seen_filter_ids:
            continue
        seen_filter_ids.add(eid)
        name = e.get('name', '')
        key = FILTER_PRESET_MAP.get(name, name.lower().replace(' ', '_'))
        filter_templates[key] = {
            'display_name': name,
            'material': dict(e),
            'default_intensity': e.get('value', 0.3),
        }
    (OUT_DIR / 'filters.json').write_text(
        json.dumps(filter_templates, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f'[ok] filters.json — {len(filter_templates)} presets: {list(filter_templates.keys())}')

    # ===== 4. Reference: 세그먼트 구조 (새로 만들 때 field shape 참조용) =====
    seg_ref = {}
    for tr in d['tracks']:
        t = tr.get('type')
        if t in ('audio', 'effect', 'filter') and tr.get('segments'):
            if f'{t}_segment' not in seg_ref:
                seg_ref[f'{t}_segment'] = tr['segments'][0]
    for tr in d['tracks']:
        if tr.get('type') == 'text':
            for s in tr.get('segments', []):
                if s.get('extra_material_refs'):
                    seg_ref['text_segment_with_anim_ref'] = s
                    break
            if 'text_segment_with_anim_ref' in seg_ref:
                break
    (OUT_DIR / '_segment_reference.json').write_text(
        json.dumps(seg_ref, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f'[ok] _segment_reference.json — types: {list(seg_ref.keys())}')

    # ===== 5. Reference: 새 track 만들 때 참조용 (audio/effect) =====
    tracks_ref = {}
    for tr in d['tracks']:
        t = tr.get('type')
        if t in ('audio', 'effect', 'filter'):
            # segments 제외한 track skeleton
            skel = {k: v for k, v in tr.items() if k != 'segments'}
            skel['segments'] = []
            if t not in tracks_ref:
                tracks_ref[t] = skel
    (OUT_DIR / '_track_reference.json').write_text(
        json.dumps(tracks_ref, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    print(f'[ok] _track_reference.json — types: {list(tracks_ref.keys())}')

    # ===== 6. Consolidated registry (single source of truth) =====
    # Every preset actually present in the template JSONs is listed here.
    # capcut_fx_patcher._load_registry() 및 check_registry_drift.py 가 소비.
    registry = {
        'schema_version': 1,
        'source_draft': SOURCE_DRAFT_NAME,
        'extracted_at': datetime.now().isoformat(),
        'required_fx_keys': REQUIRED_FX_KEYS_SPEC,
        'presets': {
            'animations':    sorted(anim_templates.keys()),
            'audios':        sorted(audio_templates.keys()),
            'video_effects': sorted(fx_templates.keys()),
            'filters':       sorted(filter_templates.keys()),
        },
        'category_hints': CATEGORY_HINTS,
    }
    (OUT_DIR / '_registry.json').write_text(
        json.dumps(registry, ensure_ascii=False, indent=2), encoding='utf-8'
    )
    total_presets = sum(len(v) for v in registry['presets'].values())
    print(f'[ok] _registry.json — {total_presets} presets across '
          f'{len(registry["presets"])} groups, '
          f'{len(REQUIRED_FX_KEYS_SPEC)} required fx keys')

    print('\nTemplates extracted to:', OUT_DIR)


if __name__ == '__main__':
    main()
