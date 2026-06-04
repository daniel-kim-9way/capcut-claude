#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""verify_step.py — Machine verifier for /capcut pipeline gates.

Replaces fakeable markdown/shell checklists with concrete verification commands
that print stdout evidence. Fixes the `wc -c` Korean UTF-8 byte-count bug by
using Python's native `len()` on decoded strings (UTF-8 code points).

Usage:
    PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/verify_step.py <step> --name PROJECT [extra]
    PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/verify_step.py --all --name PROJECT

Exit codes:
    0 = PASS
    1 = generic error (bad args, I/O, etc.)
    5 = FAIL — specific gate problems; each printed on its own line
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Constants & helpers
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]

BANNED_PHRASES = ["충격!", "대박!", "무조건", "100%", "반드시", "인생이 바뀝니다"]

# Basic emoji ranges — covers most pictographs + dingbats
EMOJI_RE = re.compile(
    r"[\U0001F300-\U0001FAFF\u2600-\u27BF\U0001F1E6-\U0001F1FF\U0001F900-\U0001F9FF]"
)

HASHTAG_RE = re.compile(r"#\S+")
SRT_TIMECODE_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,.]\d{3})"
)


def draft_dir(name: str) -> Path:
    lap = os.environ.get("LOCALAPPDATA")
    if not lap:
        # Fallback for WSL/bash-on-Windows contexts
        home = Path.home()
        lap = str(home / "AppData" / "Local")
    return Path(lap) / "CapCut" / "User Data" / "Projects" / "com.lveditor.draft" / name


def output_dir(name: str) -> Path:
    return REPO_ROOT / "output" / name


class Result:
    """Collects pass/fail/warn lines for a single step."""

    def __init__(self, tag: str):
        self.tag = tag
        self.problems: list[str] = []
        self.warnings: list[str] = []
        self.info: dict[str, Any] = {}

    def fail(self, msg: str) -> None:
        self.problems.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    def note(self, key: str, value: Any) -> None:
        self.info[key] = value

    @property
    def ok(self) -> bool:
        return not self.problems

    def emit(self) -> None:
        status = "PASS" if self.ok else "FAIL"
        info_str = ", ".join(f"{k}={v}" for k, v in self.info.items())
        print(f"[{self.tag}] {status}: {info_str}")
        for w in self.warnings:
            print(f"        ! {w}")
        for p in self.problems:
            print(f"        X {p}")


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_srt_cues(text: str) -> list[tuple[str, str]]:
    """Return list of (start, end) timecodes from an SRT body."""
    return [(m.group(1), m.group(2)) for m in SRT_TIMECODE_RE.finditer(text)]


# ---------------------------------------------------------------------------
# Step 1 — pipeline output
# ---------------------------------------------------------------------------

def step1(name: str) -> Result:
    r = Result("step1")
    d_dir = draft_dir(name)
    draft_path = d_dir / "draft_content.json"

    if not draft_path.exists():
        r.fail(f"draft_content.json not found at {draft_path}")
        r.fail("hint: re-run /capcut or check project name")
        return r

    try:
        draft = _load_json(draft_path)
    except Exception as e:
        r.fail(f"draft_content.json invalid JSON: {e}")
        return r

    tracks = draft.get("tracks", [])
    video_tracks = [t for t in tracks if t.get("type") == "video"]
    if not video_tracks:
        r.fail("draft has no video tracks")
        return r

    main_video = None
    for t in video_tracks:
        segs = t.get("segments", [])
        if segs:
            main_video = t
            break
    if main_video is None:
        r.fail("no video track with segments")
        return r

    scene_count = len(main_video["segments"])
    r.note("scene_count", scene_count)
    if scene_count < 1:
        r.fail("video track has 0 segments")

    out = output_dir(name)
    srt = out / "subs" / "transcript.srt"
    tj = out / "subs" / "transcript.json"
    if not srt.exists():
        r.fail(f"missing {srt}")
    if not tj.exists():
        r.fail(f"missing {tj}")

    cue_count = 0
    if srt.exists():
        cues = _parse_srt_cues(srt.read_text(encoding="utf-8", errors="replace"))
        cue_count = len(cues)
        r.note("transcript_cue_count", cue_count)
        if cue_count == 0:
            r.fail("transcript.srt has 0 cues")
    return r


