"""
FunnelMaster 업로드 모듈

최종 릴스 영상을 funnelmaster.kr에 업로드합니다.

플로우:
  1. create_narration(script, caption) → generation_id
  2. upload_video(generation_id, video_path)
  3. get_generation(generation_id) → 업로드 URL 확인

환경변수 (.env):
  FUNNELMASTER_API_KEY — https://funnelmaster.kr/settings/ai 에서 생성
"""
import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv


ROOT = Path(__file__).parent.parent.parent
load_dotenv(ROOT / ".env")

FM_API_BASE = "https://funnelmaster.kr/api/v1"


def get_api_key() -> str:
    key = os.getenv("FUNNELMASTER_API_KEY", "").strip()
    if not key:
        print("[ERROR] FUNNELMASTER_API_KEY not set in .env")
        print("        Generate key at https://funnelmaster.kr/settings/ai")
        sys.exit(1)
    return key


def create_narration(
    topic: str,
    script: str,
    caption: str,
    api_key: Optional[str] = None,
) -> dict:
    """
    나레이션 (script + caption) 생성.

    Returns: {"id": "...", ...}
    """
    api_key = api_key or get_api_key()
    payload = {
        "content_type": "narration",
        "prompt_used": topic,
        "structured_data": {
            "script": script,
            "caption": caption,
        },
    }

    resp = requests.post(
        f"{FM_API_BASE}/generations",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        print(f"[ERROR] {resp.status_code}: {resp.text}")
        resp.raise_for_status()

    data = resp.json()
    gen_id = data.get("id") or data.get("generation_id") or data.get("data", {}).get("id")
    print(f"[FM] Narration created: generation_id={gen_id}")
    return data


def upload_video(
    generation_id: str,
    video_path: Path,
    api_key: Optional[str] = None,
) -> dict:
    """영상 파일 업로드."""
    api_key = api_key or get_api_key()

    if not video_path.exists():
        raise FileNotFoundError(f"video not found: {video_path}")

    size_mb = video_path.stat().st_size / 1024 / 1024
    print(f"[FM] Uploading {video_path.name} ({size_mb:.1f} MB)...")

    with open(video_path, "rb") as f:
        files = {"video": (video_path.name, f, "video/mp4")}
        resp = requests.post(
            f"{FM_API_BASE}/generations/{generation_id}/upload_video",
            headers={"Authorization": f"Bearer {api_key}"},
            files=files,
            timeout=300,
        )

    if resp.status_code not in (200, 201):
        print(f"[ERROR] {resp.status_code}: {resp.text}")
        resp.raise_for_status()

    data = resp.json()
    print(f"[FM] Upload complete")
    return data


def get_generation(
    generation_id: str,
    api_key: Optional[str] = None,
) -> dict:
    """생성된 릴스 정보 조회."""
    api_key = api_key or get_api_key()

    resp = requests.get(
        f"{FM_API_BASE}/generations/{generation_id}",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=15,
    )

    if resp.status_code != 200:
        print(f"[ERROR] {resp.status_code}: {resp.text}")
        resp.raise_for_status()

    return resp.json()


def upload_reel(
    project_dir: Path,
    topic: str,
    api_key: Optional[str] = None,
) -> dict:
    """
    프로젝트 디렉토리에서 최종 파일들을 읽어 funnelmaster.kr 업로드.

    필요 파일:
      - deliverables/final_reel.mp4
      - deliverables/ig_caption.txt
      - script/winner.md 또는 scene_plan의 narration들 합침
    """
    api_key = api_key or get_api_key()

    video_path = project_dir / "deliverables" / "final_reel.mp4"
    caption_path = project_dir / "deliverables" / "ig_caption.txt"

    if not video_path.exists():
        raise FileNotFoundError(f"final_reel.mp4 not found: {video_path}")

    # 캡션 읽기
    caption = caption_path.read_text(encoding="utf-8").strip() if caption_path.exists() else ""

    # 스크립트 읽기: scene_plan의 narration 합치기 (실제 TTS 스크립트)
    # winner.md는 quality_judge report라서 대본 본문이 아님
    script = ""
    locked_path = project_dir / "scenes" / "scene_plan_reels.locked.json"
    plan_path = project_dir / "scenes" / "scene_plan_reels.json"
    sp_path = locked_path if locked_path.exists() else plan_path
    if sp_path.exists():
        sp = json.loads(sp_path.read_text(encoding="utf-8"))
        script = " ".join(b.get("narration", "").strip() for b in sp.get("beats", []) if b.get("narration"))

    # Step 1: Narration 생성
    narration_result = create_narration(topic, script, caption, api_key=api_key)
    gen_id = narration_result.get("id") or narration_result.get("generation_id") or narration_result.get("data", {}).get("id")
    if not gen_id:
        print(f"[ERROR] generation_id not found in response: {narration_result}")
        sys.exit(2)

    # Step 2: 영상 업로드
    upload_result = upload_video(gen_id, video_path, api_key=api_key)

    # Step 3: 결과 조회
    final = get_generation(gen_id, api_key=api_key)

    print("\n=== Upload Complete ===")
    print(f"Generation ID: {gen_id}")
    video_url = final.get("video_url") or final.get("data", {}).get("video_url")
    if video_url:
        print(f"Video URL: {video_url}")
    return final


# ===== CLI =====

def main():
    parser = argparse.ArgumentParser(description="FunnelMaster 업로드")
    sub = parser.add_subparsers(dest="cmd")

    p_up = sub.add_parser("upload", help="프로젝트 전체 업로드")
    p_up.add_argument("--project", required=True, help="프로젝트 디렉토리")
    p_up.add_argument("--topic", required=True, help="주제 (prompt_used)")

    p_n = sub.add_parser("narration", help="나레이션만 생성")
    p_n.add_argument("--topic", required=True)
    p_n.add_argument("--script", required=True, help="스크립트 텍스트 또는 @파일")
    p_n.add_argument("--caption", required=True, help="캡션 텍스트 또는 @파일")

    p_v = sub.add_parser("video", help="영상만 업로드 (generation_id 있을 때)")
    p_v.add_argument("--gen-id", required=True)
    p_v.add_argument("--video", required=True)

    p_s = sub.add_parser("status", help="업로드 상태 조회")
    p_s.add_argument("--gen-id", required=True)

    args = parser.parse_args()

    if args.cmd == "upload":
        upload_reel(Path(args.project), args.topic)

    elif args.cmd == "narration":
        script = args.script
        caption = args.caption
        if script.startswith("@"):
            script = Path(script[1:]).read_text(encoding="utf-8").strip()
        if caption.startswith("@"):
            caption = Path(caption[1:]).read_text(encoding="utf-8").strip()
        result = create_narration(args.topic, script, caption)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.cmd == "video":
        result = upload_video(args.gen_id, Path(args.video))
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif args.cmd == "status":
        result = get_generation(args.gen_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
