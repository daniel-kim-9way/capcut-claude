#!/usr/bin/env python3
"""
CapCut Overlay Patcher (MVP)

기존 `draft_content.json`에 B-roll 이미지 오버레이 트랙을 추가합니다.
기존 video material / speed / segment / track 을 템플릿으로 깊은복사하여
스키마 불일치 없이 안전하게 주입합니다.

⚠️  CapCut 이 열려있으면 `.locked` 파일 때문에 실패합니다. 먼저 닫으세요.

Usage:
    python tools/capcut_pipeline/overlay_patcher.py \
        --draft <draft_content.json path> \
        --plan <broll_plan.json>

broll_plan.json 형식:
    {
      "items": [
        {
          "scene_idx": 2,
          "style": "split",
          "image_path": "abs/path/to/broll.png",
          "image_width": 1080,
          "image_height": 1920,
          "opacity": 1.0,            // optional
          "ratio": 0.55,            // optional (split only)
          // --- 신규 optional 필드 (2026-06-04, 전부 default가 기존 동작 보존) ---
          "start_offset_sec": 0.0,  // CE-01: overlay 등장 시점(씬 시작 기준 초). default 0.
          "display_dur_sec": null,  // CE-01: 표시 길이(초). null이면 MOV=intrinsic / static=글자수.
          "position_y": "top",      // CE-02/CE-03: overlay 세로 슬롯 top/center/lower. default top.
          "overlay_h_ratio": 0.55,  // CE-02: overlay 가로 점유 비율(기존 ratio 의미). 미지정 시 ratio.
          "auto_crop_margins": false // CE-04: 정적 overlay PNG 위아래 투명여백 크롭(opt-in).
        },
        ...
      ]
    }
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
import uuid
from copy import deepcopy
from pathlib import Path


# Motion overlay (2026-04-22): video files (.mov/.mp4/.webm) can be used as
# overlays in addition to static PNGs. When a video overlay is detected we
# MUST read its actual duration via ffprobe and set source/target timeranges
# so they match the video's own length — NOT the scene length. Otherwise
# CapCut applies automatic stretch (exactly the same bug pattern we fixed in
# capcut_fx_patcher for BGM). See feedback_bgm_clamp_to_source_length.md.
VIDEO_OVERLAY_EXTS = {".mov", ".mp4", ".webm", ".m4v"}


def _probe_video_duration_us(path: Path) -> int:
    """Return video duration in microseconds via ffprobe."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            text=True,
        ).strip()
        return int(float(out) * SEC)
    except Exception:
        return 0


def _probe_video_size(path: Path) -> tuple[int, int]:
    """Return (width, height) via ffprobe."""
    try:
        out = subprocess.check_output(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height",
                "-of", "csv=p=0:s=x",
                str(path),
            ],
            text=True,
        ).strip()
        w, h = out.split("x")
        return int(w), int(h)
    except Exception:
        return 1920, 1080

try:
    from PIL import Image, ImageDraw, ImageFont  # type: ignore
except ImportError:
    Image = ImageDraw = ImageFont = None  # type: ignore

SEC = 1_000_000  # 1 second in microseconds


# ===== 멱등성 (idempotency) =====
# 같은 draft에 overlay_patcher를 2회 이상 실행하면 B-roll·emphasis가 누적 중복되는
# 버그를 방지하기 위한 상태 관리. 사이드카 JSON 파일에 마지막 patch의 plan_hash를
# 저장하고, 같은 plan이면 no-op, 다른 plan이면 .clean_bak에서 복구 후 재patch.
# (draft_content.json 내부 필드로 저장하면 CapCut 자동저장이 제거할 가능성이 있어
# 별도 사이드카로 분리.)

PATCH_STATE_FILENAME = ".omc_patch_state.json"
PATCHED_TRACK_NAMES = {"broll_overlay", "emphasis_text"}  # sanity check용


