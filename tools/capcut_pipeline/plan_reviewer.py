"""
CapCut B-roll Plan Reviewer — 에이전트팀 비평적 검토 시스템

5개 리뷰 관점 (Round 2 통합 합의):
  1. Hook Reviewer       — 첫 3-5초 후킹 (title_hook, first_scene_hook)
  2. Retention Reviewer  — 시청 지속력 (variety, pacing)
  3. Visual Flow Reviewer — 시각 흐름 (contrast, flow)
  4. Context Match Reviewer — 맥락 일치 (narration_match, specificity)
  5. Restraint Reviewer (Devil's Advocate, Round 2 단독) — 억지 B-roll 반려 (necessity, minimalism)

서브커맨드 (scene_designer.py에서 호출):
  review-context  → _claude_review_context.md 생성 (Claude가 5관점으로 평가할 가이드)
  review-ingest   → _claude_review.json 검증 + PASS/REJECT 판정

판정 기준:
  - 총점 42/50 이상 (84%)
  - 각 차원 3점 이상 (restraint는 4점 이상 — 억지 B-roll 무관용)
  - feedback 내 "[CRITICAL]" 지적이 있으면 즉시 REJECT (점수 무관)
  - 3회 연속 REJECT 시 폴백: 최고점 draft + CRITICAL만 반영 → 강제 PASS (forced_pass=true)

Weight 규칙:
  - 첫 씬(scene_idx 0-1)은 Hook weight 1.5× (후킹 없으면 영상 자체 실패)
  - 그 외 씬은 Restraint weight 1.3× (중반 이후 억지 방지가 우선)

설계 원칙:
  - Round 1 (4명 병렬): Hook/Retention/VisualFlow/ContextMatch 독립 평가
  - Round 2 (1명 단독): Restraint가 Round 1 결과 읽고 cross-critique, 반려 리스트
  - Claude 메인이 종합 시 Restraint CRITICAL을 우선 반영
"""
import json
from pathlib import Path
from typing import Any


# ===== 4개 리뷰 관점 정의 =====

