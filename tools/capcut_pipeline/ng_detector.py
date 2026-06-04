"""NG/묵음/retake 감지 — word-level dry-run.

Claude Code(LLM)가 transcript의 word-level timing을 보고 keep_intervals.json
(어떤 시간 범위를 살릴지)을 직접 판단할 수 있게 context를 준비하고, 그 결과물을
검증/리포트한다.

설계 원칙 (사용자 합의):
    - silencedetect 씬 분할을 버리고 LLM이 transcript 직접 본다.
    - 문장 단위(Scribe '.', '?', '!' + silence > 0.5s)로 utterance grouping.
    - Retake pair 분류: "drop earlier, keep later" — 같은 발화 반복 시 앞 take(NG)를 drop.
    - 어미 보존(+400ms), audio crossfade(50ms), transcript timeline shift는
      ng_cutter.py가 자동 처리. LLM은 raw word boundary만 결정.

Subcommands:
    analyze  — transcript.json → temp/<name>/ng_context.md
               (utterance 표 + 판단 rubric + 출력 스키마)
    report   — temp/<name>/keep_intervals.json 검증 + ng_plan_review.md 생성

Usage:
    PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/ng_detector.py \\
        analyze --name <영상명>
    # Claude가 ng_context.md 읽고 keep_intervals.json Write
    PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/ng_detector.py \\
        report  --name <영상명>
    PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/ng_cutter.py \\
        --source <원본.mp4> --name <영상명>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(os.environ.get("CAPCUT_PROJECT_ROOT") or Path(__file__).resolve().parents[2])
SENTENCE_END_PUNCT = (".", "?", "!")
UTTERANCE_GAP_SEC = 0.5  # gap > this between words → new utterance

# --- paths ---------------------------------------------------------------

def _paths(name: str) -> dict[str, Path]:
    return {
        "transcript_src": PROJECT_ROOT / "temp"   / name / "scribe_raw" / "transcript.json",
        "transcript_pipe": PROJECT_ROOT / "output" / name / "subs" / "transcript.json",
        "context": PROJECT_ROOT / "temp"   / name / "ng_context.md",
        "plan":    PROJECT_ROOT / "temp"   / name / "keep_intervals.json",
        "review":  PROJECT_ROOT / "temp"   / name / "ng_plan_review.md",
    }


def _read_transcript(p: dict[str, Path]) -> dict:
    """Prefer scribe_raw/transcript.json (untouched source timeline) over
    output/<name>/subs/transcript.json (may be already shifted).
    """
    if p["transcript_src"].exists():
        return json.loads(p["transcript_src"].read_text(encoding="utf-8"))
    return json.loads(p["transcript_pipe"].read_text(encoding="utf-8"))


def _flat_words(transcript: dict) -> list[tuple[float, float, str]]:
    out = []
    for s in transcript.get("segments", []):
        for w in s.get("words", []):
            t = (w.get("word") or "").strip()
            if t:
                out.append((float(w["start"]), float(w["end"]), t))
    return sorted(out, key=lambda x: x[0])


def _group_utterances(words: list[tuple[float, float, str]]) -> list[list[tuple[float, float, str]]]:
    """Sentence-level utterance grouping: split on punctuation OR silence > UTTERANCE_GAP_SEC."""
    if not words:
        return []
    groups: list[list] = [[words[0]]]
    for i in range(1, len(words)):
        prev_text = words[i-1][2]
        gap = words[i][0] - words[i-1][1]
        if prev_text.endswith(SENTENCE_END_PUNCT) or gap > UTTERANCE_GAP_SEC:
            groups.append([])
        groups[-1].append(words[i])
    return [g for g in groups if g]


# --- retake hint detection ----------------------------------------------

def _norm(text: str) -> list[str]:
    """Normalize text for similarity: strip punct + whitespace."""
    cleaned = re.sub(r"[.,!?…]", "", text)
    return [t for t in cleaned.split() if t]


def _detect_retake_hints(utts: list[list[tuple[float, float, str]]]) -> dict[int, str]:
    """For each utterance, detect if a LATER utterance starts with same N words.

    Returns idx → hint string (e.g. "→ retake of by utt 6 (5/8 word match)").
    Only flags pairs where ≥3 leading words match — strong retake signal.
    """
    hints: dict[int, str] = {}
    norms = []
    for utt in utts:
        text = " ".join(w[2] for w in utt)
        norms.append(_norm(text))

    for i in range(len(utts)):
        for j in range(i+1, len(utts)):
            ni, nj = norms[i], norms[j]
            if not ni or not nj:
                continue
            # leading-word match
            match = 0
            for a, b in zip(ni, nj):
                if a == b:
                    match += 1
                else:
                    break
            if match >= 3:
                hints[i] = f"⚠ retake EARLIER of utt {j} (leading {match}-word match) → likely DROP"
                hints[j] = hints.get(j, f"✓ retake LATER of utt {i} → likely KEEP")
                break
    return hints


# --- analyze -------------------------------------------------------------

RUBRIC = """\
## 판단 규칙 (LLM 적용)

### 핵심 규칙: drop_earlier_retake_keep_later

