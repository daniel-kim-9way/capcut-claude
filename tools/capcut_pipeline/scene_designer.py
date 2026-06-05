"""
CapCut Scene Designer — 자동 B-roll plan 생성

create-reels의 scene_designer 패턴을 CapCut 파이프라인에 적용.

서브커맨드:
  context   → broll_designer_context.md 생성 (Claude Code가 읽고 판단)
  ingest    → _claude_broll_plan.json 검증 → broll_plan.json 출력

워크플로우:
  1. run_pipeline.py가 STT + scenes.json 생성
  2. scene_designer.py context 실행 → context 파일 생성
  3. Claude Code가 context 읽고 _claude_broll_plan.json 직접 작성
  4. scene_designer.py ingest 실행 → broll_plan.json 검증/저장
  5. (선택) broll_image_gen.py 또는 Claude가 Gemini로 이미지 생성
  6. overlay_patcher.py 실행

설계 원칙:
  - Claude가 맥락을 이해하고 판단 (규칙 기반 classifier 아님)
  - create-reels Step 3a의 의사결정 트리 재활용
  - overlay_patcher가 기대하는 broll_plan.json 형식 정확히 준수
"""
import argparse
import difflib
import functools
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


# Motion B-roll (2026-04-24): Hyperframes-inspired GSAP+Playwright 렌더 통합.
# _claude_broll_plan.json의 broll.motion=True면 ingest가 render_motion.py를 subprocess로
# 호출해 MOV 생성, broll_plan.json의 image_path에 절대경로 기록.
_MOTION_ASPECT_MAP = {
    ("16", "9"): (1920, 1080),
    ("9", "16"): (1080, 1920),
    ("1", "1"): (1080, 1080),
    ("4", "3"): (1440, 1080),
    ("3", "4"): (1080, 1440),
}


def _motion_aspect_to_dim(template_stem: str) -> tuple[int, int] | None:
    """템플릿 파일명 끝 `_NxM` → (width, height) 매핑. 매칭 실패 시 None."""
    m = re.search(r"_(\d+)x(\d+)$", template_stem)
    if not m:
        return None
    return _MOTION_ASPECT_MAP.get((m.group(1), m.group(2)))


@functools.lru_cache(maxsize=1)
def _list_motion_templates() -> tuple[str, ...]:
    """tools/motion_graphics/templates/*.html 자동 스캔하여 사용 가능한 stem 목록 반환.

    제외: shared.css (확장자 다름), .pre_shared 백업 파일.
    LRU cache로 ingest 한 번 실행에서 중복 디스크 IO 방지.
    """
    here = Path(__file__).resolve().parent.parent / "motion_graphics" / "templates"
    if not here.exists():
        return tuple()
    stems = []
    for path in sorted(here.glob("*.html")):
        # 백업 파일 제외 (`*.html.pre_shared` → suffix=.pre_shared 가 아닌 .html)
        if ".pre_shared" in path.name:
            continue
        stems.append(path.stem)
    return tuple(stems)


@functools.lru_cache(maxsize=1)
def _load_sample_catalog() -> dict | None:
    """sample_catalog.json 로드. 없거나 깨졌으면 None.

    catalog가 없으면 validate가 strict-mode를 발동하지 않음 (post-migration
    grace period). catalog가 있으면 forbidden 검사 + sample_reviewed 권고.
    """
    catalog_path = Path(__file__).resolve().parent.parent / "motion_graphics" / "sample_catalog.json"
    if not catalog_path.exists():
        return None
    try:
        return json.loads(catalog_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _validate_motion_template(template_stem: str) -> tuple[bool, str | None]:
    """(is_valid, error_message). error_message 에는 후보 제안 포함.

    Catalog가 있으면 user_approved set로 엄격 검증. forbidden(no_sample_yet)
    template은 reject — 사용자가 sample을 지웠거나(별로) 아직 검증 안 된 것.
    """
    available = _list_motion_templates()
    if template_stem not in available:
        # 후보 제안 (유사도 0.5 이상)
        suggestions = difflib.get_close_matches(template_stem, available, n=3, cutoff=0.5)
        msg_parts = [f"motion_template '{template_stem}' 가 templates/ 에 없음."]
        if suggestions:
            msg_parts.append(f"비슷한 후보: {', '.join(suggestions)}")
        # aspect 추출 시도해서 같은 aspect의 다른 type 제안
        aspect_match = re.search(r"_(\d+x\d+)$", template_stem)
        if aspect_match:
            aspect = aspect_match.group(1)
            same_aspect = [s for s in available if s.endswith(f"_{aspect}")]
            if same_aspect and not suggestions:
                msg_parts.append(f"같은 aspect({aspect}) 가용: {', '.join(same_aspect[:5])}")
        return (False, " ".join(msg_parts))

    # HTML은 존재 — 이제 catalog에서 user_approved 여부 검사
    catalog = _load_sample_catalog()
    if catalog is None:
        return (True, None)  # catalog 없으면 grace mode (HTML 존재만 검증)

    entry = catalog.get("templates", {}).get(template_stem, {})
    if not entry.get("user_approved", False):
        forbidden = catalog.get("no_sample_yet", [])
        in_forbidden = template_stem in forbidden
        # 같은 시나리오 hint 가진 approved 후보 제안
        approved_stems = [
            s for s, e in catalog.get("templates", {}).items() if e.get("user_approved")
        ]
        same_aspect_approved: list[str] = []
        aspect_match = re.search(r"_(\d+x\d+)$", template_stem)
        if aspect_match:
            aspect = aspect_match.group(1)
            same_aspect_approved = [s for s in approved_stems if s.endswith(f"_{aspect}")]
        msg = (
            f"motion_template '{template_stem}' 는 "
            + ("forbidden 목록" if in_forbidden else "user_approved 아님")
            + " — sample이 없거나 사용자가 별로라 판단함. "
            "tools/motion_graphics/sample_catalog.json 확인 후 user_approved 목록에서 선택."
        )
        if same_aspect_approved:
            msg += f" 같은 aspect approved: {', '.join(same_aspect_approved[:5])}"
        return (False, msg)
    return (True, None)


def _render_motion_mov(
    motion_template: str,
    motion_params: dict,
    project_name: str,
    scene_idx: int,
) -> tuple[str, int, int]:
    """render_motion.py subprocess 호출 후 (mov_path, width, height) 반환.

    Raises:
      FileNotFoundError: 템플릿 파일 또는 render_motion.py 없음.
      ValueError: aspect 파싱 실패.
      subprocess.CalledProcessError: 렌더 실패.
    """
    here = Path(__file__).resolve().parent
    mg_dir = here.parent / "motion_graphics"
    template_file = mg_dir / "templates" / f"{motion_template}.html"
    if not template_file.exists():
        raise FileNotFoundError(
            f"motion_template '{motion_template}' 파일 없음: {template_file}"
        )

    dim = _motion_aspect_to_dim(motion_template)
    if dim is None:
        raise ValueError(
            f"motion_template '{motion_template}' aspect 파싱 불가. "
            f"파일명 끝에 _16x9 / _9x16 / _1x1 같은 suffix 필요."
        )
    w, h = dim

    out_dir = Path("output") / project_name / "broll_motion"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_base = out_dir / f"scene_{scene_idx:03d}_motion"

    render_script = mg_dir / "render_motion.py"
    if not render_script.exists():
        raise FileNotFoundError(f"render_motion.py 없음: {render_script}")

    print(
        f"[motion] scene {scene_idx}: rendering {motion_template} "
        f"→ {out_base.name}.mov ({w}x{h})",
        file=sys.stderr,
    )
    # Playwright는 보통 시스템 Python에만 설치돼 있음. ingest를 hermes/conda venv에서
    # 호출하면 sys.executable에 playwright 없음 → render 실패. 환경변수로 명시적 override.
    # 우선순위: $OMC_RENDER_PYTHON → 자동 탐색 (Windows: Python313) → sys.executable fallback
    render_python = os.environ.get("OMC_RENDER_PYTHON")
    if not render_python:
        # 자동 탐색: Windows 표준 경로
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python313" / "python.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python312" / "python.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python311" / "python.exe",
        ]
        for cand in candidates:
            if cand.exists():
                render_python = str(cand)
                break
    if not render_python:
        render_python = sys.executable  # last resort
    cmd = [
        render_python, str(render_script),
        "--template", str(template_file),
        "--params", json.dumps(motion_params, ensure_ascii=False),
        "--out-base", str(out_base),
        "--width", str(w),
        "--height", str(h),
        "--fps", "30",
    ]
    subprocess.run(cmd, check=True)
    mov_path = str(out_base.with_suffix(".mov").resolve())
    return mov_path, w, h


