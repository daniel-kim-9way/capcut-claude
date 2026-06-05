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

# ----- anti-cliché config (deterministic, runs even without SDK) -----
# 2026-06-04: 사용자 컴플레인 "맨날 똑같은 뻔한 b-roll" → 결정론 게이트 강화.
# 핵심: SDK 미설치 시 3-persona 리뷰는 placeholder로 빠지므로, 항상 도는
# _pre_filter_plan이 클리셰/중복/단조/영상간반복을 막아야 함.

# "스타일 입힌 글자 카드" = 화면 emphasis 자막과 정보량 중복. 기본 reject,
# broll.justification(비어있지 않은 문자열) + 영상당 최대 1개일 때만 허용.
_TEXT_CARD_TEMPLATES = {
    "text_hero_aurora_16x9", "text_hero_sparkles_1x1",
    "text_hero_aurora", "text_hero_sparkles",
}

# "실제 시각 정보"(UI/데이터/차트/관계도) 를 담은 템플릿 — 글자 카드 대비 변별력.
# overlay가 2개 이상인데 이 계열이 0개면 "검은 카드만" 단조 → reject.
# 2026-06-04 SI-03: device_mockup(실제 스크린샷 디바이스 목업) prefix 추가.
_SUBSTANCE_TEMPLATE_PREFIXES = (
    "ui_evidence_", "line_chart", "bar_chart", "metric_ring",
    "avatar_group", "animated_beam", "orbiting_circles", "logo_marquee",
    "device_mockup",
)

# 정적 ui_evidence(모션 없음)가 실제 화면 묘사를 담았는지 가르는 최소 길이.
# 빈/스텁 src_hint(내용 없는 카드)는 substance로 인정하지 않기 위한 결정론 임계.
# (키워드 화이트리스트 금지 — LLM 판단 영역 침범 회피. 길이만 본다.)
_SUBSTANCE_HINT_MIN_LEN = 30

# 영상 간 반복 방지 ledger — 최근 영상에서 쓴 템플릿 재사용 시 경고/감점.
_USAGE_LOG = HERE / ".broll_usage_log.json"
# 2026-06-04 SI-02: lookback 2→4 확대. 2는 너무 짧아 '맨날 똑같은'을 못 막음.
_USAGE_LOOKBACK = 4  # 최근 N개 영상과 겹치면 경고
# Rule 7 ratio 임계 — distinct template(또는 키)이 3개 이상일 때만 비율 적용.
# 과반(>=0.6)이 최근과 겹치면 단조로 판정. distinct<=2면 ratio 무의미하므로
# full-overlap + type 수렴 검사로 대체(아래 Rule 7 참고).
_USAGE_OVERLAP_RATIO = 0.6
# 같은 type(특히 ui_evidence_*)이 최근 N영상 연속 등장하면 cross-video 수렴.
# 6-type 분모가 작아 type 수렴이 단조를 가장 잘 잡음(SI-02 1순위 신호).
_TYPE_CONVERGENCE_RUN = 3
# aspect suffix 정규화용 — stat_card_16x9 vs stat_card_9x16를 동일 stem 취급.
_ASPECT_SUFFIX_RE = re.compile(r'_(?:16x9|9x16|1x1)$')


def _strip_aspect(stem: str) -> str:
    """템플릿/키 끝의 aspect suffix(_16x9/_9x16/_1x1)를 제거해 stem으로 정규화.

    2026-06-04 SI-02: aspect만 바뀐 동일 연출(stat_card_16x9 vs _9x16)을
    '새 template'으로 빠져나가지 못하게 비교 전 정규화한다.
    """
    if not stem:
        return ""
    return _ASPECT_SUFFIX_RE.sub("", stem)


def _is_substance_template(motion_template: str, btype: str,
                           src_hint: str = "") -> bool:
    """B-roll이 '실제 시각 정보'(UI/데이터/차트/관계도)를 담는지 판정.

    2026-06-04 SI-03: 기존 `type=="ui_evidence" → 무조건 True` 허점 제거.
    - 1순위: motion_template prefix (검증된 모션 계열, device_mockup 포함).
    - 정적 ui_evidence(모션 template 없음)는 src_hint에 실제 화면 묘사가
      있을 때만(len>=30) substance로 인정. 빈/스텁 카드는 substance 아님.
      (키워드 매칭 금지 — 길이 기반 결정론 게이트만.)
    """
    mt = motion_template or ""
    if mt.startswith(_SUBSTANCE_TEMPLATE_PREFIXES):
        return True
    # 정적 ui_evidence(모션 없이 Gemini PNG)는 실제 화면 묘사가 있을 때만 인정.
    if btype == "ui_evidence":
        hint = (src_hint or "").strip()
        return len(hint) >= _SUBSTANCE_HINT_MIN_LEN
    return False