# ---------------------------------------------------------------------------
# Step 2 — subtitle correction
# ---------------------------------------------------------------------------

def step2(name: str) -> Result:
    r = Result("step2")
    subs = output_dir(name) / "subs"
    raw = subs / "transcript_wrapped.raw.srt"
    edited = subs / "transcript_wrapped.srt"

    if not raw.exists():
        r.fail(f"backup missing: {raw}")
        r.fail("hint: re-run subtitle wrap stage; raw.srt is the pre-edit snapshot")
        return r
    if not edited.exists():
        r.fail(f"edited missing: {edited}")
        return r

    raw_txt = raw.read_text(encoding="utf-8", errors="replace")
    ed_txt = edited.read_text(encoding="utf-8", errors="replace")

    raw_cues = _parse_srt_cues(raw_txt)
    ed_cues = _parse_srt_cues(ed_txt)

    r.note("cues", len(ed_cues))

    if len(raw_cues) != len(ed_cues):
        r.fail(f"cue count mismatch: raw={len(raw_cues)} edited={len(ed_cues)}")

    ts_match = raw_cues == ed_cues
    r.note("timestamps_match", ts_match)
    if not ts_match and len(raw_cues) == len(ed_cues):
        # Find first differing cue for clarity
        for i, (a, b) in enumerate(zip(raw_cues, ed_cues), 1):
            if a != b:
                r.fail(f"timestamp changed at cue #{i}: {a} -> {b}")
                break

    if raw_txt.strip() == ed_txt.strip():
        r.warn("wrapped.srt identical to raw.srt — did you forget to edit it?")
    return r


# ---------------------------------------------------------------------------
# Step 2.5 — re-run check (draft regenerated after subtitle fix)
# ---------------------------------------------------------------------------

def step2_5(name: str) -> Result:
    r = Result("step2_5")
    edited = output_dir(name) / "subs" / "transcript_wrapped.srt"
    draft = draft_dir(name) / "draft_content.json"

    if not edited.exists():
        r.fail(f"missing {edited}")
        return r
    if not draft.exists():
        r.fail(f"missing {draft}")
        return r

    ed_mt = edited.stat().st_mtime
    dr_mt = draft.stat().st_mtime
    r.note("draft_mtime", int(dr_mt))
    r.note("wrapped_mtime", int(ed_mt))

    if dr_mt <= ed_mt:
        r.fail("draft_content.json older than transcript_wrapped.srt")
        r.fail("hint: re-run `/capcut --skip-stt --skip-wrap --skip-cut` to regenerate draft")
    return r


# ---------------------------------------------------------------------------
# Step 3 — B-roll + overlay
# ---------------------------------------------------------------------------

def step3(name: str) -> Result:
    r = Result("step3")
    broll_dir = output_dir(name) / "broll_gemini"
    motion_dir = output_dir(name) / "broll_motion"
    imgs = sorted(broll_dir.glob("*.png")) if broll_dir.exists() else []
    motion_files = sorted(motion_dir.glob("*.mov")) if motion_dir.exists() else []
    r.note("broll_image_count", len(imgs))
    r.note("broll_motion_count", len(motion_files))
    if len(imgs) + len(motion_files) < 1:
        r.fail(f"no B-roll assets in {broll_dir} or {motion_dir}")

    d_dir = draft_dir(name)
    state = d_dir / ".omc_patch_state.json"
    if not state.exists():
        r.fail(f"overlay patch state missing: {state}")
        r.fail("hint: run overlay_patcher.py")

    draft_path = d_dir / "draft_content.json"
    text_track_count = 0
    if draft_path.exists():
        try:
            draft = _load_json(draft_path)
            tracks = draft.get("tracks", [])
            text_tracks = [t for t in tracks if t.get("type") == "text"]
            text_track_count = len(text_tracks)
            r.note("text_track_count", text_track_count)

            # Heuristic: emphasis track is usually a second text track, or a
            # text track whose segments reference material_animations.
            mats = draft.get("materials", {})
            anim_ids = {a.get("id") for a in mats.get("material_animations", [])}
            emphasis_found = False
            if text_track_count >= 2:
                emphasis_found = True
            else:
                for t in text_tracks:
                    for seg in t.get("segments", []):
                        refs = set(seg.get("extra_material_refs", []) or [])
                        if refs & anim_ids:
                            emphasis_found = True
                            break
                    if emphasis_found:
                        break
            if not emphasis_found:
                r.fail("no emphasis text track detected (need >=2 text tracks or animation-linked text)")
        except Exception as e:
            r.fail(f"failed reading draft: {e}")
    return r