def _src_hint_hash(hint: str) -> str:
    """src_hint 변경 감지를 위한 short hash (12 chars)."""
    return hashlib.sha256(hint.encode("utf-8")).hexdigest()[:12]


def _hash_sidecar_path(image_path: Path) -> Path:
    """이미지 옆 사이드카 파일 (.src_hint_hash)."""
    return image_path.with_suffix(image_path.suffix + ".hint_hash")


def _read_cached_hint_hash(image_path: Path) -> str | None:
    """이미지와 함께 저장된 src_hint hash 읽기. 없으면 None."""
    sc = _hash_sidecar_path(image_path)
    if not sc.exists():
        return None
    try:
        return sc.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def _write_hint_hash(image_path: Path, hint: str) -> None:
    """이미지 생성 후 src_hint hash 기록 (다음 재생성 시 변경 감지용)."""
    sc = _hash_sidecar_path(image_path)
    sc.write_text(_src_hint_hash(hint), encoding="utf-8")


ROOT = Path(__file__).parent.parent.parent


# ===== CapCut B-roll style 어휘 =====

CAPCUT_STYLES = {
    "overlay": {
        "description": "1개 이미지, 상단 중앙 floating (화면 55%, 16:9 권장)",
        "use_cases": ["작은 참조용", "구체 제품/UI 슬쩍 보여주기", "숫자/메트릭 강조"],
        "aspect_ratio": "16:9",
        "max_images": 1,
    },
    "dual": {
        "description": "좌/우 2개 이미지 나란히 (각 42%)",
        "use_cases": ["비교/대조", "A vs B", "전후 상태"],
        "aspect_ratio": "1:1",
        "max_images": 2,
    },
    "split": {
        "description": "상단 영역 전체 덮기 + 메인 영상을 아래로 이동",
        "use_cases": ["화면 설명이 필수", "리스트/단계/체크", "핵심 UI 풀스크린"],
        "aspect_ratio": "16:9",
        "max_images": 1,
    },
}


# ===== B-roll 의사결정 트리 (skip-first 원칙) =====
#
# Round 2 통합 합의: "억지 B-roll 방지"가 최우선. 기본값은 skip이고,
# B-roll 추가는 예외적 결정. 두 조건을 **모두** 만족할 때만 B-roll 허용:
#   1. 관문 ≥ 1개 통과 (narration이 시각화할 구체 대상을 명명)
#   2. 안티패턴 0개 (아래 7개 중 어디에도 해당하지 않음)

