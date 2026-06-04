"""
Phase 4b: B-roll Generator (Gemini 이미지 + 내장 text_card)

scene_plan_reels.locked.json의 각 비트를 읽고:
  - `screenshot` 타입: Gemini Imagen으로 src_hint 프롬프트 이미지 생성
  - `text_card` 타입: Python PIL로 직접 합성 (API 불필요)
  - `logo_lockup` 타입: Gemini Imagen으로 브랜드 로고 락업 생성
  - `comparison_split` 타입: 두 이미지 Gemini로 생성 후 합성
  - `screen_recording` 타입: ⚠️ Gemini 이미지로 대체 (실제 스크린 레코딩 불가)
  - `none` (HOOK/CTA): skip

출력:
  broll/<beat_id>.png (or .mp4)
  broll/metadata.json

주의:
  Gemini Imagen은 스크린 레코딩 동영상을 못 만들기 때문에,
  `screen_recording` 비트도 정적 이미지로 대체됩니다 (스크린샷 느낌).
  실제 동영상 녹화가 필요하면 Playwright 경로 사용 (별도).

참고:
  tools/gemini_image_generator.py (기존, 스타일 참고)
"""
import argparse
import base64
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).parent.parent.parent


# ===== .env loader =====

def load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if v and k not in os.environ:
            os.environ[k] = v


# ===== Gemini client =====

def get_genai_client():
    load_env()
    api_key = os.environ.get("GOOGLE_AI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_AI_API_KEY missing (check .env)")

    from google import genai
    client = genai.Client(api_key=api_key)
    return client


# ===== Text card (PIL, no API) =====