화자가 같은 내용을 두 번 이상 말하면(retake), **앞 take = NG로 drop**, 뒤 take 유지.
의심스러우면 keep — False Positive(좋은 take drop) 금지.

### Drop 카테고리

1. **retake** — 앞 utterance와 같은 시작/내용. 뒤 take가 더 polished.
2. **silence** — utterance 사이 긴 silence는 keep_intervals 사이 자연스럽게 비워짐 (drop 아님).
3. **filler** — 단독 발화 "어/음/그/아", 1-2 단어.
4. **incomplete** — 문장 중간에 끊긴 미완성 발화 ("...같은", "그런데...")로 끝남.
5. **noise** — `(괄호)` 표기 audio_event ("(문 여는 소리)" 등).
6. **frustration** — "아 미치겠다", "왜 이렇게", "하." 등 화자 좌절/사과 발화.

### Keep 조건 (의심 시 keep)

- 완결된 문장 (마침표·물음표·감탄부호로 끝남)
- 키 메시지 / CTA / 핵심 인용
- 강조 단독 발화 (의도된 짧은 문장)
- 다른 utterance와 텍스트 겹침 없음

### 출력 스키마 (temp/<name>/keep_intervals.json)

```json
{
  "version": 6,
  "name": "<영상명>",
  "source_duration_sec": 262.39,
  "stt_engine": "elevenlabs_scribe_v1",
  "rule": "drop_earlier_retake_keep_later",
  "keep_intervals": [
    {
      "start": 5.20,
      "end": 11.34,
      "text": "이메일 보냈는데 왜 답장이 없지? ...",
      "reason": "opening hook + explanation"
    }
  ]
}
```

### 자동 처리 (LLM이 신경 쓸 필요 없음)

`ng_cutter.py`가 keep_intervals를 받아 자동으로:
- **각 end +400ms 연장** (Scribe word_end가 한국어 어미 vowel decay 직전 끝남)
- **다음 NG와 50ms safety margin** 자동 cap
- **각 cut clip 50ms audio fade-in/out** (boundary click 제거)
- **transcript timeline shift** (clean 좌표계로 + per-interval segment split)
- **scenes/scene_XX.mp4 재인코딩** (frame-accurate, audio 192kbps)

→ LLM은 **raw Scribe word_start/word_end**만 keep_intervals에 담는다. 어미 연장/breath buffer 수동 추가 금지.

### 작업 순서

1. 아래 utterance 표 정독.
2. retake hint(⚠/✓) 표시된 곳 우선 판단.
3. 의심 시 keep, 명확한 retake/filler/noise만 drop.
4. 연속 utterance를 하나의 keep_interval로 묶을 수 있다 (start = 첫 utt start, end = 마지막 utt end).
5. `keep_intervals.json` Write 후:
   `python tools/capcut_pipeline/ng_detector.py report --name <영상명>` 으로 검증.
