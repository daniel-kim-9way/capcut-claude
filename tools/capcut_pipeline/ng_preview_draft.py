"""NG plan 리뷰용 CapCut 드래프트 생성.

`ng_plan.json`의 keep 씬만 모아 새 CapCut 드래프트를 만든다.
기존 <name> 드래프트는 건드리지 않고 **<name>_NG_REVIEW** 로 저장.

목적: LLM이 drop으로 판정한 씬들이 실제 NG/묵음/retake가 맞는지
사용자가 CapCut에서 재생하며 시각적으로 확인.

Usage:
    PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/ng_preview_draft.py \\
        --name PROMPTER_20260417_161003

→ CapCut에서 `<name>_NG_REVIEW` 드래프트 열어 재생.
   - 재생 중 NG/묵음/retake가 여전히 보이면 LLM 판단 오류
   - 자연스러운 흐름으로 이어지면 판단 성공

자막/B-roll/FX 없음 — 순수 영상 비교만.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Reuse run_pipeline's build_draft so we don't duplicate CapCut draft logic.
sys.path.insert(0, str(Path(__file__).parent))
from run_pipeline import build_draft, PROJECT_ROOT, CAPCUT_ROOT  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--name", required=True, help="원본 영상 name (기존 drafts에 있어야 함)")
    p.add_argument("--suffix", default="_NG_REVIEW",
                   help="생성될 드래프트 이름의 접미사 (기본 _NG_REVIEW)")
    p.add_argument("--fps", type=int, default=30)
    args = p.parse_args()

    name = args.name
    tmp_dir = PROJECT_ROOT / "temp" / name

    plan_path = tmp_dir / "ng_plan.json"
    scenes_path = tmp_dir / "scene_files.json"
    probe_path = tmp_dir / "probe.json"

    for pth, label in [(plan_path, "ng_plan.json"), (scenes_path, "scene_files.json"),
                       (probe_path, "probe.json")]:
        if not pth.exists():
            print(f"error: missing {label} at {pth}", file=sys.stderr)
            return 1

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    scene_files = json.loads(scenes_path.read_text(encoding="utf-8"))
    probe = json.loads(probe_path.read_text(encoding="utf-8"))

    keep_idxs = {s["idx"] for s in plan["scenes"] if s["decision"] == "keep"}
    drop_idxs = {s["idx"] for s in plan["scenes"] if s["decision"] == "drop"}

    filtered = [sf for sf in scene_files if sf["idx"] in keep_idxs]
    if not filtered:
        print("error: no keep scenes after filtering", file=sys.stderr)
        return 1

    # verify all keep files exist
    missing = [sf for sf in filtered if not Path(sf["file"]).exists()]
    if missing:
        print(f"error: {len(missing)} scene files missing, first: {missing[0]['file']}", file=sys.stderr)
        return 1

    review_name = f"{name}{args.suffix}"
    keep_dur = sum(sf["duration"] for sf in filtered)
    drop_dur = sum(sf["duration"] for sf in scene_files if sf["idx"] in drop_idxs)

    # Check CapCut is not running
    try:
        import subprocess
        r = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe"],
                           capture_output=True, text=True)
        if "CapCut.exe" in r.stdout:
            print("warning: CapCut is running. Close it before draft generation.", file=sys.stderr)
            print(f"         tasklist output:\n{r.stdout}", file=sys.stderr)
            return 2
    except Exception:
        pass

    print(f"[ng-preview] creating draft: {review_name}")
    print(f"  keep scenes: {len(filtered)} / {len(scene_files)}")
    print(f"  duration:    {keep_dur:.1f}s  (dropped {drop_dur:.1f}s, {drop_dur/(keep_dur+drop_dur)*100:.1f}%)")

    draft = build_draft(
        review_name,
        probe["width"],
        probe["height"],
        args.fps,
        filtered,
        None,  # no subtitles — visual-only review
    )
    print(f"[ng-preview] draft written: {draft}")
    print()
    print(f"→ CapCut 열고 프로젝트 목록에서 '{review_name}' 클릭해 재생 확인")
    print(f"  drop된 씬이 실제로 NG/묵음/retake 맞는지 판단")
    return 0


if __name__ == "__main__":
    sys.exit(main())