# ---------------------------------------------------------------------------
# Step 4 — title + caption
# ---------------------------------------------------------------------------

def step4(name: str) -> Result:
    r = Result("step4")
    deliv = output_dir(name) / "deliverables"
    title_p = deliv / "title.txt"
    cap_p = deliv / "ig_caption.txt"

    if not title_p.exists():
        r.fail(f"missing {title_p}")
    else:
        title = title_p.read_text(encoding="utf-8").strip()
        tlen = len(title)  # UTF-8 code points (Korean-safe), NOT bytes
        r.note("title.txt", f"{tlen}자")
        if tlen == 0:
            r.fail("title.txt empty")
        if tlen > 20:
            r.warn(f"title > 20 chars ({tlen}) — spec says <=20")

    if not cap_p.exists():
        r.fail(f"missing {cap_p}")
        return r

    cap_raw = cap_p.read_text(encoding="utf-8")
    lines = cap_raw.splitlines()
    # Find the last non-empty line; treat it as hashtag block if it contains #
    last_nonempty_idx = -1
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].strip():
            last_nonempty_idx = i
            break

    hashtag_line = ""
    body_lines = lines[:]
    if last_nonempty_idx >= 0 and "#" in lines[last_nonempty_idx]:
        hashtag_line = lines[last_nonempty_idx]
        body_lines = lines[:last_nonempty_idx]

    body = "\n".join(body_lines).strip()
    body_len = len(body)
    r.note("ig_caption", f"{body_len}자")
    if not (400 <= body_len <= 600):
        r.fail(f"ig_caption body_len={body_len} (need 400-600)")

    hashtags = HASHTAG_RE.findall(hashtag_line)
    r.note("hashtags", len(hashtags))
    if len(hashtags) != 5:
        r.fail(f"hashtag count = {len(hashtags)} (need exactly 5, last line of file)")

    # Emoji detection — rules say 0 emoji
    emoji_hits = EMOJI_RE.findall(cap_raw)
    r.note("emoji", len(emoji_hits))
    if emoji_hits:
        sample = "".join(emoji_hits[:5])
        r.warn(f"emoji detected ({len(emoji_hits)}): {sample} — rules say 0")

    # Banned phrase check — warn but don't hard-fail (caller can decide)
    banned_hits: list[tuple[int, str]] = []
    for lineno, line in enumerate(lines, 1):
        for phrase in BANNED_PHRASES:
            if phrase in line:
                banned_hits.append((lineno, phrase))
    r.note("banned", len(banned_hits))
    for lineno, phrase in banned_hits:
        r.warn(f'banned phrase "{phrase}" in caption (line {lineno})')

    return r


# ---------------------------------------------------------------------------
# Step 5 — FX patch applied
# ---------------------------------------------------------------------------

REQUIRED_FX_KEYS = (
    "title_animation",
    "outro_animation",
    "sfx",
    "scene_effects",
    "bgm",
    "filter",
)


