"""
Automated 3-persona B-roll plan reviewer.

Runs BEFORE image generation to enforce reproducible quality across projects.

Personas (defined in templates/persona_reviewers.json):
  1. gen_z_student   — 20대 트렌디 대학생 (인스타/틱톡 관점)
  2. office_worker   — 30대 직장인 (실용성/명확성 관점)
  3. sns_expert      — 40대 SNS 전문가 (마케팅 전문성/매칭 관점)

PASS 기준:
  - 각 페르소나 overall >= 4.0 (5점 만점)
  - 각 페르소나 rejects 배열 빈 상태 (critical issue 없음)
  - aggregate(3인 평균 overall) >= 4.0

Exit codes:
  0  PASS
  2  REJECT
  3  input/config error (e.g. missing files)

Mode:
  Option 1 (default): Anthropic SDK가 설치되고 ANTHROPIC_API_KEY 있음 → 각 페르소나 1회 API call
  Option 2 (fallback): --emit-review-prompts / 위 조건 미충족 시 prompt 파일 3개 출력해서
                        외부 오케스트레이터(Claude Code)가 Agent로 직접 돌리게 함.

CLI:
  PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/broll_reviewer.py \\
    --plan temp/<name>/_claude_broll_plan.json \\
    --transcript output/<name>/subs/transcript.json \\
    --scenes temp/<name>/scenes.json \\
    --out temp/<name>/broll_review.json

  # Force fallback mode:
  ... --emit-review-prompts
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# ----- config -----

HERE = Path(__file__).resolve().parent
PERSONAS_JSON = HERE / "templates" / "persona_reviewers.json"
MODEL = "claude-opus-4-6"
MAX_TOKENS = 2000
PASS_OVERALL = 4.0
PASS_AGGREGATE = 4.0
VISUAL_ONLY_VALUE_MIN = 4  # if any persona gives this score < 4 → reject

# ----- pre-filter patterns (deterministic, no LLM) -----

# src_hint patterns that indicate "pure text stack" or "emphasis-equivalent"
# content — these fail "visual info only" rule regardless of persona opinion.
_BANNED_SRC_HINT_PATTERNS = [
    # Pure vertical word stack (the old split_stack template signature)
    re.compile(r'[Kk]orean\s+words?\s+vertically\s+stacked'),
    re.compile(r'[Vv]ertical\s+stack\s+of\s+\d*\s*[Kk]orean'),
    # Typography-only "two numbers stacked" when it's actually a single-value
    # emphasis wrapped in number_hero language
    re.compile(r'[Kk]orean\s+number\s+[\'\"][^\'"]+[\'\"]\s+centered'),
    # Literal typography-only poster (single word on black, heavy weight)
    re.compile(r'[Ss]ingle\s+[Kk]orean\s+word.*on\s+(?:pure\s+)?black.*(?:ExtraBold|Bold)'),
    # Editorial poster layout with multiple Korean items + ExtraBold on black
    # (catches the split_stack editorial variant src_hint)
    re.compile(r'[Ee]ditorial\s+magazine\s+poster.*[Kk]orean\s+(?:items|words)'),
]

# ----- helpers -----

def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _scene_narration(scenes: list[dict], segments: list[dict]) -> dict[int, str]:
    """Map scene_idx → narration text (from word-level transcript)."""
    out: dict[int, str] = {}
    for sc in scenes:
        s_start, s_end = sc["start"], sc["end"]
        words: list[str] = []
        for seg in segments:
            if seg["end"] < s_start or seg["start"] > s_end:
                continue
            for w in seg.get("words", []):
                if w["start"] >= s_start and w["end"] <= s_end:
                    words.append(w["word"].strip())
        out[sc["idx"]] = " ".join(words).strip() or "(무음)"
    return out


def _summarize_plan(plan: dict, scenes: list[dict], narr: dict[int, str]) -> str:
    """Build a compact human-readable summary of the plan scene-by-scene."""
    lines: list[str] = []
    title = plan.get("title", {})
    if title:
        lines.append(f"# TITLE: \"{title.get('text','')}\" "
                     f"accent={title.get('accent_words',[])} "
                     f"duration={title.get('duration_sec',4.0)}s")
        lines.append("")

    plan_scenes = {s["scene_idx"]: s for s in plan.get("scenes", [])}

    lines.append("# SCENE-BY-SCENE PLAN")
    lines.append("")
    for sc in scenes:
        idx = sc["idx"]
        n = narr.get(idx, "")
        ps = plan_scenes.get(idx)
        if not ps:
            lines.append(f"[{idx:02d}] {sc['start']:.1f}-{sc['end']:.1f}s  "
                         f"narration=\"{n}\"  decision=UNSPECIFIED")
            continue
        decision = ps.get("decision", "?")
        head = f"[{idx:02d}] {sc['start']:.1f}-{sc['end']:.1f}s  " \
               f"narration=\"{n}\"  decision={decision}"
        lines.append(head)
        if decision == "skip":
            if ps.get("reason"):
                lines.append(f"     reason: {ps['reason']}")
        elif decision == "text_only":
            if ps.get("reason"):
                lines.append(f"     reason: {ps['reason']}")
            emp = ps.get("emphasis") or {}
            if emp:
                lines.append(f"     emphasis: \"{emp.get('text','')}\" "
                             f"accent={emp.get('accent_words',[])}")
        elif decision == "dual":
            for i, b in enumerate(ps.get("brolls", []), 1):
                hint = b.get("src_hint", "")
                lines.append(f"     broll{i} type={b.get('type','?')}: {hint[:200]}")
        else:
            b = ps.get("broll", {}) or {}
            hint = b.get("src_hint", "")
            lines.append(f"     broll type={b.get('type','?')}: {hint[:260]}")
            emp = ps.get("emphasis")
            if emp:
                lines.append(f"     emphasis: \"{emp.get('text','')}\" "
                             f"accent={emp.get('accent_words',[])}")
    return "\n".join(lines)


# ----- prompt construction -----

def _build_user_prompt(persona_key: str, persona: dict, plan_summary: str) -> str:
    dims = persona["scoring_dims"]
    dim_block = "\n".join(
        f"  - `{d['key']}`: {d['question']} (0-5 integer)" for d in dims
    )
    example_scores = {d["key"]: 4 for d in dims}
    example_scores["overall"] = 4.0
    example = {
        "scores": example_scores,
        "comments": [
            "scene 10 stat_card feels editorial, works",
            "scene 16 split_stack: good, avoids waste"
        ],
        "rejects": [
            "scene X: forced desk+notepad setup — violates no_forced_setup rule"
        ],
    }
    return (
        f"아래는 CapCut B-roll 자동 설계 시스템이 만든 plan입니다. "
        f"당신의 페르소나 관점에서 엄격히 평가하고 반드시 JSON만 반환하세요.\n\n"
        f"## 평가 차원 (각 0-5 정수)\n{dim_block}\n"
        f"  - `overall`: 차원 평균 소수 1자리 (float)\n\n"
        f"## 철칙\n"
        f"- B-roll 이미지는 emphasis 텍스트로 전달 불가능한 시각 정보일 때만 생성.\n"
        f"- 단일 숫자 강조는 emphasis만으로 충분 — B-roll 불필요.\n"
        f"- 실사 사진 setup(책상/메모장/펜) 금지.\n"
        f"- 깔끔한 그래픽·타이포·실제 스크린샷·아이콘만 허용.\n"
        f"- 위 철칙을 위반한 scene은 `rejects` 배열에 `\"scene N: 이유\"` 형식으로 기록.\n\n"
        f"## comments\n"
        f"- 각 페르소나 관점으로 구체적인 인상을 2-6개. 모호한 'good/bad' 금지.\n\n"
        f"## 출력 스키마 (다른 텍스트 금지)\n"
        f"```json\n{json.dumps(example, ensure_ascii=False, indent=2)}\n```\n\n"
        f"## 검토 대상\n```\n{plan_summary}\n```\n"
    )


def _parse_json_from_text(text: str) -> dict:
    """Strip markdown fences and parse JSON. Raises on failure."""
    t = text.strip()
    # Markdown fence strip
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", t, re.DOTALL)
    if m:
        t = m.group(1)
    else:
        # Fallback: extract first balanced {...}
        start = t.find("{")
        end = t.rfind("}")
        if start != -1 and end != -1 and end > start:
            t = t[start:end + 1]
    return json.loads(t)


def _validate_persona_output(persona: dict, data: dict) -> dict:
    """Ensure scores has all expected dims + overall, coerce types, clamp."""
    dims = [d["key"] for d in persona["scoring_dims"]]
    scores = data.get("scores", {}) or {}
    clean: dict[str, Any] = {}
    for k in dims:
        v = scores.get(k)
        if v is None:
            raise ValueError(f"missing score dim: {k}")
        clean[k] = max(0, min(5, int(v)))
    # overall: compute if missing
    if "overall" in scores and scores["overall"] is not None:
        clean["overall"] = round(float(scores["overall"]), 2)
    else:
        clean["overall"] = round(sum(clean[k] for k in dims) / len(dims), 2)

    comments = data.get("comments") or []
    if not isinstance(comments, list):
        comments = [str(comments)]
    rejects = data.get("rejects") or []
    if not isinstance(rejects, list):
        rejects = [str(rejects)]
    return {**clean, "comments": [str(c) for c in comments],
            "rejects": [str(r) for r in rejects]}


# ----- SDK path (Option 1) -----

def _try_load_env() -> None:
    """Load .env from project root if python-dotenv is available."""
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    # Walk up to find .env (project root has it)
    for parent in [HERE, *HERE.parents]:
        env_path = parent / ".env"
        if env_path.exists():
            load_dotenv(env_path)
            return


def _call_persona_via_sdk(persona_key: str, persona: dict,
                          plan_summary: str) -> dict:
    import anthropic  # type: ignore
    client = anthropic.Anthropic()
    user_prompt = _build_user_prompt(persona_key, persona, plan_summary)
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=persona["system_prompt"],
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = resp.content[0].text
    raw = _parse_json_from_text(text)
    return _validate_persona_output(persona, raw)


# ----- fallback path (Option 2) -----

def _emit_prompt_files(personas: dict, plan_summary: str, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for key, persona in personas.items():
        user = _build_user_prompt(key, persona, plan_summary)
        p = out_dir / f"review_prompt_{key}.md"
        p.write_text(
            f"# Persona: {persona['label']} (`{key}`)\n\n"
            f"## SYSTEM\n```\n{persona['system_prompt']}\n```\n\n"
            f"## USER\n{user}\n",
            encoding="utf-8",
        )
        paths.append(p)
    return paths


# ----- pre-filter (deterministic) -----

def _pre_filter_plan(plan: dict) -> list[str]:
    """Scan plan for hard rule violations that don't need LLM judgment.
    Returns a list of critical issues (empty → pre-filter passes).
    """
    issues: list[str] = []
    for sc in plan.get("scenes", []):
        sidx = sc.get("scene_idx", "?")
        decision = sc.get("decision", "")
        if decision not in ("overlay", "dual"):
            continue

        brolls = []
        if decision == "dual":
            brolls = sc.get("brolls", []) or []
        else:
            b = sc.get("broll")
            if b:
                brolls = [b]

        for b in brolls:
            t = b.get("type", "")
            hint = b.get("src_hint", "") or ""

            # Rule 1: split_stack type is deprecated
            if t == "split_stack":
                issues.append(
                    f"scene {sidx}: split_stack 타입 폐기됨 (2026-04-21) — "
                    f"단어 세로 스택은 emphasis 순차로 대체해야 함"
                )
                continue

            # Rule 2: src_hint describes pure text stack / emphasis-equivalent
            for pat in _BANNED_SRC_HINT_PATTERNS:
                if pat.search(hint):
                    issues.append(
                        f"scene {sidx}: src_hint가 순수 텍스트 나열 묘사 — "
                        f"emphasis로 대체 가능 (pattern: {pat.pattern[:40]}...)"
                    )
                    break

    return issues


# ----- aggregation / verdict -----

def _aggregate(persona_scores: dict[str, dict]) -> tuple[bool, float, list[str]]:
    overalls = [p["overall"] for p in persona_scores.values()]
    aggregate = round(sum(overalls) / len(overalls), 2) if overalls else 0.0

    critical: list[str] = []
    visual_only_value_fail = False
    for key, p in persona_scores.items():
        if p["overall"] < PASS_OVERALL:
            critical.append(f"{key}: overall {p['overall']:.1f} < {PASS_OVERALL}")
        # visual_only_value is the most important rule — if any persona scored
        # it below threshold, the plan fails regardless of overall.
        vov = p.get("visual_only_value")
        if vov is not None and vov < VISUAL_ONLY_VALUE_MIN:
            visual_only_value_fail = True
            critical.append(
                f"{key}: visual_only_value {vov} < {VISUAL_ONLY_VALUE_MIN} "
                f"(text로 대체 가능한 이미지 존재)"
            )
        for rej in p["rejects"]:
            critical.append(f"{key}: {rej}")

    passed = (
        aggregate >= PASS_AGGREGATE
        and all(p["overall"] >= PASS_OVERALL for p in persona_scores.values())
        and all(not p["rejects"] for p in persona_scores.values())
        and not visual_only_value_fail
    )
    return passed, aggregate, critical


def _collect_suggestions(persona_scores: dict[str, dict]) -> list[str]:
    out: list[str] = []
    for key, p in persona_scores.items():
        for c in p.get("comments", []):
            if any(kw in c.lower() for kw in ("should", "change", "변경", "제거", "추가", "권고")):
                out.append(f"{key}: {c}")
    return out


# ----- main -----

def main() -> int:
    ap = argparse.ArgumentParser(description="3-persona B-roll plan reviewer")
    ap.add_argument("--plan", required=True, type=Path)
    ap.add_argument("--transcript", required=True, type=Path)
    ap.add_argument("--scenes", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--emit-review-prompts", action="store_true",
                    help="Skip SDK; emit 3 prompt .md files for orchestrator to run.")
    ap.add_argument("--personas", type=Path, default=PERSONAS_JSON)
    args = ap.parse_args()

    for p in (args.plan, args.transcript, args.scenes, args.personas):
        if not p.exists():
            print(f"[ERROR] missing file: {p}", file=sys.stderr)
            return 3

    plan = _load_json(args.plan)
    transcript = _load_json(args.transcript)
    scenes_data = _load_json(args.scenes)
    personas_cfg = _load_json(args.personas)
    personas: dict[str, dict] = personas_cfg.get("personas", {})
    if not personas:
        print("[ERROR] no personas in config", file=sys.stderr)
        return 3

    scenes = scenes_data.get("scenes", [])
    narr = _scene_narration(scenes, transcript.get("segments", []))
    plan_summary = _summarize_plan(plan, scenes, narr)

    # ----- Pre-filter: deterministic rule violations -----
    # Runs BEFORE any SDK/fallback — bails out early if plan has hard
    # violations (split_stack type, pure-text-stack src_hint, etc.).
    pre_issues = _pre_filter_plan(plan)
    if pre_issues:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({
            "plan_path": str(args.plan),
            "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
            "mode": "pre_filter",
            "pass": False,
            "aggregate_score": 0.0,
            "persona_scores": {},
            "critical_issues": pre_issues,
            "suggestions": [
                "plan_generator.py를 최신 버전으로 재생성하세요 "
                "(split_stack 제거, 텍스트 스택 → text_only)."
            ],
            "thresholds": {
                "per_persona_overall": PASS_OVERALL,
                "aggregate": PASS_AGGREGATE,
                "visual_only_value_min": VISUAL_ONLY_VALUE_MIN,
            },
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print("[pre_filter] REJECT — hard rule violations detected:",
              file=sys.stderr)
        for issue in pre_issues:
            print(f"  - {issue}", file=sys.stderr)
        print(f"[pre_filter] wrote {args.out}", file=sys.stderr)
        return 2

    # Decide mode
    _try_load_env()
    has_sdk = False
    try:
        import anthropic  # noqa: F401
        has_sdk = True
    except Exception:
        has_sdk = False
    has_key = bool(os.getenv("ANTHROPIC_API_KEY"))

    use_sdk = has_sdk and has_key and not args.emit_review_prompts

    args.out.parent.mkdir(parents=True, exist_ok=True)

    if not use_sdk:
        reason = ("user requested --emit-review-prompts" if args.emit_review_prompts
                  else ("anthropic SDK not installed" if not has_sdk
                        else "ANTHROPIC_API_KEY not set in env/.env"))
        prompts_dir = args.out.parent / "broll_review_prompts"
        paths = _emit_prompt_files(personas, plan_summary, prompts_dir)
        # Write a placeholder review output so downstream knows to wait
        args.out.write_text(json.dumps({
            "plan_path": str(args.plan),
            "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
            "mode": "fallback_prompts",
            "reason": reason,
            "prompt_files": [str(p) for p in paths],
            "instruction": (
                "Spawn 3 Claude Code agents with these prompts, collect each "
                "persona's JSON, merge into broll_review.json scores manually, "
                "and re-run with --out or evaluate pass yourself."
            ),
            "pass": False,
            "aggregate_score": 0.0,
            "persona_scores": {},
            "critical_issues": [],
            "suggestions": [],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[fallback] SDK path unavailable: {reason}", file=sys.stderr)
        print(f"[fallback] wrote {len(paths)} prompt files to {prompts_dir}",
              file=sys.stderr)
        print(f"[fallback] placeholder review -> {args.out}", file=sys.stderr)
        return 2

    # Option 1: SDK call per persona
    print(f"[reviewer] model={MODEL} personas={list(personas.keys())}",
          file=sys.stderr)
    persona_scores: dict[str, dict] = {}
    for key, persona in personas.items():
        print(f"[reviewer] querying {key} ({persona['label']}) ...",
              file=sys.stderr)
        try:
            persona_scores[key] = _call_persona_via_sdk(key, persona, plan_summary)
        except Exception as e:
            print(f"[ERROR] {key} review failed: {e}", file=sys.stderr)
            return 3

    passed, aggregate, critical = _aggregate(persona_scores)
    suggestions = _collect_suggestions(persona_scores)

    result = {
        "plan_path": str(args.plan),
        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        "mode": "sdk",
        "model": MODEL,
        "persona_scores": persona_scores,
        "pass": passed,
        "aggregate_score": aggregate,
        "critical_issues": critical,
        "suggestions": suggestions,
        "thresholds": {
            "per_persona_overall": PASS_OVERALL,
            "aggregate": PASS_AGGREGATE,
            "visual_only_value_min": VISUAL_ONLY_VALUE_MIN,
        },
    }
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # Console summary
    print("\n" + "=" * 60)
    print(f" 3-Persona B-roll Review  (aggregate={aggregate:.2f})")
    print("=" * 60)
    for key, p in persona_scores.items():
        mark = "PASS" if p["overall"] >= PASS_OVERALL and not p["rejects"] else "FAIL"
        print(f"  [{mark}] {key:16s} overall={p['overall']:.2f}  "
              f"rejects={len(p['rejects'])}")
    if critical:
        print("\n  Critical issues:")
        for c in critical[:10]:
            print(f"   - {c}")
    verdict = "PASS" if passed else "REJECT"
    print(f"\n  Verdict: {verdict}")
    print(f"  Written: {args.out}")
    print("=" * 60)

    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