def build_text_card(
    headline: str,
    subline: Optional[str] = None,
    size: tuple[int, int] = (1080, 960),
    bg_color: str = "#0D0D0D",
    accent_color: str = "#2C6EFF",
) -> bytes:
    """
    text_card broll을 PIL로 직접 렌더.
    반환: PNG bytes
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise RuntimeError("Pillow required for text_card: pip install Pillow")

    img = Image.new("RGB", size, bg_color)
    draw = ImageDraw.Draw(img)

    # 폰트 로드 (시스템 기본 한글 폰트 시도)
    font_paths = [
        "C:/Windows/Fonts/malgun.ttf",         # Windows 맑은 고딕
        "C:/Windows/Fonts/malgunbd.ttf",       # Windows 맑은 고딕 Bold
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",  # macOS
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",  # Linux
    ]
    headline_font = None
    subline_font = None
    for fp in font_paths:
        if os.path.exists(fp):
            try:
                headline_font = ImageFont.truetype(fp, 96)
                subline_font = ImageFont.truetype(fp, 48)
                break
            except Exception:
                pass

    if not headline_font:
        headline_font = ImageFont.load_default()
        subline_font = ImageFont.load_default()

    # No accent border — clean design

    # Headline (multi-line)
    headline_lines = headline.split("\n")
    line_height = 120
    total_height = len(headline_lines) * line_height
    y_start = (size[1] - total_height) // 2 - (30 if subline else 0)

    for i, line in enumerate(headline_lines):
        try:
            bbox = draw.textbbox((0, 0), line, font=headline_font)
            text_w = bbox[2] - bbox[0]
        except Exception:
            text_w = len(line) * 60
        x = (size[0] - text_w) // 2
        y = y_start + i * line_height
        draw.text((x, y), line, fill="white", font=headline_font)

    # Subline
    if subline:
        try:
            bbox = draw.textbbox((0, 0), subline, font=subline_font)
            text_w = bbox[2] - bbox[0]
        except Exception:
            text_w = len(subline) * 30
        x = (size[0] - text_w) // 2
        y = y_start + total_height + 40
        draw.text((x, y), subline, fill=(255, 255, 255, 150), font=subline_font)

    # Save to bytes
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ===== Gemini image generation =====

def generate_gemini_image(
    client,
    prompt: str,
    aspect_ratio: str = "1:1",
    output_path: Path = None,
) -> bytes:
    """
    Gemini Imagen 호출. aspect_ratio를 API config로 강제.

    지원 비율: 1:1, 9:16, 16:9, 3:4, 4:3, 3:2, 2:3, 4:5, 5:4, 21:9
    Returns: PNG bytes
    """
    from google.genai import types

    # 나노바나나Pro 우선 (Gemini 3 Pro Image — 4K, 정확한 텍스트 렌더링)
    model_candidates = [
        "gemini-3-pro-image-preview",
        "gemini-3.1-flash-image-preview",
        "gemini-2.5-flash-image",
    ]
    config = types.GenerateContentConfig(
        response_modalities=["image", "text"],
        image_config=types.ImageConfig(aspect_ratio=aspect_ratio),
    )
    last_err = None
    response = None
    for model_name in model_candidates:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=config,
            )
            break
        except Exception as e:
            last_err = e
            continue
    if response is None:
        raise RuntimeError(f"Gemini image gen failed all models: {last_err}")

    # Extract image from response
    for cand in response.candidates:
        for part in cand.content.parts:
            if hasattr(part, "inline_data") and part.inline_data:
                data = part.inline_data.data
                if isinstance(data, str):
                    return base64.b64decode(data)
                return data

    raise RuntimeError("no image in response")


def _layout_to_aspect(layout: str) -> tuple[str, str, str]:
    """레이아웃 → (비율 문구, 크기 문구, Gemini config 비율).

    Remotion 컨테이너 실제 크기에 맞춤:
    - full_broll: 전체 1080x1920 (9:16)
    - split: 상단 55% 1080x1056 (≈1:1)
    - overlay: 960x560 (≈16:9)

    Gemini config 비율이 API가 강제하는 실제 이미지 크기.
    """
    if layout == "full_broll":
        return ("PORTRAIT 9:16 aspect ratio (1080x1920)", "tall vertical portrait image", "9:16")
    elif layout == "split":
        return ("SQUARE 1:1 aspect ratio (1080x1080)", "square image", "1:1")
    elif layout == "overlay":
        return ("LANDSCAPE 16:9 aspect ratio (960x560)", "landscape horizontal image", "16:9")
    else:
        return ("PORTRAIT 9:16 aspect ratio (1080x1920)", "tall vertical portrait image", "9:16")


def _has_text_overlay_animations(beat: dict) -> bool:
    """
    Beat에 텍스트 오버레이 애니메이션이 있는지 감지.

    이 경우 B-roll 이미지는 '배경 전용'이어야 함 (텍스트 없음).
    Remotion이 위에 text_pop을 그리므로 이미지 내 텍스트는 중복 + 잘림 원인.
    """
    text_overlay_types = {"text_pop", "text_label", "number_counter", "typing"}
    animations = beat.get("animations") or []
    for anim in animations:
        if not isinstance(anim, dict):
            continue
        if anim.get("type") in text_overlay_types:
            return True
    return False


def _import_broll_prompts():
    """capcut_pipeline/broll_prompts.py에서 build_prompt/validate_prompt 가져오기.

    Reels와 CapCut 파이프라인 모두 동일한 8-type 체계를 공유.
    """
    import sys as _sys
    from pathlib import Path as _Path
    capcut_dir = _Path(__file__).parent.parent / "capcut_pipeline"
    if str(capcut_dir) not in _sys.path:
        _sys.path.insert(0, str(capcut_dir))
    from broll_prompts import build_prompt, validate_prompt, TYPES
    return build_prompt, validate_prompt, TYPES


# Legacy (reels v1) type → NEW 8-type 매핑.
# webtoon removed — use symbol_moment or icon_hero.
_LEGACY_TYPE_MAP = {
    "screenshot": "ui_evidence",
    "screen_recording": "ui_evidence",
    "logo_lockup": "dual_icon",
    "comparison_split": "dual_icon",
    "image_sequence": "symbol_moment",
    "product_showcase": "icon_hero",
    "atmospheric": "symbol_moment",
    # identity mappings for NEW types (so JSON can already use them directly)
    "icon_hero": "icon_hero",
    "number_hero": "number_hero",
    "stat_card": "stat_card",
    "message_object": "message_object",
    "symbol_moment": "symbol_moment",
    "split_stack": "split_stack",
    "dual_icon": "dual_icon",
    "ui_evidence": "ui_evidence",
}


def build_prompt_for_broll(beat: dict) -> tuple[str, str]:
    """B-roll 비트 → (Gemini 프롬프트, Gemini config 비율).

    NEW 8-type system에 위임. 단, reels 고유의 두 가지 레이아웃-의존 로직은
    여기서 유지:
      1. text_pop 등 텍스트 오버레이가 있으면 "텍스트 없는 배경" 모드로 강제
      2. 최종 aspect_ratio는 Remotion 레이아웃 크기에 맞춤 (_layout_to_aspect)

    프롬프트 자체(구체물 렌더링 지시)는 broll_prompts.build_prompt이 담당.
    """
    broll = beat.get("broll", {})
    broll_type_raw = broll.get("type", "")
    src_hint = broll.get("src_hint", "")
    brand_key = broll.get("brand_key")
    layout = beat.get("layout", "full_broll")

    aspect_str, shape_str, gemini_ratio = _layout_to_aspect(layout)

    # ===== 배경 전용 모드 (text_pop 등 텍스트 오버레이가 있는 경우) =====
    # 이 경우 broll_prompts의 구체물 프롬프트 대신 "텍스트 없는 배경" 프롬프트를
    # 인라인으로 구성 — Remotion이 위에 텍스트를 그리기 때문.
    if _has_text_overlay_animations(beat):
        no_text_directive = (
            "ABSOLUTELY NO TEXT. NO WORDS. NO LETTERS. NO TYPOGRAPHY. NO NUMBERS. "
            "NO LABELS. NO CAPTIONS. NO UI ELEMENTS. NO BUTTONS. NO MENUS. NO SCREENSHOTS. "
            "NO LOGOS. NO BRAND NAMES. NO WRITTEN CONTENT WHATSOEVER. "
            "The image must be PURE VISUAL BACKGROUND ONLY. "
            "If you include ANY text or letters, the image will be REJECTED. "
        )
        composition = ""
        if layout == "full_broll":
            composition = "9:16 vertical composition. Leave generous empty negative space in the center for text overlay. "
        elif layout == "split":
            composition = "1:1 square composition. "
        elif layout == "overlay":
            composition = "16:9 landscape composition. "

        return (
            f"Generate a {shape_str} with {aspect_str}. {composition}"
            f"ATMOSPHERIC BACKGROUND IMAGE (no foreground content, no text). "
            f"{no_text_directive}"
            f"Visual mood/setting: {src_hint}. "
            f"Cinematic photographic style: soft lighting, shallow depth of field, "
            f"subtle gradients, abstract textures, silhouettes, or blurred environmental shots. "
            f"Dark moody color palette. Leave the center area visually simple (empty) "
            f"so overlay text remains readable. High production quality, premium look."
            , gemini_ratio
        )

    # ===== 일반 모드 — broll_prompts.build_prompt 위임 =====
    build_prompt, validate_prompt, _TYPES = _import_broll_prompts()

    # Legacy type 매핑
    new_type = _LEGACY_TYPE_MAP.get(broll_type_raw)
    if not new_type:
        # 모르는 타입은 가장 안전한 symbol_moment로 폴백 (배경/감성)
        print(
            f"  [warn] unknown broll type '{broll_type_raw}' — falling back to symbol_moment",
            file=sys.stderr,
        )
        new_type = "symbol_moment"

    # 레이아웃 구도 규칙 prefix — broll_prompts는 레이아웃 독립이므로 여기서 얹기
    composition_rule = ""
    if layout == "full_broll":
        composition_rule = (
            f"Generate a {shape_str} with {aspect_str}. "
            "CRITICAL COMPOSITION: 9:16 VERTICAL (portrait). "
            "If content compares A vs B, stack them VERTICALLY (top/bottom), NEVER side by side. "
            "If content lists items, arrange them VERTICALLY (column), NEVER horizontal row. "
            "Flow top → bottom. Use the full vertical height for clear readability.\n\n"
        )
    elif layout == "split":
        composition_rule = (
            f"Generate a {shape_str} with {aspect_str}. "
            "COMPOSITION: Square 1:1 image, centered composition. "
            "Comparisons may be horizontal (left/right).\n\n"
        )
    elif layout == "overlay":
        composition_rule = (
            f"Generate a {shape_str} with {aspect_str}. "
            "COMPOSITION: Landscape 16:9, horizontal flow for comparisons.\n\n"
        )

    try:
        core_prompt = build_prompt(new_type, src_hint, brand_key=brand_key)
    except ValueError as e:
        print(f"  [warn] build_prompt failed ({e}) — using raw src_hint", file=sys.stderr)
        core_prompt = src_hint

    violations = validate_prompt(core_prompt)
    if violations:
        print(f"  [warn] prompt contains banned phrases: {violations}", file=sys.stderr)

    return (composition_rule + core_prompt, gemini_ratio)


# ===== Main runner =====

def generate_brolls(
    scene_plan_path: Path,
    out_dir: Path,
    dry_run: bool = False,
    skip_existing: bool = True,
) -> dict:
    """
    scene_plan의 모든 B-roll 비트 처리.

    Returns: {"generated": int, "skipped": int, "failed": int, "cost_usd": float}
    """
    scene_plan = json.loads(scene_plan_path.read_text(encoding="utf-8"))
    beats = scene_plan.get("beats", [])

    out_dir.mkdir(parents=True, exist_ok=True)

    generated = 0
    skipped = 0
    failed = 0
    failed_items = []
    generated_files = []

    client = None
    if not dry_run:
        try:
            client = get_genai_client()
        except Exception as e:
            print(f"  [WARN] Gemini client unavailable: {e}")
            client = None

    for beat in beats:
        broll = beat.get("broll")
        if not broll or not isinstance(broll, dict):
            continue

        beat_id = beat.get("beat_id", "unknown")
        broll_type = broll.get("type", "")
        out_path = out_dir / f"{beat_id}.png"

        if skip_existing and out_path.exists():
            print(f"  [skip] {beat_id}.png exists")
            skipped += 1
            generated_files.append(str(out_path))
            continue

        if dry_run:
            out_path.write_bytes(b"")
            generated += 1
            continue

        try:
            # text_card: PIL 직접 렌더
            if broll_type == "text_card":
                props = broll.get("props", {}) or {}
                headline = props.get("headline") or broll.get("src_hint", "TEXT CARD")
                subline = props.get("subline")
                accent = props.get("accentColor", "#2C6EFF")
                img_bytes = build_text_card(
                    headline=headline,
                    subline=subline,
                    accent_color=accent,
                )
                out_path.write_bytes(img_bytes)
                print(f"  [ok] {beat_id}.png (text_card PIL)")
                generated += 1
                generated_files.append(str(out_path))
                continue

            # Gemini 이미지 생성
            if not client:
                print(f"  [WARN] {beat_id}: no Gemini client, creating placeholder text_card")
                img_bytes = build_text_card(
                    headline=broll_type.upper(),
                    subline=(broll.get("src_hint", "") or "")[:50],
                )
                out_path.write_bytes(img_bytes)
                generated += 1
                generated_files.append(str(out_path))
                continue

            prompt, gemini_ratio = build_prompt_for_broll(beat)
            img_bytes = generate_gemini_image(client, prompt, aspect_ratio=gemini_ratio)
            out_path.write_bytes(img_bytes)
            print(f"  [ok] {beat_id}.png (Gemini, {len(img_bytes)//1024} KB)")
            generated += 1
            generated_files.append(str(out_path))

            # Rate limit
            time.sleep(0.5)

        except Exception as e:
            print(f"  [FAIL] {beat_id}: {e}")
            failed += 1
            failed_items.append({"beat_id": beat_id, "error": str(e)})
            # Fallback: text card
            try:
                img_bytes = build_text_card(
                    headline=broll_type.upper(),
                    subline=(broll.get("src_hint", "") or "")[:50],
                )
                out_path.write_bytes(img_bytes)
                print(f"    [fallback] text_card placeholder saved")
                generated_files.append(str(out_path))
            except Exception:
                pass

    # Metadata
    # Gemini 2.5 Flash Image: approximately $0.04/image
    cost_estimate = generated * 0.04 if client else 0.0

    metadata = {
        "scene_plan": str(scene_plan_path),
        "out_dir": str(out_dir),
        "generated": generated,
        "skipped": skipped,
        "failed": failed,
        "failed_items": failed_items,
        "generated_files": generated_files,
        "estimated_cost_usd": round(cost_estimate, 4),
    }
    (out_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return metadata


def main():
    parser = argparse.ArgumentParser(description="Phase 4b: B-roll Generator")
    parser.add_argument("--scene-plan", required=True, help="scene_plan_reels.locked.json")
    parser.add_argument("--out-dir", required=True, help="broll/ 출력 경로")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force", action="store_true", help="기존 파일 무시하고 재생성")
    args = parser.parse_args()

    result = generate_brolls(
        scene_plan_path=Path(args.scene_plan),
        out_dir=Path(args.out_dir),
        dry_run=args.dry_run,
        skip_existing=not args.force,
    )

    print("\n=== B-roll Summary ===")
    print(f"Generated: {result['generated']}")
    print(f"Skipped: {result['skipped']}")
    print(f"Failed: {result['failed']}")
    print(f"Cost: ${result['estimated_cost_usd']:.4f}")
    return 0 if result["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
