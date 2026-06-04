"""End-to-end CapCut pipeline.

Usage:
    python tools/capcut_pipeline/run_pipeline.py <video_path> [--name NAME] [--model SIZE]
                                                 [--min-silence SEC] [--noise DB]
                                                 [--min-scene SEC] [--skip-stt]
                                                 [--skip-cut] [--skip-draft]

Runs:
    1. ffprobe -> metadata
    2. ffmpeg silencedetect -> scene boundaries
    3. faster-whisper -> transcript.srt / .json
    4. ffmpeg -c copy -> scene_XX.mp4 files
    5. pycapcut -> CapCut draft in %LocalAppData%\\CapCut\\...\\com.lveditor.draft\\NAME\\
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# Windows cp949 stdout can't encode em-dashes used throughout the script.
# Force UTF-8 so print() never crashes mid-pipeline.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# --- paths ---------------------------------------------------------------

PROJECT_ROOT = Path(os.environ.get("CAPCUT_PROJECT_ROOT") or Path(__file__).resolve().parents[2])
# FFmpeg/FFprobe: env override → PATH (assumes ffmpeg & ffprobe installed and resolvable)
_FFMPEG_BIN = os.environ.get("CAPCUT_FFMPEG_BIN")
if _FFMPEG_BIN:
    FFBIN = Path(_FFMPEG_BIN)
    FFMPEG = str(FFBIN / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"))
    FFPROBE = str(FFBIN / ("ffprobe.exe" if os.name == "nt" else "ffprobe"))
else:
    FFMPEG = "ffmpeg"
    FFPROBE = "ffprobe"
CAPCUT_ROOT = Path(os.environ.get("CAPCUT_DRAFT_ROOT") or (Path(os.environ["LOCALAPPDATA"]) / "CapCut/User Data/Projects/com.lveditor.draft"))


# --- step 1: probe -------------------------------------------------------

def probe(src: Path) -> dict:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-of", "json", "-show_format", "-show_streams", str(src)],
        capture_output=True, text=True, check=True,
    )
    d = json.loads(out.stdout)
    info = {"duration": float(d["format"]["duration"]), "size_mb": int(d["format"]["size"]) / 1024 / 1024}
    for s in d["streams"]:
        if s["codec_type"] == "video":
            info["width"] = s["width"]; info["height"] = s["height"]
            info["video_codec"] = s["codec_name"]
        elif s["codec_type"] == "audio":
            info["audio_codec"] = s["codec_name"]
            info["sample_rate"] = s.get("sample_rate")
    return info


# --- step 2: silence -> scenes ------------------------------------------

def detect_silence(src: Path, log_path: Path, noise_db: float, min_silence: float) -> list[tuple[float, float]]:
    subprocess.run(
        [FFMPEG, "-hide_banner", "-nostats", "-i", str(src),
         "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-"],
        stderr=log_path.open("w", encoding="utf-8"), stdout=subprocess.DEVNULL, check=True,
    )
    starts, ends = [], []
    pat_s = re.compile(r"silence_start:\s*([\d.]+)")
    pat_e = re.compile(r"silence_end:\s*([\d.]+)")
    for line in log_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if (m := pat_s.search(line)): starts.append(float(m.group(1)))
        elif (m := pat_e.search(line)): ends.append(float(m.group(1)))
    return list(zip(starts, ends))


def build_scenes(pairs: list[tuple[float, float]], duration: float, min_scene: float) -> list[dict]:
    cuts = sorted((s + e) / 2 for s, e in pairs if 0.5 < (s + e) / 2 < duration - 0.5)
    scenes: list[tuple[float, float]] = []
    prev = 0.0
    for c in cuts:
        scenes.append((prev, c)); prev = c
    scenes.append((prev, duration))

    merged: list[tuple[float, float]] = []
    i = 0
    while i < len(scenes):
        s, e = scenes[i]
        while (e - s) < min_scene and (i + 1) < len(scenes):
            i += 1; e = scenes[i][1]
        merged.append((s, e)); i += 1
    if len(merged) >= 2 and (merged[-1][1] - merged[-1][0]) < min_scene:
        last = merged.pop()
        merged[-1] = (merged[-1][0], last[1])
    return [{"idx": i, "start": round(s, 3), "end": round(e, 3), "length": round(e - s, 3)}
            for i, (s, e) in enumerate(merged)]


# --- step 3: STT ---------------------------------------------------------

def run_stt(src: Path, subs_dir: Path, model_size: str) -> Path:
    from faster_whisper import WhisperModel  # lazy import
    print(f"[stt] loading model={model_size}")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        str(src), language="ko", vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500}, word_timestamps=True,
    )
    print(f"[stt] language={info.language} prob={info.language_probability:.2f}")

    def ts(t: float) -> str:
        h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60); ms = int((t - int(t)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    srt, segs = [], []
    for i, seg in enumerate(segments, 1):
        srt += [str(i), f"{ts(seg.start)} --> {ts(seg.end)}", seg.text.strip(), ""]
        segs.append({"idx": i, "start": round(seg.start, 3), "end": round(seg.end, 3),
                     "text": seg.text.strip(),
                     "words": [{"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word}
                               for w in (seg.words or [])]})
    srt_path = subs_dir / "transcript.srt"
    srt_path.write_text("\n".join(srt), encoding="utf-8")
    (subs_dir / "transcript.json").write_text(
        json.dumps({"language": info.language, "segments": segs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[stt] wrote {len(segs)} segments → {srt_path}")
    return srt_path


# --- step 4: cut scenes --------------------------------------------------

def _probe_duration(path: Path) -> float:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-of", "json", "-show_entries", "format=duration", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def cut_scenes(src: Path, scenes: list[dict], scenes_dir: Path, *, accurate: bool = True) -> list[dict]:
    """Extract scene clips with ffmpeg.

    accurate=True  → re-encode for frame-accurate cuts (no keyframe overlap)
    accurate=False → stream copy (fast but snaps to keyframes, may overlap)

    The manifest returns the ACTUAL measured duration of each output file, not
    the requested length. Frame alignment during re-encoding can shorten a clip
    by a few ms — pycapcut rejects source_timerange > material duration.
    """
    manifest = []
    for sc in scenes:
        out = scenes_dir / f"scene_{sc['idx']:02d}.mp4"
        if accurate:
            # -ss AFTER -i + re-encode = frame-accurate cut, no keyframe snap
            cmd = [
                FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(src),
                "-ss", str(sc["start"]),
                "-t", str(sc["length"]),
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(out),
            ]
        else:
            cmd = [
                FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
                "-ss", str(sc["start"]), "-i", str(src), "-t", str(sc["length"]),
                "-c", "copy", "-avoid_negative_ts", "make_zero", str(out),
            ]
        subprocess.run(cmd, check=True)
        actual = _probe_duration(out)
        mode = "reencode" if accurate else "copy"
        marker = "" if abs(actual - sc["length"]) < 0.01 else f"  (actual={actual:.3f}s)"
        print(f"[cut/{mode}] #{sc['idx']:02d} {sc['start']:.2f}+{sc['length']:.2f} → {out.name}{marker}")
        manifest.append({"idx": sc["idx"], "file": str(out).replace("\\", "/"),
                         "start": sc["start"], "end": sc["start"] + actual, "duration": actual})
    return manifest


# --- subtitle word-wrap --------------------------------------------------

def _fmt_ts(t: float) -> str:
    h = int(t // 3600); m = int((t % 3600) // 60); s = int(t % 60); ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


# 한국어 자연 break-point scoring (2026-05-13).
# 토큰 끝에서 끊으면 얼마나 자연스러운지 가중치. wrap_segments에서 사용해
# "답답한 / 건데," 같은 명사구 분리 + "이 3가지 중 / 하나에서" 같은 명사+조사 분리를 방지.
_KO_CLAUSE_ENDINGS = (
    # 연결어미 (절 분리에 자연스러운 지점)
    "지만", "는데", "인데", "면서", "려고", "려면",
    "니까", "므로", "거든", "기에", "다가", "다면",
    "고서", "면서도", "ㄴ다면", "어서", "아서",
)
_KO_PARTICLES = (
    # 자주 쓰이는 조사 (명사 끝)
    "은", "는", "이", "가", "을", "를", "에", "에서", "으로",
    "로", "와", "과", "도", "만", "조차", "뿐", "마저",
    "께서", "한테", "에게", "께", "보다", "처럼", "같이",
    "부터", "까지", "라", "라고", "이라고", "이라며",
)
_SENT_END = (".", "?", "!")
_COMMA_END = (",",)


def _semantic_break_score(token: str) -> int:
    """이 토큰 끝에서 끊으면 자연스러운가. 높을수록 끊기 좋은 위치.

    0 = 부자연 (명사 한가운데, 형용사 활용형 끝 등)
    3 = 조사 끝 (명사+조사 직후 = 다음 구문 시작 OK)
    5 = 연결어미 끝 (절 경계)
    8 = 쉼표
    10 = 문장 종결부호 (이미 pre-split됐어야 함)
    """
    if not token:
        return 0
    # 문장 종결부호 (split_words_at_sentences가 이미 split했어야)
    if any(token.endswith(e) for e in _SENT_END):
        return 10
    if any(token.endswith(e) for e in _COMMA_END):
        return 8
    stem = token.rstrip(",.!?")
    if not stem:
        return 0
    # 어미 매칭 — 긴 ending 우선
    for ending in sorted(_KO_CLAUSE_ENDINGS, key=len, reverse=True):
        if stem.endswith(ending):
            return 5
    # 명사 + 조사 (stem이 ending보다 충분히 긴 경우만; 단음절 단어는 단어 자체일 수 있음)
    for particle in sorted(_KO_PARTICLES, key=len, reverse=True):
        if stem.endswith(particle) and len(stem) > len(particle):
            return 3
    return 0


def wrap_segments(segments: list[dict], max_chars: int) -> list[dict]:
    """Semantic Korean-aware wrap (2026-05-13 rewrite).

    이전 알고리즘은 글자수 균등 분할만 해서 한국어 의미 경계를 무시 → cue가
    "답답한 / 건데," "이 3가지 중 / 하나에서" 같이 부자연스럽게 끊김. 새 알고리즘:

    1. 토큰별로 _semantic_break_score 계산 (어미·조사·구두점)
    2. 누적 글자수가 max_chars * 0.5 이상이면 자연 break 후보로 인정
    3. max_chars 초과 임박 시 강제 break
    4. 우선순위: 문장종결 > 쉼표 > 연결어미 > 조사 > 강제(자연 0점)

    Pre-step: 문장 종결부호로 segment 분할 (기존 유지).

    Uses word-level timestamps when available for precise timing.
    """
    import math
    # Lazy import to avoid circular when ng_cutter imports this module.
    sys.path.insert(0, str(Path(__file__).parent))
    from korean_text_normalize import split_words_at_sentences  # type: ignore

    # 1) split each segment at internal sentence endings, expanding the list.
    expanded: list[dict] = []
    for seg in segments:
        words = [w for w in (seg.get("words") or []) if (w.get("word") or "").strip()]
        if not words:
            expanded.append(seg)
            continue
        groups = split_words_at_sentences(words)
        if len(groups) == 1:
            expanded.append(seg)
            continue
        for g in groups:
            text = " ".join((w.get("word") or "").strip() for w in g).strip()
            expanded.append({
                "start": g[0]["start"],
                "end": g[-1]["end"],
                "text": text,
                "words": g,
            })

    out: list[dict] = []
    for seg in expanded:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        total = len(text)
        if total <= max_chars:
            out.append({"start": seg["start"], "end": seg["end"], "text": text})
            continue

        num_cues = max(2, math.ceil(total / max_chars))

        words = [w for w in (seg.get("words") or []) if (w.get("word") or "").strip()]

        if words:
            # each token carries its (start, end, len including leading space)
            toks = []
            for i, w in enumerate(words):
                t = w["word"].strip()
                toks.append({
                    "tok": t,
                    "start": w["start"],
                    "end": w["end"],
                    "span": len(t) + (1 if i > 0 else 0),  # +1 for joining space
                })

            # ⭐ Semantic break: 한국어 의미 경계 우선 (조사·어미·쉼표·종결)
            #
            # 절차:
            #   1. 현재 토큰 추가 후 자연 break score 계산
            #   2. cur_chars >= max_chars * 0.4 이상이면 자연 break 후보 활성
            #   3. 다음 토큰 추가 시 max_chars 초과 임박 (>= max_chars - 2)이면 강제 break
            #   4. 자연 break score 3 이상이면 break (조사/어미/쉼표)
            #   5. 단, 다음 토큰까지 합쳐도 max_chars 이하이고 score 0이면 계속 누적
            #      → "이 3가지 중 / 하나에서" 부자연 분리 방지
            min_chars_to_break = max(6, int(max_chars * 0.4))
            soft_overflow = max_chars - 2  # buffer
            groups: list[list[dict]] = []
            cur: list[dict] = []
            cur_chars = 0
            for i, tk in enumerate(toks):
                cur.append(tk)
                cur_chars += tk["span"]
                next_span = toks[i + 1]["span"] if i + 1 < len(toks) else 0
                would_overflow = (cur_chars + next_span) > max_chars
                # 마지막 토큰
                if i == len(toks) - 1:
                    continue
                tok_score = _semantic_break_score(tk["tok"])
                should_break = False
                if would_overflow:
                    # 강제 break: 다음 토큰 추가 시 max 초과
                    should_break = True
                elif tok_score >= 3 and cur_chars >= min_chars_to_break:
                    # 자연 break: 충분히 길고 어미/조사/쉼표
                    should_break = True
                    # ⭐ look-ahead 보류 (2026-06-01): 조사/연결어미(3~5점)에서 끊으려 할 때,
                    # max_chars 내에 더 좋은 break(쉼표/종결 8+)가 도달 가능하면 거기까지 보류.
                    # → "신중하게 하고 싶은" / "마음," 처럼 관형형 어미("싶은")에서
                    #    명사구("싶은 마음,")가 조기 분리되는 문제 방지.
                    if tok_score < 8:
                        la_chars = cur_chars
                        for j in range(i + 1, len(toks)):
                            la_chars += toks[j]["span"]
                            if la_chars > max_chars:
                                break
                            if _semantic_break_score(toks[j]["tok"]) >= 8:
                                should_break = False  # 쉼표/종결까지 보류
                                break
                elif cur_chars >= soft_overflow:
                    # soft overflow buffer 도달: 0점이라도 자르기
                    should_break = True
                if should_break:
                    groups.append(cur)
                    cur = []
                    cur_chars = 0
            if cur:
                groups.append(cur)

            for g in groups:
                cue_text = "".join(
                    (" " if i > 0 else "") + t["tok"] for i, t in enumerate(g)
                )
                out.append({
                    "start": g[0]["start"],
                    "end": g[-1]["end"],
                    "text": cue_text,
                })
        else:
            # no word timing → split tokens by char budget + proportional timing
            tokens = text.split()
            spans = [len(t) + (1 if i > 0 else 0) for i, t in enumerate(tokens)]

            groups_tok: list[list[int]] = []  # lists of token indices
            cur_idx: list[int] = []
            cur_chars = 0
            consumed = 0
            for i, tok in enumerate(tokens):
                cur_idx.append(i)
                cur_chars += spans[i]
                remaining_groups = num_cues - len(groups_tok)
                if remaining_groups <= 1:
                    continue
                remaining_chars = total - consumed
                target = remaining_chars / remaining_groups
                next_span = spans[i + 1] if i + 1 < len(tokens) else 0
                if cur_chars >= target or (cur_chars + next_span) > max_chars:
                    groups_tok.append(cur_idx)
                    consumed += cur_chars
                    cur_idx = []
                    cur_chars = 0
            if cur_idx:
                groups_tok.append(cur_idx)

            dur = max(1e-3, seg["end"] - seg["start"])
            cursor = seg["start"]
            total_span = sum(spans)
            for g in groups_tok:
                g_text = " ".join(tokens[i] for i in g)
                g_span = sum(spans[i] for i in g)
                end_t = cursor + dur * (g_span / total_span)
                out.append({"start": cursor, "end": min(end_t, seg["end"]), "text": g_text})
                cursor = end_t
    return out


def write_wrapped_srt(transcript_json: Path, out_path: Path, max_chars: int) -> Path:
    sys.path.insert(0, str(Path(__file__).parent))
    from korean_text_normalize import convert_korean_numbers  # type: ignore
    data = json.loads(transcript_json.read_text(encoding="utf-8"))
    # Normalize Korean numbers (사십칠개 → 47개) at the segment level so
    # the char-based wrap budgets shorter strings.
    for seg in data.get("segments", []):
        if seg.get("text"):
            seg["text"] = convert_korean_numbers(seg["text"])
        for w in seg.get("words", []):
            if w.get("word"):
                w["word"] = convert_korean_numbers(w["word"])
    cues = wrap_segments(data.get("segments", []), max_chars)
    # Final pass: convert any remaining Korean numbers in cue text (compound
    # spans across word boundaries can leave residue).
    for c in cues:
        c["text"] = convert_korean_numbers(c["text"])
    lines: list[str] = []
    for i, c in enumerate(cues, 1):
        lines += [str(i), f"{_fmt_ts(c['start'])} --> {_fmt_ts(c['end'])}", c["text"], ""]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[wrap] {len(data.get('segments', []))} segments → {len(cues)} cues (<={max_chars} chars) → {out_path.name}")
    return out_path


# --- step 5: CapCut draft ------------------------------------------------

def build_draft(
    name: str, width: int, height: int, fps: int, manifest: list[dict], srt: Path | None,
    *, font_size: float = 13.0, sub_y: float = -0.234, stroke_ui: float = 20.0,
    border_color: tuple[float, float, float] = (0.0, 0.0, 0.0),
    text_color: tuple[float, float, float] = (1.0, 1.0, 1.0), align: int = 1,
    font_path: str | None = None, font_title: str | None = None,
    sub_offset_ms: int = 0, sub_max_duration_ms: int = 0,
) -> Path:
    # CapCut UI "획 두께" units vs internal pycapcut/JSON units:
    #   UI value  40  ↔  pycapcut TextBorder width  40  ↔  JSON strokes.width  0.08
    # Empirically (confirmed via CapCut UI): pycapcut = UI * 1, JSON = UI * 0.002.
    pycapcut_border = stroke_ui * 1.0
    json_stroke = stroke_ui * 0.002
    import pycapcut as pc
    # Read CapCut's master project registry BEFORE overwriting the folder.
    # CapCut identifies projects by draft_id (UUID). pycapcut's allow_replace=True
    # generates a fresh UUID each run, so we must preserve the existing UUID
    # (if any) to keep the registry and the folder in sync — otherwise CapCut's
    # project panel clicks won't open the draft.
    registry_path = CAPCUT_ROOT / "root_meta_info.json"
    preserved_draft_id: str | None = None
    preserved_create_time: int | None = None
    if registry_path.exists():
        try:
            reg_data = json.loads(registry_path.read_text(encoding="utf-8"))
            for entry in reg_data.get("all_draft_store", []):
                if entry.get("draft_name") == name:
                    preserved_draft_id = entry.get("draft_id")
                    preserved_create_time = entry.get("tm_draft_create")
                    break
        except Exception as e:
            print(f"[warn] couldn't read registry: {e}")

    folder = pc.DraftFolder(str(CAPCUT_ROOT))
    script = folder.create_draft(name, width, height, fps=fps, allow_replace=True)
    script.add_track(pc.TrackType.video, "main_video")
    script.add_track(pc.TrackType.text, "subtitles", relative_index=1)
    cursor = 0
    for sc in manifest:
        mat = pc.VideoMaterial(sc["file"], material_name=f"scene_{sc['idx']:02d}")
        # Trust pycapcut's own duration reading (via pymediainfo) — ffprobe
        # and pymediainfo disagree by up to ~40ms on re-encoded files, and
        # pycapcut rejects source_timerange > material.duration.
        dur_us = mat.duration
        if dur_us <= 0:
            continue
        seg = pc.VideoSegment(
            mat,
            target_timerange=pc.Timerange(cursor, dur_us),
            source_timerange=pc.Timerange(0, dur_us),
        )
        script.add_segment(seg, track_name="main_video")
        cursor += dur_us
    if srt and srt.exists():
        # style reference carries text fill + border; clip_settings is passed
        # separately because import_srt uses its own default otherwise.
        style_ref = pc.TextSegment(
            "Aa",
            pc.Timerange(0, pc.SEC),
            style=pc.TextStyle(
                size=font_size,
                color=text_color,
                align=align,
                auto_wrapping=False,
            ),
            border=pc.TextBorder(color=border_color, width=pycapcut_border, alpha=1.0),
        )
        clip_s = pc.ClipSettings(transform_x=0.0, transform_y=sub_y)
        script.import_srt(
            str(srt), track_name="subtitles",
            style_reference=style_ref,
            clip_settings=clip_s,
        )
    script.save()

    # Post-process draft_content.json to inject the custom TTF path and
    # enforce a uniform stroke width on every subtitle segment. pycapcut's
    # FontType enum only supports a fixed list of built-in fonts, and
    # style_reference doesn't always carry stroke width through to every
    # cue, so we patch the JSON directly as the source of truth.
    if font_path:
        _patch_fonts(CAPCUT_ROOT / name, font_path, font_title or "")
    _patch_strokes(CAPCUT_ROOT / name, json_stroke, border_color)
    # Clip cues that span multiple scenes (Whisper captures NG retakes as a
    # single long segment from first-attempt to last-attempt's end). Since
    # the scene boundaries ARE the NG silence points, the successful take
    # lives in the LAST overlapping scene. Clipping the start to that
    # scene's start aligns the subtitle with the final delivery. Must run
    # BEFORE group binding so the cue binds to the correct (last) scene.
    _patch_subtitle_scene_clip(CAPCUT_ROOT / name)
    # Bind each subtitle to its parent scene via shared group_id so deleting
    # an NG scene in CapCut also removes its subtitles and the remaining
    # subtitles stay aligned with the remaining scenes.
    _patch_scene_subtitle_groups(CAPCUT_ROOT / name)
    # Shift every subtitle target_timerange by sub_offset_ms. Whisper word
    # timestamps lead the audible start by ~100-300ms (phoneme-onset bias);
    # a constant positive offset nudges subtitles to land when speech
    # actually becomes audible. Applied AFTER group binding so bindings
    # stay valid (group_id is not affected by the shift).
    if sub_offset_ms:
        _patch_subtitle_offset(CAPCUT_ROOT / name, sub_offset_ms)
    # Cap every subtitle's on-screen duration. Whisper tends to stretch a
    # word's end timestamp to cover trailing silence or NG pauses, leaving
    # some cues on-screen for 5-7 seconds. A hard cap keeps subtitles off
    # screen during silence without interfering with the group binding.
    if sub_max_duration_ms:
        _patch_subtitle_max_duration(CAPCUT_ROOT / name, sub_max_duration_ms)

    # Critical: keep pycapcut-generated folder in sync with CapCut's project
    # registry. Otherwise CapCut can't open the draft from its project panel.
    _patch_draft_meta(CAPCUT_ROOT / name, preserved_draft_id, preserved_create_time)
    _sync_registry(CAPCUT_ROOT / name, registry_path)
    return CAPCUT_ROOT / name


def _patch_subtitle_scene_clip(draft_dir: Path) -> None:
    """For cues that span 2+ scenes, clip cue.start to the LAST overlapping
    scene's start (reduce duration accordingly).

    Why: when the speaker re-takes a line after an NG, Whisper often
    collapses all attempts into one segment — start at the first attempt,
    end at the successful last attempt. Scene boundaries are at silence
    points (so NG pauses sit between scenes), which means the successful
    take always lives in the LAST scene the cue overlaps. Clipping to
    that scene's start realigns the subtitle with the final delivery and
    removes lingering "phantom" text over earlier NG takes.
    """
    content_path = draft_dir / "draft_content.json"
    if not content_path.exists():
        return
    data = json.loads(content_path.read_text(encoding="utf-8"))
    vtrack = next((t for t in data.get("tracks", []) if t.get("name") == "main_video"), None)
    ttrack = next((t for t in data.get("tracks", []) if t.get("name") == "subtitles"), None)
    if not vtrack or not ttrack:
        return
    scenes = sorted(
        (
            (vs["target_timerange"]["start"],
             vs["target_timerange"]["start"] + vs["target_timerange"]["duration"])
            for vs in vtrack.get("segments", [])
        ),
        key=lambda p: p[0],
    )
    clipped = 0
    for ts in ttrack.get("segments", []):
        tr = ts.get("target_timerange")
        if not tr or tr.get("duration", 0) <= 0:
            continue
        cue_start = tr["start"]
        cue_end = cue_start + tr["duration"]
        overlapping = [(s, e) for s, e in scenes if s < cue_end and e > cue_start]
        if len(overlapping) < 2:
            continue
        last_start = overlapping[-1][0]
        if cue_start < last_start:
            new_duration = cue_end - last_start
            if new_duration > 0:
                tr["start"] = last_start
                tr["duration"] = new_duration
                clipped += 1
    content_path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"[scene-clip] re-anchored {clipped} cross-scene subtitles to last overlapping scene")


def _patch_subtitle_max_duration(
    draft_dir: Path, max_ms: int, ms_per_char: int = 250, min_ms: int = 1000,
    buffer_ms: int = 500,
) -> None:
    """Clip each subtitle's on-screen duration using a character-aware budget.

    The effective cap is:
        allowed = max(min_ms, min(max_ms, chars * ms_per_char + buffer_ms))

    Short NG cues like '댓글에...' (4 chars) shrink to ~1.5s instead of
    lingering for the full max_ms. Long cues still cap at max_ms.

    Character count is read from the text material's `content` JSON so
    proofread edits are reflected. start_offset stays put because only
    duration is changed.
    """
    content_path = draft_dir / "draft_content.json"
    if not content_path.exists():
        return
    data = json.loads(content_path.read_text(encoding="utf-8"))
    text_track = next((t for t in data.get("tracks", []) if t.get("name") == "subtitles"), None)
    if not text_track:
        return
    text_mats = {m["id"]: m for m in data.get("materials", {}).get("texts", [])}

    def chars_for(mat: dict) -> int:
        try:
            return len(json.loads(mat.get("content", "{}")).get("text", ""))
        except Exception:
            return 0

    clipped = 0
    for ts in text_track.get("segments", []):
        tr = ts.get("target_timerange")
        if not tr or tr.get("duration", 0) <= 0:
            continue
        chars = chars_for(text_mats.get(ts.get("material_id"), {}))
        budget_ms = max(min_ms, min(max_ms, chars * ms_per_char + buffer_ms))
        budget_us = budget_ms * 1000
        if tr["duration"] > budget_us:
            tr["duration"] = budget_us
            clipped += 1
    content_path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"[max-dur] clipped {clipped} subtitles (per-char={ms_per_char}ms, min={min_ms}ms, max={max_ms}ms)")


def _patch_subtitle_offset(draft_dir: Path, offset_ms: int) -> None:
    """Shift every subtitle segment's target_timerange.start by offset_ms.

    Whisper's word_timestamps=True reports starts at phoneme onset, which
    in practice leads the audible start of the word by ~100-300ms. A
    constant positive offset compensates. Duration stays put so end
    times shift by the same amount.
    """
    offset_us = int(offset_ms) * 1000
    content_path = draft_dir / "draft_content.json"
    if not content_path.exists():
        return
    data = json.loads(content_path.read_text(encoding="utf-8"))
    text_track = next((t for t in data.get("tracks", []) if t.get("name") == "subtitles"), None)
    if not text_track:
        return
    shifted = 0
    for ts in text_track.get("segments", []):
        tr = ts.get("target_timerange")
        if tr and "start" in tr:
            tr["start"] += offset_us
            shifted += 1
    content_path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"[offset] shifted {shifted} subtitles by +{offset_ms}ms")


def _patch_scene_subtitle_groups(draft_dir: Path) -> None:
    """Assign a shared group_id to each scene and every subtitle that falls
    within its target_timerange so CapCut groups them as one editable unit.

    Why: with subtitles imported via import_srt using absolute timestamps, the
    text segments live on an independent track. Deleting an NG scene on the
    video track leaves the matching subtitles dangling and pushes the rest of
    the timeline out of sync. Linking each text cue to its parent video clip
    via the shared group_id field makes CapCut treat them as one group:
    delete the scene → its subtitles go with it; remaining scenes + subtitles
    auto-align because they share timing.

    Cues that straddle a scene boundary are bound to the scene where they
    START. The silence-based cut boundaries mean this is rare in practice.
    """
    import uuid
    content_path = draft_dir / "draft_content.json"
    if not content_path.exists():
        return
    data = json.loads(content_path.read_text(encoding="utf-8"))
    video_track = next((t for t in data.get("tracks", []) if t.get("name") == "main_video"), None)
    text_track = next((t for t in data.get("tracks", []) if t.get("name") == "subtitles"), None)
    if not video_track or not text_track:
        return
    vsegs = sorted(video_track.get("segments", []), key=lambda s: s["target_timerange"]["start"])
    tsegs = text_track.get("segments", [])

    # assign a fresh group_id per scene
    scene_groups: list[tuple[int, int, str]] = []  # (start_us, end_us, group_id)
    for vs in vsegs:
        tr = vs["target_timerange"]
        gid = uuid.uuid4().hex.upper()
        vs["group_id"] = gid
        scene_groups.append((tr["start"], tr["start"] + tr["duration"], gid))

    bound = 0
    for ts in tsegs:
        ts_start = ts["target_timerange"]["start"]
        for s_start, s_end, gid in scene_groups:
            if s_start <= ts_start < s_end:
                ts["group_id"] = gid
                bound += 1
                break

    content_path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"[group] bound {bound} subtitles to {len(scene_groups)} scenes via group_id")


def _patch_fonts(draft_dir: Path, font_path: str, font_title: str) -> None:
    """Set the custom font on every text material so CapCut displays and
    renders it correctly.

    CapCut identifies user-registered fonts by their display name which lives
    in  %LocalAppData%\\CapCut\\User Data\\Config\\userFontData  as entries
    like  Od%UC788%UC5B4%UBE4C%UB9AC%UD2F0=<path>  (URL-encoded Korean).
    The UI's font picker reads `font_name` on the text material and matches
    it against that registry. We also set `font_path` for direct loading and
    inject a font reference into the embedded content.styles[*].font object
    so CapCut's renderer picks up the face on first load.
    """
    content_path = draft_dir / "draft_content.json"
    if not content_path.exists():
        return
    data = json.loads(content_path.read_text(encoding="utf-8"))
    texts = data.get("materials", {}).get("texts", [])
    display_name = _resolve_user_font_name(font_path) or font_title
    count = 0
    for t in texts:
        t["font_path"] = font_path
        t["font_name"] = display_name
        if font_title:
            t["font_title"] = font_title
        # also embed into content.styles[*].font so the renderer sees it
        try:
            inner = json.loads(t["content"])
            for st in inner.get("styles", []):
                st["font"] = {"path": font_path, "id": "", "name": display_name}
            t["content"] = json.dumps(inner, ensure_ascii=False)
        except Exception:
            pass
        count += 1
    content_path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
    print(f"[font] patched {count} text materials → name='{display_name}' path={font_path}")


def _patch_strokes(draft_dir: Path, width: float, color: tuple[float, float, float]) -> None:
    """Force every text material's stroke width and color to match.

    Works around cases where pycapcut's style_reference writes inconsistent
    stroke values across 70+ imported SRT cues — we make the JSON the single
    source of truth by overwriting strokes[*] on each material.
    """
    content_path = draft_dir / "draft_content.json"
    if not content_path.exists():
        return
    data = json.loads(content_path.read_text(encoding="utf-8"))
    fixed = 0
    for t in data.get("materials", {}).get("texts", []):
        try:
            inner = json.loads(t["content"])
        except Exception:
            continue
        changed = False
        for st in inner.get("styles", []):
            st["strokes"] = [{
                "content": {"solid": {"alpha": 1.0, "color": list(color)}},
                "width": width,
            }]
            changed = True
        if changed:
            t["content"] = json.dumps(inner, ensure_ascii=False)
            # mirror to top-level convenience fields CapCut also reads
            t["border_color"] = "#{:02x}{:02x}{:02x}".format(
                int(color[0] * 255), int(color[1] * 255), int(color[2] * 255)
            )
            t["border_width"] = width
            t["border_alpha"] = 1.0
            fixed += 1
    content_path.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
    ui = width / 0.002
    print(f"[stroke] forced {fixed} text materials -> width={width} (UI~{ui:.0f})")


def _resolve_user_font_name(font_path: str) -> str | None:
    """Look up the display name CapCut uses for a custom font by parsing
    its  userFontData  registry. Returns None if not found.
    """
    reg = Path(os.environ["LOCALAPPDATA"]) / "CapCut/User Data/Config/userFontData"
    if not reg.exists():
        return None
    target = font_path.replace("\\", "/").lower()
    try:
        for raw in reg.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" not in raw or raw.strip().startswith("["):
                continue
            key, _, val = raw.partition("=")
            if val.strip().replace("\\", "/").lower() == target:
                # key is URL-encoded with %UXXXX — decode Korean codepoints
                return _decode_capcut_key(key.strip())
    except Exception:
        pass
    return None


def _decode_capcut_key(key: str) -> str:
    """Decode CapCut's peculiar %UXXXX escape format into a real string."""
    out = []
    i = 0
    while i < len(key):
        if key[i] == "%" and i + 5 < len(key) and key[i + 1] in ("U", "u"):
            try:
                out.append(chr(int(key[i + 2 : i + 6], 16)))
                i += 6
                continue
            except ValueError:
                pass
        out.append(key[i])
        i += 1
    return "".join(out)


