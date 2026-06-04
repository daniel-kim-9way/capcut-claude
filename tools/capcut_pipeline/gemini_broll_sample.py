#!/usr/bin/env python3
"""
overlay_test 용 Gemini B-roll 생성기 (정교한 cinematic 스타일).

원칙 (create-reels + 사용자 피드백):
  - 이미지는 **cinematic editorial photograph** (HTML/UI screenshot 느낌 X)
  - Laptop/device mockup 스타일로 자연스럽게
  - 텍스트/로고/UI text 절대 금지 (텍스트는 PIL emphasis 로 별도 렌더)
  - Premium magazine quality, shallow DOF, rich color grading
  - Split 레이아웃 (상단 1:1 정사각형) 타겟
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "reels_pipeline"))
from broll_generator import (  # type: ignore
    get_genai_client,
    generate_gemini_image,
    build_prompt_for_broll,
)


_PROJECT_ROOT = Path(os.environ.get("CAPCUT_PROJECT_ROOT") or Path(__file__).resolve().parents[2])
OUT_DIR = _PROJECT_ROOT / "output/overlay_test/broll_gemini"


TASKS = [
    {
        "beat_id": "scene_11_split_screenshot",
        "out": "scene_11_split.png",
        "layout": "overlay",   # build_prompt_for_broll → aspect 16:9 (1920x1080)
        "broll": {
            # 실제 UI 스크린샷 느낌 (GitHub, Claude UI 같은). atmospheric 과 다름.
            "type": "screenshot",
            "src_hint": (
                "Realistic modern Korean SaaS analytics dashboard web application. "
                "Clean product UI with a left sidebar menu listing Korean menu items "
                "like '대시보드', '리포트', '사용자', '설정'. Main content area shows "
                "a large prominent bold ascending blue line chart with X/Y axis labels "
                "in numbers only, and a highlighted summary metric card at the top "
                "containing Korean label '전환율' with the big number '15%' and a "
                "small '▲ 개선' indicator in green. Pretendard Korean typography "
                "throughout, crisp pixel-perfect SaaS product UI, realistic screenshot "
                "aesthetic like a real web dashboard. Light theme, white background, "
                "blue accent (#2C6EFF). Korean text must be rendered accurately. "
                "No people, no faces, no photographic elements — purely a clean app UI."
            ),
        },
    },
]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    client = get_genai_client()

    for i, task in enumerate(TASKS, 1):
        out_path = OUT_DIR / task["out"]
        prompt, aspect = build_prompt_for_broll(task)
        print(f"[{i}/{len(TASKS)}] {task['out']} (aspect={aspect}) ...", flush=True)
        t0 = time.time()
        try:
            png = generate_gemini_image(client, prompt, aspect)
            out_path.write_bytes(png)
            dt = time.time() - t0
            print(f"   → {out_path.name} ({len(png)//1024}KB, {dt:.1f}s)", flush=True)
        except Exception as e:
            print(f"   ✗ FAILED: {e}", flush=True)

    print()
    print(f"Done. Output: {OUT_DIR}")


if __name__ == "__main__":
    main()