"""


def cmd_analyze(args) -> int:
    p = _paths(args.name)
    transcript = _read_transcript(p)
    words = _flat_words(transcript)
    if not words:
        print("error: empty transcript", file=sys.stderr); return 1
    utts = _group_utterances(words)
    hints = _detect_retake_hints(utts)
    src_dur = words[-1][1] if words else 0.0

    lines = [
        f"# NG 판별 컨텍스트 (word-level) — {args.name}",
        "",
        f"- STT 엔진: ElevenLabs Scribe v1",
        f"- Source words: **{len(words)}**",
        f"- Utterances (sentence-level): **{len(utts)}**",
        f"- Source duration: ~{src_dur:.1f}s",
        f"- 출력 대상: `temp/{args.name}/keep_intervals.json`",
        "",
        RUBRIC.strip(),
        "",
        "## Utterance 표 (Claude가 판단 대상)",
        "",
        "| utt | [start-end] | 길이 | 단어 | 텍스트 | retake hint |",
        "|----:|:------------|-----:|-----:|:-------|:------------|",
    ]
    for i, u in enumerate(utts):
        s = u[0][0]
        e = u[-1][1]
        txt = " ".join(w[2] for w in u).replace("|", "\\|")
        if len(txt) > 90:
            txt = txt[:87] + "..."
        hint = hints.get(i, "").replace("|", "\\|")
        lines.append(
            f"| {i:2d} "
            f"| [{s:6.2f}-{e:6.2f}] "
            f"| {e-s:5.2f}s "
            f"| {len(u)} "
            f"| {txt} "
            f"| {hint} |"
        )

    lines.extend([
        "",
        "## 다음 단계",
        "",
        "1. 위 표 + retake hint 보고 `keep_intervals.json` Write.",
        f"2. `python tools/capcut_pipeline/ng_detector.py report --name {args.name}` 검증.",
        f"3. `python tools/capcut_pipeline/ng_cutter.py --source <원본.mp4> --name {args.name}` 컷 적용.",
    ])

    p["context"].parent.mkdir(parents=True, exist_ok=True)
    p["context"].write_text("\n".join(lines), encoding="utf-8")
    print(f"[ng-analyze] wrote {p['context']}")
    print(f"  utterances={len(utts)}  retake_hints={sum(1 for h in hints.values() if '⚠' in h)}")
    print(f"  next: Claude reads ng_context.md and writes keep_intervals.json")
    return 0


# --- report --------------------------------------------------------------

def _validate_plan(plan: dict, src_dur: float) -> list[str]:
    errs = []
    if plan.get("version") not in (1, 2, 3, 4, 5, 6):
        errs.append(f"unexpected version {plan.get('version')} (expected 6 for word-level)")
    intervals = plan.get("keep_intervals")
    if not isinstance(intervals, list) or not intervals:
        errs.append("keep_intervals must be non-empty list")
        return errs
    prev_end = -1.0
    for i, iv in enumerate(intervals):
        if "start" not in iv or "end" not in iv:
            errs.append(f"keep_intervals[{i}] missing start/end")
            continue
        if iv["end"] <= iv["start"]:
            errs.append(f"keep_intervals[{i}]: end {iv['end']} <= start {iv['start']}")
        if iv["start"] < prev_end:
            errs.append(f"keep_intervals[{i}]: start {iv['start']} < prev end {prev_end} (overlap)")
        if iv["end"] > src_dur + 1.0:
            errs.append(f"keep_intervals[{i}]: end {iv['end']} > source duration {src_dur:.1f}")
        prev_end = iv["end"]
    return errs


def cmd_report(args) -> int:
    p = _paths(args.name)
    if not p["plan"].exists():
        print(f"error: missing {p['plan']} — run analyze + Claude writes plan first", file=sys.stderr)
        return 1
    transcript = _read_transcript(p)
    words = _flat_words(transcript)
    src_dur = words[-1][1] if words else 0.0

    plan = json.loads(p["plan"].read_text(encoding="utf-8"))
    errs = _validate_plan(plan, src_dur)
    if errs:
        print("[ng-report] SCHEMA ERRORS:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 2

    intervals = plan["keep_intervals"]
    kept_dur = sum(iv["end"] - iv["start"] for iv in intervals)
    drop_dur = src_dur - kept_dur

    # build per-interval rows
    lines = [
        f"# Keep Intervals Review — {args.name}",
        "",
        "## 요약",
        "",
        f"- Source duration: **{src_dur:.1f}s**",
        f"- Kept intervals: **{len(intervals)}**",
        f"- Kept duration: **{kept_dur:.1f}s**",
        f"- Dropped duration: **{drop_dur:.1f}s** (−{drop_dur/src_dur*100:.1f}%)",
        f"- Rule: `{plan.get('rule', '?')}`",
        f"- STT engine: `{plan.get('stt_engine', '?')}`",
        "",
        "## Keep Intervals",
        "",
        "| # | [src start-end] | 길이 | 텍스트 | 사유 |",
        "|--:|:----------------|-----:|:-------|:-----|",
    ]
    for i, iv in enumerate(intervals):
        txt = (iv.get("text") or "").replace("|", "\\|")[:80]
        reason = (iv.get("reason") or "").replace("|", "\\|")
        lines.append(
            f"| {i} | [{iv['start']:6.2f}-{iv['end']:6.2f}] | {iv['end']-iv['start']:5.2f}s "
            f"| {txt} | {reason} |"
        )

    # sanity: highlight long gaps (likely retake clusters dropped)
    lines.extend(["", "## Drop 구간 (interval 사이)", "",
                  "| 시작 | 끝 | 길이 |", "|----:|---:|-----:|"])
    prev_end = 0.0
    for iv in intervals:
        gap = iv["start"] - prev_end
        if gap > 1.0:
            lines.append(f"| {prev_end:6.2f} | {iv['start']:6.2f} | {gap:5.2f}s |")
        prev_end = iv["end"]
    if src_dur - prev_end > 1.0:
        lines.append(f"| {prev_end:6.2f} | {src_dur:6.2f} | {src_dur-prev_end:5.2f}s |")

    lines.extend([
        "",
        "## 다음 단계",
        "",
        f"```bash",
        f"PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/ng_cutter.py \\",
        f"    --source <원본.mp4> --name {args.name}",
        f"```",
        "",
        "ng_cutter가 자동:",
        "- 각 end +400ms 어미 연장 (safety 50ms cap)",
        "- 50ms audio fade per clip",
        "- transcript timeline shift (per-interval segment split)",
        "- scenes/scene_XX.mp4 재인코딩",
    ])

    p["review"].write_text("\n".join(lines), encoding="utf-8")
    print(f"[ng-report] wrote {p['review']}")
    print(f"  intervals={len(intervals)}  kept={kept_dur:.1f}s  dropped={drop_dur:.1f}s "
          f"({drop_dur/src_dur*100:.1f}%)")
    return 0


# --- main ----------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", help="utterance 컨텍스트 + retake hint 생성")
    a.add_argument("--name", required=True)

    r = sub.add_parser("report", help="keep_intervals.json 검증 + review.md")
    r.add_argument("--name", required=True)

    args = p.parse_args()
    return {"analyze": cmd_analyze, "report": cmd_report}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