def _canonical_plan_hash(plan: dict) -> str:
    """공백·키 순서에 독립적인 canonical hash (short 16 chars)."""
    canonical = json.dumps(
        plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _patch_state_path(draft_path: Path) -> Path:
    return draft_path.parent / PATCH_STATE_FILENAME


def _read_patch_state(draft_path: Path) -> dict | None:
    p = _patch_state_path(draft_path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_patch_state(draft_path: Path, state: dict) -> None:
    p = _patch_state_path(draft_path)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _detect_existing_patch(draft: dict, draft_path: Path) -> dict | None:
    """사이드카 + 트랙 이름 prefix 이중 체크. 둘 중 하나라도 있으면 patched."""
    state = _read_patch_state(draft_path)
    if state:
        return state
    for t in draft.get("tracks", []):
        if t.get("name", "") in PATCHED_TRACK_NAMES:
            return {"detected_via": "track_name", "plan_hash": None}
    return None


def _restore_from_clean_bak(draft_path: Path) -> dict:
    """`.clean_bak`에서 복구하여 draft dict 반환."""
    clean = draft_path.with_suffix(".json.clean_bak")
    if not clean.exists():
        raise RuntimeError(
            f"[mode=clean] .clean_bak 없음 — 복구 불가.\n"
            f"  run_pipeline.py로 draft 재생성 필요: {clean}\n"
            f"  (--skip-stt --skip-wrap --skip-cut 권장)"
        )
    shutil.copy2(clean, draft_path)
    with open(draft_path, "r", encoding="utf-8") as f:
        return json.load(f)


def new_uuid_simple() -> str:
    """CapCut 일반 material id 형식 (32 hex, no dash)."""
    return uuid.uuid4().hex


def new_uuid_dashed() -> str:
    """CapCut 일부 필드는 대시형 UUID 사용 (참고용, 현재는 미사용)."""
    return str(uuid.uuid4()).upper()


DEFAULT_FONT = r"C:\Users\kbjhh\AppData\Local\Microsoft\Windows\Fonts\ODITTABILITY.TTF"


def _decode_capcut_key(key: str) -> str:
    """CapCut userFontData 키를 실제 문자열로 디코드.

    CapCut 은 폰트명을 **혼합 인코딩**으로 저장한다:
      - 한글/비ASCII → ``%UXXXX`` (4 hex). NFD(자모 분해) 라 NFC 정규화 필수.
      - 공백 등 ASCII 특수문자 → ``%XX`` 표준 URL percent (2 hex). 예: ``%20``=공백.
    예) ``Pretendard%20Black`` → "Pretendard Black",
        ``Od%UC788%UC5B4...`` → "Od있어빌리티".
    과거엔 ``%UXXXX``만 처리해 "Pretendard Black"(공백 ``%20``)을 못 찾아
    emphasis 폰트가 CapCut System으로 폴백됐다 (2026-06-04 fix).
    """
    import unicodedata
    out = []
    i = 0
    n = len(key)
    while i < n:
        if key[i] == "%" and i + 1 < n and key[i + 1] in ("U", "u"):
            # %UXXXX — CapCut 유니코드(4 hex)
            if i + 6 <= n:
                try:
                    out.append(chr(int(key[i + 2:i + 6], 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
        if key[i] == "%" and i + 3 <= n:
            # %XX — 표준 URL percent(2 hex). %20(공백) 등.
            try:
                out.append(chr(int(key[i + 1:i + 3], 16)))
                i += 3
                continue
            except ValueError:
                pass
        out.append(key[i])
        i += 1
    return unicodedata.normalize("NFC", "".join(out))


def resolve_font_path_by_name(font_name: str) -> str | None:
    """CapCut userFontData 레지스트리에서 이름으로 폰트 경로 역방향 조회.
    예: "아네모네" → "C:/Users/.../Fonts/Anemone.ttf"
    """
    import os
    import unicodedata
    reg = Path(os.environ.get("LOCALAPPDATA", "")) / "CapCut/User Data/Config/userFontData"
    if not reg.exists():
        return None
    target = unicodedata.normalize("NFC", font_name)
    try:
        for raw in reg.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" not in raw or raw.strip().startswith("["):
                continue
            key, _, val = raw.partition("=")
            val_stripped = val.strip()
            # 폰트 엔트리는 값이 파일 경로. Order= 같은 메타 라인 스킵.
            if not val_stripped or ("\\" not in val_stripped and "/" not in val_stripped):
                continue
            if _decode_capcut_key(key.strip()) == target:
                return val_stripped.replace("\\", "/")
    except Exception:
        pass
    return None


def hex_to_rgb_tuple(hex_str: str) -> tuple[int, int, int]:
    """`#RRGGBB` → (R, G, B) 0~255."""
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def render_emphasis_png(
    text: str,
    out_path: Path,
    canvas_w: int = 1080,
    canvas_h: int = 1920,
    font_path: str = DEFAULT_FONT,
    font_size: int = 120,
    color_hex: str = "#FFFFFF",           # 기본 흰색
    accent_color_hex: str = "#FFD54F",    # 연한 황금 (accent 단어용)
    accent_words: list[str] | None = None,
    stroke_width: int = 3,                # 얇게 (참고 이미지 수준)
    stroke_color: str = "#000000",
) -> tuple[int, int]:
    """투명 배경 PNG 에 한국어 텍스트를 렌더.

    accent_words 에 포함된 단어만 accent_color 로 칠하고,
    나머지는 기본 color 로 칠함 (create-reels titleAccentWords 패턴).

    공백으로 단어를 split → 각 단어를 수평으로 나열하며 색상 차등 적용.
    """
    if Image is None:
        raise RuntimeError("Pillow 미설치. `pip install Pillow` 필요.")

    accent_set = set(accent_words or [])

    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(font_path, font_size)
    except Exception:
        font = ImageFont.load_default()

    fill_default = hex_to_rgb_tuple(color_hex) + (255,)
    fill_accent = hex_to_rgb_tuple(accent_color_hex) + (255,)
    stroke = hex_to_rgb_tuple(stroke_color) + (255,)

    # 단어 단위 split (공백 유지)
    tokens = text.split(" ")
    space_w = int(font_size * 0.35)  # 단어 간 간격

    # 전체 너비 계산
    widths = [draw.textlength(t, font=font) for t in tokens]
    total_w = sum(widths) + space_w * (len(tokens) - 1)

    # bbox 로 세로 중앙 맞추기
    ref_bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    text_h = ref_bbox[3] - ref_bbox[1]
    y = (canvas_h - text_h) / 2 - ref_bbox[1]
    x = (canvas_w - total_w) / 2

    for tok, w in zip(tokens, widths):
        col = fill_accent if tok in accent_set else fill_default
        draw.text(
            (x, y), tok, font=font,
            fill=col,
            stroke_width=stroke_width,
            stroke_fill=stroke,
        )
        x += w + space_w

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "PNG")
    return (canvas_w, canvas_h)


def hex_to_rgb01(hex_str: str) -> tuple[float, float, float]:
    """`#RRGGBB` → (r, g, b) 0.0~1.0 범위."""
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0)


def emphasis_position_y(position: str) -> float:
    """CapCut 텍스트 트랙 좌표계: 비디오 트랙과 동일 (양수=상단, 음수=하단).

    포지션 지침:
      - "top" : 상단 (이미지 없는 씬에서 권장)
      - "center" : 화면 중앙
      - "lower" : 자막 바로 위 (split 이미지 있는 씬에서 권장, 이미지와 안 겹침)
      - "bottom" : 자막 위치 근처
    """
    return {
        "top": 0.7,
        "center": 0.2,
        "lower": -0.1,
        "bottom": -0.18,
    }.get(position, 0.7)


# ===== CE-02/CE-03 (2026-06-04): overlay position_y 슬롯 → transform.y 매핑 =====
# CONTRACT §2 준수. CapCut 좌표: y 양수=위, 음수=아래. 자막 y≈-0.234(하단),
# 얼굴 세이프존 = 정중앙 normalized -0.15 ~ +0.15 (정적 토킹헤드 가정).
# overlay/dual 카드의 "중심 transform.y"를 슬롯명으로 고른다. 자유 float 금지.
#   - "top"    : 상단(얼굴 위). 기존 overlay 하드코딩 0.55와 동일 동작(하위호환 default).
#   - "center" : 0.0 (얼굴 위 — 비권장. CE-03 가드가 경고).
#   - "lower"  : 자막 바로 위 빈 공간. 카드 하단이 자막존(-0.20)을 넘지 않게 CE-03가 보정.
# 미지정(=None)이면 top으로 떨어져 현재 동작 보존.
SUBTITLE_ZONE_Y = -0.234          # 자막 중심 y (CONTRACT §2)
SUBTITLE_ZONE_GUARD = -0.20       # 카드 하단이 이 값보다 내려가면 자막존 침범
FACE_SAFEZONE_HALF = 0.15         # 얼굴 세이프존 = 정중앙 ±0.15 (정적 토킹헤드)


def overlay_position_y(position: str) -> float:
    """overlay/dual 카드 중심의 normalized transform.y 슬롯 매핑.

    값은 "카드 중심" 기준이며, 실제 카드 높이를 모르는 상태의 기본 슬롯이다.
    bbox 기반 정밀 보정(자막존/얼굴존 회피)은 _guard_overlay_zone()이 수행한다.
    미지정/미인식 슬롯은 기존 overlay 하드코딩과 동일한 top(0.55)으로 폴백.
    """
    return {
        "top": 0.55,     # 기존 overlay 하드코딩 값 그대로(하위호환)
        "center": 0.0,
        "lower": -0.05,  # 자막 바로 위. CE-03가 카드 높이 따라 추가 보정
    }.get(position, 0.55)


def _overlay_render_half_height_norm(
    style: str, target_ratio: float,
    canvas_w: int, canvas_h: int,
    material_w: int, material_h: int,
) -> float:
    """overlay/dual 카드의 화면 내 정규화 세로 반높이(half-height) 계산.

    style_clip_and_uniform과 동일한 scale 공식을 재사용:
      scale_value = target_ratio × (canvas_w / material_w)
      렌더 픽셀 높이 = material_h × scale_value
      정규화 높이   = 렌더 픽셀 높이 / canvas_h
      half-height   = 정규화 높이 / 2
    split은 자체적으로 자막과 안 겹치게 main을 밀어내므로 가드 대상 아님 → 0 반환.
    """
    if style not in ("overlay", "dual"):
        return 0.0
    if material_w <= 0:
        material_w = canvas_w
    if canvas_h <= 0 or material_h <= 0:
        return 0.0
    scale_value = target_ratio * (canvas_w / float(material_w))
    render_h_px = material_h * scale_value
    h_norm = render_h_px / float(canvas_h)
    return h_norm / 2.0


def _guard_overlay_zone(
    style: str, pos_y: float, half_h: float, scene_label: str = "",
) -> float:
    """CE-03: overlay/dual bbox가 자막존/얼굴 세이프존을 침범하면 상단 push + 경고.

    bbox = [pos_y - half_h, pos_y + half_h] (CapCut 좌표, 양수=위).
    - 카드 하단(pos_y - half_h)이 자막존 가드(-0.20)보다 아래로 내려가면 → 위로 push.
    - 카드가 얼굴 세이프존(중앙 ±0.15)을 침범하면 → 세이프존 위로 push.
    경고는 stderr로만 출력(warning-only, hard-block 아님). split은 패스(self-resolve).
    반환: 보정된 pos_y (침범 없으면 입력 그대로).
    """
    import sys
    if style not in ("overlay", "dual") or half_h <= 0:
        return pos_y

    new_y = pos_y
    bottom = pos_y - half_h  # 카드 하단 y (작을수록 아래)
    top = pos_y + half_h     # 카드 상단 y

    # (a) 자막존 침범: 카드 하단이 -0.20보다 아래 → 카드 하단을 -0.20에 맞춤
    if bottom < SUBTITLE_ZONE_GUARD:
        new_bottom = SUBTITLE_ZONE_GUARD
        pushed = new_bottom + half_h
        print(
            f"[CE-03 warn]{(' ' + scene_label) if scene_label else ''} "
            f"overlay 카드 하단({bottom:+.3f})이 자막존({SUBTITLE_ZONE_Y:+.3f}) 침범 "
            f"→ transform.y {new_y:+.3f}→{pushed:+.3f} 상단 push",
            file=sys.stderr,
        )
        new_y = pushed
        bottom = new_y - half_h
        top = new_y + half_h

    # (b) 얼굴 세이프존(중앙 ±0.15) 침범: 카드가 세이프존과 겹치면 세이프존 위로 push.
    #     겹침 조건 = (bottom < +0.15) and (top > -0.15).
    if bottom < FACE_SAFEZONE_HALF and top > -FACE_SAFEZONE_HALF:
        # 카드 하단을 얼굴 세이프존 상단(+0.15) 위로 올림.
        pushed = FACE_SAFEZONE_HALF + half_h
        if pushed > new_y:  # 위로만 밀어냄(아래로 끌어내리지 않음)
            print(
                f"[CE-03 warn]{(' ' + scene_label) if scene_label else ''} "
                f"overlay 카드(bbox [{bottom:+.3f},{top:+.3f}])가 얼굴 세이프존"
                f"(±{FACE_SAFEZONE_HALF}) 침범 → transform.y {new_y:+.3f}→{pushed:+.3f} 상단 push",
                file=sys.stderr,
            )
            new_y = pushed

    # 상단 클램프: 카드 상단이 화면 밖(>1.0)으로 너무 나가지 않게 보호.
    if new_y + half_h > 1.0:
        clamped = 1.0 - half_h
        if clamped < new_y:
            new_y = clamped

    return new_y


def auto_static_overlay_dur_us(text: str | None, scene_remaining_us: int) -> int:
    """CE-01: 정적 PNG overlay 표시 길이 자동 산정 (display_dur 미지정 시).

    글자수 기반: len/13 + 0.7s 버퍼. 2.5~7s clamp. 항상 씬 잔여 길이로 추가 clamp.
    text 미제공(None/빈문자)이면 기본 3.5s를 씬 잔여로 clamp.
    MOV overlay는 intrinsic timeline 길이를 쓰므로 이 함수 대상 아님.
    """
    n = len(text) if text else 0
    if n > 0:
        dur_sec = n / 13.0 + 0.7
    else:
        dur_sec = 3.5
    dur_sec = max(2.5, min(7.0, dur_sec))
    dur_us = int(dur_sec * SEC)
    if scene_remaining_us > 0:
        dur_us = min(dur_us, scene_remaining_us)
    return dur_us


def make_emphasis_text_material(
    tpl: dict,
    text: str,
    font_size: float,
    color_hex: str = "#FFFFFF",
    accent_color_hex: str = "#FFD54F",
    accent_words: list[str] | None = None,
    stroke_width: float = 0.04,
    font_name: str | None = None,
    font_path: str | None = None,
) -> dict:
    """자막 텍스트 material 템플릿에서 강조 텍스트 material 생성.

    단어 단위로 styles[] 배열을 여러 개 생성하여 accent_words 에 포함된 단어만
    accent_color 로 칠함 (CapCut 의 부분 색상 지정 방식).
    """
    mat = deepcopy(tpl)
    mat_id = new_uuid_simple()
    mat["id"] = mat_id

    base_rgb = list(hex_to_rgb01(color_hex))
    accent_rgb = list(hex_to_rgb01(accent_color_hex))
    accent_set = set(accent_words or [])

    content = json.loads(mat["content"])
    content["text"] = text

    # 기본 스타일 템플릿 (첫 번째 기존 스타일 복제)
    base_style_tpl = deepcopy(content["styles"][0]) if content.get("styles") else None
    if base_style_tpl is None:
        # 최소한의 fallback 스타일
        base_style_tpl = {
            "fill": {"alpha": 1.0, "content": {"render_type": "solid", "solid": {"alpha": 1.0, "color": [1, 1, 1]}}},
            "size": float(font_size),
            "bold": False,
            "italic": False,
            "underline": False,
            "strokes": [{"content": {"solid": {"alpha": 1.0, "color": [0, 0, 0]}}, "width": stroke_width}],
        }

    # 단어 경계로 스타일 배열 구성. 빈 토큰 (연속 공백 때문에 발생) 은 건너뜀.
    # 각 토큰의 range 는 trailing space 까지 확장 — 안 그러면 CapCut 이
    # 스타일 없는 공백을 기본 폰트로 더 넓게 렌더링해서 비정상 자간이 생김.
    tokens = text.split(" ")
    styles = []
    char_idx = 0
    for i, tok in enumerate(tokens):
        tok_len = len(tok)
        if tok_len == 0:
            char_idx += 1
            continue
        is_last = i == len(tokens) - 1
        range_end = char_idx + tok_len + (0 if is_last else 1)
        style = deepcopy(base_style_tpl)
        style["range"] = [char_idx, range_end]
        style["size"] = float(font_size)
        use_accent = tok in accent_set
        rgb = accent_rgb if use_accent else base_rgb
        style["fill"]["content"]["solid"]["color"] = rgb
        style["fill"]["content"]["solid"]["alpha"] = 1.0
        if style.get("strokes"):
            style["strokes"][0]["width"] = stroke_width
            style["strokes"][0]["content"]["solid"]["color"] = [0.0, 0.0, 0.0]
            style["strokes"][0]["content"]["solid"]["alpha"] = 1.0
        styles.append(style)
        char_idx += tok_len + (1 if i < len(tokens) - 1 else 0)  # 공백 한 칸

    # font_name / font_path override (예: 타이틀은 "아네모네", 자막은 ODITTABILITY)
    # 자막과 동일한 방식: top-level 필드 + content.styles[*].font 모두 덮어씀.
    # font_name 이 주어지면 font_path 는 CapCut userFontData 레지스트리에서 역조회.
    if font_name is not None:
        resolved_path = font_path
        if resolved_path is None:
            resolved_path = resolve_font_path_by_name(font_name) or ""
        mat["font_name"] = font_name
        mat["font_title"] = font_name
        mat["font_path"] = resolved_path
        for s in styles:
            if "font" in s and isinstance(s["font"], dict):
                s["font"]["name"] = font_name
                s["font"]["path"] = resolved_path
                s["font"]["id"] = ""
    elif font_path is not None:
        mat["font_path"] = font_path
        for s in styles:
            if "font" in s and isinstance(s["font"], dict):
                s["font"]["path"] = font_path

    content["styles"] = styles
    mat["content"] = json.dumps(content, ensure_ascii=False)
    mat["font_size"] = float(font_size)
    mat["text_size"] = int(font_size * 2)  # UI 단위
    mat["text_color"] = color_hex
    mat["border_color"] = "#000000"
    mat["border_width"] = stroke_width
    mat["border_alpha"] = 1.0
    return mat


def crop_vertical_transparent_margins(
    img_path: str, out_dir: Path | None = None, alpha_threshold: int = 0,
) -> tuple[str, int, int] | None:
    """CE-04 (2026-06-04): 정적 PNG 카드의 위아래 투명 여백만 자동 크롭/리프레임.

    16:9 카드 material은 1920×1080 viewport 중앙 정렬이라 위아래 투명 padding이 크고,
    overlay scale 공식상 캔버스 세로의 ~17%만 차지한다. 위아래 투명 여백을 잘라내면
    동일 가로 점유율(overlay_h_ratio)을 유지하면서 콘텐츠가 box를 꽉 채워 더 크게 보인다.

    설계(revision_note 준수):
      - ffmpeg cropdetect 대신 PIL alpha 채널 getbbox 사용(반투명 카드는 alpha>0 전 영역이
        content이므로 정확). glow/blur는 alpha>0이라 자연히 포함 → 클립 방지.
      - **세로 padding만 제거, 가로(width)는 보존**. 가로까지 크롭하면 scale 공식이
        material_w를 입력으로 width-anchored 재계산하므로 의도치 않은 확대가 생긴다.
      - 크롭본을 <stem>.cropped.png로 저장하고 (path, new_w, new_h) 반환.
      - 크롭 불필요(여백 거의 없음)·실패·PIL 미설치·비PNG면 None 반환 → 호출부는 원본 사용.

    Returns: (cropped_path, new_w, new_h) 또는 None.
    """
    import sys
    if Image is None:
        return None
    p = Path(img_path)
    if p.suffix.lower() not in (".png",):
        return None  # 알파 채널 없는 포맷은 대상 아님(MOV/JPG 등은 통합 노트 참조)
    try:
        with Image.open(p) as im:
            im = im.convert("RGBA")
            w, h = im.size
            alpha = im.getchannel("A")
            if alpha_threshold > 0:
                alpha = alpha.point(lambda a: 255 if a > alpha_threshold else 0)
            bbox = alpha.getbbox()  # (left, upper, right, lower) — 불투명 경계
            if bbox is None:
                return None  # 완전 투명 → 크롭 의미 없음
            _, upper, _, lower = bbox
            # 세로 padding만 제거. 가로는 0~w 그대로 보존(scale 공식 width-anchor 보호).
            top_pad = upper
            bot_pad = h - lower
            # 위아래 합쳐 세로의 4% 미만이면 크롭 이득 미미 → skip(무한 재처리/노이즈 방지).
            if (top_pad + bot_pad) < max(2, int(h * 0.04)):
                return None
            cropped = im.crop((0, upper, w, lower))
            new_w, new_h = cropped.size
            if new_h <= 0 or new_w <= 0:
                return None
            target_dir = out_dir if out_dir is not None else p.parent
            target_dir.mkdir(parents=True, exist_ok=True)
            out_path = target_dir / f"{p.stem}.cropped.png"
            cropped.save(out_path, "PNG")
            print(
                f"[CE-04] {p.name}: 세로 투명여백 크롭 {w}x{h} → {new_w}x{new_h} "
                f"(top={top_pad}px, bottom={bot_pad}px)",
                file=sys.stderr,
            )
            return (str(out_path), new_w, new_h)
    except Exception as e:  # 크롭 실패는 치명적이지 않음 — 원본으로 폴백.
        print(f"[CE-04 warn] crop 실패 ({img_path}): {e} → 원본 사용", file=sys.stderr)
        return None


def style_clip_and_uniform(
    style: str, opacity: float, ratio: float, side: str = "center",
    img_aspect: float = 1.0,
    canvas_w: int = 2160, canvas_h: int = 3840,
    material_w: int = 1920, material_h: int = 1080,
    overlay_pos_y: float | None = None,
    overlay_h_ratio: float | None = None,
) -> tuple[dict, dict]:
    """오버레이 스타일별 (clip, uniform_scale) 반환.

    CE-02 (2026-06-04): overlay 분기의 transform.y / target_ratio 하드코딩 0.55를
    인자로 분리. 변수명 혼동 제거를 위해 세로위치=overlay_pos_y, 가로점유=overlay_h_ratio
    로 분리한다. 둘 다 None이면 기존 동작(0.55/0.55)을 그대로 유지(하위호환).
      - overlay_pos_y   : overlay 카드 중심 transform.y (None → 0.55, 기존 동작)
      - overlay_h_ratio : overlay 가로 점유 비율 (None → ratio 인자, 그래도 None이면 0.55)
    uniform_scale.value는 항상 1.0 불변(아래 docstring 경고 참조).

    ⚠️ CapCut scale 규칙 (2026-05-29 재확정 — 이전 "세 값 일치" 가정은 버그였음):
       - CapCut의 clip.scale은 material 원본 픽셀에 곱해지는 배율 (절대 pixel 기준).
         실제 렌더 크기는 **오직 clip.scale.x/y**가 결정한다.
       - uniform_scale.on=True = CapCut UI의 **Aspect Lock(가로세로 비율 고정)** 플래그.
       - ⛔ uniform_scale.value는 **항상 1.0**이어야 한다 (Aspect Lock의 기준 배율).
         여기에 clip.scale과 같은 크기값(예: 0.37)을 넣으면 CapCut이 첫 로드 시
         value를 크기에 **이중 적용**해 overlay를 세로로 길게 왜곡시킨다.
         (실측: value=0.37 + scale=0.37 → 세로로 찌그러짐. UI에서 Aspect Lock을
          껐다 켜면 CapCut이 value를 1.0으로 리셋하며 정상화됨.)
       - 따라서 크기 = clip.scale.x = clip.scale.y = target_ratio × (canvas_w / material_w),
         그리고 **uniform_scale = {on: True, value: 1.0}** 으로 고정.
       - split 도 동일하게 value=1.0 (전체 화면 너비 fit).

    좌표계: y 양수 = 상단, y 음수 = 하단 (비디오 트랙).
    """
    if style == "split":
        # Split 구조:
        #   - uniform_scale=True, value=1.0 → 이미지가 화면 가로(2160)에 fit, 원본 비율 유지
        #   - 이미지 세로(화면 좌표) = 2160 / img_aspect
        #   - 화면 세로 대비 정규화 = (1/img_aspect) × (9/16)
        #   - transform.y (상단 정렬) = 1.0 - image_h_norm
        # 예시:
        #   16:9 이미지 (aspect=1.78) → image_h_norm=0.316 → y=+0.684 → 상단 1/3
        #   1:1 이미지 (aspect=1.0)  → image_h_norm=0.563 → y=+0.437 → 상단 56%
        #   이미지 원본 비율 그대로 유지됨 (왜곡 0).
        image_h_norm = (1.0 / img_aspect) * (9.0 / 16.0)
        y_offset = 1.0 - image_h_norm
        v = 1.0
        clip = {
            "scale": {"x": v, "y": v},
            "rotation": 0.0,
            "transform": {"x": 0.0, "y": y_offset},
            "flip": {"vertical": False, "horizontal": False},
            "alpha": opacity,
        }
        uniform = {"on": True, "value": v}
        return clip, uniform
    if style == "overlay":
        # target_ratio = overlay가 canvas 가로의 몇 %를 차지할지 (기본 55%)
        # 크기는 clip.scale.x/y가 결정. uniform_scale.value는 1.0 고정(위 docstring 참조).
        # CE-02: 하드코딩 대신 overlay_h_ratio(가로점유) / overlay_pos_y(세로위치) 인자 사용.
        # None이면 각각 0.55로 폴백 → 기존 동작 그대로 보존.
        h_ratio = overlay_h_ratio
        if h_ratio is None:
            h_ratio = ratio if ratio is not None else 0.55
        pos_y = overlay_pos_y if overlay_pos_y is not None else 0.55
        target_ratio = h_ratio
        if material_w <= 0:
            material_w = canvas_w
        scale_value = target_ratio * (canvas_w / float(material_w))
        clip = {
            "scale": {"x": scale_value, "y": scale_value},
            "rotation": 0.0,
            "transform": {"x": 0.0, "y": pos_y},
            "flip": {"vertical": False, "horizontal": False},
            "alpha": opacity,
        }
        uniform = {"on": True, "value": 1.0}
        return clip, uniform
    if style == "dual":
        target_ratio = 0.42
        if material_w <= 0:
            material_w = canvas_w
        scale_value = target_ratio * (canvas_w / float(material_w))
        x_off = -0.28 if side == "left" else 0.28
        clip = {
            "scale": {"x": scale_value, "y": scale_value},
            "rotation": 0.0,
            "transform": {"x": x_off, "y": 0.6},
            "flip": {"vertical": False, "horizontal": False},
            "alpha": opacity,
        }
        uniform = {"on": True, "value": 1.0}
        return clip, uniform
    raise ValueError(f"Unknown style: {style!r} (expected split|overlay|dual)")


def get_scene_timerange(draft: dict, scene_idx: int) -> tuple[int, int]:
    """메인 비디오 트랙의 scene_idx 번째 세그먼트의 (start_us, duration_us)."""
    main_segs = draft["tracks"][0]["segments"]
    if scene_idx >= len(main_segs):
        raise IndexError(f"scene_idx={scene_idx} out of range (main has {len(main_segs)} segments)")
    tr = main_segs[scene_idx]["target_timerange"]
    return tr["start"], tr["duration"]


def max_render_index(draft: dict) -> int:
    m = 0
    for t in draft["tracks"]:
        for s in t.get("segments", []):
            m = max(m, s.get("render_index", 0))
    return m


def patch(
    draft_path: Path,
    plan_path: Path,
    backup: bool = True,
    *,
    mode: str = "auto",
) -> dict:
    """B-roll/emphasis/title을 draft에 주입.

    Args:
        mode: idempotency 처리 방식
            - "auto" (기본): 같은 plan_hash면 no-op, 다른 plan이면 .clean_bak 복구 후 재패치
            - "force": 기존 patch 감지 무시하고 그대로 append (위험 — 중복 누적)
            - "reject": 이미 patched면 RuntimeError
            - "clean": 무조건 .clean_bak에서 복구 후 재패치
    """
    draft_path = Path(draft_path)
    plan_path = Path(plan_path)

    with open(draft_path, "r", encoding="utf-8") as f:
        draft = json.load(f)
    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    plan_hash = _canonical_plan_hash(plan)
    existing = _detect_existing_patch(draft, draft_path)

    if existing:
        existing_hash = existing.get("plan_hash")
        detected_via = existing.get("detected_via", "state_file")
        if mode == "reject":
            raise RuntimeError(
                f"[mode=reject] 이미 patched됨 (hash={existing_hash}, via={detected_via}).\n"
                f"  다른 mode 사용: --mode auto|clean|force"
            )
        if mode == "force":
            print(f"[mode=force] 기존 patch 감지 무시 — 중복 누적 위험")
        elif mode == "clean" or (mode == "auto" and existing_hash != plan_hash):
            reason = "동일 mode=clean 요청" if mode == "clean" else f"plan_hash 불일치 (기존={existing_hash}, 신규={plan_hash})"
            print(f"[mode={mode}] 기존 patch 감지 ({reason}) → .clean_bak 복구 후 재patch")
            draft = _restore_from_clean_bak(draft_path)
        elif mode == "auto" and existing_hash == plan_hash:
            print(f"[mode=auto] 동일 plan_hash={plan_hash} 재patch 요청 → no-op (이미 적용됨)")
            return {
                "draft": str(draft_path),
                "skipped": True,
                "reason": "idempotent: same plan_hash already applied",
                "plan_hash": plan_hash,
                "existing_state": existing,
            }

    # .clean_bak은 최초 1회만 생성 (patched 안 된 상태일 때만)
    clean_bak_path = draft_path.with_suffix(".json.clean_bak")
    if not clean_bak_path.exists() and not existing:
        shutil.copy2(draft_path, clean_bak_path)
        print(f"[clean_bak] {clean_bak_path} (최초 1회 영구 백업)")

    # 템플릿 확보
    tpl_video_mat = deepcopy(draft["materials"]["videos"][0])
    tpl_speed = deepcopy(draft["materials"]["speeds"][0])
    tpl_main_track = draft["tracks"][0]
    tpl_seg = deepcopy(tpl_main_track["segments"][0])

    # 새 오버레이 트랙 생성 (기존 main_video 트랙을 템플릿)
    overlay_track = {k: v for k, v in tpl_main_track.items() if k != "segments"}
    overlay_track = deepcopy(overlay_track)
    overlay_track["id"] = new_uuid_simple()
    overlay_track["name"] = "broll_overlay"
    overlay_track["is_default_name"] = False
    overlay_track["segments"] = []

    base_render = max_render_index(draft) + 1

    def _make_broll_segment(img_path_str: str, img_w: int, img_h: int,
                            start_us: int, duration_us: int,
                            style: str, opacity: float, ratio: float,
                            render_idx: int, side: str = "center",
                            position_y: str | None = None,
                            overlay_h_ratio: float | None = None,
                            text_for_dur: str | None = None,
                            display_dur_us: int | None = None,
                            scene_label: str = "",
                            auto_crop: bool = False) -> dict:
        # CE-01/CE-02/CE-03/CE-04 (2026-06-04):
        #   position_y       : overlay/dual 세로위치 슬롯(top/center/lower). None→top(기존 0.55).
        #   overlay_h_ratio  : overlay 가로 점유 비율. None이면 ratio 인자 사용(하위호환).
        #   text_for_dur     : 정적 PNG display_dur 자동 산정용 텍스트(글자수 기반).
        #   display_dur_us   : plan에서 명시한 표시 길이(µs). 지정 시 우선. 항상 씬 잔여로 clamp.
        #   scene_label      : stderr 경고용 라벨.
        #   auto_crop        : CE-04 — overlay 정적 PNG 위아래 투명여백 크롭(opt-in, 기본 off).
        # CE-04: overlay 정적 PNG 위아래 투명여백 자동 크롭(opt-in). 가로 보존 → scale 공식
        # 그대로 가로 점유율 유지, content만 box를 꽉 채워 더 크게 보임. 실패 시 원본 폴백.
        if auto_crop and style == "overlay":
            _suf = Path(img_path_str).suffix.lower()
            if _suf not in VIDEO_OVERLAY_EXTS:
                cropped = crop_vertical_transparent_margins(img_path_str)
                if cropped is not None:
                    img_path_str, img_w, img_h = cropped

        new_mat_id = new_uuid_simple()
        new_mat = deepcopy(tpl_video_mat)
        new_mat["id"] = new_mat_id
        new_mat["material_id"] = new_mat_id
        new_mat["path"] = img_path_str.replace("/", "\\")
        new_mat["material_name"] = f"broll_{style}_{side}"

        # Detect video overlays (.mov/.mp4/.webm) vs static images (.png/.jpg).
        # For video: read real duration via ffprobe → clamp source/target to
        # video's own length → prevents CapCut stretch (same pattern as BGM bug fix).
        suffix = Path(img_path_str).suffix.lower()
        is_video_overlay = suffix in VIDEO_OVERLAY_EXTS

        # CE-01: display_dur 적용. duration_us는 호출부에서 이미 (씬길이 - offset)으로
        # 산정된 "씬 잔여 길이"다. 항상 이 값으로 상한 clamp한다(씬 경계 보호).
        if is_video_overlay:
            video_dur_us = _probe_video_duration_us(Path(img_path_str))
            if video_dur_us <= 0:
                raise ValueError(
                    f"ffprobe could not read duration of video overlay: {img_path_str}"
                )
            # MOV는 intrinsic timeline 길이를 그대로 사용(GSAP 등장/fade tail 포함).
            # 씬보다 길면 잔여 씬길이로 clamp(나머지 구간엔 overlay 없음 — 루프 아님, 의도적).
            effective_us = min(duration_us, video_dur_us)
            # display_dur_sec를 명시했으면 추가 상한으로만 적용(intrinsic보다 짧게 자르기).
            if display_dur_us is not None and display_dur_us > 0:
                effective_us = min(effective_us, display_dur_us)
            new_mat["type"] = "video"
            new_mat["width"] = img_w
            new_mat["height"] = img_h
            new_mat["duration"] = video_dur_us  # full source length
            src_dur_us = effective_us
            tgt_dur_us = effective_us
        else:
            # 정적 PNG: display_dur_us 명시 시 우선, 미지정 시 글자수 기반 자동 산정.
            # (미지정인데 text도 없으면 auto_static_overlay_dur_us가 기본 3.5s 사용)
            if display_dur_us is not None and display_dur_us > 0:
                static_dur = min(display_dur_us, duration_us) if duration_us > 0 else display_dur_us
            elif text_for_dur is not None:
                static_dur = auto_static_overlay_dur_us(text_for_dur, duration_us)
            else:
                # text/display_dur 둘 다 미지정 → 기존 동작(씬 잔여 전체 재생) 보존.
                static_dur = duration_us
            new_mat["type"] = "photo"
            new_mat["width"] = img_w
            new_mat["height"] = img_h
            new_mat["duration"] = static_dur
            src_dur_us = static_dur
            tgt_dur_us = static_dur

        if "has_audio" in new_mat:
            new_mat["has_audio"] = False
        draft["materials"]["videos"].append(new_mat)

        new_speed_id = new_uuid_simple()
        new_speed = deepcopy(tpl_speed)
        new_speed["id"] = new_speed_id
        draft["materials"]["speeds"].append(new_speed)

        seg = deepcopy(tpl_seg)
        seg["id"] = new_uuid_simple()
        seg["material_id"] = new_mat_id
        seg["extra_material_refs"] = [new_speed_id]
        seg["target_timerange"] = {"start": start_us, "duration": tgt_dur_us}
        seg["source_timerange"] = {"start": 0, "duration": src_dur_us}
        seg["render_timerange"] = {"start": 0, "duration": 0}
        img_aspect = img_w / img_h if img_h > 0 else 1.0
        # Canvas size for scale calculation (draft.canvas_config defaults to 2160x3840 for 9:16)
        canvas_cfg = draft.get("canvas_config", {}) or {}
        canvas_w = int(canvas_cfg.get("width", 2160))
        canvas_h = int(canvas_cfg.get("height", 3840))

        # CE-02/CE-03: overlay/dual의 세로위치 슬롯 → transform.y 매핑 + zone 가드.
        # split은 자체적으로 자막과 안 겹치게 main을 밀어내므로 가드/슬롯 비대상(None 유지).
        resolved_pos_y = None
        resolved_h_ratio = overlay_h_ratio  # None이면 style_clip_and_uniform이 ratio로 폴백
        if style == "overlay":
            # position_y 미지정 시 top(=0.55, 기존 동작) 폴백.
            base_pos_y = overlay_position_y(position_y) if position_y else 0.55
            eff_ratio = resolved_h_ratio if resolved_h_ratio is not None else (
                ratio if ratio is not None else 0.55
            )
            half_h = _overlay_render_half_height_norm(
                "overlay", eff_ratio, canvas_w, canvas_h, img_w, img_h,
            )
            resolved_pos_y = _guard_overlay_zone("overlay", base_pos_y, half_h, scene_label)

        clip, uniform = style_clip_and_uniform(
            style, opacity, ratio, side=side, img_aspect=img_aspect,
            canvas_w=canvas_w, canvas_h=canvas_h,
            material_w=img_w, material_h=img_h,
            overlay_pos_y=resolved_pos_y,
            overlay_h_ratio=resolved_h_ratio,
        )
        seg["clip"] = clip
        seg["uniform_scale"] = uniform
        seg["render_index"] = render_idx
        seg["track_render_index"] = 0
        return seg

    items = plan.get("items", [])
    added = []
    render_counter = 0
    for i, item in enumerate(items):
        scene_idx = int(item["scene_idx"])
        style = item["style"]
        opacity = float(item.get("opacity", 1.0))
        ratio = float(item.get("ratio", 0.55))

        # CE-01/CE-02 신규 plan 필드 (전부 optional, default가 기존 동작 보존):
        #   start_offset_sec : overlay 등장 시점(씬 시작 기준 초). default 0.0.
        #   display_dur_sec  : overlay 표시 길이(초). None이면 MOV=intrinsic / static=글자수.
        #   position_y       : overlay 세로위치 슬롯(top/center/lower). None→top.
        #   overlay_h_ratio  : overlay 가로 점유 비율. 미지정 시 ratio 사용(하위호환).
        start_offset_sec = float(item.get("start_offset_sec", 0.0) or 0.0)
        _disp = item.get("display_dur_sec", None)
        display_dur_us = int(float(_disp) * SEC) if _disp not in (None, "") else None
        position_y = item.get("position_y")  # 슬롯 문자열 또는 None
        overlay_h_ratio = item.get("overlay_h_ratio")  # 신규 명칭 우선
        overlay_h_ratio = float(overlay_h_ratio) if overlay_h_ratio not in (None, "") else None
        # CE-04 (opt-in): item 또는 plan 최상위 auto_crop_margins=true 시 정적 overlay 크롭.
        auto_crop = bool(item.get("auto_crop_margins", plan.get("auto_crop_margins", False)))

        scene_start_us, scene_dur_us = get_scene_timerange(draft, scene_idx)

        # CE-01: start_offset 적용. 씬 경계를 넘으면 0으로 클램프(emphasis L780-784 패턴).
        offset_us = int(max(0.0, start_offset_sec) * SEC)
        if offset_us >= scene_dur_us:
            import sys as _sys
            print(
                f"[CE-01 warn] scene {scene_idx} start_offset_sec={start_offset_sec}s가 "
                f"씬 길이({scene_dur_us/SEC:.2f}s) 초과 → offset 0으로 클램프",
                file=_sys.stderr,
            )
            offset_us = 0
        start_us = scene_start_us + offset_us
        # duration_us = 씬 잔여 길이(offset 이후). _make_broll_segment가 display_dur로 추가 clamp.
        duration_us = scene_dur_us - offset_us

        scene_label = f"scene {scene_idx}"

        if style == "dual":
            # 2개 이미지. item.images = [{path, width, height}, ...] 형식
            imgs = item.get("images", [])
            if len(imgs) != 2:
                raise ValueError(f"dual style requires exactly 2 images, got {len(imgs)} (scene {scene_idx})")
            sides = ["left", "right"]
            for j, (img, side) in enumerate(zip(imgs, sides)):
                img_path_s = str(Path(img["path"]).resolve())
                seg = _make_broll_segment(
                    img_path_s, int(img["width"]), int(img["height"]),
                    start_us, duration_us, "dual", opacity, ratio,
                    base_render + render_counter, side=side,
                    position_y=position_y, overlay_h_ratio=overlay_h_ratio,
                    text_for_dur=item.get("text"), display_dur_us=display_dur_us,
                    scene_label=scene_label,
                )
                overlay_track["segments"].append(seg)
                render_counter += 1
            added.append({
                "scene_idx": scene_idx, "style": "dual",
                "start_us": start_us, "duration_us": duration_us,
                "start_offset_sec": start_offset_sec,
                "image_count": 2, "main_shift_y": 0.0,
            })
        else:
            img_path_s = str(Path(item["image_path"]).resolve())
            seg = _make_broll_segment(
                img_path_s, int(item["image_width"]), int(item["image_height"]),
                start_us, duration_us, style, opacity, ratio,
                base_render + render_counter,
                position_y=position_y, overlay_h_ratio=overlay_h_ratio,
                text_for_dur=item.get("text"), display_dur_us=display_dur_us,
                scene_label=scene_label, auto_crop=auto_crop,
            )
            overlay_track["segments"].append(seg)
            render_counter += 1

            # split 모드: 메인 비디오를 이미지 차지 영역 바로 아래로 자동 이동.
            # image_h_norm = (1/aspect) × (9/16) → 이미지가 화면 세로에서 차지하는 정규화 높이
            # main_shift_y = -image_h_norm (이미지 세로만큼 아래로 이동)
            main_shift_y = 0.0
            if style == "split":
                main_seg = draft["tracks"][0]["segments"][scene_idx]
                img_w_px = int(item.get("image_width", 1920))
                img_h_px = int(item.get("image_height", 1080))
                aspect = img_w_px / img_h_px if img_h_px else 1.0
                image_h_norm = (1.0 / aspect) * (9.0 / 16.0)
                if "main_shift_y" in item:
                    main_shift_y = float(item["main_shift_y"])  # 수동 override
                else:
                    main_shift_y = -image_h_norm
                main_seg["clip"]["transform"]["y"] = main_shift_y

            added.append({
                "scene_idx": scene_idx, "style": style,
                "start_us": start_us, "duration_us": duration_us,
                "render_index": seg["render_index"],
                "main_shift_y": main_shift_y,
            })

    # 트랙 추가 (세그먼트 없으면 스킵)
    if overlay_track["segments"]:
        draft["tracks"].append(overlay_track)

    # --- Title (영상 시작 타이틀 — 무조건 권장) ---
    # broll_plan.json 최상위 `title` 필드가 있으면 씬 0 시작에 큰 강조 텍스트 자동 주입.
    # 이후 emphasis 리스트 맨 앞에 합쳐서 동일 파이프라인으로 처리.
    emphases = list(plan.get("emphasis", []))
    title_cfg = plan.get("title")
    title_injected = None
    if title_cfg and title_cfg.get("text"):
        title_emp = {
            "scene_idx": int(title_cfg.get("scene_idx", 0)),
            "text": str(title_cfg["text"]),
            "accent_words": title_cfg.get("accent_words", []),
            "start_offset_sec": float(title_cfg.get("start_offset_sec", 0.0)),
            "duration_sec": float(title_cfg.get("duration_sec", 4.0)),
            "position": title_cfg.get("position", "center"),
            "font_size": float(title_cfg.get("font_size", 20.0)),
            "color": title_cfg.get("color", "#FFFFFF"),
            "accent_color": title_cfg.get("accent_color", "#B366FF"),
            "stroke_width": float(title_cfg.get("stroke_width", 0.06)),
            # 2026-06-04: 미설치 "아네모네" → 등록된 "Pretendard Black" (System 폴백 방지)
            "font_name": title_cfg.get("font_name", "Pretendard Black"),
            "font_path": title_cfg.get("font_path"),
        }
        emphases.insert(0, title_emp)
        title_injected = title_emp

    # --- Emphasis (텍스트 트랙 주입) ---
    # CapCut 텍스트 트랙을 사용. accent_words 는 styles[] 배열 여러 개로 구현
    # (단어별 색상 지정). 사용자가 CapCut 에서 직접 편집 가능.
    emphasis_added = []
    if emphases:
        tpl_text_mat = deepcopy(draft["materials"]["texts"][0])
        tpl_sub_track = draft["tracks"][1]  # subtitles 트랙 템플릿
        tpl_sub_seg = deepcopy(tpl_sub_track["segments"][0])

        emphasis_track = {k: v for k, v in tpl_sub_track.items() if k != "segments"}
        emphasis_track = deepcopy(emphasis_track)
        emphasis_track["id"] = new_uuid_simple()
        emphasis_track["name"] = "emphasis_text"
        emphasis_track["is_default_name"] = False
        emphasis_track["segments"] = []

        emp_base_render = max(max_render_index(draft) + 10, 20000)

        for i, emp in enumerate(emphases):
            scene_idx = int(emp["scene_idx"])
            text = str(emp["text"])
            start_offset = float(emp.get("start_offset_sec", 0.0))
            duration_sec = float(emp.get("duration_sec", 2.0))
            position = emp.get("position", "top")
            font_size = float(emp.get("font_size", 30))  # CapCut 텍스트 단위 (자막=15)
            color = emp.get("color", "#FFFFFF")
            accent_color = emp.get("accent_color", "#FFD54F")
            accent_words = emp.get("accent_words", [])
            stroke_w = float(emp.get("stroke_width", 0.04))  # CapCut 비율 단위
            font_name = emp.get("font_name")
            font_path = emp.get("font_path")

            scene_start_us, scene_dur_us = get_scene_timerange(draft, scene_idx)
            start_us = scene_start_us + int(start_offset * SEC)
            duration_us = int(duration_sec * SEC)
            max_end = scene_start_us + scene_dur_us
            if start_us + duration_us > max_end:
                duration_us = max_end - start_us

            # 텍스트 material (단어별 색상)
            new_mat = make_emphasis_text_material(
                tpl_text_mat,
                text=text,
                font_size=font_size,
                color_hex=color,
                accent_color_hex=accent_color,
                accent_words=accent_words,
                stroke_width=stroke_w,
                font_name=font_name,
                font_path=font_path,
            )
            draft["materials"]["texts"].append(new_mat)

            # 세그먼트 (자막 트랙 템플릿 복사 후 좌표/타이밍 수정)
            new_seg = deepcopy(tpl_sub_seg)
            new_seg["id"] = new_uuid_simple()
            new_seg["material_id"] = new_mat["id"]
            new_seg["extra_material_refs"] = []
            new_seg["target_timerange"] = {"start": start_us, "duration": duration_us}
            new_seg["source_timerange"] = {"start": 0, "duration": duration_us}
            new_seg["render_timerange"] = {"start": 0, "duration": 0}
            # 텍스트 트랙 좌표 (비디오 트랙과 동일: y 양수=상단, 음수=하단)
            new_seg["clip"]["transform"]["x"] = 0.0
            new_seg["clip"]["transform"]["y"] = emphasis_position_y(position)
            new_seg["clip"]["scale"] = {"x": 1.0, "y": 1.0}
            new_seg["clip"]["alpha"] = 1.0
            new_seg["render_index"] = emp_base_render + i

            emphasis_track["segments"].append(new_seg)
            emphasis_added.append({
                "scene_idx": scene_idx, "text": text,
                "start_us": start_us, "duration_us": duration_us,
                "position": position, "font_size": font_size,
                "accent_words": accent_words,
            })

        if emphasis_track["segments"]:
            draft["tracks"].append(emphasis_track)

    # 하위호환 .overlay_bak (최신 pre-patch 상태만)
    if backup:
        bak = draft_path.with_suffix(".json.overlay_bak")
        shutil.copy2(draft_path, bak)
        print(f"[backup] {bak}")

    with open(draft_path, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False)

    # 사이드카 state 기록 (다음 실행 시 멱등성 판단 재료)
    _write_patch_state(draft_path, {
        "plan_hash": plan_hash,
        "patched_at": int(time.time()),
        "mode": mode,
        "plan_path": str(plan_path),
        "items_count": len(added),
        "emphasis_count": len(emphasis_added),
    })

    # .fx_clean_bak + fx state 무효화 — overlay 변경은 fx_patcher가 clean 모드에서
    # 복구 baseline으로 삼는 pre-FX snapshot을 stale하게 만든다. 예) 이전 plan에서 7개
    # broll overlay가 있었는데 새 plan이 3개라면, 남아있는 fx_clean_bak에 옛 7개가 박혀 있고,
    # fx_patcher가 clean 모드로 복구하면 옛 overlay가 부활함. overlay 패치 직후 이 파일들을
    # 삭제하여 다음 fx_patcher 실행 시 현재 draft(=새 overlay 반영 상태)를 fresh baseline으로
    # 저장하게 한다. (2026-04-22 162141 프로젝트에서 실제 발생한 버그 수정)
    invalidated = []
    fx_clean_bak = draft_path.with_suffix(".json.fx_clean_bak")
    if fx_clean_bak.exists():
        fx_clean_bak.unlink()
        invalidated.append(fx_clean_bak.name)
    fx_state_path = draft_path.parent / ".omc_fx_patch_state.json"
    if fx_state_path.exists():
        fx_state_path.unlink()
        invalidated.append(fx_state_path.name)
    if invalidated:
        print(f"[invalidate] overlay 변경으로 fx 아티팩트 제거: {', '.join(invalidated)}")
        print(f"             → 다음 fx_patcher 실행 시 현재 draft를 fresh baseline으로 저장")

    return {
        "draft": str(draft_path),
        "plan_hash": plan_hash,
        "mode": mode,
        "title_injected": title_injected,
        "added": added,
        "emphasis_added": emphasis_added,
        "total_videos": len(draft["materials"]["videos"]),
        "total_texts": len(draft["materials"]["texts"]),
        "total_tracks": len(draft["tracks"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--draft", required=True, help="draft_content.json 절대경로")
    ap.add_argument("--plan", required=True, help="broll_plan.json 절대경로")
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument(
        "--mode",
        choices=["auto", "force", "reject", "clean"],
        default="auto",
        help=(
            "멱등성 모드 (기본 auto): "
            "auto=동일 plan no-op/다른 plan 복구 후 재패치 | "
            "force=감지 무시 (위험) | "
            "reject=이미 patched면 에러 | "
            "clean=무조건 .clean_bak 복구 후 재패치"
        ),
    )
    args = ap.parse_args()

    result = patch(
        Path(args.draft),
        Path(args.plan),
        backup=not args.no_backup,
        mode=args.mode,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
