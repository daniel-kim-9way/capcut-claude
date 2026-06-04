"""ElevenLabs Scribe v1 STT → faster-whisper-compatible transcript.{srt,json}.

ElevenLabs Scribe returns a flat word stream (word / spacing / audio_event).
Downstream tooling (run_pipeline.wrap_segments, scene_designer, plan_generator)
expects faster-whisper's shape: `{"language": "ko", "segments": [{idx, start, end,
text, words: [{start, end, word}]}]}`. This module adapts Scribe into that shape
by grouping consecutive word tokens whenever the inter-word gap exceeds a
threshold (default 0.7s) — roughly matching Whisper's VAD-driven segmentation.

API: https://api.elevenlabs.io/v1/speech-to-text  (multipart POST)
Docs: https://elevenlabs.io/docs/api-reference/speech-to-text

Env: ELEVENLABS_API_KEY must be set (loaded from .env).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import requests

# --- paths ---------------------------------------------------------------
PROJECT_ROOT = Path(os.environ.get("CAPCUT_PROJECT_ROOT") or Path(__file__).resolve().parents[2])
_FFMPEG_BIN = os.environ.get("CAPCUT_FFMPEG_BIN")
if _FFMPEG_BIN:
    FFBIN = Path(_FFMPEG_BIN)
    FFMPEG = str(FFBIN / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg"))
else:
    FFMPEG = "ffmpeg"

SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"
# Scribe hard limit is ~1GB / ~8h. We extract a compact mono m4a first.
DEFAULT_MODEL_ID = "scribe_v1"
# Gap between word end[i] and word start[i+1] above which we start a new segment.
# Whisper's VAD uses ~500ms silence; 0.7s gives slightly chunkier segments
# which map 1:1 onto sentence boundaries for Korean narration.
SEGMENT_GAP_SEC = 0.7


# --- helpers -------------------------------------------------------------

def _load_env() -> str:
    """Read ELEVENLABS_API_KEY from environment or .env file."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if key:
        return key
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ELEVENLABS_API_KEY="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError("ELEVENLABS_API_KEY not set (env or .env)")


