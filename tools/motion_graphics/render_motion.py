"""
Motion graphics renderer — HTML (GSAP timeline) → MP4 + alpha MOV.

POC (2026-04-22): Hyperframes-inspired pattern. We skip the HeyGen
Hyperframes CLI entirely and drive Chromium directly via Playwright.

Pipeline:
  1. Playwright opens template HTML with blue-chroma (#0000FF) background.
  2. Parameters injected via `window.__params` before GSAP timeline starts.
  3. Renderer steps `window.__tl.progress(p); window.__tl.pause();` per frame
     and screenshots each frame to a PNG.
  4. FFmpeg assembles PNG sequence → MP4 (preserves blue chroma for CapCut
     chroma-key) AND → MOV with ProRes 4444 alpha (pre-keyed, drop-in).

Usage:
  python render_motion.py \\
      --template templates/stat_card.html \\
      --params   '{"top_number":10,"bottom_number":4,"duration":5.5}' \\
      --out-base out/scene_010_motion \\
      --fps 30
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


HERE = Path(__file__).resolve().parent


def render_html_to_png_sequence(
    template_path: Path,
    params: dict,
    out_frames_dir: Path,
    fps: int,
    viewport_w: int = 1920,
    viewport_h: int = 1080,
    transparent: bool = False,
    card_opacity: float = 0.62,
) -> tuple[int, float]:
    """Open HTML via Playwright, step GSAP timeline per frame, screenshot each.

    Returns (frame_count, tl_duration_sec).

    transparent=True: body 블루 배경을 투명으로 override + .card 배경을 반투명
    (card_opacity)으로 만들고 omit_background로 캡처 → 진짜 alpha 보존.
    카드 뒤로 메인 영상이 비쳐 보임 (검정 박스가 화면을 덮지 않음).
    """
    out_frames_dir.mkdir(parents=True, exist_ok=True)
    for old in out_frames_dir.glob("*.png"):
        old.unlink()

    # Inject {__LABEL_TOP__} / {__LABEL_BOTTOM__} substitution if template has them
    raw = template_path.read_text(encoding="utf-8")
    label_top = params.get("top_label", "")
    label_bottom = params.get("bottom_label", "")
    raw = raw.replace("__LABEL_TOP__", label_top).replace("__LABEL_BOTTOM__", label_bottom)

    # Write a temporary processed HTML next to the template so relative fonts etc. work
    processed = template_path.parent / f".__processed_{template_path.stem}.html"
    processed.write_text(raw, encoding="utf-8")
    file_url = processed.resolve().as_uri()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(
            viewport={"width": viewport_w, "height": viewport_h},
            device_scale_factor=1,
        )
        page = ctx.new_page()

        # Inject params BEFORE the page's inline script runs
        page.add_init_script(f"window.__params = {json.dumps(params)};")

        page.goto(file_url, wait_until="networkidle")

        # transparent 모드: 블루(chroma) 배경 제거. 카드 배경 처리는 card_opacity에 따라 분기.
        #   - card_opacity < 1.0 : 카드를 반투명 dark(rgba(13,13,15,α))로 강제 → 텍스트/그래픽
        #       카드가 영상 위에 "떠 보이게". (kinetic_type, graphic_insight 등 장식 카드)
        #   - card_opacity >= 1.0: ⛔ .card 배경을 **덮어쓰지 않는다** → 템플릿 고유 배경
        #       (노션 #FFF, 터미널 dark 등) 그대로 불투명. (2026-06-09 fix: 모든 카드를 0.62
        #       dark로 강제 덮어 노션·모니터 등 UI 화면이 반투명해지던 버그 해결.)
        if transparent:
            style = "html, body { background: transparent !important; }"
            if card_opacity < 1.0:
                style += f" .card {{ background: rgba(13,13,15,{card_opacity}) !important; }}"
            page.add_style_tag(content=style)

        # Wait until template signals ready (window.__ready + window.__tl)
        page.wait_for_function("() => window.__ready === true && !!window.__tl", timeout=10_000)

        # Fonts might load slightly after networkidle. Give a brief grace period.
        page.wait_for_function("() => document.fonts.ready.then(() => true)", timeout=5_000)

        # 이미지 decode 대기 (TL-03, 2026-06-04): device_mockup 등 <img src=file://...>를
        # 쓰는 템플릿은 첫 프레임 캡처 전에 모든 이미지가 완전히 로드돼야 깨짐 방지.
        # 이미지가 없으면 every()가 즉시 true → 기존 템플릿 동작 영향 없음(하위호환).
        page.wait_for_function(
            "() => [...document.images].every(i => i.complete && i.naturalWidth > 0)",
            timeout=10_000,
        )

        tl_duration = float(page.evaluate("() => window.__tl.duration()"))
        total_frames = max(1, int(round(tl_duration * fps)))

        print(f"[render] timeline duration = {tl_duration:.3f}s, frames = {total_frames} @ {fps}fps")

        t0 = time.time()
        for i in range(total_frames):
            progress = i / (total_frames - 1) if total_frames > 1 else 1.0
            # Pin the timeline to this exact progress (paused so no auto-play races)
            page.evaluate(
                "(p) => { window.__tl.progress(p); window.__tl.pause(); }",
                progress,
            )
            frame_path = out_frames_dir / f"frame_{i:05d}.png"
            page.screenshot(path=str(frame_path), omit_background=transparent, full_page=False)

            if i % 30 == 0:
                elapsed = time.time() - t0
                rate = (i + 1) / max(0.001, elapsed)
                eta = (total_frames - i - 1) / max(0.001, rate)
                print(f"[render] frame {i+1}/{total_frames}  rate={rate:.1f} fps  eta={eta:.1f}s")

        browser.close()

    processed.unlink(missing_ok=True)
    return total_frames, tl_duration


def ffmpeg_png_sequence_to_mp4(
    frames_dir: Path,
    out_mp4: Path,
    fps: int,
) -> None:
    """Assemble PNG sequence into an MP4 with the original blue-chroma bg."""
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        "-preset", "medium",
        "-movflags", "+faststart",
        str(out_mp4),
    ]
    print(f"[ffmpeg] MP4 (blue chroma preserved): {out_mp4.name}")
    subprocess.run(cmd, check=True, capture_output=True)


def ffmpeg_png_sequence_to_alpha_mov(
    frames_dir: Path,
    out_mov: Path,
    fps: int,
    transparent: bool = False,
) -> None:
    """PNG sequence → ProRes 4444 MOV with alpha channel.

    transparent=False (기본, 블루 크로마): colorkey 0x0000FF로 블루 배경을 alpha로.
    transparent=True: PNG가 이미 native alpha(omit_background 캡처)를 가지므로
        colorkey 생략하고 alpha를 그대로 보존 (반투명 카드 alpha 유지).
    """
    vf = "format=yuva444p" if transparent else "colorkey=0x0000FF:0.20:0.10,format=yuva444p"
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-vf", vf,
        "-c:v", "prores_ks",
        "-profile:v", "4444",  # supports alpha
        "-pix_fmt", "yuva444p10le",
        "-qscale:v", "11",
        str(out_mov),
    ]
    print(f"[ffmpeg] MOV alpha (ProRes 4444){' [transparent]' if transparent else ''}: {out_mov.name}")
    subprocess.run(cmd, check=True, capture_output=True)


def ffmpeg_png_sequence_to_alpha_webm(
    frames_dir: Path,
    out_webm: Path,
    fps: int,
) -> None:
    """PNG sequence → colorkey → VP9 WebM with alpha (smaller than ProRes)."""
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(fps),
        "-i", str(frames_dir / "frame_%05d.png"),
        "-vf", "colorkey=0x0000FF:0.20:0.10",
        "-c:v", "libvpx-vp9",
        "-pix_fmt", "yuva420p",
        "-b:v", "2M",
        "-auto-alt-ref", "0",
        str(out_webm),
    ]
    print(f"[ffmpeg] WebM alpha (VP9): {out_webm.name}")
    subprocess.run(cmd, check=True, capture_output=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--template", required=True, help="path to HTML template")
    ap.add_argument("--params", required=True, help="JSON string of parameters")
    ap.add_argument("--out-base", required=True, help="output basename (no extension)")
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--width", type=int, default=1920)
    ap.add_argument("--height", type=int, default=1080)
    ap.add_argument(
        "--keep-frames", action="store_true",
        help="keep PNG sequence (default: remove after MP4 made)",
    )
    ap.add_argument(
        "--transparent", action="store_true",
        help="블루 크로마 대신 투명 배경 + 반투명 카드로 렌더 (영상이 카드 뒤로 비침)",
    )
    ap.add_argument(
        "--card-opacity", type=float, default=0.62,
        help="--transparent 시 카드 배경 불투명도 (0=완전투명, 1=불투명, 기본 0.62)",
    )
    args = ap.parse_args()

    template = Path(args.template).resolve()
    if not template.exists():
        print(f"[err] template not found: {template}", file=sys.stderr)
        return 2

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"[err] invalid --params JSON: {e}", file=sys.stderr)
        return 2

    out_base = Path(args.out_base).resolve()
    out_base.parent.mkdir(parents=True, exist_ok=True)
    frames_dir = out_base.parent / f".__frames_{out_base.stem}"

    frame_count, tl_duration = render_html_to_png_sequence(
        template_path=template,
        params=params,
        out_frames_dir=frames_dir,
        fps=args.fps,
        viewport_w=args.width,
        viewport_h=args.height,
        transparent=args.transparent,
        card_opacity=args.card_opacity,
    )

    out_mp4 = out_base.with_suffix(".mp4")
    out_mov = out_base.with_suffix(".mov")

    ffmpeg_png_sequence_to_mp4(frames_dir, out_mp4, args.fps)
    ffmpeg_png_sequence_to_alpha_mov(frames_dir, out_mov, args.fps, transparent=args.transparent)

    if not args.keep_frames:
        shutil.rmtree(frames_dir, ignore_errors=True)

    mp4_size = out_mp4.stat().st_size / 1024
    mov_size = out_mov.stat().st_size / 1024
    print()
    print("=== Render complete ===")
    print(f"  frames:       {frame_count}")
    print(f"  duration:     {tl_duration:.2f}s @ {args.fps}fps")
    print(f"  MP4 (bg):     {out_mp4} ({mp4_size:.0f} KB)")
    print(f"  MOV (alpha):  {out_mov} ({mov_size:.0f} KB)")
    print()
    print(f"CapCut usage:")
    print(f"  - {out_mov.name}: drag into CapCut directly (alpha preserved)")
    print(f"  - {out_mp4.name}: drag + apply CapCut Chroma Key filter (#0000FF)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