def step5(name: str) -> Result:
    r = Result("step5")
    d_dir = draft_dir(name)
    state_p = d_dir / ".omc_fx_patch_state.json"
    draft_p = d_dir / "draft_content.json"

    if not state_p.exists():
        r.fail(f"fx patch state missing: {state_p}")
        r.fail("hint: run capcut_fx_patcher.py")
        return r

    try:
        state = _load_json(state_p)
    except Exception as e:
        r.fail(f"fx state invalid JSON: {e}")
        return r

    log = state.get("log") or {}
    missing_keys: list[str] = []
    short_keys: list[str] = []
    for key in REQUIRED_FX_KEYS:
        val = log.get(key)
        if val is None:
            missing_keys.append(key)
            continue
        if key in ("sfx", "scene_effects"):
            try:
                n = len(val)
            except TypeError:
                n = 0
            if n < 3:
                short_keys.append(f"{key}(len={n})")
    if missing_keys:
        r.fail(f"fx log missing keys: {', '.join(missing_keys)}")
    if short_keys:
        r.fail(f"fx log keys too short (need >=3): {', '.join(short_keys)}")

    r.note("fx_log_keys", len([k for k in REQUIRED_FX_KEYS if log.get(k) is not None]))

    if not draft_p.exists():
        r.fail(f"missing {draft_p}")
        return r

    try:
        draft = _load_json(draft_p)
    except Exception as e:
        r.fail(f"draft invalid JSON: {e}")
        return r

    mats = draft.get("materials", {})
    effects = mats.get("effects", []) or []
    audios = mats.get("audios", []) or []
    video_effects = mats.get("video_effects", []) or []

    filter_count = sum(1 for e in effects if e.get("type") == "filter")
    r.note("filter_effects", filter_count)
    if filter_count < 1:
        r.fail("materials.effects has no filter entry")

    r.note("audios", len(audios))
    if len(audios) < 4:
        r.fail(f"materials.audios = {len(audios)} (need >=4: 3 SFX + 1 BGM)")

    r.note("video_effects", len(video_effects))
    if len(video_effects) < 3:
        r.fail(f"materials.video_effects = {len(video_effects)} (need >=3)")

    tracks = draft.get("tracks", []) or []
    track_types = {t.get("type") for t in tracks}
    if "filter" not in track_types:
        r.fail("tracks has no 'filter' track")
    if "effect" not in track_types:
        r.fail("tracks has no 'effect' track")
    return r


# ---------------------------------------------------------------------------
# Step 6 — final export
# ---------------------------------------------------------------------------

def step6(name: str) -> Result:
    r = Result("step6")
    final = output_dir(name) / "deliverables" / "final.mp4"
    if not final.exists():
        r.fail(f"missing {final}")
        r.fail("hint: export from CapCut to this path")
        return r

    size = final.stat().st_size
    r.note("final_size_mb", f"{size / 1e6:.1f}")
    if size < 1_000_000:
        r.fail(f"final.mp4 too small ({size} bytes; need >1MB)")

    return r


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

STEP_FUNCS = {
    "1": step1,
    "2": step2,
    "2.5": step2_5,
    "3": step3,
    "4": step4,
    "5": step5,
    "6": step6,
}


def run_all(name: str) -> int:
    results: list[Result] = []
    for key in ["1", "2", "2.5", "3", "4", "5", "6"]:
        fn = STEP_FUNCS[key]
        try:
            res = fn(name)
        except Exception as e:
            res = Result(f"step{key}")
            res.fail(f"exception: {e}")
        res.emit()
        results.append(res)

    passed = sum(1 for r in results if r.ok)
    total = len(results)
    print(f"\n[summary] {passed}/{total} gates passed")
    return 0 if passed == total else 5


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Verify /capcut pipeline step gates")
    p.add_argument("step", nargs="?", help="Step number: 1, 2, 2.5, 3, 4, 5, 6")
    p.add_argument("--name", required=True, help="Project name (draft dir stem)")
    p.add_argument("--all", action="store_true", help="Run all steps sequentially")
    args = p.parse_args(argv)

    if args.all:
        return run_all(args.name)

    if not args.step:
        print("error: step number required (or use --all)", file=sys.stderr)
        return 1
    if args.step not in STEP_FUNCS:
        print(f"error: unknown step '{args.step}'. Valid: {list(STEP_FUNCS)}", file=sys.stderr)
        return 1

    fn = STEP_FUNCS[args.step]
    try:
        res = fn(args.name)
    except Exception as e:
        res = Result(f"step{args.step}")
        res.fail(f"exception: {e}")

    res.emit()
    return 0 if res.ok else 5


if __name__ == "__main__":
    sys.exit(main())