def _fmt_ts(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = int(t % 60)
    ms = int((t - int(t)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _extract_audio(src: Path, out_path: Path) -> Path:
    """Extract compact mono AAC audio for Scribe upload.

    Scribe accepts video directly but uploading raw mp4 wastes bandwidth.
    16 kHz mono 64 kbps is ample for STT and shrinks 1h/200MB → ~30MB.
    """
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(src),
        "-vn",                 # drop video
        "-ac", "1",            # mono
        "-ar", "16000",        # 16 kHz
        "-c:a", "aac",
        "-b:a", "64k",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)
    return out_path


def _call_scribe(audio_path: Path, api_key: str, language_code: str = "kor") -> dict:
    """POST audio to ElevenLabs Scribe. Returns the raw JSON response."""
    with audio_path.open("rb") as f:
        files = {"file": (audio_path.name, f, "audio/mp4")}
        data = {
            "model_id": DEFAULT_MODEL_ID,
            "language_code": language_code,
            # ask for word-level timestamps (default, made explicit)
            "timestamps_granularity": "word",
            "tag_audio_events": "false",
            "diarize": "false",
        }
        headers = {"xi-api-key": api_key}
        # Scribe is fast but large files can take ~0.5x real-time; generous timeout.
        r = requests.post(SCRIBE_URL, files=files, data=data, headers=headers, timeout=1800)
    if r.status_code != 200:
        raise RuntimeError(f"Scribe API {r.status_code}: {r.text[:500]}")
    return r.json()


def _words_to_segments(words: list[dict], gap: float = SEGMENT_GAP_SEC) -> list[dict]:
    """Group Scribe word tokens into Whisper-style segments.

    Scribe's `words` is a flat mixed list: `{type: word|spacing|audio_event,
    text, start, end, ...}`. We keep only `type == "word"` and start a new
    segment whenever the gap from the previous word's end exceeds `gap`.
    """
    clean = [w for w in words if w.get("type") == "word" and w.get("text")]
    if not clean:
        return []

    groups: list[list[dict]] = [[clean[0]]]
    for prev, cur in zip(clean, clean[1:]):
        if (cur.get("start", 0.0) - prev.get("end", 0.0)) > gap:
            groups.append([cur])
        else:
            groups[-1].append(cur)

    out: list[dict] = []
    for idx, grp in enumerate(groups, 1):
        # Join with spaces; matches faster-whisper's behaviour of space-separated text.
        text = " ".join(w["text"].strip() for w in grp).strip()
        out.append({
            "idx": idx,
            "start": round(grp[0]["start"], 3),
            "end": round(grp[-1]["end"], 3),
            "text": text,
            "words": [
                {
                    "start": round(w["start"], 3),
                    "end": round(w["end"], 3),
                    # Whisper uses key "word" (with possible leading space);
                    # we strip and let downstream re-add separators.
                    "word": w["text"].strip(),
                }
                for w in grp
            ],
        })
    return out


def _write_outputs(segments: list[dict], language: str, subs_dir: Path) -> Path:
    srt_lines: list[str] = []
    for seg in segments:
        srt_lines.append(str(seg["idx"]))
        srt_lines.append(f"{_fmt_ts(seg['start'])} --> {_fmt_ts(seg['end'])}")
        srt_lines.append(seg["text"])
        srt_lines.append("")
    srt_path = subs_dir / "transcript.srt"
    srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
    (subs_dir / "transcript.json").write_text(
        json.dumps({"language": language, "segments": segments}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return srt_path


# --- public entry --------------------------------------------------------

def run_stt_elevenlabs(src: Path, subs_dir: Path, *, language_code: str = "kor",
                       keep_audio: bool = False) -> Path:
    """Drop-in replacement for run_pipeline.run_stt().

    Extracts audio, hits Scribe, writes transcript.{srt,json} matching the
    faster-whisper schema so downstream wrap/scene_designer/plan_generator
    work unchanged.
    """
    api_key = _load_env()
    subs_dir.mkdir(parents=True, exist_ok=True)

    audio_path = subs_dir / "_elevenlabs_upload.m4a"
    print(f"[stt:elevenlabs] extracting audio → {audio_path.name}")
    _extract_audio(src, audio_path)
    size_mb = audio_path.stat().st_size / 1024 / 1024
    print(f"[stt:elevenlabs] audio ready: {size_mb:.1f}MB, uploading to Scribe…")

    try:
        resp = _call_scribe(audio_path, api_key, language_code=language_code)
    finally:
        if not keep_audio and audio_path.exists():
            audio_path.unlink()

    raw_words = resp.get("words") or []
    language = resp.get("language_code") or "ko"
    prob = resp.get("language_probability")
    print(f"[stt:elevenlabs] language={language} prob={prob} words={len(raw_words)}")

    segments = _words_to_segments(raw_words)
    if not segments:
        raise RuntimeError("Scribe returned no word-level tokens (check audio / language_code)")

    srt_path = _write_outputs(segments, language, subs_dir)
    print(f"[stt:elevenlabs] wrote {len(segments)} segments → {srt_path}")
    return srt_path


# --- standalone CLI (A/B testing) ---------------------------------------

def main() -> int:
    import argparse
    p = argparse.ArgumentParser(description="ElevenLabs Scribe STT standalone runner")
    p.add_argument("video", type=Path)
    p.add_argument("--out", type=Path, required=True, help="subs/ output directory")
    p.add_argument("--lang", default="kor", help="ISO-639-3 code (default: kor)")
    p.add_argument("--keep-audio", action="store_true", help="retain extracted m4a for debugging")
    args = p.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")

    run_stt_elevenlabs(args.video.resolve(), args.out.resolve(),
                       language_code=args.lang, keep_audio=args.keep_audio)
    return 0


if __name__ == "__main__":
    sys.exit(main())