def _load_usage_log() -> list[dict]:
    try:
        data = json.loads(_USAGE_LOG.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


# 2026-06-04 SI-02: deprecated(=no_sample_yet) 템플릿은 recent set에서 제외.
# (이미 폐기/미승인이라 cross-video 반복 판정에 넣으면 노이즈.)
_CATALOG_JSON = HERE.parent / "motion_graphics" / "sample_catalog.json"


def _deprecated_template_stems() -> set[str]:
    """sample_catalog.json의 deprecated/no_sample_yet stem 집합(aspect 정규화).

    best-effort: 카탈로그를 못 읽으면 빈 집합(=제외 안 함, 기존 동작 보존).
    """
    stems: set[str] = set()
    try:
        cat = json.loads(_CATALOG_JSON.read_text(encoding="utf-8"))
        for key in ("deprecated", "no_sample_yet"):
            for t in cat.get(key, []) or []:
                if t:
                    stems.add(_strip_aspect(str(t)))
    except Exception:
        return set()
    return stems


def _static_broll_key(broll: dict) -> str:
    """모션 template이 없는(정적) B-roll의 cross-video 비교 키.

    2026-06-04 SI-01: ledger를 motion만이 아니라 static/dual 전체로 확장.
    형식: "type:핵심명사" — 같은 type이라도 'claude_code 터미널' vs
    'Notion DB 화면'을 구별 가능하게 src_hint의 핵심 명사 1-2개를 정규화해 덧붙임.
    (전체 해시 금지 — 노이즈. SI-01 keep 권고 반영.)
    """
    t = (broll.get("type") or "static").strip().lower()
    hint = (broll.get("src_hint") or "").strip().lower()
    # 핵심 명사 추출: 영문/한글 토큰만, 너무 일반적인 어휘는 제거하지 않고
    # 단순히 처음 등장하는 식별성 있는 토큰 1-2개만 취함(결정론, 키워드 금지).
    toks = re.findall(r"[a-z0-9가-힣]+", hint)
    toks = [w for w in toks if len(w) >= 2][:2]
    suffix = "_".join(toks)
    return f"{t}:{suffix}" if suffix else t


def _recent_keys(lookback: int = _USAGE_LOOKBACK) -> dict[str, Any]:
    """최근 lookback개 영상의 사용 키를 종류별로 수집.

    2026-06-04 SI-01/SI-02:
      - templates: motion_template stem 집합(aspect 정규화, deprecated 제외).
      - static_keys: 정적/dual B-roll의 'type:핵심명사' 키 집합.
      - type_runs: 영상별 사용 type 집합 리스트(최신순 X, 로그 순서) —
        type 연속 수렴 검사(_TYPE_CONVERGENCE_RUN)에 사용.

    하위호환: 과거 ledger 엔트리는 types/static_keys 키가 없을 수 있으므로
    모두 .get(..., []) 폴백. templates만 있던 기존 로그도 그대로 동작.
    """
    dep = _deprecated_template_stems()
    templates: set[str] = set()
    static_keys: set[str] = set()
    type_runs: list[set[str]] = []
    for entry in _load_usage_log()[-lookback:]:
        for t in entry.get("templates", []) or []:
            if t:
                stem = _strip_aspect(t)
                if stem not in dep:
                    templates.add(stem)
        for sk in entry.get("static_keys", []) or []:
            if sk:
                static_keys.add(sk)
        ent_types: set[str] = set()
        for ty in entry.get("types", []) or []:
            if ty:
                ent_types.add(str(ty).strip().lower())
        type_runs.append(ent_types)
    return {"templates": templates, "static_keys": static_keys,
            "type_runs": type_runs}


def _recent_templates(lookback: int = _USAGE_LOOKBACK) -> set[str]:
    """최근 lookback개 영상에서 사용된 motion_template stem 집합.

    2026-04-21 호환 유지용 thin wrapper. 내부적으로 _recent_keys를 사용하며
    aspect 정규화 + deprecated 제외가 적용된 stem 집합을 돌려준다.
    """
    return _recent_keys(lookback)["templates"]


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

# 2026-06-04 VQ-01: 영구 forbidden 장식 글자 hero — motion_template로 쓰면 즉시 reject.
# CONTRACT §4. build_catalog FORCE_FORBIDDEN과 이중 방어(카탈로그 강등 우회 차단).
_FORBIDDEN_MOTION_TEMPLATES = {
    "text_hero_aurora_16x9", "text_hero_sparkles_1x1",
}

# 2026-06-04 VQ-01 Rule 8: 다색 장식 시그니처(design_tokens: accent 1색 원칙 위반).
# 향후 유사 장식 template이 추가돼도 src_hint/motion_params 묘사로 잡는 미래 안전망.
# 단일 accent gradient(1색 sweep)는 오탐 방지 위해 매칭하지 않음 — 명백한 다색/파티클만.
_DECORATIVE_SIGNATURES = [
    re.compile(r'\brainbow\b', re.IGNORECASE),
    re.compile(r'무지개'),
    re.compile(r'6\s*색'),                       # "6색 그라데이션"
    re.compile(r'(?:6|six)[\s-]*color\b', re.IGNORECASE),
    re.compile(r'multi[\s-]*color(?:ed)?\b', re.IGNORECASE),
    re.compile(r'\baurora\b.*(?:gradient|sweep|multi|색)', re.IGNORECASE),
    re.compile(r'\b(?:sparkle|sparkles|particle|particles|twinkle|twinkling)\b',
               re.IGNORECASE),
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

# VQ-02: 자막-overlay 텍스트 중복 검사 대상 — 자유 텍스트를 담는 글자형 overlay만.
# (모션의 구조적 items나 ui_evidence/차트는 제외 — 자막 echo가 일어날 수 없는 형태.)
_FREE_TEXT_BROLL_TYPES = {"text_hero", "typography", "title", "quote"}


def _normalize_ko(text: str) -> str:
    """한국어 텍스트 정규화 — 공백/문장부호/대표 조사 제거 후 소문자.

    VQ-02 중복 비교용. 형태소 분석기 없이 결정론적으로만(조사 휴리스틱 최소).
    """
    t = (text or "").lower()
    # 한글/영문/숫자만 남김
    t = re.sub(r"[^0-9a-z가-힣]", "", t)
    return t


def _overlay_echoes_narration(overlay_text: str, narration: str) -> bool:
    """overlay 자유텍스트가 같은 씬 narration을 거의 그대로 반복하는지.

    VQ-02 revision_note (b): 자카드/형태소 머신 대신 단순 휴리스틱 —
    정규화 후 연속 4자 이상 한국어 substring이 일치하고, 그 일치가
    overlay 길이의 60% 이상을 차지하면 '자막 반복'으로 판정.
    (짧은 키워드 1개 추출은 통과 — overlay가 narration의 부분집합이어도
     길이 비중이 작으면 정당한 핵심어 추출.)
    """
    ov = _normalize_ko(overlay_text)
    na = _normalize_ko(narration)
    if len(ov) < 4 or not na:
        return False
    # overlay 전체가 narration에 그대로 포함 + overlay가 충분히 길면 echo.
    if ov in na and len(ov) >= 6:
        return True
    # 가장 긴 공통 연속 substring을 찾아 overlay 대비 비중 측정.
    best = 0
    for i in range(len(ov)):
        for j in range(i + 4, len(ov) + 1):
            if ov[i:j] in na:
                best = max(best, j - i)
            else:
                break
    return best >= 4 and best >= 0.6 * len(ov)


def _pre_filter_plan(plan: dict,
                     scene_narr: dict[int, str] | None = None) -> list[str]:
    """Scan plan for hard rule violations that don't need LLM judgment.
    Returns a list of critical issues (empty → pre-filter passes).

    scene_narr: scene_idx → narration text. None이면 VQ-02 자막-overlay
    중복 검사를 건너뛴다(하위호환 — 기존 호출부는 인자 미전달 시 그대로 동작).
    """
    issues: list[str] = []

    # --- anti-cliché 누적 카운터 (영상 전체 기준) ---
    overlay_count = 0
    text_card_count = 0
    substance_count = 0
    template_uses: dict[str, int] = {}
    type_uses: dict[str, int] = {}
    plan_templates: list[str] = []
    # 2026-06-04 SI-01: 정적/dual 포함 cross-video 키. static 키는 type:핵심명사.
    plan_static_keys: list[str] = []
    plan_types: set[str] = set()

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
            mt = b.get("motion_template", "") or ""
            overlay_count += 1
            if mt:
                template_uses[mt] = template_uses.get(mt, 0) + 1
                plan_templates.append(mt)
            if t:
                type_uses[t] = type_uses.get(t, 0) + 1
                plan_types.add(str(t).strip().lower())
            if _is_substance_template(mt, t, hint):
                substance_count += 1
            # 2026-06-04 SI-01: cross-video 키 — motion은 template stem,
            # 정적/dual(모션 없음)은 type:핵심명사 키로 수집.
            if mt:
                plan_static_keys.append(_strip_aspect(mt))
            else:
                plan_static_keys.append(_static_broll_key(b))

            # Rule 0 (VQ-01): 영구 forbidden 장식 글자 hero는 motion_template로
            # 쓰면 무조건 즉시 reject. justification escape hatch 없음(영구 금지).
            if mt in _FORBIDDEN_MOTION_TEMPLATES:
                issues.append(
                    f"scene {sidx}: '{mt}'는 영구 forbidden 장식 글자 hero "
                    f"(다색 그라데이션/파티클 = design_tokens 단일-accent 위반 + "
                    f"emphasis 자막과 정보 중복). 어떤 justification으로도 사용 불가 — "
                    f"text_only + emphasis 또는 kinetic_type 계열로 전환할 것."
                )
                continue

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

            # Rule 3 (anti-cliché): 스타일 입힌 글자 카드 = emphasis 자막과 중복.
            # justification 명시가 없으면 reject (text_only로 유도).
            just = (b.get("justification") or b.get("text_card_justified") or "")
            has_just = isinstance(just, str) and bool(just.strip())
            if mt in _TEXT_CARD_TEMPLATES:
                text_card_count += 1
                if not has_just:
                    issues.append(
                        f"scene {sidx}: '{mt}'는 스타일 입힌 글자 카드 — 화면 emphasis "
                        f"자막과 정보량 중복(뻔함). 기본 'decision: text_only' + emphasis로 "
                        f"전환할 것. 꼭 써야 하면 broll.justification에 '다중 색 그라데이션/"
                        f"파티클이 메시지에 필수인 이유'를 명시 (영상당 최대 1개)."
                    )

            # Rule 8 (VQ-01): 다색 장식 시그니처(향후 신규 장식 template 안전망).
            # Rule 3 escape hatch 존중 — justification이 있고 글자카드 한도 내면 skip.
            # (이름이 아니라 src_hint/motion_params 묘사로 잡으므로 미등록 template도 커버.)
            if not (has_just and text_card_count <= 1):
                desc = hint
                mp = b.get("motion_params")
                if mp is not None:
                    desc = f"{desc} {json.dumps(mp, ensure_ascii=False)}"
                for pat in _DECORATIVE_SIGNATURES:
                    if pat.search(desc):
                        issues.append(
                            f"scene {sidx}: 다색/파티클 장식 시그니처 감지 "
                            f"(pattern: {pat.pattern[:32]}) — design_tokens 단일-accent "
                            f"원칙 위반. text_only + emphasis로 전환할 것. 꼭 써야 하면 "
                            f"broll.justification에 필수 이유 명시(영상당 최대 1개)."
                        )
                        break

            # VQ-02: 자막-overlay 텍스트 중복 — 글자형 overlay가 같은 씬 narration을
            # 거의 그대로 반복하면 split-attention/redundancy(뻔함). 경고+justification 요구.
            if (scene_narr is not None and t in _FREE_TEXT_BROLL_TYPES
                    and not has_just):
                ov_text = (b.get("text") or b.get("phrase")
                           or b.get("title") or b.get("page_title") or "")
                narration = scene_narr.get(sidx, "") if isinstance(sidx, int) else ""
                if isinstance(ov_text, str) and ov_text.strip() and narration:
                    if _overlay_echoes_narration(ov_text, narration):
                        issues.append(
                            f"scene {sidx}: overlay 텍스트('{ov_text[:24]}')가 같은 씬 "
                            f"자막(narration)을 거의 그대로 반복 — 정보량 중복(뻔함). "
                            f"자막=흐름 / overlay=핵심 1개로 역할 분리. 키워드/숫자 1개만 "
                            f"추출하거나 text_only로 전환. 꼭 반복해야 하면 justification 명시."
                        )

    # --- 영상 전체 기준 anti-cliché 규칙 ---

    # Rule 4: 같은 motion_template 2회 이상 반복 → 단조
    for mt, n in template_uses.items():
        if n >= 2:
            issues.append(
                f"motion_template '{mt}' {n}회 반복 — 한 영상에 같은 템플릿 중복 금지. "
                f"다른 시나리오엔 다른 template로 변별할 것."
            )
    # Rule 4b: 같은 type 2회 이상 반복
    for t, n in type_uses.items():
        if n >= 2:
            issues.append(
                f"type '{t}' {n}회 반복 — 같은 type 중복 금지(다양성). "
                f"6-type 중 서로 다른 것으로 분산."
            )

    # Rule 5: 스타일 글자 카드는 영상당 최대 1개
    if text_card_count > 1:
        issues.append(
            f"text_hero(글자 카드) {text_card_count}개 — 영상당 최대 1개. "
            f"나머지는 text_only emphasis로."
        )

    # Rule 6 (monotony): overlay 2개 이상인데 실제 UI/데이터 0개 = '검은 글자 카드만'
    if overlay_count >= 2 and substance_count == 0:
        issues.append(
            f"overlay {overlay_count}개 전부 글자/도형 카드 — 시각 변별 부족(뻔함). "
            f"실제 UI 증빙(ui_evidence: claude_code/terminal/notion 등) 또는 "
            f"데이터 차트(line_chart/bar_chart/metric_ring) 최소 1개 포함할 것. "
            f"AI·툴·빌딩 주제면 ui_evidence를 1순위로."
        )

    # Rule 7 (cross-video variety): 최근 영상과 과하게 겹치면 경고성 reject.
    # 2026-06-04 SI-01/SI-02 강화:
    #   - 비교 키를 motion_template stem(aspect 정규화) + 정적/dual static_key까지 확장.
    #   - distinct 키 >=3이면 overlap_ratio>=0.6(과반)에서 reject(부분 겹침도 감점).
    #     distinct <=2면 ratio 무의미 → full-overlap일 때만 reject(기존 동작 보존).
    #   - type-convergence: 최근 N영상 연속 동일 type(특히 ui_evidence_*) → 1순위 경고.
    recent = _recent_keys()
    recent_keys: set[str] = set(recent["templates"]) | set(recent["static_keys"])

    # 이번 plan의 cross-video 키 집합(aspect 정규화된 motion stem + 정적 키).
    plan_keys = {k for k in plan_static_keys if k}
    if plan_keys and recent_keys:
        overlap = {k for k in plan_keys if k in recent_keys}
        distinct = len(plan_keys)
        if overlap:
            if distinct >= 3:
                ratio = len(overlap) / distinct
                if ratio >= _USAGE_OVERLAP_RATIO:
                    issues.append(
                        f"이번 plan의 B-roll 키 과반({len(overlap)}/{distinct}, "
                        f"{ratio:.0%})이 최근 {_USAGE_LOOKBACK}개 영상과 겹침"
                        f"({sorted(overlap)}) — '맨날 똑같은' 반복. 겹치지 않는 "
                        f"template/소스로 최소 (distinct-과반) 개를 교체할 것."
                    )
            else:
                # distinct<=2: 전부 겹칠 때만(기존 full-overlap 룰 유지).
                if len(overlap) == distinct:
                    issues.append(
                        f"이번 plan의 B-roll 키가 전부 최근 {_USAGE_LOOKBACK}개 영상에서 "
                        f"이미 사용됨({sorted(overlap)}) — '맨날 똑같은' 반복. "
                        f"최소 1개는 최근에 안 쓴 template/소스로 교체할 것."
                    )

    # type-convergence(SI-02 1순위 신호): 최근 영상이 연속으로 같은 type만 썼고
    # 이번에도 그 type을 쓰면 cross-video 단조. 6-type 분모가 작아 가장 잘 잡힘.
    type_runs = recent["type_runs"]
    if plan_types and len(type_runs) >= _TYPE_CONVERGENCE_RUN:
        tail = type_runs[-_TYPE_CONVERGENCE_RUN:]
        # 최근 run 동안 매 영상에 등장한 type의 교집합.
        common: set[str] = set(tail[0])
        for s in tail[1:]:
            common &= s
        converged = {ty for ty in common if ty in plan_types}
        if converged:
            issues.append(
                f"type {sorted(converged)}가 최근 {_TYPE_CONVERGENCE_RUN}개 영상 연속 "
                f"사용됨 — 이번에도 반복 시 cross-video 단조('맨날 똑같은'). "
                f"6-type 중 최근에 안 쓴 type으로 최소 1개 분산할 것."
            )

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
    # VQ-02: scene narration을 넘겨 자막-overlay 텍스트 중복 검사 활성화.
    pre_issues = _pre_filter_plan(plan, scene_narr=narr)
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