REVIEW_DIMENSIONS = {
    "hook": {
        "name": "Hook Reviewer",
        "subagent_type": "general-purpose",
        "system_prompt": (
            "당신은 Instagram/YouTube 쇼트 영상의 첫 3-5초 후킹 전문가입니다. "
            "시청자가 스크롤을 멈추고 계속 보게 만드는 요소를 평가합니다. "
            "오로지 '후킹력'만 평가하고 다른 관점(맥락 일치, 흐름 등)은 다른 에이전트가 담당하므로 신경쓰지 않습니다."
        ),
        "description": "첫 3-5초 후킹 — 시선을 사로잡고 스크롤을 멈추게 하는가?",
        "criteria": [
            "title이 호기심/반전/숫자/비밀로 후킹하는가?",
            "title의 강조 단어(accent_words)가 임팩트 있는가?",
            "첫 씬(scene_idx 0~2)의 B-roll 또는 emphasis가 '계속 볼 이유'를 제공하는가?",
            "title이 과장/자극(충격, 대박)이 아니라 구체적 이득을 약속하는가?",
        ],
        "scores": {
            "title_hook": "title 텍스트 자체의 후킹력 (0-5)",
            "first_scene_hook": "첫 씬(0-5초)의 시각적 후킹 강도 (0-5)",
        },
    },
    "retention": {
        "name": "Retention Reviewer",
        "subagent_type": "general-purpose",
        "system_prompt": (
            "당신은 영상 리텐션(시청 지속률) 전문가입니다. "
            "중간 이탈(drop-off)을 방지하는 B-roll 다양성과 리듬감을 평가합니다. "
            "Hook(첫 3초), Flow(씬 간 대비), Context(맥락 일치)는 다른 에이전트가 담당하므로 신경쓰지 않습니다."
        ),
        "description": "시청 지속력 — 중간에 이탈하지 않게 만드는가?",
        "criteria": [
            "B-roll style(overlay/dual/split/skip)이 너무 단조롭지 않은가?",
            "emphasis 강조가 리듬감 있게 배치되어 있는가 (너무 많거나 너무 적거나)?",
            "긴 skip 구간이 연속으로 있어 시각적 공백이 되는 구간이 없는가?",
            "15초 이상 같은 style이 이어지지 않는가?",
        ],
        "scores": {
            "variety": "B-roll 스타일 다양성 — 4가지 style + skip이 고르게 섞였는가 (0-5)",
            "pacing": "리듬감 — emphasis/B-roll 배치 간격이 적절한가 (0-5)",
        },
    },
    "visual_flow": {
        "name": "Visual Flow Reviewer",
        "subagent_type": "general-purpose",
        "system_prompt": (
            "당신은 영상 에디터 전문가로 씬 간 시각적 흐름을 평가합니다. "
            "이야기와 시각의 synchronization, 같은 style 연속 반복 방지, 감정 피크에 full_person 배치 등을 봅니다. "
            "Hook, Retention, Context는 다른 에이전트가 담당하므로 신경쓰지 않습니다."
        ),
        "description": "시각 흐름 — 씬 간 대비와 연결이 자연스러운가?",
        "criteria": [
            "연속된 씬이 같은 style을 3회 이상 반복하지 않는가?",
            "정보 밀도가 높은 구간(설명/나열)에 skip이 몰려있지 않은가?",
            "감정 피크 순간에 full_person(B-roll 없음)이 배치되어 임팩트를 주는가?",
            "style 전환이 의미 있는가? (비교 구간에 dual, 리스트에 split 등)",
        ],
        "scores": {
            "contrast": "씬 간 대비 — 변화의 임팩트 (0-5)",
            "flow": "연결성 — 이야기 흐름을 시각이 뒷받침하는가 (0-5)",
        },
    },
    "context_match": {
        "name": "Context Match Reviewer",
        "subagent_type": "general-purpose",
        "system_prompt": (
            "당신은 B-roll과 narration의 맥락 일치도를 평가하는 편집 감독입니다. "
            "narration이 말하는 것과 B-roll이 보여주는 것의 1:1 대응을 엄격히 검증합니다. "
            "구체 제품 언급 시 분위기 사진 대체 금지. 한국어 텍스트만. "
            "Hook, Retention, Flow는 다른 에이전트가 담당하므로 신경쓰지 않습니다."
        ),
        "description": "맥락 일치 — narration과 B-roll이 정확히 대응하는가?",
        "criteria": [
            "구체 제품/서비스 언급(예: 노션, 카톡) 시 반드시 해당 UI가 있는가?",
            "숫자/통계 언급 시 emphasis로 해당 숫자가 강조되는가?",
            "추상/감정 문장에 과도한 UI 스크린샷이 들어가 맥락이 깨지지 않는가?",
            "src_hint가 narration의 핵심 명사와 명확히 매칭되는가?",
            "모든 src_hint에 '한국어 텍스트만 사용'이 명시되어 있는가?",
        ],
        "scores": {
            "narration_match": "narration ↔ B-roll 1:1 매칭 정확도 (0-5)",
            "specificity": "구체성 — 분위기 사진 남발 없이 의미 전달 (0-5)",
        },
    },
    # Round 2 단독 실행 — Round 1 결과와 plan을 모두 읽고 cross-critique
    "restraint": {
        "name": "Restraint Reviewer (Devil's Advocate)",
        "subagent_type": "general-purpose",
        "system_prompt": (
            "당신은 미니멀리즘 편집자이자 Devil's Advocate입니다. "
            "B-roll·emphasis를 **줄이는 방향만** 평가합니다. 억지 매칭, 불필요한 추가, 의미 없는 style 전환을 지적합니다. "
            "Round 1의 Hook/Retention/VisualFlow/ContextMatch 4개 제안도 검토해서 '추가 불필요' 항목은 반려합니다. "
            "scene_designer DECISION_TREE의 2단계 룰(관문 ≥1 AND 안티패턴 =0)을 엄격 적용. "
            "안티패턴(타이틀 구간/추상 질문/내러티브 setup/추상 결론/대명사/필러/NG)에 B-roll 발견 시 '[CRITICAL]' 접두사로 지적하세요."
        ),
        "description": "억지 B-roll 반려 — B-roll이 정말 필요한지 도전",
        "criteria": [
            "모든 overlay/dual/split이 narration에 **필수**적인가? (없으면 의미 전달 실패?)",
            "skip이 '회피'가 아니라 '의도'인가? (감정 피크는 full_person이 더 강함)",
            "B-roll을 제거해도 메시지가 전달되는 씬은 어디? → 해당 씬은 skip 권고",
            "Round 1의 '추가 제안' 중 반려해야 할 항목은? (특히 추가 편향이 의심되는 것)",
            "안티패턴(타이틀/추상 질문/내러티브/결론/대명사/필러/NG)에 B-roll 있으면 [CRITICAL]",
        ],
        "scores": {
            "necessity": "B-roll 필요성 — 모든 B-roll이 정당화되는가 (0-5)",
            "minimalism": "미니멀리즘 — 불필요한 추가 없이 절제된 설계인가 (0-5)",
        },
    },
}

