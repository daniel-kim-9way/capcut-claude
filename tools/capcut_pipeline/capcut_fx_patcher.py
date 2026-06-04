"""
CapCut FX Patcher — 제목 애니메이션 / 강조 SFX / 씬 효과 자동 주입.

사용자가 편집본에서 수동으로 추가한 패턴(타자기 애니메이션, 滴答 SFX, 렌즈 줌 효과)을
templates/ 에서 읽어 draft_content.json에 주입한다.

주요 함수:
- patch_text_animation(draft, text_seg_id, preset_name)
- patch_sfx(draft, preset_name, start_us, duration_us, volume=-10dB)
- patch_scene_effect(draft, preset_name, start_us, duration_us)

CLI:
  python capcut_fx_patcher.py \\
    --draft "%LocalAppData%\\CapCut\\...\\draft_content.json" \\
    --plan  temp/<name>/fx_plan.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import subprocess
import sys
import uuid
from pathlib import Path


HERE = Path(__file__).parent
TEMPLATES_DIR = HERE / 'templates'

# -10dB 기본 SFX 볼륨 (보이스오버 깔림 방지) — user 편집본과 동일
DEFAULT_SFX_VOLUME = 10 ** (-10 / 20)  # ≈ 0.3162
DEFAULT_BGM_VOLUME = 10 ** (-20 / 20)  # ≈ 0.1


# ============================================================
# 공통 유틸
# ============================================================

def _uuid_dashed() -> str:
    """Standard UUID4 dashed — 대소문자 혼합(CapCut 스타일)."""
    u = str(uuid.uuid4()).upper()
    # CapCut는 8-4-4-4-12 형식에서 뒤 3블록 소문자 섞는 경향.
    # 간단히 전체 대문자 사용 — CapCut 호환 확인됨.
    return u


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8'))


def _load_templates() -> dict:
    filters_path = TEMPLATES_DIR / 'filters.json'
    return {
        'animations': _load_json(TEMPLATES_DIR / 'animations.json'),
        'audios': _load_json(TEMPLATES_DIR / 'audios.json'),
        'video_effects': _load_json(TEMPLATES_DIR / 'video_effects.json'),
        'filters': _load_json(filters_path) if filters_path.exists() else {},
    }


def _probe_audio_duration_us(path: str) -> int:
    """ffprobe로 오디오 파일(mp3/wav 등)의 길이를 microseconds로 반환."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f'BGM path not found: {p}')
    cmd = [
        'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
        '-of', 'json', str(p),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
    info = json.loads(proc.stdout)
    seconds = float(info['format']['duration'])
    return int(seconds * 1_000_000)


def _build_bgm_preset_from_path(
    path: str,
    base_template: dict,
    *,
    display_name: str | None = None,
) -> dict:
    """로컬 BGM 파일에서 audios.json 호환 BGM preset dict를 생성.

    base_template: audios.json의 기존 BGM preset (예: bgm_good_mood)
                  — material 구조를 복사 베이스로 사용 (CapCut JSON 호환성 유지).
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f'BGM path not found: {p}')
    duration_us = _probe_audio_duration_us(str(p))
    name = display_name or p.stem

    material = copy.deepcopy(base_template['material'])
    material['id'] = _uuid_dashed()
    material['name'] = name
    material['path'] = str(p).replace('\\', '/')
    material['duration'] = duration_us
    material['category_name'] = 'Local BGM'
    # CapCut 라이브러리 식별자 클리어 (로컬 파일은 해당 ID 없음)
    for key in ('music_id', 'category_id', 'request_id', 'team_id',
                'video_id', 'effect_id', 'resource_id', 'third_resource_id',
                'local_material_id', 'pgc_id', 'pgc_name'):
        if key in material and isinstance(material[key], str):
            material[key] = ''
    if 'app_id' in material:
        material['app_id'] = 0

    return {
        'display_name': name,
        'material': material,
        'is_bgm': True,
    }


# ============================================================
# 지원 material 생성 (audio segment 주입 시 필요)
# ============================================================

def _make_speed_material() -> dict:
    return {
        'id': _uuid_dashed(),
        'type': 'speed',
        'mode': 0,
        'speed': 1.0,
        'curve_speed': None,
    }


def _make_placeholder_info() -> dict:
    return {
        'id': _uuid_dashed(),
        'type': 'placeholder_info',
        'meta_type': 'none',
        'res_path': '',
        'res_text': '',
        'error_path': '',
        'error_text': '',
    }


def _make_sound_channel_mapping() -> dict:
    return {
        'id': _uuid_dashed(),
        'type': 'none',
        'audio_channel_mapping': 0,
        'is_config_open': False,
    }


def _make_vocal_separation() -> dict:
    return {
        'id': _uuid_dashed(),
        'type': 'vocal_separation',
        'choice': 0,
        'removed_sounds': [],
        'time_range': None,
        'production_path': '',
        'final_algorithm': '',
        'enter_from': '',
    }


def _make_beat() -> dict:
    return {
        'id': _uuid_dashed(),
        'type': 'beats',
        'enable_ai_beats': False,
        'gear': 404,
        'gear_count': 0,
        'mode': 404,
        'user_beats': [],
        'user_delete_ai_beats': None,
        'ai_beats': {
            'melody_url': '',
            'melody_path': '',
            'beats_url': '',
            'beats_path': '',
            'melody_percents': [],
            'beat_speed_infos': [],
        },
    }


def _make_material_animation_with_entry(anim_entry: dict, duration_us: int | None = None) -> dict:
    """material_animations 엔트리 생성.

    anim_entry: templates/animations.json의 'animation_entry' (실제 애니메이션 내용)
    duration_us: 애니메이션 지속 시간 (None이면 entry의 duration 사용)
    """
    entry = copy.deepcopy(anim_entry)
    if duration_us is not None:
        entry['duration'] = duration_us
    return {
        'id': _uuid_dashed(),
        'type': 'sticker_animation',
        'animations': [entry],
        'multi_language_current': 'none',
    }


# ============================================================
# Track helpers
# ============================================================

def _audio_track_skeleton(name: str = '') -> dict:
    return {
        'id': _uuid_dashed(),
        'type': 'audio',
        'flag': 0,
        'attribute': 0,
        'name': name,
        'is_default_name': True,
        'segments': [],
    }


def _effect_track_skeleton() -> dict:
    return {
        'id': _uuid_dashed(),
        'type': 'effect',
        'flag': 0,
        'attribute': 0,
        'name': '',
        'is_default_name': True,
        'segments': [],
    }


def _filter_track_skeleton() -> dict:
    return {
        'id': _uuid_dashed(),
        'type': 'filter',
        'flag': 0,
        'attribute': 0,
        'name': '',
        'is_default_name': True,
        'segments': [],
    }


def _ensure_track(draft: dict, track_type: str, *, prefer_existing_idx: int = 0) -> dict:
    """Draft에 해당 타입 트랙이 없으면 생성, 있으면 기존 트랙 반환.

    prefer_existing_idx: 여러 개 있을 때 어느 트랙에 넣을지.

    트랙 배치 규칙:
    - audio: 배열 끝에 append (z-order 영향 없음)
    - effect: **main_video 바로 위에 insert**. CapCut은 tracks[] 인덱스가 큰 쪽이
      z-order 위로 렌더되므로, effect를 텍스트 트랙보다 아래(작은 인덱스)에 두어야
      자막/강조 텍스트가 effect에 왜곡되지 않음. 160404 편집본도 동일 패턴
      (video[0] → text → ... → effect → broll → effect → ...).
    """
    matching = [tr for tr in draft['tracks'] if tr.get('type') == track_type]
    if matching:
        return matching[min(prefer_existing_idx, len(matching) - 1)]

    skel_fn = {
        'audio': _audio_track_skeleton,
        'effect': _effect_track_skeleton,
        'filter': _filter_track_skeleton,
    }[track_type]
    skel = skel_fn()

    if track_type in ('effect', 'filter'):
        # 첫 video 트랙(=main_video) 바로 뒤에 insert. 이렇게 하면 effect/filter가
        # main_video 바로 위에 놓이고, 뒤에 오는 모든 text/broll 트랙이 effect
        # 위에 렌더되어 자막·강조 텍스트가 왜곡되지 않는다. filter도 동일 원칙.
        insert_at = 1
        for i, tr in enumerate(draft['tracks']):
            if tr.get('type') == 'video':
                insert_at = i + 1
                break
        draft['tracks'].insert(insert_at, skel)
    else:
        draft['tracks'].append(skel)
    return skel


def _ensure_material_bucket(draft: dict, bucket: str) -> list:
    """materials[bucket]이 없으면 빈 배열로 생성."""
    if bucket not in draft['materials']:
        draft['materials'][bucket] = []
    return draft['materials'][bucket]


# ============================================================
# P2. Text animation
# ============================================================

def patch_text_animation(
    draft: dict,
    *,
    text_seg_id: str,
    preset_name: str,
    templates: dict,
    duration_us: int | None = None,
) -> str:
    """텍스트 segment에 애니메이션 주입.

    Returns: 생성된 material_animation의 id.
    """
    anim_templates = templates['animations']
    if preset_name not in anim_templates:
        raise ValueError(
            f"unknown animation preset '{preset_name}'. "
            f'available: {list(anim_templates.keys())}'
        )

    tpl = anim_templates[preset_name]
    dur = duration_us if duration_us is not None else tpl['default_duration_us']

    new_anim = _make_material_animation_with_entry(tpl['animation_entry'], duration_us=dur)

    # material_animations에 append
    _ensure_material_bucket(draft, 'material_animations').append(new_anim)

    # 대상 text segment 찾아서 extra_material_refs에 추가
    found = False
    for tr in draft['tracks']:
        if tr.get('type') != 'text':
            continue
        for seg in tr.get('segments', []):
            if seg.get('id') == text_seg_id:
                refs = seg.setdefault('extra_material_refs', [])
                if new_anim['id'] not in refs:
                    refs.append(new_anim['id'])
                found = True
                break
        if found:
            break
    if not found:
        # material_animations는 이미 추가됐으니 cleanup
        draft['materials']['material_animations'].pop()
        raise ValueError(f"text segment id '{text_seg_id}' not found in draft")

    return new_anim['id']


def find_text_seg_id_at(draft: dict, t_us: int, tolerance_us: int = 200_000) -> str | None:
    """주어진 타임스탬프(us) 근처에서 시작하는 text segment id 반환.

    제목/CTA처럼 특정 시점 시작 text를 찾을 때 사용.
    """
    best = (tolerance_us + 1, None)
    for tr in draft['tracks']:
        if tr.get('type') != 'text':
            continue
        for seg in tr.get('segments', []):
            start = seg.get('target_timerange', {}).get('start', -1)
            diff = abs(start - t_us)
            if diff < best[0]:
                best = (diff, seg.get('id'))
    return best[1]


# ============================================================
# P3. SFX
# ============================================================

def _build_audio_segment(
    *,
    audio_material_id: str,
    extra_refs: list[str],
    start_us: int,
    duration_us: int,
    volume: float,
) -> dict:
    return {
        'id': _uuid_dashed(),
        'source_timerange': {'start': 0, 'duration': duration_us},
        'target_timerange': {'start': start_us, 'duration': duration_us},
        'render_timerange': {'start': 0, 'duration': 0},
        'desc': '',
        'state': 0,
        'speed': 1.0,
        'is_loop': False,
        'is_tone_modify': False,
        'reverse': False,
        'intensifies_audio': False,
        'cartoon': False,
        'volume': volume,
        'last_nonzero_volume': 1.0,
        'clip': None,
        'uniform_scale': None,
        'material_id': audio_material_id,
        'extra_material_refs': extra_refs,
        'render_index': 0,
        'keyframe_refs': [],
        'enable_lut': False,
        'enable_adjust': False,
        'enable_hsl': False,
        'visible': True,
        'group_id': '',
        'enable_color_curves': True,
        'enable_hsl_curves': True,
        'track_render_index': 0,
        'hdr_settings': None,
        'enable_color_wheels': True,
        'track_attribute': 0,
        'is_placeholder': False,
        'template_id': '',
        'enable_smart_color_adjust': False,
        'template_scene': 'default',
        'common_keyframes': [],
        'caption_info': None,
        'responsive_layout': {
            'enable': False,
            'target_follow': '',
            'size_layout': 0,
            'horizontal_pos_layout': 0,
            'vertical_pos_layout': 0,
        },
        'enable_color_match_adjust': False,
        'enable_color_correct_adjust': False,
        'enable_adjust_mask': False,
        'raw_segment_id': '',
        'lyric_keyframes': None,
        'enable_video_mask': True,
        'digital_human_template_group_id': '',
        'color_correct_alg_result': '',
        'source': 'segmentsourcenormal',
        'enable_mask_stroke': False,
        'enable_mask_shadow': False,
        'enable_color_adjust_pro': False,
    }


def patch_sfx(
    draft: dict,
    *,
    preset_name: str,
    start_us: int,
    duration_us: int | None = None,
    volume: float | None = None,
    templates: dict,
    track_idx: int = 0,
) -> str:
    """오디오 트랙에 효과음(또는 BGM) 세그먼트 주입.

    preset_name: templates/audios.json 의 key (tick/mouse_click/...)
    duration_us: None이면 preset의 기본 길이 사용
    volume: None이면 SFX=-10dB, BGM=-20dB 자동 선택
    track_idx: 여러 audio 트랙 중 어느 것에 넣을지 (기본 첫번째).
    """
    audio_templates = templates['audios']
    if preset_name not in audio_templates:
        raise ValueError(
            f"unknown audio preset '{preset_name}'. "
            f'available: {list(audio_templates.keys())}'
        )
    tpl = audio_templates[preset_name]
    is_bgm = bool(tpl.get('is_bgm'))

    # 1. audio material 복사 + 새 UUID
    new_audio = copy.deepcopy(tpl['material'])
    new_audio['id'] = _uuid_dashed()
    new_audio['wave_points'] = []  # CapCut 재생성
    full_audio_len_us = int(new_audio.get('duration', 0))

    if duration_us is None:
        duration_us = full_audio_len_us if full_audio_len_us else 1_000_000

    # BGM stretch 버그 방지 (2026-04-22):
    # BGM은 영상 전체 길이(예: 207초)로 target_duration을 요청하는 경우가 많지만,
    # 원본 BGM 파일이 더 짧으면(예: bgm_good_mood = 157초) CapCut이
    # source_timerange.duration > 원본 audio length를 감지하고 자동 stretch를
    # 적용해 재생 속도를 낮춰버린다 (1.32배 stretch = 32% slow-down 관찰).
    # 원본 길이로 clamp하여 원속도 재생을 보장. BGM이 영상보다 짧으면
    # 영상 끝부분은 무음이 된다 — 루프/페이드를 원하면 별도 옵션으로 확장.
    if is_bgm and full_audio_len_us > 0 and duration_us > full_audio_len_us:
        print(
            f'[bgm-clamp] {preset_name}: target={duration_us/1e6:.2f}s > '
            f'원본 {full_audio_len_us/1e6:.2f}s → 원본 길이로 clamp (원속도 재생 보장)',
            file=sys.stderr,
        )
        duration_us = full_audio_len_us

    if volume is None:
        volume = DEFAULT_BGM_VOLUME if is_bgm else DEFAULT_SFX_VOLUME

    # 2. 지원 material 5개 생성 + append
    speed = _make_speed_material()
    placeholder = _make_placeholder_info()
    sch_map = _make_sound_channel_mapping()
    vocal_sep = _make_vocal_separation()
    beat = _make_beat()

    _ensure_material_bucket(draft, 'audios').append(new_audio)
    _ensure_material_bucket(draft, 'speeds').append(speed)
    _ensure_material_bucket(draft, 'placeholder_infos').append(placeholder)
    _ensure_material_bucket(draft, 'sound_channel_mappings').append(sch_map)
    _ensure_material_bucket(draft, 'vocal_separations').append(vocal_sep)
    _ensure_material_bucket(draft, 'beats').append(beat)

    # 3. audio track (없으면 생성) 에 segment append
    track = _ensure_track(draft, 'audio', prefer_existing_idx=track_idx)
    extra_refs = [speed['id'], placeholder['id'], beat['id'], sch_map['id'], vocal_sep['id']]
    seg = _build_audio_segment(
        audio_material_id=new_audio['id'],
        extra_refs=extra_refs,
        start_us=start_us,
        duration_us=duration_us,
        volume=volume,
    )
    track.setdefault('segments', []).append(seg)
    return seg['id']


# ============================================================
# P4. Scene effect
# ============================================================

def _build_effect_segment(
    *,
    effect_material_id: str,
    start_us: int,
    duration_us: int,
    render_index: int,
) -> dict:
    return {
        'id': _uuid_dashed(),
        'source_timerange': None,
        'target_timerange': {'start': start_us, 'duration': duration_us},
        'render_timerange': {'start': 0, 'duration': 0},
        'desc': '',
        'state': 0,
        'speed': 1.0,
        'is_loop': False,
        'is_tone_modify': False,
        'reverse': False,
        'intensifies_audio': False,
        'cartoon': False,
        'volume': 1.0,
        'last_nonzero_volume': 1.0,
        'clip': None,
        'uniform_scale': None,
        'material_id': effect_material_id,
        'extra_material_refs': [],
        'render_index': render_index,
        'keyframe_refs': [],
        'enable_lut': False,
        'enable_adjust': False,
        'enable_hsl': False,
        'visible': True,
        'group_id': '',
        'enable_color_curves': True,
        'enable_hsl_curves': True,
        'track_render_index': 0,
        'hdr_settings': None,
        'enable_color_wheels': True,
        'track_attribute': 0,
        'is_placeholder': False,
        'template_id': '',
        'enable_smart_color_adjust': False,
        'template_scene': 'default',
        'common_keyframes': [],
        'caption_info': None,
        'responsive_layout': {
            'enable': False,
            'target_follow': '',
            'size_layout': 0,
            'horizontal_pos_layout': 0,
            'vertical_pos_layout': 0,
        },
        'enable_color_match_adjust': False,
        'enable_color_correct_adjust': False,
        'enable_adjust_mask': False,
        'raw_segment_id': '',
        'lyric_keyframes': None,
        'enable_video_mask': True,
        'digital_human_template_group_id': '',
        'color_correct_alg_result': '',
        'source': 'segmentsourcenormal',
        'enable_mask_stroke': False,
        'enable_mask_shadow': False,
        'enable_color_adjust_pro': False,
    }


def patch_scene_effect(
    draft: dict,
    *,
    preset_name: str,
    start_us: int,
    duration_us: int,
    templates: dict,
    track_idx: int = 0,
) -> str:
    """effect 트랙에 씬 효과 세그먼트 주입.

    preset_name: templates/video_effects.json 의 key (lens_zoom/math_rush/flash_warm)
    """
    fx_templates = templates['video_effects']
    if preset_name not in fx_templates:
        raise ValueError(
            f"unknown effect preset '{preset_name}'. "
            f'available: {list(fx_templates.keys())}'
        )
    tpl = fx_templates[preset_name]
    new_fx = copy.deepcopy(tpl['material'])
    new_fx['id'] = _uuid_dashed()
    _ensure_material_bucket(draft, 'video_effects').append(new_fx)

    # effect 트랙의 render_index는 기존 overlay 범위(20000+) 이상을 피하기 위해
    # 11000 영역 사용 (편집본과 동일)
    render_index = 11001

    track = _ensure_track(draft, 'effect', prefer_existing_idx=track_idx)
    seg = _build_effect_segment(
        effect_material_id=new_fx['id'],
        start_us=start_us,
        duration_us=duration_us,
        render_index=render_index,
    )
    track.setdefault('segments', []).append(seg)
    return seg['id']


# ============================================================
# P5. Filter (색조 필터)
# ============================================================

def _build_filter_segment(
    *,
    filter_material_id: str,
    start_us: int,
    duration_us: int,
    render_index: int = 10000,
) -> dict:
    """filter 트랙 세그먼트. 160404 편집본 형식."""
    return {
        'id': _uuid_dashed(),
        'source_timerange': None,
        'target_timerange': {'start': start_us, 'duration': duration_us},
        'render_timerange': {'start': 0, 'duration': 0},
        'desc': '',
        'state': 0,
        'speed': 1.0,
        'is_loop': False,
        'is_tone_modify': False,
        'reverse': False,
        'intensifies_audio': False,
        'cartoon': False,
        'volume': 1.0,
        'last_nonzero_volume': 1.0,
        'clip': None,
        'uniform_scale': None,
        'material_id': filter_material_id,
        'extra_material_refs': [],
        'render_index': render_index,
        'keyframe_refs': [],
        'enable_lut': False,
        'enable_adjust': False,
        'enable_hsl': False,
        'visible': True,
        'group_id': '',
        'enable_color_curves': True,
        'enable_hsl_curves': True,
        'track_render_index': 0,
        'hdr_settings': None,
        'enable_color_wheels': True,
        'track_attribute': 0,
        'is_placeholder': False,
        'template_id': '',
        'enable_smart_color_adjust': False,
        'template_scene': 'default',
        'common_keyframes': [],
        'caption_info': None,
        'responsive_layout': {
            'enable': False,
            'target_follow': '',
            'size_layout': 0,
            'horizontal_pos_layout': 0,
            'vertical_pos_layout': 0,
        },
        'enable_color_match_adjust': False,
        'enable_color_correct_adjust': False,
        'enable_adjust_mask': False,
        'raw_segment_id': '',
        'lyric_keyframes': None,
        'enable_video_mask': True,
        'digital_human_template_group_id': '',
        'color_correct_alg_result': '',
        'source': 'segmentsourcenormal',
        'enable_mask_stroke': False,
        'enable_mask_shadow': False,
        'enable_color_adjust_pro': False,
    }


def patch_filter(
    draft: dict,
    *,
    preset_name: str,
    start_us: int = 0,
    duration_us: int | None = None,
    intensity: float | None = None,
    templates: dict,
) -> str:
    """filter 트랙에 색조 필터 세그먼트 주입.

    preset_name: templates/filters.json 의 key (natural_ii)
    duration_us: None이면 total_duration_us() 사용 (전구간)
    intensity: 0.0~1.0, None이면 preset 기본값
    """
    filter_templates = templates.get('filters', {})
    if preset_name not in filter_templates:
        raise ValueError(
            f"unknown filter preset '{preset_name}'. "
            f'available: {list(filter_templates.keys())}'
        )
    tpl = filter_templates[preset_name]

    # Filter material은 materials.effects[] 에 저장 (video_effects 아님)
    new_filter = copy.deepcopy(tpl['material'])
    new_filter['id'] = _uuid_dashed()
    if intensity is not None:
        new_filter['value'] = max(0.0, min(1.0, intensity))
    _ensure_material_bucket(draft, 'effects').append(new_filter)

    # duration 기본: 전구간
    if duration_us is None:
        duration_us = total_duration_us(draft) - start_us

    track = _ensure_track(draft, 'filter')
    seg = _build_filter_segment(
        filter_material_id=new_filter['id'],
        start_us=start_us,
        duration_us=duration_us,
        render_index=10000,
    )
    track.setdefault('segments', []).append(seg)
    return seg['id']


# ============================================================
# 헬퍼 — 씬 타임레인지 조회 (overlay_patcher의 것과 동일)
# ============================================================

def scene_timerange(draft: dict, scene_idx: int) -> tuple[int, int]:
    """Main video track (첫 비디오 트랙)의 N번째 segment의 start/duration (us)."""
    for tr in draft['tracks']:
        if tr.get('type') == 'video':
            segs = tr.get('segments', [])
            if not (0 <= scene_idx < len(segs)):
                raise IndexError(f'scene_idx {scene_idx} out of range (0..{len(segs) - 1})')
            r = segs[scene_idx]['target_timerange']
            return r['start'], r['duration']
    raise ValueError('no video track found')


def total_duration_us(draft: dict) -> int:
    """모든 main video segment 의 최대 end 시점."""
    end = 0
    for tr in draft['tracks']:
        if tr.get('type') == 'video':
            for s in tr.get('segments', []):
                r = s.get('target_timerange', {})
                end = max(end, r.get('start', 0) + r.get('duration', 0))
    return end


# ============================================================
# Plan-driven CLI
# ============================================================

FX_PLAN_SCHEMA_DOC = '''
fx_plan.json 스키마:

{
  "title_animation": {              // 선택 — 씬 0 근처 text seg에 애니메이션
    "preset": "typewriter",
    "scene_idx": 0,
    "duration_us": 1400000          // 선택, 생략시 preset 기본값
  },
  "outro_animation": {              // 선택 — 마지막 씬 근처 text seg
    "preset": "typewriter",
    "scene_idx": -1                  // -1이면 마지막 씬
  },
  "sfx": [                          // 선택 — 여러 개
    {"preset": "keyboard_typing", "start_sec": 0.0, "duration_sec": 1.87},
    {"preset": "mouse_click",     "start_sec": 2.9, "duration_sec": 0.77},
    {"preset": "tick",            "start_sec": 12.17, "duration_sec": 0.87},
    ...
  ],
  "scene_effects": [                // 선택
    {"preset": "flash_warm", "start_sec": 0.0,  "duration_sec": 1.87},
    {"preset": "math_rush",  "start_sec": 2.9,  "duration_sec": 3.0},
    {"preset": "lens_zoom",  "start_sec": 13.97,"duration_sec": 5.63},
    ...
  ],
  "bgm": {                          // 선택 — preset 또는 path 중 하나
    // (A) 로컬 파일 직접 주입 (권장) ↓
    "path": "BGM/Sunlit Cup.mp3",   // 로컬 mp3/wav 절대/상대 경로
    "display_name": "Sunlit Cup",   // 선택, 로그 라벨용 (없으면 파일명)
    "volume_db": -25,               // 기본 -30, 로컬 BGM은 -25 권장

    // (B) audios.json preset 사용 (legacy) ↓
    // "preset": "bgm_good_mood",
    // "volume_db": -30,

    "fade_in_sec": 0.5              // TODO: 현 버전 미지원
  },
  "filter": {                       // 선택 — 전구간 색조 필터 1개
    "preset": "natural_ii",
    "intensity": 0.3,               // 선택, 0.0~1.0, 생략 시 preset 기본값
    "start_sec": 0.0,               // 선택, 기본 0
    "duration_sec": null            // 선택, null/생략 시 영상 전구간
  }
}
'''


def apply_plan(draft: dict, plan: dict, templates: dict) -> dict:
    """plan 적용 → 적용 결과 로그 dict 반환."""
    log = {'title_animation': None, 'outro_animation': None, 'sfx': [], 'scene_effects': [], 'bgm': None, 'filter': None}

    # title_animation
    if plan.get('title_animation'):
        spec = plan['title_animation']
        scene_idx = spec.get('scene_idx', 0)
        start, _dur = scene_timerange(draft, scene_idx)
        tolerance_us = int(spec.get('tolerance_ms', 2000)) * 1_000
        text_id = find_text_seg_id_at(draft, start, tolerance_us=tolerance_us)
        if text_id is None:
            print(f'[warn] title_animation: no text segment near scene {scene_idx} start', file=sys.stderr)
        else:
            anim_id = patch_text_animation(
                draft,
                text_seg_id=text_id,
                preset_name=spec['preset'],
                templates=templates,
                duration_us=spec.get('duration_us'),
            )
            log['title_animation'] = {'text_seg_id': text_id, 'anim_id': anim_id}
            print(f'[ok] title_animation({spec["preset"]}) → text {text_id[:8]}')

    # outro_animation
    if plan.get('outro_animation'):
        spec = plan['outro_animation']
        # 마지막 씬 계산 — main video 트랙(첫 video 트랙)만 기준. broll/기타 video 트랙 무시
        main_segs = next(
            (tr.get('segments', []) for tr in draft['tracks'] if tr.get('type') == 'video'),
            [],
        )
        scene_idx = spec.get('scene_idx', -1)
        if scene_idx < 0:
            scene_idx = len(main_segs) + scene_idx
        start, _dur = scene_timerange(draft, scene_idx)
        tolerance_us = int(spec.get('tolerance_ms', 2000)) * 1_000
        text_id = find_text_seg_id_at(draft, start, tolerance_us=tolerance_us)
        if text_id is None:
            print(f'[warn] outro_animation: no text near scene {scene_idx}', file=sys.stderr)
        else:
            anim_id = patch_text_animation(
                draft,
                text_seg_id=text_id,
                preset_name=spec['preset'],
                templates=templates,
                duration_us=spec.get('duration_us'),
            )
            log['outro_animation'] = {'text_seg_id': text_id, 'anim_id': anim_id}
            print(f'[ok] outro_animation({spec["preset"]}) → text {text_id[:8]}')

    # SFX (segment 단위 배열)
    for i, spec in enumerate(plan.get('sfx', [])):
        start_us = int(spec['start_sec'] * 1_000_000)
        dur_us = int(spec.get('duration_sec', 0) * 1_000_000) or None
        vol = spec.get('volume')
        seg_id = patch_sfx(
            draft,
            preset_name=spec['preset'],
            start_us=start_us,
            duration_us=dur_us,
            volume=vol,
            templates=templates,
            track_idx=0,
        )
        log['sfx'].append({'seg_id': seg_id, 'preset': spec['preset'], 'start_sec': spec['start_sec']})
        print(f'[ok] sfx[{i}] {spec["preset"]} @ {spec["start_sec"]:.2f}s')

    # BGM — 별도 audio 트랙(index 1)
    if plan.get('bgm'):
        spec = plan['bgm']

        # path 모드: 로컬 BGM 파일 직접 주입 (audios.json preset 거치지 않음)
        if spec.get('path'):
            base = templates['audios'].get('bgm_good_mood')
            if base is None:
                raise ValueError(
                    'bgm_good_mood preset이 audios.json에 필요 (path 모드 베이스 템플릿).'
                )
            synthetic = _build_bgm_preset_from_path(
                spec['path'],
                base,
                display_name=spec.get('display_name'),
            )
            synthetic_key = f'_bgm_path_{_uuid_dashed()[:8]}'
            templates['audios'][synthetic_key] = synthetic
            preset_name = synthetic_key
            log_label = synthetic['display_name']
        else:
            preset_name = spec['preset']
            log_label = preset_name

        vol = spec.get('volume')
        if vol is None and 'volume_db' in spec:
            vol = 10 ** (spec['volume_db'] / 20)
        total_us = total_duration_us(draft)
        # 새 audio 트랙을 강제로 하나 더 추가 (BGM 전용)
        bgm_track = _audio_track_skeleton(name='BGM')
        draft['tracks'].append(bgm_track)
        # 내부적으로 patch_sfx를 쓰되 track_idx 마지막을 쓰도록
        # patch_sfx는 track_idx 인자를 쓰지만 기존 생성한 BGM 트랙을 가리키게 해야 함
        # → 간단히 audio 트랙 개수 - 1
        bgm_idx = sum(1 for tr in draft['tracks'] if tr.get('type') == 'audio') - 1
        seg_id = patch_sfx(
            draft,
            preset_name=preset_name,
            start_us=0,
            duration_us=total_us,
            volume=vol,
            templates=templates,
            track_idx=bgm_idx,
        )
        # patch_sfx가 BGM을 원본 길이로 clamp한 경우 실제 duration을 draft에서 다시 읽어옴
        bgm_seg = next(
            (s for tr in draft['tracks'] if tr.get('name') == 'BGM'
             for s in tr.get('segments', [])
             if s.get('id') == seg_id),
            None,
        )
        actual_dur = bgm_seg['target_timerange']['duration'] if bgm_seg else total_us
        log['bgm'] = {
            'seg_id': seg_id, 'preset': log_label,
            'duration_us': actual_dur,
            'requested_us': total_us,
            'clamped': actual_dur != total_us,
            'path': spec.get('path'),
            'volume_db': spec.get('volume_db'),
        }
        if actual_dur != total_us:
            print(f'[ok] bgm {log_label} duration={actual_dur/1e6:.2f}s '
                  f'(영상 {total_us/1e6:.2f}s 중 원본 길이로 clamp, 이후 무음)')
        else:
            print(f'[ok] bgm {log_label} duration={actual_dur/1e6:.2f}s')

    # Scene effects
    for i, spec in enumerate(plan.get('scene_effects', [])):
        start_us = int(spec['start_sec'] * 1_000_000)
        dur_us = int(spec.get('duration_sec', 0) * 1_000_000)
        if dur_us <= 0:
            print(f'[skip] scene_effect[{i}] duration_sec missing/zero', file=sys.stderr)
            continue
        seg_id = patch_scene_effect(
            draft,
            preset_name=spec['preset'],
            start_us=start_us,
            duration_us=dur_us,
            templates=templates,
        )
        log['scene_effects'].append({'seg_id': seg_id, 'preset': spec['preset'], 'start_sec': spec['start_sec']})
        print(f'[ok] scene_effect[{i}] {spec["preset"]} @ {spec["start_sec"]:.2f}s dur={spec["duration_sec"]:.2f}s')

    # Filter (색조 필터, 보통 전구간 1개)
    if plan.get('filter'):
        spec = plan['filter']
        start_us = int(spec.get('start_sec', 0.0) * 1_000_000)
        dur_sec = spec.get('duration_sec')
        dur_us = int(dur_sec * 1_000_000) if dur_sec else None
        seg_id = patch_filter(
            draft,
            preset_name=spec['preset'],
            start_us=start_us,
            duration_us=dur_us,
            intensity=spec.get('intensity'),
            templates=templates,
        )
        effective_dur = dur_sec if dur_sec else total_duration_us(draft) / 1_000_000
        log['filter'] = {
            'seg_id': seg_id,
            'preset': spec['preset'],
            'intensity': spec.get('intensity'),
        }
        print(f'[ok] filter {spec["preset"]} intensity={spec.get("intensity","default")} dur={effective_dur:.2f}s')

    return log


# ============================================================
# CLI
# ============================================================

def _plan_hash(plan: dict) -> str:
    s = json.dumps(plan, sort_keys=True, ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(s).hexdigest()[:16]


def _state_file(draft_path: Path) -> Path:
    return draft_path.parent / '.omc_fx_patch_state.json'


def _check_fx_state(draft_path: Path, plan_hash: str) -> str | None:
    """'applied' / 'different' / None(신규) 반환."""
    sf = _state_file(draft_path)
    if not sf.exists():
        return None
    try:
        st = json.loads(sf.read_text(encoding='utf-8'))
    except Exception:
        return None
    if st.get('fx_plan_hash') == plan_hash:
        return 'applied'
    return 'different'


def _write_fx_state(draft_path: Path, plan_hash: str, log: dict) -> None:
    sf = _state_file(draft_path)
    sf.write_text(
        json.dumps({'fx_plan_hash': plan_hash, 'log': log}, ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


def _make_fx_clean_bak(draft_path: Path) -> Path:
    """FX 패치 전 베이스를 .fx_clean_bak 로 따로 저장 (overlay_patcher의 .clean_bak과 분리)."""
    bak = draft_path.with_suffix(draft_path.suffix + '.fx_clean_bak')
    if not bak.exists():
        bak.write_bytes(draft_path.read_bytes())
    return bak


def _restore_fx_clean(draft_path: Path) -> None:
    bak = draft_path.with_suffix(draft_path.suffix + '.fx_clean_bak')
    if bak.exists():
        draft_path.write_bytes(bak.read_bytes())


# ============================================================
# 완결성 검증 — fx_plan.json에 필수 FX 구성요소가 빠지는 것을 구조적으로 막음.
# ============================================================

# Fallback spec used when templates/_registry.json is absent (pre-registry
# extract_templates runs, or fresh checkout without extraction step).
# Must stay in sync with extract_templates.REQUIRED_FX_KEYS_SPEC.
_FALLBACK_REQUIRED_FX_KEYS = {
    'title_animation': {'type': 'dict'},
    'outro_animation': {'type': 'dict'},
    'sfx':             {'type': 'list', 'min_count': 3},
    'scene_effects':   {'type': 'list', 'min_count': 3},
    'bgm':             {'type': 'dict'},
    'filter':          {'type': 'dict'},
}


def _load_registry() -> dict:
    """Load templates/_registry.json if present, else return a minimal shim
    carrying the legacy hardcoded REQUIRED_FX_KEYS for backward compat.

    extract_templates.py writes _registry.json; this loader lets the patcher
    consume that single source of truth without breaking on older checkouts.
    """
    reg_path = TEMPLATES_DIR / '_registry.json'
    if not reg_path.exists():
        return {
            'schema_version': 0,
            'required_fx_keys': _FALLBACK_REQUIRED_FX_KEYS,
            'presets': {},
            'category_hints': {},
        }
    try:
        return json.loads(reg_path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f'[warn] _registry.json unreadable ({e}); using hardcoded fallback',
              file=sys.stderr)
        return {
            'schema_version': 0,
            'required_fx_keys': _FALLBACK_REQUIRED_FX_KEYS,
            'presets': {},
            'category_hints': {},
        }


def verify_plan_completeness(plan: dict, strict: bool = True) -> list[str]:
    """fx_plan.json이 160404 레퍼런스 디자인 언어의 필수 FX 구성요소를 포함하는지 검증.

    returns: 문제 메시지 리스트 (비어있으면 통과)
    strict: True면 6개 카테고리 모두 요구. False면 sfx/scene_effects 하한만 요구.

    Required keys + their specs are loaded from templates/_registry.json so
    patcher, skill doc, and extractor can't drift.
    """
    reg = _load_registry()
    required = reg.get('required_fx_keys', _FALLBACK_REQUIRED_FX_KEYS)
    problems = []
    for key, spec in required.items():
        # spec can be:
        #   {"type": "dict", ...}
        #   {"type": "list", "min_count": 3, ...}
        # Normalise both the old (tuple/string) fallback and the new dict form.
        if isinstance(spec, dict):
            spec_type = spec.get('type')
            min_count = spec.get('min_count', 1)
        elif spec == 'dict':
            spec_type, min_count = 'dict', 1
        elif isinstance(spec, tuple) and spec[0] == 'list':
            spec_type, min_count = 'list', spec[1]
        else:
            continue

        val = plan.get(key)
        if spec_type == 'dict':
            if not isinstance(val, dict) or not val:
                problems.append(
                    f"'{key}' missing or empty. 160404 edit had this. "
                    f"If intentionally omitted, set `{key}: null` with a comment explaining why."
                )
        elif spec_type == 'list':
            if not isinstance(val, list) or len(val) < min_count:
                problems.append(
                    f"'{key}' needs >= {min_count} entries (got {len(val) if isinstance(val, list) else 0}). "
                    f"Major emphasis points should each get a tick SFX + lens_zoom."
                )
    # 명시적 null 허용 — 'key': null 이면 경고만
    for key in required:
        if key in plan and plan[key] is None:
            problems = [p for p in problems if not p.startswith(f"'{key}'")]
            if strict:
                print(f"[info] '{key}' explicitly set to null — skipping (verify this is intentional)")
    return problems


def main():
    parser = argparse.ArgumentParser(description='CapCut FX (animation/sfx/effect) patcher')
    parser.add_argument('--draft', help='draft_content.json 경로')
    parser.add_argument('--plan', help='fx_plan.json 경로')
    parser.add_argument(
        '--mode',
        choices=['auto', 'clean', 'force', 'reject'],
        default='auto',
        help='auto(기본): 동일 plan 재실행 시 no-op, 다르면 복구 후 재패치',
    )
    parser.add_argument('--show-schema', action='store_true', help='fx_plan.json 스키마 출력 후 종료')
    parser.add_argument(
        '--verify-completeness',
        action='store_true',
        help='fx_plan.json의 필수 키(filter/sfx/scene_effects/bgm/animations) 검증만 하고 종료. '
             '빠진 항목 있으면 exit 5.',
    )
    parser.add_argument(
        '--allow-incomplete',
        action='store_true',
        help='완결성 검증 실패해도 패치 진행 (경고만). 디폴트는 실패 시 exit 5.',
    )
    args = parser.parse_args()

    if args.show_schema:
        print(FX_PLAN_SCHEMA_DOC)
        return

    # --verify-completeness: plan만 검증하고 종료
    if args.verify_completeness:
        if not args.plan:
            print('[err] --plan required for --verify-completeness', file=sys.stderr)
            sys.exit(2)
        plan = _load_json(Path(args.plan))
        problems = verify_plan_completeness(plan)
        if problems:
            print('[FAIL] fx_plan.json is incomplete:')
            for p in problems:
                print(f'  ❌ {p}')
            print('\nSee .claude/skills/capcut-fx/SKILL.md for the full design spec '
                  '(must include filter + bgm + sfx + scene_effects + title_animation + outro_animation).')
            sys.exit(5)
        print('[PASS] fx_plan.json has all required FX components.')
        return

    if not args.draft or not args.plan:
        parser.error('--draft and --plan are required (unless --show-schema / --verify-completeness)')

    draft_path = Path(args.draft)
    plan_path = Path(args.plan)

    if not draft_path.exists():
        print(f'[err] draft not found: {draft_path}', file=sys.stderr)
        sys.exit(2)
    if not plan_path.exists():
        print(f'[err] plan not found: {plan_path}', file=sys.stderr)
        sys.exit(2)

    plan = _load_json(plan_path)
    templates = _load_templates()

    # ⛔ 완결성 게이트 — 필수 FX 구성요소 누락 시 기본적으로 패치 거부.
    problems = verify_plan_completeness(plan)
    if problems:
        print('[WARN] fx_plan.json incomplete:')
        for p in problems:
            print(f'  ❌ {p}')
        if not args.allow_incomplete:
            print('\n[ABORT] Use --allow-incomplete to bypass this gate. '
                  'See .claude/skills/capcut-fx/SKILL.md for required components.')
            sys.exit(5)
        print('[continue] --allow-incomplete set, proceeding despite missing components.\n')

    ph = _plan_hash(plan)
    print(f'[info] plan_hash={ph}')

    state = _check_fx_state(draft_path, ph)

    # Mode handling:
    # - clean: 항상 .fx_clean_bak에서 복구 + 재적용 (코드 변경/손상 복구용)
    # - force: 복구 없이 강제 재적용 (중복 누적 위험, 디버깅용)
    # - auto:  applied면 no-op, different면 복구 후 재적용
    # - reject: different면 에러로 중단
    if args.mode == 'clean':
        print('[info] clean mode — restoring from .fx_clean_bak and reapplying')
        _restore_fx_clean(draft_path)
    elif args.mode == 'force':
        print('[info] force mode — reapplying without restore (may cause duplicates)')
    else:
        # auto / reject
        if state == 'applied':
            print('[skip] identical fx_plan already applied (no-op). '
                  'Use --mode=force to reapply or --mode=clean to restore+reapply.')
            return
        if state == 'different':
            if args.mode == 'reject':
                print('[err] different plan already applied. '
                      'Use --mode=clean/auto/force.', file=sys.stderr)
                sys.exit(3)
            # auto — different plan이므로 복구 후 재적용
            print('[info] auto mode — different plan detected, restoring from .fx_clean_bak')
            _restore_fx_clean(draft_path)

    # .fx_clean_bak 없으면 생성 (최초 패치 시)
    _make_fx_clean_bak(draft_path)

    draft = _load_json(draft_path)
    log = apply_plan(draft, plan, templates)

    draft_path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding='utf-8')
    _write_fx_state(draft_path, ph, log)
    print(f'\n[done] fx patch applied. state → {_state_file(draft_path).name}')


if __name__ == '__main__':
    main()