def _patch_draft_meta(draft_dir: Path, preserved_id: str | None, preserved_create: int | None) -> None:
    """Fill in the empty fields pycapcut leaves behind, and restore the
    draft_id that CapCut's registry has on file so the project stays openable.
    """
    import time
    meta_path = draft_dir / "draft_meta_info.json"
    if not meta_path.exists():
        return
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    root = draft_dir.parent
    now_us = int(time.time() * 1_000_000)

    if preserved_id:
        meta["draft_id"] = preserved_id
    meta["draft_name"] = draft_dir.name
    meta["draft_fold_path"] = str(draft_dir).replace("\\", "/")
    meta["draft_root_path"] = str(root).replace("\\", "/")
    meta.setdefault("draft_cover", "")
    meta["tm_draft_create"] = preserved_create or meta.get("tm_draft_create") or now_us
    meta["tm_draft_modified"] = now_us
    meta.setdefault("draft_need_rename_folder", False)
    meta.setdefault("draft_is_web_article_video", False)
    meta.setdefault("draft_web_article_video_enter_from", "")
    meta.setdefault("tm_draft_cloud_parent_entry_id", -1)
    meta.setdefault("tm_draft_cloud_space_id", -1)
    meta.setdefault("tm_draft_cloud_user_id", -1)
    meta["tm_draft_cloud_entry_id"] = -1
    meta_path.write_text(json.dumps(meta, indent=4, ensure_ascii=False), encoding="utf-8")
    kept = "preserved" if preserved_id else "new"
    print(f"[meta] draft_meta_info.json → id={kept} ({meta['draft_id']})")