DECISION_TREE = """
## B-roll Decision Tree (NEW 6-type system — 실사 사진 금지, split_stack 제거)

⛔ **실사 사진 전면 금지** (2026-04-21 개편):
  - `symbol_moment` / `number_hero` 완전 제거
  - `split_stack` 제거: 텍스트 나열은 emphasis 오버레이로 충분 (이미지 낭비)
  - 감정·분위기·추상 씬 → `decision: text_only`
  - 단일 숫자 강조 → `decision: text_only` + emphasis
  - 3-item 리스트 → `decision: text_only` + emphasis (씬마다 순차 배치)
  - 모든 비주얼은 flat editorial graphic (`graphic_insight`) 또는 actual screenshot (`ui_evidence`)로만

### 근본 원칙
**정말 시각 자산으로만 전달 가능한 순간에만 B-roll.**
텍스트만 있는 이미지 = emphasis 오버레이로 더 타이트하게 통제 가능.

### Step 1 — 관문 (≥1 통과해야 B-roll 후보)

| 관문 | Narration 예시 | DEFAULT type | 예외 (→ ui_evidence) |
|---|---|---|---|
| G1a | 단일 브랜드/앱 언급 ("노션에서", "카톡으로") | `icon_hero` | 특정 계정/content 언급 시 |
| G1b | 메시지/알림 맥락 ("카톡 왔어요") | `message_object` | "이 대화 보세요" 면 |
| G2a | 단일 숫자/통계 ("500만 건", "40%") | **decision: `text_only`** + emphasis | 특정 계정 프로필 지표면 |
| G2b | 숫자 비교 ("5,500→6,900") | `stat_card` | — |
| G3  | CTA 버튼 언급 | `icon_hero` (플랫폼 로고만) | — |
| G4  | 교과서 정의/개념 ("자이가르닉 효과") | **decision: `text_only`** 또는 `graphic_insight` | — |
| G5  | 3-item 리스트 | **decision: `text_only`** + emphasis (순차) | — |
| G6  | 양쪽 명명 비교 | `dual_icon` | — |
| G7  | 개념·상태·진행도 시각화 ("뇌는 4개만 기억") | `graphic_insight` | — |
| Atmos | 시간·의식·감정 (타이틀 후 첫 씬) | **decision: `text_only`** | — |

### Step 2 — 안티패턴 (1개라도 해당하면 SKIP)
A1 타이틀/무음/오프닝 씬
A2 추상 후킹 질문 ("왜 안 될까?")
A3 내러티브 setup ("어떤 사람이 있었어요")
A4 추상 결론/잠언 ("결국 중요한 건...")
A5 대명사/지시어만 ("이게 바로")
A6 필러/연결구 ("그런데", "사실", "근데")
A7 NG 의심 테이크 (반복, 말더듬)

### Step 3 — text_only 선택

관문 통과했지만 "이미지 없어도 narration이 자기 완결적"이면 `decision: text_only`.
이 경우 emphasis 텍스트 오버레이만 나오고 이미지는 생성 안 함.
예시:
- "본문이 아니라 제목에 시간 쓰는 게 진짜 생산성이에요"
  → text_only + emphasis "제목에 시간"
- "같은 회의인데 세 가지를 실천하면 돼요"
  → text_only (G5 3-item 리스트는 순차 emphasis로 처리, split_stack 제거됨)
- "500만 건" → text_only + emphasis "500만" (과거 number_hero 대체)
- "커피 한 잔" → text_only + emphasis (과거 symbol_moment 대체; 실사 금지)

### Step 4 — ui_evidence 판정

다음 **모두 AND**면 `ui_evidence` 우선:
1. 특정 플랫폼 + 특정 데이터 지목 ("@유니약사 278명", "이 터미널 출력")
2. 데이터가 가짜면 narration 가치가 없음 (진실성이 핵심)
3. 해당 플랫폼의 고유 UI 언어를 있는 그대로 표현 가능

허용되는 UI: Instagram / macOS Finder / Terminal / VSCode / Claude Code / YouTube / Gmail / 노션 / 토스 / 카톡 (실제 대화) / Twitter-X / Discord 등

금지: 가상 SaaS 대시보드, 가짜 회사 UI, 모방 제품 UI

### Step 5 — graphic_insight 판정

개념·상태·진행도·추상 관계를 **flat editorial graphic**으로 시각화하고 싶을 때.
실사 사진 대신 쓰는 유일한 옵션. 예시:
- "자이가르닉 효과(미완성 일감이 기억에 남음)" → 6개 체크박스 중 2개 체크, flat
- "뇌는 4개만 기억" → 4칸 박스 + 2칸만 채워짐, flat design
- "4개 vs 10개" (개념적 비교) → 두 숫자 flat graphic
  * 주의: `stat_card`는 **정량적 before→after**만 (5,500→6,900). 개념적 대조면 `graphic_insight`

---

## decision ↔ type 매핑 (style은 decision 레벨)

| decision | 이미지 생성 | 용도 |
|---|---|---|
| `skip` | 없음 | 안티패턴 해당 / B-roll 불필요 |
| `text_only` | 없음 | 관문은 통과했으나 emphasis만으로 충분 — 감정/숫자/개념 대부분 여기로 |
| `overlay` | 1장 | 단일 이미지 (icon_hero / stat_card / message_object / graphic_insight / ui_evidence) |
| `split` | 1장 | 상단 풀스크린 (graphic_insight / ui_evidence 등 — 시각 증빙이 필요한 풀스크린) |
| `dual` | 2장 | 좌우 2개 (dual_icon — A vs B) |

## 절대 원칙

1. **narration 1:1 대응**: src_hint의 구체물이 narration 단어와 **같은 씬** 안에 있어야 함
2. **추상어에 UI 금지**: "중요합니다"에 대시보드 금지
3. **한국어 텍스트만**: src_hint에 한국어 구체물 기술 (발신자/앱/레이블 등)
4. **emphasis는 1-3 단어**: narration 전체 복사 금지
5. **opacity는 decision이 결정**: split=1.0 (덮는 레이아웃), overlay=0.75, dual=0.75
6. **실사 photo 금지**: 감정/상황도 **실사 setup 금지** (symbol_moment 제거). text_only 또는 graphic_insight로.
7. **가짜 SaaS 금지**: ui_evidence는 **실제 존재하는 플랫폼** UI만. 가상 회사 대시보드 만들지 말 것
"""


# ===== Context 생성 =====