# Round 2 합의 (Round 2 reviewer 설계안):
#   PASS_TOTAL 32/40 → 42/50 (50점 만점 중 84%)
#   restraint 차원은 4점 이상 요구 (억지 B-roll 무관용)
#   "[CRITICAL]" 접두사 issue가 있으면 점수 무관 즉시 REJECT
PASS_TOTAL = 42  # 50점 만점 중 42점(84%) 이상
PASS_MIN_PER_DIM = 3  # 대부분 차원 최소 3점
PASS_MIN_RESTRAINT = 4  # restraint는 4점 이상 (억지 무관용)
MAX_REJECT_ATTEMPTS = 3  # 3회 연속 REJECT 시 폴백 (강제 PASS + CRITICAL만 반영)


# ===== Review context 생성 =====

def build_review_context(
    plan_path: Path,
    scenes_path: Path,
    transcript_path: Path,
    out_path: Path,
) -> None:
    """Claude가 4관점으로 plan을 평가할 context markdown 생성."""
    with open(plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)
    with open(scenes_path, "r", encoding="utf-8") as f:
        scenes_data = json.load(f)
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = json.load(f)

    scenes = scenes_data.get("scenes", [])
    segments = transcript.get("segments", [])

    # 각 scene의 narration 매핑
    scene_narr: dict[int, str] = {}
    for scene in scenes:
        s_start, s_end = scene["start"], scene["end"]
        words = []
        for seg in segments:
            if seg["end"] < s_start or seg["start"] > s_end:
                continue
            for w in seg.get("words", []):
                if w["start"] >= s_start and w["end"] <= s_end:
                    words.append(w["word"].strip())
        scene_narr[scene["idx"]] = " ".join(words).strip() or "(무음)"

    # plan의 scenes → dict for lookup
    plan_scenes = {s["scene_idx"]: s for s in plan.get("scenes", [])}

    lines: list[str] = []
    lines.append("# CapCut B-roll Plan Review Context")
    lines.append("")
    lines.append("## 🎯 작업")
    lines.append("")
    lines.append("이 broll_plan을 **5개 관점**에서 비평적으로 검토하세요 (Round 1: 4명 병렬, Round 2: Restraint 단독).")
    lines.append("각 차원별로 **0-5점** + **구체적 피드백**을 `_claude_review.json`에 작성.")
    lines.append("")
    lines.append(f"**PASS 기준**:")
    lines.append(f"- 총점 ≥ {PASS_TOTAL}/50")
    lines.append(f"- 대부분 차원 ≥ {PASS_MIN_PER_DIM}점, restraint(necessity·minimalism) ≥ {PASS_MIN_RESTRAINT}점 (억지 무관용)")
    lines.append(f"- feedback의 issues에 `[CRITICAL]` prefix가 있으면 점수 무관 즉시 REJECT (단 Restraint override로 무효화 가능)")
    lines.append(f"- 3회 연속 REJECT 시 폴백: 최고점 draft + CRITICAL만 반영 → 강제 PASS")
    lines.append("")
    lines.append("### Round 2 cross-critique + Restraint Override (Round 3 설계)")
    lines.append("")
    lines.append("Restraint Reviewer는 Round 1의 다른 4명의 issues/suggestions를 읽고 비판합니다.")
    lines.append("- `feedback.restraint.suggestions`에 Round 1 제안 중 **반려할 항목**을 적습니다.")
    lines.append(f"- 특정 Round 1 CRITICAL이 DECISION_TREE 안티패턴(A1-A7) 유발이거나 관문(G1-G4)")
    lines.append(f"  미충족으로 판단되면, `suggestions`에 **`[CRITICAL 반박]`** prefix를 붙여 기록.")
    lines.append(f"- 또는 `\"Round 1 [차원명] ... 반려\"` 형식으로 기록해도 동일하게 처리됨.")
    lines.append("")
    lines.append(f"**Override 효과** (restraint 평균 ≥ {PASS_MIN_RESTRAINT}일 때만 발동):")
    lines.append(f"- 반박 대상 Round 1 차원의 CRITICAL은 집계에서 무효화")
    lines.append(f"- 해당 차원의 weak threshold가 {PASS_MIN_PER_DIM}점 → {PASS_MIN_OVERRIDDEN}점으로 완화")
    lines.append(f"- Restraint가 Round 1 '추가 편향(additive bias)'을 반박할 구조적 권한")
    lines.append("")

    # Plan 전체 요약
    lines.append("## 📋 검토 대상 Plan")
    lines.append("")
    title = plan.get("title", {})
    if title:
        lines.append(f"**Title**: `{title.get('text', '')}`")
        lines.append(f"**Accent**: {title.get('accent_words', [])}")
        lines.append(f"**Duration**: {title.get('duration_sec', 4.0)}s")
        lines.append("")

    # 씬별 narration + decision 매핑
    lines.append("### 씬별 narration × plan decision")
    lines.append("")
    lines.append("| idx | time | narration | decision | detail |")
    lines.append("|---|---|---|---|---|")
    for s in scenes:
        idx = s["idx"]
        narr = scene_narr.get(idx, "").replace("|", "\\|")[:60]
        ps = plan_scenes.get(idx)
        if not ps:
            decision = "(미지정)"
            detail = ""
        else:
            decision = ps.get("decision", "?")
            if decision == "skip":
                detail = ps.get("reason", "")[:40]
            elif decision == "dual":
                hints = [b.get("src_hint", "")[:30] for b in ps.get("brolls", [])]
                detail = " ／ ".join(hints)
            else:
                b = ps.get("broll", {})
                detail = b.get("src_hint", "")[:50]
                emp = ps.get("emphasis")
                if emp:
                    detail += f" ⚡ `{emp.get('text', '')}`"
        detail = detail.replace("|", "\\|")
        lines.append(f"| {idx} | {s['start']:.1f}s | {narr} | `{decision}` | {detail} |")
    lines.append("")

    # 스타일 통계
    style_counts: dict[str, int] = {"skip": 0, "overlay": 0, "dual": 0, "split": 0}
    for ps in plan_scenes.values():
        d = ps.get("decision", "skip")
        style_counts[d] = style_counts.get(d, 0) + 1
    emphasis_count = sum(1 for ps in plan_scenes.values() if ps.get("emphasis"))
    lines.append("### 📊 Plan 통계")
    lines.append("")
    lines.append(f"- 총 씬: {len(scenes)}개")
    lines.append(f"- Plan 커버: {len(plan_scenes)}개 (skip: {style_counts['skip']}, overlay: {style_counts['overlay']}, dual: {style_counts['dual']}, split: {style_counts['split']})")
    lines.append(f"- Emphasis: {emphasis_count}개")
    lines.append("")

    # 5개 리뷰 관점 상세
    lines.append("## 🔍 5개 리뷰 관점 (Round 1: 4개 병렬, Round 2: restraint 단독)")
    lines.append("")
    for dim_key, dim in REVIEW_DIMENSIONS.items():
        lines.append(f"### {dim['name']} — `{dim_key}`")
        lines.append(f"> {dim['description']}")
        lines.append("")
        lines.append("**체크리스트:**")
        for c in dim["criteria"]:
            lines.append(f"- [ ] {c}")
        lines.append("")
        lines.append("**점수 차원 (각 0-5점):**")
        for score_key, score_desc in dim["scores"].items():
            lines.append(f"- `{score_key}` — {score_desc}")
        lines.append("")

    # 출력 형식
    lines.append("---")
    lines.append("")
    lines.append("## 📝 작성 템플릿 (`_claude_review.json`)")
    lines.append("")
    lines.append("```json")
    example = {
        "attempt_count": 1,
        "scores": {
            "title_hook": 4,
            "first_scene_hook": 3,
            "variety": 4,
            "pacing": 3,
            "contrast": 4,
            "flow": 3,
            "narration_match": 5,
            "specificity": 4,
            "necessity": 4,
            "minimalism": 4,
        },
        "feedback": {
            "hook": {
                "strengths": ["title '...'이 숫자로 호기심 유발"],
                "issues": ["첫 씬이 skip이라 시각적 후킹 약함 (단 restraint와 충돌 가능)"],
                "suggestions": ["scene_idx 0에 overlay 추가 — 문제 상황 UI"],
            },
            "retention": {
                "strengths": ["중반부 dual로 비교 강조 좋음"],
                "issues": ["15초 연속 skip 구간(scene 5~8) 있음 — 이탈 위험"],
                "suggestions": ["scene 6에 emphasis만 추가해서 시각 공백 메우기"],
            },
            "visual_flow": {
                "strengths": ["감정 씬(scene 10)에 skip 배치 — 임팩트 ↑"],
                "issues": ["scene 12,13,14 모두 overlay 연속"],
                "suggestions": ["scene 13을 split으로 변경해서 대비 만들기"],
            },
            "context_match": {
                "strengths": ["모든 src_hint에 '한국어' 명시됨"],
                "issues": ["scene 7 narration '노션에서' → B-roll이 일반 메모앱"],
                "suggestions": ["scene 7 src_hint를 '노션 웹앱 UI'로 변경"],
            },
            "restraint": {
                "strengths": ["skip 비율 적절, 추상 씬에 B-roll 없음"],
                "issues": [
                    "[CRITICAL] scene 2(추상 후킹 질문)에 overlay — 안티패턴 A2 위반",
                    "scene 6 atmospheric B-roll은 제거해도 의미 전달됨",
                ],
                "suggestions": [
                    "[CRITICAL 반박] Round 1 Retention의 'scene 0에 overlay 추가' 제안 반려 — A1 타이틀 구간 위반 유발",
                    "[CRITICAL 반박] Round 1 Retention의 'scene 6 emphasis 추가' 반려 — A3 내러티브 setup 위반",
                    "scene 6 decision을 skip으로 변경, emphasis만 유지",
                ],
            },
        },
        "verdict": "REJECT",
        "revision_priority": [
            "[CRITICAL] scene 2: 안티패턴 A2 — skip으로 변경",
            "scene 6: B-roll 제거, emphasis만",
            "scene 7: 노션 UI로 정확히 매칭",
        ],
    }
    lines.append(json.dumps(example, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## 🚨 평가 원칙")
    lines.append("")
    lines.append("1. **가혹하게 점수**: 대충 넘기지 말고 약점을 구체적으로 짚을 것. 5점은 예외적.")
    lines.append("2. **구체적 제안**: '개선 필요' 같은 모호한 말 금지. 어떤 scene을 어떻게 고칠지 명시.")
    lines.append("3. **전체 맥락 우선**: 개별 씬만 보지 말고 영상 전체 리듬/흐름 기준으로 판단.")
    lines.append(f"4. **verdict**: 총점 < {PASS_TOTAL} / necessity·minimalism < {PASS_MIN_RESTRAINT} / 다른 차원 < {PASS_MIN_PER_DIM} / CRITICAL 지적 있음 중 하나라도 → REJECT.")
    lines.append("5. **[CRITICAL] prefix 사용법**: 안티패턴(타이틀/추상 질문/내러티브/결론/대명사/필러/NG)에 B-roll이 있으면 `restraint.issues` 또는 다른 차원 issues에 `[CRITICAL] ...` 으로 지적 → 즉시 REJECT.")
    lines.append("6. **revision_priority**: REJECT 시 가장 중요한 수정 3-5개를 우선순위 순으로. CRITICAL은 `[CRITICAL]` prefix 유지.")
    lines.append("7. **attempt_count**: 재검토일 경우 `attempt_count`를 이전 값+1로 기록. 3회 도달 시 자동 폴백 PASS.")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[save] review context -> {out_path}")
    print(f"  scenes: {len(scenes)}, plan covers: {len(plan_scenes)}")


# ===== Review ingest (판정 + 피드백 출력) =====

# Round 1 차원 → score key 매핑 (Restraint override weak threshold 완화에 사용)
ROUND1_DIM_TO_SCORES = {
    "hook": ["title_hook", "first_scene_hook"],
    "retention": ["variety", "pacing"],
    "visual_flow": ["contrast", "flow"],
    "context_match": ["narration_match", "specificity"],
}
ROUND1_DIMS = set(ROUND1_DIM_TO_SCORES.keys())
PASS_MIN_OVERRIDDEN = 2  # Restraint override된 차원의 weak threshold (3 → 2로 완화)


def _collect_critical_issues(feedback: dict) -> list[tuple[str, str]]:
    """모든 차원의 feedback.issues에서 '[CRITICAL]' prefix 이슈 추출."""
    criticals = []
    for dim_key, fb in feedback.items():
        if not isinstance(fb, dict):
            continue
        for issue in fb.get("issues", []):
            if isinstance(issue, str) and issue.lstrip().startswith("[CRITICAL]"):
                criticals.append((dim_key, issue))
    return criticals


def _collect_restraint_overrides(feedback: dict) -> list[str]:
    """Restraint의 suggestions에서 '[CRITICAL 반박]' 또는 Round 1 '반려' 패턴 추출.

    Restraint가 Round 1의 CRITICAL/추가 제안을 DECISION_TREE 안티패턴 근거로 반박하면,
    해당 Round 1 차원의 CRITICAL은 무효화되고 weak threshold는 완화됨.
    """
    overrides = []
    restraint_fb = feedback.get("restraint", {})
    if not isinstance(restraint_fb, dict):
        return overrides
    for sug in restraint_fb.get("suggestions", []):
        if not isinstance(sug, str):
            continue
        # "[CRITICAL 반박]" prefix 또는 "Round 1 X 반려" 패턴
        if sug.lstrip().startswith("[CRITICAL 반박]") or "반려" in sug:
            overrides.append(sug.strip())
    return overrides


def _overridden_dims_from_restraint(overrides: list[str]) -> set[str]:
    """Restraint overrides 문자열에서 언급된 Round 1 차원 키를 추출.

    overrides 문자열에 'Retention', 'Hook', 'Visual Flow', 'Context Match'가 포함되면
    해당 Round 1 차원으로 간주. 매핑 → dim_key (소문자 스네이크).
    """
    name_to_key = {
        "hook": "hook",
        "retention": "retention",
        "visual flow": "visual_flow",
        "visual_flow": "visual_flow",
        "context match": "context_match",
        "context_match": "context_match",
    }
    found = set()
    for s in overrides:
        lower = s.lower()
        for name, key in name_to_key.items():
            if name in lower:
                found.add(key)
    return found


def review_ingest(review_path: Path) -> bool:
    """
    _claude_review.json 검증 + PASS/REJECT 판정.

    판정 규칙 (Round 2/3 합의):
      1. CRITICAL veto: feedback 내 "[CRITICAL]" 이슈 1개라도 있으면 즉시 REJECT
      2. **Restraint override**: Restraint suggestions의 "[CRITICAL 반박]" 또는 "반려" 문구가
         언급된 Round 1 차원의 CRITICAL을 무효화 (추가 편향 반박)
      3. restraint 차원 < PASS_MIN_RESTRAINT(4) → REJECT (억지 B-roll 무관용)
      4. 다른 차원 < PASS_MIN_PER_DIM(3) → REJECT.
         단 Restraint가 해당 차원을 override하고 restraint 평균 >= 4면 threshold 완화 (3 → 2)
      5. 총점 < PASS_TOTAL(42) → REJECT
      6. review.attempt_count >= MAX_REJECT_ATTEMPTS → 강제 PASS (forced_pass=true)

    Returns: True if PASS (or forced), False if REJECT
    """
    with open(review_path, "r", encoding="utf-8") as f:
        review = json.load(f)

    scores = review.get("scores", {})
    feedback = review.get("feedback", {})
    verdict = review.get("verdict", "REJECT")
    revision_priority = review.get("revision_priority", [])
    attempt_count = review.get("attempt_count", 1)

    # 모든 차원 점수 확인 (restraint 포함 10개 → 50점)
    required_dims = [
        "title_hook", "first_scene_hook",
        "variety", "pacing",
        "contrast", "flow",
        "narration_match", "specificity",
        "necessity", "minimalism",  # restraint
    ]
    missing = [d for d in required_dims if d not in scores]
    if missing:
        print(f"[ERROR] missing score dimensions: {missing}")
        return False

    total = sum(scores[d] for d in required_dims)

    # Restraint override 분석
    restraint_avg = (scores.get("necessity", 0) + scores.get("minimalism", 0)) / 2
    restraint_overrides = _collect_restraint_overrides(feedback)
    overridden_dims = _overridden_dims_from_restraint(restraint_overrides)
    # Restraint가 실제로 강하고(평균 >=4) override가 있을 때만 완화 적용
    override_active = restraint_avg >= PASS_MIN_RESTRAINT and bool(overridden_dims)

    # 약점 차원: override 적용 시 해당 Round 1 차원 threshold를 3 → 2로 완화
    weak = []
    relaxed_dims = []
    for dim_key, score_keys in ROUND1_DIM_TO_SCORES.items():
        if override_active and dim_key in overridden_dims:
            threshold = PASS_MIN_OVERRIDDEN
            relaxed_dims.append(dim_key)
        else:
            threshold = PASS_MIN_PER_DIM
        for sk in score_keys:
            if scores[sk] < threshold:
                weak.append(f"{sk}={scores[sk]}<{threshold}")
    # restraint 차원
    for sk in ("necessity", "minimalism"):
        if scores[sk] < PASS_MIN_RESTRAINT:
            weak.append(f"{sk}={scores[sk]}<{PASS_MIN_RESTRAINT}")

    # CRITICAL veto: Restraint override에 해당하는 Round 1 차원의 CRITICAL은 무효화
    criticals_all = _collect_critical_issues(feedback)
    criticals_active = []
    criticals_cancelled = []
    for dim_key, issue in criticals_all:
        if override_active and dim_key in overridden_dims:
            criticals_cancelled.append((dim_key, issue))
        else:
            criticals_active.append((dim_key, issue))
    criticals = criticals_active  # 기존 변수명 유지 (아래 로직 호환)

    print("\n" + "=" * 60)
    print(f" B-roll Plan Review (attempt {attempt_count}/{MAX_REJECT_ATTEMPTS})")
    print("=" * 60)

    # 차원별 점수 표 (override 완화 반영)
    dim_key_order = ["hook", "retention", "visual_flow", "context_match", "restraint"]
    dim_display = {"hook": "Hook", "retention": "Retention", "visual_flow": "Visual Flow",
                   "context_match": "Context Match", "restraint": "Restraint"}
    dim_scores = {
        "hook": ["title_hook", "first_scene_hook"],
        "retention": ["variety", "pacing"],
        "visual_flow": ["contrast", "flow"],
        "context_match": ["narration_match", "specificity"],
        "restraint": ["necessity", "minimalism"],
    }
    for dim_key in dim_key_order:
        score_keys = dim_scores[dim_key]
        sub_total = sum(scores[d] for d in score_keys)
        if dim_key == "restraint":
            threshold = PASS_MIN_RESTRAINT
        elif override_active and dim_key in overridden_dims:
            threshold = PASS_MIN_OVERRIDDEN
        else:
            threshold = PASS_MIN_PER_DIM
        marks = []
        for d in score_keys:
            v = scores[d]
            icon = "🟢" if v >= max(4, threshold) else ("🟡" if v >= threshold else "🔴")
            marks.append(f"{icon} {d}={v}")
        relax_tag = "  [완화]" if override_active and dim_key in overridden_dims else ""
        print(f"  {dim_display[dim_key]:14s} {sub_total}/10{relax_tag}  {' | '.join(marks)}")
    print(f"\n  TOTAL: {total}/50  (PASS >= {PASS_TOTAL})")

    # Restraint override 요약
    if override_active:
        print(f"\n[🛡️  Restraint Override 활성] (restraint 평균 {restraint_avg:.1f} >= {PASS_MIN_RESTRAINT})")
        print(f"   완화된 차원 (weak threshold {PASS_MIN_PER_DIM}→{PASS_MIN_OVERRIDDEN}): {sorted(relaxed_dims)}")
        if criticals_cancelled:
            print(f"   무효화된 CRITICAL {len(criticals_cancelled)}개 (Round 1 추가 편향으로 판정):")
            for dim_key, issue in criticals_cancelled:
                short = issue.replace("[CRITICAL]", "").strip()[:70]
                print(f"     ◇ {dim_key}: {short}...")

    # CRITICAL veto 먼저 표시 (무효화되지 않은 것만)
    if criticals:
        print(f"\n[🚨 CRITICAL 지적 — 점수 무관 REJECT]")
        for dim_key, issue in criticals:
            print(f"  ◆ {dim_key}: {issue}")

    # 피드백 출력
    print("\n[피드백]")
    for dim_key in ("hook", "retention", "visual_flow", "context_match", "restraint"):
        fb = feedback.get(dim_key, {})
        if not fb:
            continue
        print(f"\n◆ {dim_key}")
        for issue in fb.get("issues", []):
            print(f"  ❌ {issue}")
        for sug in fb.get("suggestions", []):
            print(f"  💡 {sug}")

    # Override 발동 시 PASS_TOTAL도 완화 (각 override된 차원당 2점 감면 = score key 2개 × 1점)
    # 근거: Round 1 점수가 낮은 것이 "추가 편향"이라고 Restraint가 입증하면,
    # 그 차원은 구조적으로 정당한 낮음이므로 총점에서 소폭 면제
    override_relief = len(overridden_dims) * 2 if override_active else 0
    effective_pass_total = PASS_TOTAL - override_relief
    if override_relief > 0:
        print(f"   PASS_TOTAL 완화: {PASS_TOTAL} → {effective_pass_total} (override -{override_relief})")

    # PASS/REJECT 판정
    normal_pass = (total >= effective_pass_total) and not weak and not criticals
    forced_pass = False

    # 3회 연속 REJECT 시 폴백
    if not normal_pass and attempt_count >= MAX_REJECT_ATTEMPTS:
        print(f"\n[⚠️  폴백] attempt={attempt_count} ≥ {MAX_REJECT_ATTEMPTS} → 강제 PASS (forced_pass=true)")
        print(f"   CRITICAL 지적만 반영해서 ingest 진행 권장.")
        forced_pass = True

    actual_pass = normal_pass or forced_pass
    final_verdict = "PASS" if actual_pass else "REJECT"
    if forced_pass:
        final_verdict = "PASS (forced)"

    print("\n" + "=" * 60)
    print(f" Verdict: {final_verdict}")
    if not actual_pass:
        if criticals:
            print(f"   CRITICAL veto: {len(criticals)}개 — 점수와 무관하게 REJECT")
        if total < effective_pass_total:
            print(f"   총점 {total} < {effective_pass_total} (PASS 기준)")
        if weak:
            print(f"   약점 차원: {weak}")
        if revision_priority:
            print("\n [우선 수정 항목]")
            for i, r in enumerate(revision_priority, 1):
                print(f"   {i}. {r}")
        print(f"\n  → _claude_broll_plan.json 수정 후 review 재실행 (attempt_count를 {attempt_count+1}로 기록)")
    else:
        if forced_pass:
            print("   ⚠️  강제 PASS: 품질은 불충분하나 진행. CRITICAL은 반드시 반영.")
        else:
            print("   ✅ 다음 단계 진행: ingest → generate-images → patch")
    print("=" * 60)

    # Claude가 선언한 verdict와 실제 계산이 다르면 경고
    if verdict != final_verdict:
        print(f"\n[warn] Claude 선언 verdict={verdict} ≠ 실제 계산 verdict={final_verdict}")

    return actual_pass
