"""keep_intervals.json 기반 word-level 컷팅 + transcript 타임라인 shift.

silencedetect 씬 분할을 버리고 LLM이 판단한 구간으로 재분할한다.
각 keep_interval → scene_XX.mp4 하나 (재인코딩, 프레임 정확)
transcript.json의 word timestamps를 클린 타임라인에 맞게 shift.

기존 silence-based 출력물은 .silence_bak 접미사로 보존.

Usage:
    PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/ng_cutter.py \\
        --source D:/aiprompt/04/PROMPTER_20260417_161003.mp4 \\
        --name PROMPTER_20260417_161003

Inputs:
    - {source} mp4 원본
    - temp/<name>/keep_intervals.json

Outputs (새 클린 타임라인):
    - output/<name>/scenes/scene_XX.mp4           (덮어쓰기, 기존은 .silence_bak)
    - temp/<name>/scenes.json                     (덮어쓰기)
    - temp/<name>/scene_files.json                (덮어쓰기)
    - output/<name>/subs/transcript.json          (덮어쓰기, shifted)
    - output/<name>/subs/transcript.srt           (덮어쓰기, shifted)
    - output/<name>/cleaned_timeline_map.json     (원본↔클린 매핑, 디버깅용)
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(os.environ.get("CAPCUT_PROJECT_ROOT") or Path(__file__).resolve().parents[2])
FFBIN = Path(os.environ["LOCALAPPDATA"]) / "Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin"
FFMPEG = str(FFBIN / "ffmpeg.exe")
FFPROBE = str(FFBIN / "ffprobe.exe")


def _backup(path: Path, suffix: str = ".silence_bak") -> None:
    """Rename path to path+suffix if path exists and no existing backup."""
    if not path.exists():
        return
    bak = path.with_suffix(path.suffix + suffix)
    if bak.exists():
        return  # 이미 백업 있음, 덮어쓰지 않음
    path.rename(bak)


def _backup_dir(dir_path: Path, suffix: str = ".silence_bak") -> None:
    """Rename directory to dir+suffix if it exists and no existing backup."""
    if not dir_path.exists():
        return
    bak = dir_path.parent / f"{dir_path.name}{suffix}"
    if bak.exists():
        return
    dir_path.rename(bak)


def _probe_dims(source: Path) -> tuple[int, int]:
    """Return (width, height) of source video."""
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-of", "json",
         "-select_streams", "v:0",
         "-show_entries", "stream=width,height", str(source)],
        capture_output=True, text=True, check=True,
    )
    s = json.loads(out.stdout)["streams"][0]
    return int(s["width"]), int(s["height"])


def _cut_interval(source: Path, start: float, end: float, out_path: Path,
                  *, audio_fade_ms: int = 50) -> float:
    """Re-encode cut source[start..end] → out_path with audio fade-in/out.

    Applies short triangular afade at both ends (default 50ms) so that when
    clips concat into CapCut timeline, boundaries don't click. This masks the
    room-tone discontinuity and phoneme-onset artefacts that cause the
    "disconnected" feeling at splice points.

    Returns actual out_path duration (re-encoding can shift by a few ms).
    """
    dur = end - start
    fade = audio_fade_ms / 1000.0
    # afade out: start st = dur - fade_dur
    afilter = f"afade=t=in:st=0:d={fade},afade=t=out:st={max(0, dur-fade):.3f}:d={fade}"
    # IMPORTANT: -ss BEFORE -i (input seek). Output seek (-ss after -i) + afade
    # interacts badly with ffmpeg's aac encoder → bitrate collapses to ~24kbps.
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{start:.3f}",
        "-to", f"{end:.3f}",
        "-i", str(source),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-af", afilter,
        "-avoid_negative_ts", "make_zero",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-of", "json",
         "-show_entries", "format=duration", str(out_path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def _shift_transcript(transcript: dict, intervals: list[dict],
                      clean_starts: list[float]) -> dict:
    """Shift transcript word timings to clean timeline.

    Two correctness rules:
    1. **Use ACTUAL clean_starts** (from cut manifest), not intended durations —
       re-encoding can shift each scene by a few ms; cumulative drift over 14
       segments reaches ~1s and breaks subtitle/video sync.
    2. **Split per (source_segment, interval) pair** — a Scribe segment can
       span multiple keep_intervals (e.g., source 233-244 covers keep[10]
       [233-238] and keep[11] [238-244]). Emitting one merged cue would cross
       scene boundaries, which CapCut's scene-clip patcher re-anchors to the
       LAST scene → earlier scenes lose their subtitle. Split by interval.
    """
    new_segments = []
    for seg in transcript.get("segments", []):
        # group this source segment's words by which keep_interval they fall in
        by_iv: dict[int, list[dict]] = {}
        for w in seg.get("words", []):
            ws = float(w["start"])
            we = float(w["end"])
            for i, iv in enumerate(intervals):
                if iv["start"] <= ws < iv["end"]:
                    # source → clean: shift by (clean_starts[i] - iv.start)
                    new_ws = ws - iv["start"] + clean_starts[i]
                    new_we = min(we, iv["end"]) - iv["start"] + clean_starts[i]
                    by_iv.setdefault(i, []).append({
                        "start": round(new_ws, 3),
                        "end": round(new_we, 3),
                        "word": w["word"],
                    })
                    break
        # emit one new segment per interval (no cross-scene segments)
        for i in sorted(by_iv.keys()):
            ws_list = by_iv[i]
            new_segments.append({
                "idx": len(new_segments) + 1,
                "start": ws_list[0]["start"],
                "end": ws_list[-1]["end"],
                "text": " ".join(w["word"].strip() for w in ws_list).strip(),
                "words": ws_list,
            })
    return {"language": transcript.get("language", "ko"), "segments": new_segments}


def _fmt_ts(t: float) -> str:
    h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _write_srt(transcript: dict, out_path: Path) -> None:
    lines = []
    for seg in transcript["segments"]:
        lines.append(str(seg["idx"]))
        lines.append(f"{_fmt_ts(seg['start'])} --> {_fmt_ts(seg['end'])}")
        lines.append(seg["text"])
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def _flatten_words(transcript: dict) -> list[tuple[float, float, str]]:
    out = []
    for s in transcript.get("segments", []):
        for w in s.get("words", []):
            t = (w.get("word") or "").strip()
            if t:
                out.append((float(w["start"]), float(w["end"]), t))
    return sorted(out)


def _auto_extend_ends(intervals: list[dict], all_words: list[tuple[float, float, str]],
                      extend_ms: int, safety_ms: int) -> None:
    """Extend each interval end by extend_ms to capture sentence-ending phoneme tail.

    Caps at next word_start - safety_ms or next interval start - safety_ms.
    Mutates intervals in place.

    Korean sentence endings ("~다", "~요", "~까") have voiced vowel tails that
    Scribe's word_end timestamp truncates by 100-200ms. Without extension the
    last syllable sounds clipped ("~합니" instead of "~합니다").
    """
    extend = extend_ms / 1000.0
    safety = safety_ms / 1000.0
    for i, iv in enumerate(intervals):
        cur_end = iv["end"]
        next_keep_start = intervals[i+1]["start"] if i+1 < len(intervals) else float("inf")
        # next source word AFTER current end, ignoring kept range
        next_word_start = next((w[0] for w in all_words if w[0] > cur_end), float("inf"))
        max_safe = min(next_word_start, next_keep_start) - safety
        new_end = min(cur_end + extend, max_safe)
        if new_end > cur_end:
            iv["end"] = round(new_end, 3)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, required=True, help="원본 영상 mp4")
    p.add_argument("--name", required=True, help="프로젝트 이름 (temp/output 디렉토리명)")
    p.add_argument("--no-backup", action="store_true",
                   help="기존 scenes/scene_files/transcript 백업 skip (이미 백업했을 때)")
    p.add_argument("--end-extend-ms", type=int, default=400,
                   help="각 keep interval end를 N ms 자동 연장 (Scribe word_end가 한국어 어미 vowel decay 직전에 끝남, 기본 400ms = 250 (어미 전체)+150 (자연 호흡))")
    p.add_argument("--end-safety-ms", type=int, default=50,
                   help="end 연장 시 다음 NG word/interval과 최소 safety margin (기본 50ms)")
    p.add_argument("--audio-fade-ms", type=int, default=50,
                   help="각 cut clip 시작/끝에 적용할 audio fade-in/out 길이 (기본 50ms 삼각형, click 방지)")
    # draft rebuild defaults (mirror run_pipeline.py)
    p.add_argument("--skip-draft-rebuild", action="store_true",
                   help="cut 후 transcript_wrapped.srt 재생성 + CapCut draft rebuild skip (수동으로 build_draft 부를 때만)")
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--max-chars", type=int, default=18, help="자막 wrap 최대 글자수")
    p.add_argument("--font-size", type=float, default=14.0)
    p.add_argument("--font-path", default="C:/Users/kbjhh/AppData/Local/Microsoft/Windows/Fonts/ODITTABILITY.TTF")
    p.add_argument("--font-title", default="ODITTABILITY")
    p.add_argument("--stroke", type=float, default=20.0)
    p.add_argument("--sub-y", type=float, default=-0.234)
    p.add_argument("--sub-offset-ms", type=int, default=300,
                   help="자막 N ms 뒤로 (Scribe 기본 300ms)")
    p.add_argument("--sub-max-duration-ms", type=int, default=5000)
    args = p.parse_args()

    source: Path = args.source.resolve()
    if not source.exists():
        print(f"error: source not found: {source}", file=sys.stderr); return 1

    name = args.name
    tmp_dir = PROJECT_ROOT / "temp"   / name
    out_dir = PROJECT_ROOT / "output" / name
    subs_dir = out_dir / "subs"
    scenes_dir = out_dir / "scenes"

    plan_path = tmp_dir / "keep_intervals.json"
    transcript_path = subs_dir / "transcript.json"

    if not plan_path.exists():
        print(f"error: missing {plan_path}", file=sys.stderr); return 1
    if not transcript_path.exists():
        print(f"error: missing {transcript_path}", file=sys.stderr); return 1

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    intervals = plan["keep_intervals"]
    # sanity: ascending + non-overlapping
    for a, b in zip(intervals, intervals[1:]):
        if a["end"] > b["start"]:
            print(f"error: overlap {a['end']} > {b['start']}", file=sys.stderr); return 1

    source_transcript = json.loads(transcript_path.read_text(encoding="utf-8"))

    # --- AUTO end extension (어미 보존) ---
    if args.end_extend_ms > 0:
        all_words = _flatten_words(source_transcript)
        before = [iv["end"] for iv in intervals]
        _auto_extend_ends(intervals, all_words, args.end_extend_ms, args.end_safety_ms)
        deltas = [(iv["end"] - b) * 1000 for iv, b in zip(intervals, before)]
        applied = sum(d > 0 for d in deltas)
        avg = sum(deltas) / len(deltas) if deltas else 0
        print(f"[auto-extend] {applied}/{len(intervals)} ends extended, avg +{avg:.0f}ms (target +{args.end_extend_ms}ms, safety {args.end_safety_ms}ms)")

    width, height = _probe_dims(source)

    # --- 1) backup existing silence-based outputs ---
    if not args.no_backup:
        print("[backup] silence-based outputs → .silence_bak")
        _backup_dir(scenes_dir)
        _backup(tmp_dir / "scenes.json")
        _backup(tmp_dir / "scene_files.json")
        _backup(transcript_path)
        _backup(subs_dir / "transcript.srt")

    scenes_dir.mkdir(parents=True, exist_ok=True)

    # --- 2) cut each interval into scene_XX.mp4 ---
    print(f"[cut] cutting {len(intervals)} intervals from {source.name}")
    manifest = []
    new_scenes = []
    clean_cursor = 0.0
    total_src_kept = 0.0
    for i, iv in enumerate(intervals):
        out_path = scenes_dir / f"scene_{i:02d}.mp4"
        dur = _cut_interval(source, iv["start"], iv["end"], out_path,
                            audio_fade_ms=args.audio_fade_ms)
        total_src_kept += (iv["end"] - iv["start"])
        manifest.append({
            "idx": i,
            "file": str(out_path).replace("\\", "/"),
            "start": iv["start"],                  # 원본 시간 (디버깅용)
            "end": iv["end"],
            "duration": round(dur, 3),
            "text": iv.get("text", ""),
        })
        new_scenes.append({
            "idx": i,
            "start": round(clean_cursor, 3),
            "end": round(clean_cursor + dur, 3),
            "length": round(dur, 3),
        })
        clean_cursor += dur
        print(f"  [{i:2d}] src[{iv['start']:.2f}-{iv['end']:.2f}] → clean[{new_scenes[-1]['start']:.2f}-{new_scenes[-1]['end']:.2f}] ({dur:.2f}s)")

    # --- 3) write new scenes.json / scene_files.json ---
    (tmp_dir / "scenes.json").write_text(
        json.dumps({"duration": round(clean_cursor, 3), "scenes": new_scenes},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (tmp_dir / "scene_files.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # --- 4) shift transcript using ACTUAL clean_starts from cut manifest ---
    print(f"[shift] shifting transcript to clean timeline")
    clean_starts = [sc["start"] for sc in new_scenes]
    shifted = _shift_transcript(source_transcript, intervals, clean_starts)
    subs_dir.mkdir(parents=True, exist_ok=True)
    transcript_path.write_text(
        json.dumps(shifted, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    _write_srt(shifted, subs_dir / "transcript.srt")

    # --- 5) save timeline map for debugging ---
    map_path = out_dir / "cleaned_timeline_map.json"
    map_path.parent.mkdir(parents=True, exist_ok=True)
    map_path.write_text(
        json.dumps({
            "source_duration": plan.get("source_duration_sec"),
            "clean_duration": round(clean_cursor, 3),
            "removed_duration": round((plan.get("source_duration_sec") or 0) - clean_cursor, 3),
            "intervals": [{"src_start": iv["start"], "src_end": iv["end"],
                           "clean_start": new_scenes[i]["start"],
                           "clean_end": new_scenes[i]["end"]}
                          for i, iv in enumerate(intervals)],
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # --- 6) regenerate transcript_wrapped.srt from shifted transcript ---
    if not args.skip_draft_rebuild:
        print(f"[wrap] regenerating transcript_wrapped.srt on clean timeline")
        sys.path.insert(0, str(Path(__file__).parent))
        from run_pipeline import write_wrapped_srt, build_draft  # type: ignore
        wrapped_path = subs_dir / "transcript_wrapped.srt"
        write_wrapped_srt(transcript_path, wrapped_path, args.max_chars)

        # --- 7) auto-rebuild CapCut draft on clean timeline ---
        print(f"[draft] rebuilding CapCut draft on clean timeline")
        build_draft(
            name, width, height, args.fps, manifest,
            wrapped_path,
            font_size=args.font_size,
            sub_y=args.sub_y,
            stroke_ui=args.stroke,
            font_path=args.font_path,
            font_title=args.font_title,
            sub_offset_ms=args.sub_offset_ms,
            sub_max_duration_ms=args.sub_max_duration_ms,
        )

    # --- 8) write .ng_cleaned marker — run_pipeline detects this and skips silencedetect ---
    marker_path = tmp_dir / ".ng_cleaned"
    marker_path.write_text(
        json.dumps({
            "version": 6,
            "intervals": len(intervals),
            "clean_duration": round(clean_cursor, 3),
        }, indent=2), encoding="utf-8",
    )

    src_dur = plan.get("source_duration_sec") or clean_cursor
    print()
    print(f"[ng-cut] DONE")
    print(f"  scenes:     {len(new_scenes)}")
    print(f"  clean:      {clean_cursor:.1f}s  (from {src_dur:.1f}s, −{src_dur-clean_cursor:.1f}s, −{(src_dur-clean_cursor)/src_dur*100:.1f}%)")
    print(f"  transcript: {len(shifted['segments'])} segments, "
          f"{sum(len(s['words']) for s in shifted['segments'])} words")
    print(f"  marker:     {marker_path.name} (run_pipeline silencedetect skip)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