def _sync_registry(draft_dir: Path, registry_path: Path) -> None:
    """Update CapCut's root_meta_info.json so the project entry points at the
    fresh draft_meta_info.json we just wrote. Refreshes tm_draft_modified and
    draft_timeline_materials_size on the matching entry.
    """
    if not registry_path.exists():
        print("[registry] no root_meta_info.json - CapCut will pick this up on next scan")
        return
    meta_path = draft_dir / "draft_meta_info.json"
    if not meta_path.exists():
        return
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        reg = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[registry] parse failed: {e}")
        return

    entries = reg.get("all_draft_store", [])
    name = draft_dir.name
    updated = False
    for entry in entries:
        if entry.get("draft_name") == name:
            entry["draft_id"] = meta["draft_id"]
            entry["tm_draft_modified"] = meta["tm_draft_modified"]
            entry["tm_draft_create"] = meta["tm_draft_create"]
            entry["draft_timeline_materials_size"] = meta.get("draft_timeline_materials_size_", 0)
            entry["draft_fold_path"] = meta["draft_fold_path"]
            entry["draft_root_path"] = meta["draft_root_path"]
            entry["draft_json_file"] = f"{meta['draft_fold_path']}\\draft_content.json"
            entry["draft_cover"] = f"{meta['draft_fold_path']}\\draft_cover.jpg"
            updated = True
            break

    if not updated:
        print(f"[registry] '{name}' not in registry - CapCut will pick it up on next scan")
        return

    registry_path.write_text(
        json.dumps(reg, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"[registry] synced entry '{name}' -> id={meta['draft_id']}")


# --- main ----------------------------------------------------------------

def slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_\-]", "_", s)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("video", type=Path)
    p.add_argument("--name", default=None, help="CapCut draft name (default: video stem)")
    p.add_argument("--stt-engine", choices=["elevenlabs", "whisper"], default="elevenlabs",
                   help="STT backend (default: elevenlabs Scribe v1; whisper = local faster-whisper fallback)")
    p.add_argument("--model", default="small",
                   help="faster-whisper model when --stt-engine=whisper (tiny/base/small/medium/large/large-v3)")
    p.add_argument("--min-silence", type=float, default=0.6)
    p.add_argument("--noise", type=float, default=-30.0)
    p.add_argument("--min-scene", type=float, default=1.5)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--font-size", type=float, default=13.0, help="subtitle font size")
    p.add_argument("--font-path", default="C:/Users/kbjhh/AppData/Local/Microsoft/Windows/Fonts/ODITTABILITY.TTF",
                   help="absolute path to the TTF/OTF font file for subtitles")
    p.add_argument("--font-title", default="ODITTABILITY", help="display name of the font")
    p.add_argument("--max-chars", type=int, default=18, help="wrap subtitle cues at N chars on word boundary")
    p.add_argument("--sub-y", type=float, default=-0.234, help="subtitle y position (normalized, -1..1)")
    p.add_argument("--stroke", type=float, default=20.0, help="subtitle stroke/outline thickness in CapCut UI units (획 두께)")
    p.add_argument("--fast-cut", action="store_true", help="stream-copy scene cuts (fast but may overlap at keyframes)")
    p.add_argument("--skip-stt", action="store_true")
    p.add_argument("--skip-cut", action="store_true")
    p.add_argument("--skip-draft", action="store_true")
    p.add_argument("--skip-wrap", action="store_true",
                   help="skip regenerating transcript_wrapped.srt (preserve manual proofreading edits)")
    p.add_argument("--sub-offset-ms", type=int, default=None,
                   help="shift subtitles later by N ms. default auto: 300ms for elevenlabs Scribe, 600ms for whisper (phoneme-onset early bias)")
    p.add_argument("--sub-max-duration-ms", type=int, default=5000,
                   help="cap on-screen duration per subtitle in ms (default 5000; scene-clip handles most overruns so cap is relaxed)")
    p.add_argument("--auto-broll", action=argparse.BooleanOptionalAction, default=True,
                   help="STT 완료 후 scene_designer context 자동 생성 (기본 on). 끄려면 --no-auto-broll")
    p.add_argument("--title", default="",
                   help="영상 제목 (auto-broll context에 포함)")
    args = p.parse_args()

    # Engine-appropriate default offset: Scribe is closer to ground truth than Whisper.
    # Empirical median diff over 320 words: Scribe word_start is +330ms later than Whisper.
    if args.sub_offset_ms is None:
        args.sub_offset_ms = 300 if args.stt_engine == "elevenlabs" else 600

    src: Path = args.video.resolve()
    if not src.exists():
        print(f"error: {src} not found", file=sys.stderr); return 1

    name = slug(args.name or src.stem)
    out_dir = PROJECT_ROOT / "output" / name
    scenes_dir = out_dir / "scenes"; scenes_dir.mkdir(parents=True, exist_ok=True)
    subs_dir = out_dir / "subs"; subs_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = PROJECT_ROOT / "temp" / name; tmp_dir.mkdir(parents=True, exist_ok=True)

    print(f"[1/5] probe {src.name}")
    info = probe(src)
    (tmp_dir / "probe.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"      {info['width']}x{info['height']} {info['duration']:.2f}s {info['size_mb']:.1f}MB")

    # Step 1.5 (NG cleanup) writes .ng_cleaned marker. If present, scenes.json
    # already holds the clean (word-level) timeline — running silencedetect now
    # would clobber it back to silence-based 50-scene split.
    ng_marker = tmp_dir / ".ng_cleaned"
    if ng_marker.exists() and (tmp_dir / "scenes.json").exists():
        existing = json.loads((tmp_dir / "scenes.json").read_text(encoding="utf-8"))
        scenes = existing.get("scenes", [])
        print(f"[2/5] silence detection SKIPPED — .ng_cleaned marker → reusing {len(scenes)} clean scenes")
    else:
        print(f"[2/5] silence detection (noise={args.noise}dB, min={args.min_silence}s)")
        pairs = detect_silence(src, tmp_dir / "silence.log", args.noise, args.min_silence)
        scenes = build_scenes(pairs, info["duration"], args.min_scene)
        (tmp_dir / "scenes.json").write_text(
            json.dumps({"duration": info["duration"], "scenes": scenes}, indent=2), encoding="utf-8"
        )
        print(f"      {len(pairs)} silence gaps → {len(scenes)} scenes")

    srt_path: Path | None = None
    if not args.skip_stt:
        if args.stt_engine == "elevenlabs":
            print(f"[3/5] STT (elevenlabs Scribe v1)")
            from run_stt_elevenlabs import run_stt_elevenlabs
            srt_path = run_stt_elevenlabs(src, subs_dir)
        else:
            print(f"[3/5] STT (whisper {args.model})")
            srt_path = run_stt(src, subs_dir, args.model)
    else:
        print("[3/5] STT skipped")
        cand = subs_dir / "transcript.srt"
        if cand.exists(): srt_path = cand

    # word-wrap the SRT using transcript.json word timestamps (falls back to proportional split)
    wrapped_srt: Path | None = None
    wrapped_path = subs_dir / "transcript_wrapped.srt"
    transcript_json = subs_dir / "transcript.json"
    if args.skip_wrap and wrapped_path.exists():
        wrapped_srt = wrapped_path
        print(f"[wrap] skipped (using existing {wrapped_path.name})")
    elif transcript_json.exists() and args.max_chars > 0:
        wrapped_srt = write_wrapped_srt(transcript_json, wrapped_path, args.max_chars)

    if not args.skip_cut:
        mode = "stream-copy (fast)" if args.fast_cut else "re-encode (accurate)"
        print(f"[4/5] cutting scenes [{mode}] → {scenes_dir}")
        manifest = cut_scenes(src, scenes, scenes_dir, accurate=not args.fast_cut)
        (tmp_dir / "scene_files.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    else:
        print("[4/5] cut skipped")
        manifest = json.loads((tmp_dir / "scene_files.json").read_text(encoding="utf-8"))

    if not args.skip_draft:
        print(f"[5/5] CapCut draft '{name}'")
        draft = build_draft(
            name, info["width"], info["height"], args.fps, manifest,
            wrapped_srt or srt_path,
            font_size=args.font_size,
            sub_y=args.sub_y,
            stroke_ui=args.stroke,
            font_path=args.font_path,
            font_title=args.font_title,
            sub_offset_ms=args.sub_offset_ms,
            sub_max_duration_ms=args.sub_max_duration_ms,
        )
        print(f"      → {draft}")
    else:
        print("[5/5] draft skipped")

    # Auto B-roll: scene_designer context 생성
    context_path: Path | None = None
    if args.auto_broll:
        print(f"\n[auto-broll] scene_designer context 생성")
        transcript_json_path = subs_dir / "transcript.json"
        scenes_json_path = tmp_dir / "scenes.json"
        context_path = tmp_dir / "broll_designer_context.md"

        if not transcript_json_path.exists():
            print(f"  [warn] {transcript_json_path} 없음 — STT 먼저 실행 필요")
        elif not scenes_json_path.exists():
            print(f"  [warn] {scenes_json_path} 없음")
        else:
            import subprocess
            result = subprocess.run([
                sys.executable,
                str(PROJECT_ROOT / "tools" / "capcut_pipeline" / "scene_designer.py"),
                "context",
                "--transcript", str(transcript_json_path),
                "--scenes", str(scenes_json_path),
                "--out", str(context_path),
                "--title", args.title,
            ], capture_output=True, text=True, encoding="utf-8")
            if result.returncode == 0:
                print(f"  {result.stdout.strip()}")
            else:
                print(f"  [error] {result.stderr}")
                context_path = None

    print("\n[done]")
    print(f"  output : {out_dir}")
    print(f"  draft  : {CAPCUT_ROOT / name}")

    # Auto B-roll 안내
    if args.auto_broll and context_path and context_path.exists():
        claude_plan_path = tmp_dir / "_claude_broll_plan.json"
        broll_plan_path = tmp_dir / "broll_plan.json"
        broll_images_dir = out_dir / "broll_gemini"
        draft_path = CAPCUT_ROOT / name / "draft_content.json"
        print(f"\n[next: auto-broll 워크플로우]")
        print(f"  1. Claude Code에서 context 읽고 plan 작성:")
        print(f"     {context_path}")
        print(f"     → {claude_plan_path}")
        print(f"  2. ingest + 이미지 생성 + 패치:")
        print(f"     python tools/capcut_pipeline/scene_designer.py ingest \\")
        print(f"       --input \"{claude_plan_path}\" \\")
        print(f"       --scenes \"{tmp_dir / 'scenes.json'}\" \\")
        print(f"       --out \"{broll_plan_path}\"")
        print(f"     python tools/capcut_pipeline/scene_designer.py generate-images \\")
        print(f"       --plan \"{broll_plan_path}\" \\")
        print(f"       --out-dir \"{broll_images_dir}\"")
        print(f"     python tools/capcut_pipeline/overlay_patcher.py \\")
        print(f"       --draft \"{draft_path}\" \\")
        print(f"       --plan  \"{broll_plan_path}\"")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