def build_context(
    transcript_path: Path,
    scenes_path: Path,
    out_path: Path,
    video_title: str = "",
) -> None:
    """transcript + scenes → Claude가 읽을 context markdown 생성"""
    with open(transcript_path, "r", encoding="utf-8") as f:
        transcript = json.load(f)
    with open(scenes_path, "r", encoding="utf-8") as f:
        scenes = json.load(f)

    scene_list = scenes.get("scenes", scenes if isinstance(scenes, list) else [])
    segments = transcript.get("segments", [])

    # scene_idx → narration 매핑
    scene_narrations = []
    for scene in scene_list:
        s_start = scene["start"]
        s_end = scene["end"]
        # 이 씬과 겹치는 segment들의 텍스트 수집
        words_in_scene = []
        for seg in segments:
            if seg["end"] < s_start or seg["start"] > s_end:
                continue
            for w in seg.get("words", []):
                if w["start"] >= s_start and w["end"] <= s_end:
                    words_in_scene.append(w["word"].strip())
        narration = " ".join(words_in_scene).strip()
        scene_narrations.append({
            "idx": scene["idx"],
            "start": s_start,
            "end": s_end,
            "length": s_end - s_start,
            "narration": narration or "(무음/짧은 씬)",
        })

    lines = []
    lines.append(f"# CapCut B-roll Plan Designer Context")
    if video_title:
        lines.append(f"\n**영상**: {video_title}")
    lines.append(f"\n**총 씬 수**: {len(scene_list)}")
    lines.append(f"**총 길이**: {scenes.get('duration', 0):.1f}초")
    lines.append("\n---\n")

    # 의사결정 트리
    lines.append("## 🎯 작업 내용")
    lines.append("")
    lines.append("아래 각 씬의 narration을 읽고 다음을 판단하세요:")
    lines.append("")
    lines.append("0. **기본값은 `skip`**. B-roll은 DECISION_TREE의 2단계 룰(관문 ≥1 AND 안티패턴 =0) 통과 시만.")
    lines.append("1. **B-roll 필요 여부** — 대다수 씬은 `skip`이어야 정상")
    lines.append("2. **skip이 아니면 src_hint 작성** (Gemini용 이미지 프롬프트)")
    lines.append("3. **emphasis 강조 단어 추출** (skip 씬에도 추가 가능, 1-3 단어만)")
    lines.append("")
    lines.append("결과를 `temp/<name>/_claude_broll_plan.json`에 작성 후 ingest 실행.")
    lines.append("")
    lines.append(DECISION_TREE)
    lines.append("")

    # Style 설명
    lines.append("## 📐 CapCut Style 상세\n")
    for style_name, info in CAPCUT_STYLES.items():
        lines.append(f"### `{style_name}`")
        lines.append(f"- {info['description']}")
        lines.append(f"- **권장 aspect_ratio**: {info['aspect_ratio']}")
        lines.append(f"- **용도**: {', '.join(info['use_cases'])}")
        lines.append("")

    # 씬별 narration
    lines.append("---\n")
    lines.append("## 🎬 씬별 narration (분석 대상)\n")
    for s in scene_narrations:
        lines.append(f"### Scene {s['idx']} ({s['start']:.1f}s ~ {s['end']:.1f}s, {s['length']:.1f}s)")
        lines.append(f"> {s['narration']}")
        lines.append("")

    # 작성 템플릿
    lines.append("---\n")
    lines.append("## 📝 작성 템플릿 (_claude_broll_plan.json)\n")
    lines.append("```json")
    lines.append(json.dumps({
        "title": {
            "text": "후킹되는 영상 제목",
            "accent_words": ["핵심단어"],
            "duration_sec": 4.0
        },
        "scenes": [
            {
                "scene_idx": 0,
                "decision": "skip",
                "reason": "A1 타이틀 구간 — title만으로 후킹"
            },
            {
                "scene_idx": 1,
                "decision": "skip",
                "reason": "A2 추상 후킹 질문 — emphasis만",
                "emphasis": {
                    "text": "왜 안 될까?",
                    "accent_words": ["왜"],
                    "start_offset_sec": 0.3,
                    "duration_sec": 2.5,
                    "position": "lower"
                }
            },
            {
                "scene_idx": 2,
                "decision": "skip",
                "reason": "A3 내러티브 setup — 일반명사만, 화자 오디오가 더 강함"
            },
            {
                "scene_idx": 3,
                "decision": "text_only",
                "reason": "G2a 단일 숫자 '40% 증가' — text_only + emphasis (number_hero 제거됨)",
                "emphasis": {
                    "text": "40% 증가",
                    "accent_words": ["40%"],
                    "start_offset_sec": 0.5,
                    "duration_sec": 3.0,
                    "position": "lower"
                }
            },
            {
                "scene_idx": 8,
                "decision": "overlay",
                "reason": "G7 개념 시각화 — '자이가르닉 효과' flat graphic",
                "broll": {
                    "type": "graphic_insight",
                    "src_hint": "6개 체크박스 중 2개만 체크됨, 나머지 4개는 열린 상태. flat vector, dark bg, white elements"
                },
                "emphasis": {
                    "text": "자이가르닉 효과",
                    "accent_words": ["자이가르닉"],
                    "start_offset_sec": 0.3,
                    "duration_sec": 3.2,
                    "position": "lower"
                }
            },
            {
                "scene_idx": 4,
                "decision": "text_only",
                "reason": "관문 통과했지만 narration이 자기 완결적 — emphasis만으로 충분",
                "emphasis": {
                    "text": "제목에 시간",
                    "accent_words": ["제목"],
                    "start_offset_sec": 0.3,
                    "duration_sec": 2.8,
                    "position": "lower"
                }
            },
            {
                "scene_idx": 7,
                "decision": "dual",
                "reason": "G6 양쪽 명명 비교 (노션 vs 옵시디언)",
                "brolls": [
                    {"type": "dual_icon", "src_hint": "Notion N logo"},
                    {"type": "dual_icon", "src_hint": "Obsidian purple gem logo"}
                ]
            },
            {
                "scene_idx": 12,
                "decision": "split",
                "reason": "G7 풀스크린 개념 시각화 (체크박스 진행도)",
                "broll": {
                    "type": "graphic_insight",
                    "src_hint": "6개 체크박스 중 2개 체크됨, 나머지 열린 상태. flat vector"
                }
            }
        ]
    }, ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## 🚨 검증 규칙\n")
    lines.append("- `type`은 반드시 **6-type** 중 하나: `icon_hero`, `stat_card`, `message_object`, `dual_icon`, `ui_evidence`, `graphic_insight`")
    lines.append("- `decision`은 `skip` / `text_only` / `overlay` / `split` / `dual` 중 하나")
    lines.append("- `text_only`는 이미지 생성 없이 emphasis만 — `broll` 필드 생략")
    lines.append("- 영어 이름/콘텐츠 절대 금지 (John Smith, Lorem Ipsum 등)")
    lines.append("- `dual`은 반드시 `brolls` 배열 길이 2")
    lines.append("- `overlay`/`split`은 `broll` 단일 객체")
    lines.append("- `decision: skip`은 `broll` 필드 생략 가능")
    lines.append("- scene_idx는 0부터 시작 (`scenes.json`과 일치)")
    lines.append("- ⛔ **실사 사진 금지**: `symbol_moment`·`number_hero`·webtoon 모두 제거됨")
    lines.append("- ⛔ **split_stack 제거**: 텍스트 나열은 emphasis 오버레이로 충분. 3-item 리스트는 `text_only` + 순차 emphasis")
    lines.append("- 감정/분위기/숫자 강조는 `decision: text_only`로, 개념 시각화는 `graphic_insight`로")

    # ===== Motion 카탈로그 주입 (NEW 2026-05-13) =====
    # sample_catalog.json을 읽어 LLM이 plan 작성 시 user_approved motion만
    # 선택하고, frame_thumbs PNG를 Read로 직접 시각 확인하도록 강제한다.
    _append_motion_catalog_section(lines)

    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"[save] context -> {out_path}")
    print(f"  scenes: {len(scene_list)}, narrated: {sum(1 for s in scene_narrations if s['narration'] != '(무음/짧은 씬)')}")


_CATALOG_PATH = Path(__file__).resolve().parent.parent / "motion_graphics" / "sample_catalog.json"


def _append_motion_catalog_section(lines: list[str]) -> None:
    """sample_catalog.json을 markdown으로 펼쳐 context에 주입.

    catalog가 없거나 깨졌으면 경고 섹션만 추가하고 LLM에게 build_catalog.py
    실행을 안내. catalog 없이 motion=true plan을 쓰면 ingest가 reject한다.
    """
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 🎬 Motion Template 카탈로그 (시각 확인 의무)")
    lines.append("")

    if not _CATALOG_PATH.exists():
        lines.append("⚠️ `sample_catalog.json` 없음. 먼저 빌드:")
        lines.append("```bash")
        lines.append("PYTHONIOENCODING=utf-8 python tools/motion_graphics/build_catalog.py")
        lines.append("```")
        lines.append("빌드 전에는 `motion: true` plan 작성 금지 (ingest reject됨).")
        return

    try:
        catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        lines.append(f"⚠️ catalog 로드 실패: {e}")
        lines.append("`tools/motion_graphics/build_catalog.py` 재실행 후 다시 시도하세요.")
        return

    approved = [
        (stem, entry)
        for stem, entry in catalog.get("templates", {}).items()
        if entry.get("user_approved")
    ]
    forbidden = catalog.get("no_sample_yet", [])

    lines.append("⛔ **결정 트리 (overlay 선택 시)**:")
    lines.append("")
    lines.append("1. 아래 ✅ 사용 가능 motion 중 시나리오 매칭 후보 2-3개 추리기")
    lines.append("2. **각 후보의 frame_thumbs PNG 3장(early/mid/end)을 Read 도구로 직접 확인**")
    lines.append("3. 콘텐츠 톤 ↔ 실제 시각 자산 매칭 비교 → 최종 선택")
    lines.append("4. plan에 `motion_template` + **`sample_reviewed: true`** + 비교 노트 명시")
    lines.append("")
    lines.append("⛔ **forbidden 목록 사용 시 ingest가 즉시 reject**. 사용자가 별로라 판단했거나")
    lines.append("아직 sample 검증이 안 된 template이므로 절대 선택하지 말 것.")
    lines.append("")
    lines.append(f"### ✅ 사용 가능 motion ({len(approved)}개, sample 시각 검증됨)")
    lines.append("")
    for stem, entry in approved:
        aspect = entry.get("aspect", "?")
        hints = entry.get("scenario_hints", []) or ["(시나리오 힌트 없음 — HTML 참조)"]
        params = entry.get("params_schema", [])
        thumbs = entry.get("frame_thumbs", [])
        lines.append(f"#### `{stem}` ({aspect})")
        lines.append(f"- 시나리오: {' / '.join(hints)}")
        if params:
            lines.append(f"- params: `{', '.join(params)}`")
        if thumbs:
            lines.append("- frame_thumbs (⭐ Read로 직접 시각 확인):")
            for t in thumbs:
                lines.append(f"  - `{t}`")
        sample_mov = entry.get("sample_mov")
        if sample_mov:
            lines.append(f"- 전체 sample MOV: `{sample_mov}`")
        lines.append("")

    if forbidden:
        lines.append(f"### ⛔ forbidden ({len(forbidden)}개 — 사용 금지)")
        lines.append("")
        lines.append("아래 motion은 sample이 없거나 사용자가 별로라 판단해 제거한 것. plan에 사용 시 ingest reject:")
        lines.append("")
        for stem in forbidden:
            lines.append(f"- `{stem}`")
        lines.append("")

    lines.append("### 📋 motion 사용 시 plan 필수 필드")
    lines.append("")
    lines.append("```jsonc")
    lines.append("{")
    lines.append('  "broll": {')
    lines.append('    "type": "...",                              // 6-type 중 하나')
    lines.append('    "motion": true,')
    lines.append('    "motion_template": "<approved_stem_only>",  // forbidden 목록 사용 금지')
    lines.append('    "motion_params": { ... },                    // params_schema 키만')
    lines.append('    "sample_reviewed": true,                     // ⭐ thumbs 3장 Read 완료 후 true')
    lines.append('    "sample_reviewed_notes": "early=..., mid=..., chose because ..."')
    lines.append("  }")
    lines.append("}")
    lines.append("```")
    lines.append("")
    lines.append("`sample_reviewed: false` 또는 누락 → ingest가 warning 출력 (현재 strict-mode 미설정).")


# ===== Ingest (검증 + broll_plan.json 출력) =====

def _check_broll_review_gate(plan_dir: Path) -> None:
    """3-persona review 게이트: plan 디렉토리에 broll_review.json이 존재하고
    pass:true 이어야 ingest 통과. 없거나 REJECT면 exit 2.

    Skip: `--skip-review` 플래그로 우회 가능 (ingest() 호출 전에 걸러짐).
    """
    review_path = plan_dir / "broll_review.json"
    if not review_path.exists():
        print(
            f"[ERROR] broll_review.json not found at {review_path}\n"
            f"        3-persona review가 필수입니다. 다음을 실행하세요:\n"
            f"          python tools/capcut_pipeline/broll_reviewer.py \\\n"
            f"            --plan {plan_dir / '_claude_broll_plan.json'} \\\n"
            f"            --out {review_path}\n"
            f"        또는 긴급시 `--skip-review` 플래그로 우회.",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        review = json.loads(review_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERROR] broll_review.json 파싱 실패: {e}", file=sys.stderr)
        sys.exit(2)
    if not review.get("pass"):
        verdict = review.get("verdict", "REJECT")
        issues = review.get("critical_issues", [])
        print(
            f"[ERROR] broll_review.json verdict={verdict} (pass=false).\n"
            f"        plan을 수정하거나 보조 프롬프트로 재생성한 후 재리뷰하세요.",
            file=sys.stderr,
        )
        if issues:
            print("        Critical issues:", file=sys.stderr)
            for it in issues[:10]:
                print(f"          - {it}", file=sys.stderr)
        sys.exit(2)


def ingest(
    claude_plan_path: Path,
    scenes_path: Path,
    out_path: Path,
    *,
    skip_review: bool = False,
) -> None:
    """_claude_broll_plan.json → broll_plan.json 검증 + 변환.

    ingest 전 3-persona review 게이트 통과 필수 (skip_review=False).
    """
    if not skip_review:
        _check_broll_review_gate(claude_plan_path.parent)

    with open(claude_plan_path, "r", encoding="utf-8") as f:
        claude_plan = json.load(f)
    with open(scenes_path, "r", encoding="utf-8") as f:
        scenes = json.load(f)

    scene_list = scenes.get("scenes", scenes if isinstance(scenes, list) else [])
    max_scene_idx = len(scene_list) - 1

    issues: list[str] = []

    # Title 검증
    title = claude_plan.get("title")
    if title and isinstance(title, dict):
        if not title.get("text"):
            issues.append("title.text 누락")
        elif len(title["text"]) > 20:
            issues.append(f"title.text 20자 초과: '{title['text']}' ({len(title['text'])}자)")

    # scenes 검증
    claude_scenes = claude_plan.get("scenes", [])
    if not claude_scenes:
        issues.append("scenes 배열 비어있음")

    # overlay_patcher 형식으로 변환
    items: list[dict[str, Any]] = []
    emphases: list[dict[str, Any]] = []

    for cs in claude_scenes:
        idx = cs.get("scene_idx")
        if idx is None:
            issues.append(f"scene_idx 누락: {cs}")
            continue
        if idx < 0 or idx > max_scene_idx:
            issues.append(f"scene_idx {idx} 범위 초과 (0~{max_scene_idx})")
            continue

        # NEW decisions: skip / text_only / overlay / split / dual
        # text_only = 이미지 생성 없이 emphasis만 (관문 통과했으나 자기 완결적 narration)
        decision = cs.get("decision")
        if decision not in ("skip", "text_only", "overlay", "dual", "split"):
            issues.append(f"scene {idx}: decision '{decision}' 잘못됨 (skip/text_only/overlay/dual/split)")
            continue

        # NEW 6-type whitelist (2026-04-21 — 실사 사진 금지, split_stack 제거).
        #   Removed: symbol_moment (실사 photo), number_hero (text_only로 대체),
        #            split_stack (텍스트 나열은 emphasis로 충분).
        #   Added:   graphic_insight (flat editorial 시각화).
        # LEGACY_HINTS는 broll_prompts 모듈에서 import (단일 진실 소스).
        sys.path.insert(0, str(Path(__file__).parent))
        from broll_prompts import TYPES as _TYPES, LEGACY_HINTS as _LEGACY_HINTS
        VALID_TYPES = set(_TYPES.keys())
        LEGACY_HINTS = _LEGACY_HINTS

        def _check_type(scene_idx: int, tp: str, where: str) -> None:
            if not tp:
                return
            if tp in LEGACY_HINTS:
                issues.append(
                    f"scene {scene_idx}: {where} type '{tp}' REMOVED. {LEGACY_HINTS[tp]}"
                )
                return
            if tp not in VALID_TYPES:
                issues.append(
                    f"scene {scene_idx}: {where} type '{tp}' not in 6-type whitelist "
                    f"{sorted(VALID_TYPES)}"
                )

        # B-roll item 변환
        if decision == "overlay":
            broll = cs.get("broll", {})
            tp = broll.get("type", "")
            motion = bool(broll.get("motion", False))

            # --- Motion B-roll branch (render MOV immediately) ---
            if motion:
                motion_template = broll.get("motion_template")
                motion_params = broll.get("motion_params", {}) or {}
                # ⭐ sample_reviewed 게이트 (NEW 2026-05-13)
                # LLM이 frame_thumbs PNG 3장을 Read한 후 명시적으로 true를 적었는지
                # 확인. 누락 시 경고 — 시각 검증 없이 cheat sheet 텍스트만으로
                # 고른 정황이라 plan 품질이 들쭉날쭉해진 케이스 방지.
                if not broll.get("sample_reviewed"):
                    print(
                        f"  [warn] scene {idx}: broll.motion=true인데 sample_reviewed 누락 — "
                        f"LLM이 {motion_template}의 frame_thumbs PNG를 Read 도구로 직접 확인했는지 검증 안 됨. "
                        "다음 plan부터 'sample_reviewed: true' + 'sample_reviewed_notes' 필드 작성 권장."
                    )
                if not motion_template:
                    issues.append(
                        f"scene {idx}: broll.motion=true인데 motion_template 누락. "
                        f"가용: {', '.join(_list_motion_templates()[:8])}..."
                    )
                    continue
                # 사전 검증 — 존재하지 않는 stem이면 후보 제안과 함께 reject
                ok, err = _validate_motion_template(motion_template)
                if not ok:
                    issues.append(f"scene {idx}: {err}")
                    continue
                # aspect 파싱 사전 검증 — _NxM 패턴 없으면 reject
                if _motion_aspect_to_dim(motion_template) is None:
                    issues.append(
                        f"scene {idx}: motion_template '{motion_template}' aspect 파싱 불가. "
                        f"파일명 끝에 _16x9 / _9x16 / _1x1 / _4x3 / _3x4 suffix 필요."
                    )
                    continue
                if not tp:
                    issues.append(f"scene {idx}: motion overlay인데 broll.type 누락")
                _check_type(idx, tp, "motion overlay")
                # Project name is the parent dir of _claude_broll_plan.json
                project_name = claude_plan_path.parent.name
                try:
                    mov_path, mov_w, mov_h = _render_motion_mov(
                        motion_template=motion_template,
                        motion_params=motion_params,
                        project_name=project_name,
                        scene_idx=idx,
                    )
                except (FileNotFoundError, ValueError) as e:
                    issues.append(f"scene {idx}: motion render setup error: {e}")
                    continue
                except subprocess.CalledProcessError as e:
                    issues.append(
                        f"scene {idx}: motion render failed (exit={e.returncode})"
                    )
                    continue
                items.append({
                    "scene_idx": idx,
                    "style": "overlay",
                    "image_path": mov_path,
                    "image_width": mov_w,
                    "image_height": mov_h,
                    "opacity": broll.get("opacity", 1.0),  # ProRes alpha MOV
                    "_src_hint": f"[motion] {motion_template}",
                    "_type": tp or "stat_card",
                    "_brand_key": broll.get("brand_key"),
                    "_motion": True,
                    "_motion_template": motion_template,
                })
                # ⚠️ FIX 2026-05-13: 과거에는 여기서 `continue` 했는데, 그러면
                # 아래 L939 emphasis 변환을 건너뛰어 motion 씬의 emphasis 4-5개가
                # 매번 broll_plan.json에서 누락됨. 이제 정적 분기를 else로 막고
                # fall-through 시켜 emphasis 변환에 도달하도록 변경. 정적 분기는
                # motion=False 케이스에서만 실행.

            else:  # not motion → Static PNG branch (existing Gemini flow)
                src_hint = broll.get("src_hint", "")
                if not src_hint:
                    issues.append(f"scene {idx}: overlay인데 broll.src_hint 누락")
                if not tp:
                    issues.append(f"scene {idx}: overlay인데 broll.type 누락 (6-type 중 하나)")
                _check_type(idx, tp, "overlay")
                items.append({
                    "scene_idx": idx,
                    "style": "overlay",
                    "image_path": broll.get("image_path", f"__AUTO_GENERATE__/scene_{idx:03d}.png"),
                    "image_width": broll.get("image_width", 1920),
                    "image_height": broll.get("image_height", 1080),
                    "opacity": broll.get("opacity", 0.75),
                    "_src_hint": src_hint,
                    "_type": tp or "icon_hero",
                    "_brand_key": broll.get("brand_key"),
                })

        elif decision == "split":
            broll = cs.get("broll", {})
            src_hint = broll.get("src_hint", "")
            tp = broll.get("type", "")
            if not src_hint:
                issues.append(f"scene {idx}: split인데 broll.src_hint 누락")
            if not tp:
                issues.append(f"scene {idx}: split인데 broll.type 누락 (6-type 중 하나)")
            _check_type(idx, tp, "split")
            # split은 상단 영역을 '전체 덮는' 레이아웃이라 투명도를 주면 아래
            # 메인 비디오가 비쳐 보여 이상하게 렌더됨. 기본 1.0으로 고정.
            items.append({
                "scene_idx": idx,
                "style": "split",
                "image_path": broll.get("image_path", f"__AUTO_GENERATE__/scene_{idx:03d}.png"),
                "image_width": broll.get("image_width", 1920),
                "image_height": broll.get("image_height", 1080),
                "opacity": broll.get("opacity", 1.0),
                "_src_hint": src_hint,
                "_type": tp or "graphic_insight",
                "_brand_key": broll.get("brand_key"),
            })

        elif decision == "dual":
            brolls = cs.get("brolls", [])
            if len(brolls) != 2:
                issues.append(f"scene {idx}: dual인데 brolls 배열 길이 != 2 (실제: {len(brolls)})")
                continue
            images = []
            src_hints = []
            types = []
            brand_keys = []
            for i, b in enumerate(brolls):
                sh = b.get("src_hint", "")
                btp = b.get("type", "")
                if not sh:
                    issues.append(f"scene {idx}: dual brolls[{i}].src_hint 누락")
                if not btp:
                    issues.append(f"scene {idx}: dual brolls[{i}].type 누락")
                _check_type(idx, btp, f"dual[{i}]")
                images.append({
                    "path": b.get("image_path", f"__AUTO_GENERATE__/scene_{idx:03d}_{i}.png"),
                    "width": b.get("image_width", 1080),
                    "height": b.get("image_height", 1080),
                })
                src_hints.append(sh)
                types.append(btp or "dual_icon")
                brand_keys.append(b.get("brand_key"))
            items.append({
                "scene_idx": idx,
                "style": "dual",
                "images": images,
                "opacity": brolls[0].get("opacity", 0.75),
                "_src_hints": src_hints,
                "_type": types[0] if types else "dual_icon",
                "_types": types,
                "_brand_keys": brand_keys,
            })

        # decision == "text_only": 이미지 생성 스킵, overlay_patcher는 emphasis만 주입.
        # items에 아무 것도 append 하지 않는다 — B-roll 트랙 비영향.

        # emphasis 변환
        emp = cs.get("emphasis")
        if emp and isinstance(emp, dict):
            if not emp.get("text"):
                issues.append(f"scene {idx}: emphasis.text 누락")
            else:
                emphasis_entry = {
                    "scene_idx": idx,
                    "text": emp["text"],
                    "accent_words": emp.get("accent_words", []),
                    "start_offset_sec": emp.get("start_offset_sec", 0.0),
                    "duration_sec": emp.get("duration_sec", 3.0),
                    "position": emp.get("position", "lower"),
                    "font_size": emp.get("font_size", 20),
                    "color": emp.get("color", "#FFFFFF"),
                    "accent_color": emp.get("accent_color", "#FFD54F"),
                    "stroke_width": emp.get("stroke_width", 0.04),
                    "font_name": emp.get("font_name", "Pretendard Black"),  # 2026-06-04: 기본 폰트 "아네모네"(userFontData 미등록) → "Pretendard Black"
                }
                emphases.append(emphasis_entry)

    if issues:
        print(f"[ERROR] validation issues ({len(issues)}):")
        for i in issues:
            print(f"  - {i}")
        sys.exit(2)

    # broll_plan.json 구조
    broll_plan: dict[str, Any] = {
        "items": items,
        "emphasis": emphases,
    }
    if title:
        broll_plan["title"] = title

    out_path.write_text(
        json.dumps(broll_plan, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"[save] broll_plan -> {out_path}")
    print(f"  items: {len(items)}")
    print(f"  emphasis: {len(emphases)}")
    print(f"  title: {'yes' if title else 'no'}")

    # 이미지 생성이 필요한 항목 안내
    auto_gen_count = sum(1 for it in items if any(
        "__AUTO_GENERATE__" in str(v)
        for v in (list(it.get("images", [{}]))[0].values() if "images" in it else [it.get("image_path", "")])
    ))
    if auto_gen_count:
        print(f"\n  [next] {auto_gen_count}개 이미지가 자동 생성 대기 중")
        print(f"         → scene_designer.py generate-images 실행")


# ===== 이미지 생성 (Gemini) =====

def generate_images(
    broll_plan_path: Path,
    out_dir: Path,
    force: bool = False,
    chroma_remove_enabled: bool = True,
) -> None:
    """broll_plan.json의 __AUTO_GENERATE__ 항목을 Gemini로 생성.

    Args:
        broll_plan_path: broll_plan.json 경로
        out_dir: 이미지 출력 디렉토리
        force: 기존 파일 덮어쓰기
        chroma_remove_enabled: 생성된 PNG에 자동으로 블루 크로마 제거 실행.
            기본 True. `--no-chroma-remove` 플래그로 디버깅 시 우회 가능.
    """
    # reels_pipeline의 Gemini 호출 재사용
    sys.path.insert(0, str(ROOT / "tools" / "reels_pipeline"))
    from broll_generator import generate_gemini_image, get_genai_client, load_env

    load_env()
    client = get_genai_client()

    with open(broll_plan_path, "r", encoding="utf-8") as f:
        plan = json.load(f)

    out_dir.mkdir(parents=True, exist_ok=True)

    generated = 0
    skipped = 0
    failed = 0
    # 새로 생성된 PNG 경로 (chroma_remove 대상). skip은 이미 처리된 것으로 간주.
    generated_paths: list[Path] = []

    # Load TYPES once so we can pick per-type aspect defaults.
    sys.path.insert(0, str(Path(__file__).parent))
    from broll_prompts import TYPES as BROLL_TYPES

    def _aspect_for_type(tp: str, style_fallback: str) -> str:
        meta = BROLL_TYPES.get(tp)
        if meta and meta.get("aspect_ratio"):
            return meta["aspect_ratio"]
        # Fallback by style if type unknown
        return "16:9" if style_fallback in ("overlay", "split") else "1:1"

    for item in plan.get("items", []):
        style = item.get("style")
        scene_idx = item.get("scene_idx")
        src_hint_single = item.get("_src_hint", "")
        src_hints_dual = item.get("_src_hints", [])
        # NEW 7-type (실사 사진 금지). Default icon_hero if missing.
        broll_type = item.get("_type", "icon_hero")
        brand_key_single = item.get("_brand_key")
        types_dual = item.get("_types", [])
        brand_keys_dual = item.get("_brand_keys", [])

        # style → 이미지 경로/힌트/타입/브랜드 수집
        if style in ("overlay", "split"):
            paths = [item.get("image_path", f"scene_{scene_idx:03d}.png")]
            hints = [src_hint_single] if src_hint_single else []
            per_types = [broll_type]
            per_brand_keys = [brand_key_single]
        elif style == "dual":
            paths = [img["path"] for img in item.get("images", [])]
            hints = src_hints_dual
            # dual은 각 side가 서로 다른 type일 수 있음
            per_types = types_dual if types_dual else [broll_type] * len(paths)
            per_brand_keys = (
                brand_keys_dual if brand_keys_dual else [None] * len(paths)
            )
        else:
            # text_only / skip 등은 애초에 items에 들어있지 않지만 방어적으로 skip
            continue

        for p, hint, tp, bk in zip(paths, hints, per_types, per_brand_keys):
            if not hint:
                continue
            # 경로 해석
            if "__AUTO_GENERATE__" in p:
                fname = p.split("/")[-1]
                target = out_dir / fname
            else:
                target = Path(p)

            # src_hint 변경 감지: 이미지 존재 + 해시 파일 있고 동일해야 skip
            current_hash = _src_hint_hash(hint)
            cached_hash = _read_cached_hint_hash(target) if target.exists() else None
            hint_changed = target.exists() and cached_hash is not None and cached_hash != current_hash
            hint_unknown = target.exists() and cached_hash is None  # 구버전 이미지 (해시 없음)

            if target.exists() and not force and not hint_changed:
                if hint_unknown:
                    print(f"  [skip] {target.name} 존재 (해시 미기록 — 재생성 원하면 --force)")
                else:
                    print(f"  [skip] {target.name} 존재 (해시 일치)")
                skipped += 1
                # skip이라도 plan 경로는 placeholder → 실제 경로로 업데이트해야 patcher가 찾을 수 있음
                if "__AUTO_GENERATE__" in p:
                    _update_image_path_in_plan(plan, scene_idx, style, p, str(target.resolve()))
                # 구버전(해시 없음)은 이번 기회에 해시 기록
                if hint_unknown:
                    _write_hint_hash(target, hint)
                continue

            if hint_changed:
                print(f"  [regen] {target.name} src_hint 변경 감지 (cached={cached_hash[:8]} vs new={current_hash[:8]})")

            # NEW — broll_prompts.build_prompt에 위임 (8-type)
            aspect = _aspect_for_type(tp, style)
            try:
                prompt = build_prompt_for_broll(tp, hint, brand_key=bk)
            except ValueError as e:
                print(f"  [fail] {target.name}: invalid type '{tp}' — {e}")
                failed += 1
                continue

            try:
                img_bytes = generate_gemini_image(client, prompt, aspect_ratio=aspect)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(img_bytes)
                _write_hint_hash(target, hint)
                print(f"  [ok] {target.name} ({len(img_bytes)//1024} KB, type={tp}, aspect={aspect})")
                generated += 1
                generated_paths.append(target)
                # broll_plan의 경로 업데이트
                _update_image_path_in_plan(plan, scene_idx, style, p, str(target.resolve()))
            except Exception as e:
                print(f"  [fail] {target.name}: {e}")
                failed += 1

    # 경로 업데이트된 plan 다시 저장
    broll_plan_path.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    print(f"\n=== Image Generation Summary ===")
    print(f"Generated: {generated}")
    print(f"Skipped:   {skipped}")
    print(f"Failed:    {failed}")

    # ===== 블루 크로마 자동 제거 (alpha 처리) =====
    # Gemini가 #0000FF로 채운 배경 → alpha=0 변환. CapCut에서 투명 PNG로 인식.
    if chroma_remove_enabled and generated_paths:
        print(f"\n=== Chroma Remove (blue #0000FF -> alpha) ===")
        try:
            sys.path.insert(0, str(Path(__file__).parent))
            from chroma_remove import remove_blue_chroma
        except ImportError as e:
            print(f"[warn] chroma_remove import failed: {e} — skipping alpha pass")
        else:
            chroma_ok = 0
            chroma_fail = 0
            for png_path in generated_paths:
                try:
                    stats = remove_blue_chroma(png_path)  # in-place
                    print(f"[chroma] {png_path.name} -> {stats['transparent_pct']}% transparent")
                    chroma_ok += 1
                except Exception as e:
                    print(f"[chroma-err] {png_path.name}: {e}")
                    chroma_fail += 1
            print(f"Chroma processed: {chroma_ok} ok, {chroma_fail} failed")
    elif not chroma_remove_enabled:
        print(f"\n[skip] chroma_remove disabled (--no-chroma-remove)")


def build_prompt_for_broll(type_name: str, src_hint: str, *, brand_key: str = None) -> str:
    """NEW 6-type 프롬프트 빌더 — broll_prompts 모듈에 위임.

    2026-04-21 실사 사진 전면 금지 + split_stack 제거:
      - Removed: symbol_moment (감정·분위기는 text_only), number_hero (숫자는 text_only),
                 split_stack (텍스트 나열은 emphasis로 충분)
      - Added: graphic_insight (flat editorial 시각화)

    Args:
        type_name: 6-type 중 하나 (icon_hero/stat_card/message_object/
                   dual_icon/ui_evidence/graphic_insight)
        src_hint:  Claude가 작성한 한국어 구체물 기술
        brand_key: (선택) brand_registry에 등록된 브랜드 키
    """
    sys.path.insert(0, str(Path(__file__).parent))
    from broll_prompts import build_prompt, validate_prompt

    prompt = build_prompt(type_name, src_hint, brand_key=brand_key)
    violations = validate_prompt(prompt)
    if violations:
        print(
            f"[warn] prompt contains banned phrases: {violations}",
            file=sys.stderr,
        )
    return prompt


# Backward-compat shim — old internal helper name.
# 2026-04-21: 실사 사진 금지. Use graphic_insight or text_only for legacy scenes.
def _build_capcut_broll_prompt(src_hint: str, broll_type: str, aspect: str) -> str:  # noqa: ARG001
    """Deprecated: aspect is now derived from TYPES[broll_type]. Delegates to
    build_prompt_for_broll for compatibility with older callers."""
    return build_prompt_for_broll(broll_type, src_hint)


def _update_image_path_in_plan(plan: dict, scene_idx: int, style: str, old_path: str, new_path: str) -> None:
    """plan 내부의 이미지 경로 업데이트"""
    for item in plan.get("items", []):
        if item.get("scene_idx") != scene_idx or item.get("style") != style:
            continue
        if style in ("overlay", "split"):
            if item.get("image_path") == old_path:
                item["image_path"] = new_path
        elif style == "dual":
            for img in item.get("images", []):
                if img.get("path") == old_path:
                    img["path"] = new_path


# ===== CLI =====

def main():
    ap = argparse.ArgumentParser(description="CapCut Scene Designer")
    sub = ap.add_subparsers(dest="cmd", required=True)

    ctx = sub.add_parser("context", help="Claude Code용 context markdown 생성")
    ctx.add_argument("--transcript", required=True, help="transcript.json (word timestamps)")
    ctx.add_argument("--scenes", required=True, help="scenes.json")
    ctx.add_argument("--out", required=True, help="output markdown path")
    ctx.add_argument("--title", default="", help="영상 제목 (선택)")

    ing = sub.add_parser("ingest", help="_claude_broll_plan.json → broll_plan.json")
    ing.add_argument("--input", required=True, help="_claude_broll_plan.json")
    ing.add_argument("--scenes", required=True, help="scenes.json (scene_idx 범위 검증용)")
    ing.add_argument("--out", required=True, help="broll_plan.json 출력 경로")
    ing.add_argument(
        "--skip-review",
        action="store_true",
        help="3-persona review 게이트 우회 (긴급시만. 일반 플로우에서는 broll_reviewer.py PASS 필수)",
    )

    img = sub.add_parser("generate-images", help="broll_plan의 __AUTO_GENERATE__ 이미지 생성")
    img.add_argument("--plan", required=True, help="broll_plan.json")
    img.add_argument("--out-dir", required=True, help="이미지 출력 디렉토리")
    img.add_argument("--force", action="store_true", help="기존 파일 덮어쓰기")
    img.add_argument(
        "--no-chroma-remove",
        action="store_true",
        help="블루 크로마(#0000FF) 자동 alpha 처리 비활성화 (디버깅용). "
             "기본은 on — 생성된 PNG가 CapCut에서 투명 오버레이로 동작하려면 필수.",
    )

    rvc = sub.add_parser("review-context", help="에이전트팀 리뷰용 context markdown 생성 (4관점 평가 가이드)")
    rvc.add_argument("--plan", required=True, help="_claude_broll_plan.json (검토 대상)")
    rvc.add_argument("--scenes", required=True, help="scenes.json")
    rvc.add_argument("--transcript", required=True, help="transcript.json")
    rvc.add_argument("--out", required=True, help="output markdown path")

    rvi = sub.add_parser("review-ingest", help="_claude_review.json → PASS/REJECT 판정")
    rvi.add_argument("--input", required=True, help="_claude_review.json (Claude가 4관점으로 점수 + 피드백 작성)")

    args = ap.parse_args()

    if args.cmd == "context":
        build_context(
            Path(args.transcript),
            Path(args.scenes),
            Path(args.out),
            video_title=args.title,
        )
    elif args.cmd == "ingest":
        ingest(
            Path(args.input),
            Path(args.scenes),
            Path(args.out),
            skip_review=args.skip_review,
        )
    elif args.cmd == "generate-images":
        generate_images(
            Path(args.plan),
            Path(args.out_dir),
            force=args.force,
            chroma_remove_enabled=not args.no_chroma_remove,
        )
    elif args.cmd == "review-context":
        sys.path.insert(0, str(Path(__file__).parent))
        from plan_reviewer import build_review_context
        build_review_context(
            Path(args.plan),
            Path(args.scenes),
            Path(args.transcript),
            Path(args.out),
        )
    elif args.cmd == "review-ingest":
        sys.path.insert(0, str(Path(__file__).parent))
        from plan_reviewer import review_ingest
        passed = review_ingest(Path(args.input))
        sys.exit(0 if passed else 2)


if __name__ == "__main__":
    main()
