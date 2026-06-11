---
name: capcut-broll
description: CapCut B-roll 자동 설계 + 3-persona 리뷰 + 블루 크로마 이미지 생성 + overlay 패치. 6-type 분류학 (실사 사진·순수 텍스트 나열·단일 숫자 이미지 전면 금지) + flat editorial / typography / screenshot-only 미학 + `text_only` 의사결정 + 블루 크로마 파이프라인 + 3스타일 오버레이(overlay/dual/split) 단일 소스.
---

# CapCut B-roll Skill ⭐

---

## ⛔⛔ 반-클리셰 원칙 (2026-06-04 — 최우선, 코드 게이트로 강제)

> "맨날 똑같은 뻔한 b-roll·구도 부적절" 컴플레인 대응. `broll_reviewer._pre_filter_plan`이 **SDK 없이도 결정론적으로** 아래를 강제(위반 시 ingest 차단 — 플래너 self-pass에 의존하지 않음).

| # | 규칙 | 코드 강제 |
|---|---|---|
| 1 | **글자 카드 = 자막 중복 = 뻔함.** "검은 카드 + 멋부린 글자"는 화면 emphasis 자막과 정보량 동일. **기본 `text_only` + emphasis.** 무지개 그라데이션·파티클 장식 글자카드는 만들지 않는다(단일 accent 위반). 풀스크린 글자 강조가 꼭 필요하면 `kinetic_type_9x16` | ✅ 글자만 카드면 reject |
| 2 | **같은 type/template 2회 반복 금지** — 한 영상에서 동일 motion_template·동일 6-type 중복 금지 | ✅ reject |
| 3 | **검은 카드만 금지** — overlay 2개+면 최소 1개는 **실제 시각 정보**(`ui_evidence` 진짜 UI / `line_chart`·`bar_chart`·`metric_ring` 데이터). 전부 글자/체크박스 카드면 단조 | ✅ reject |
| 4 | **주제 적합 — 기술/AI/툴/빌딩 영상은 `ui_evidence` 1순위.** "AI로 만든다·자동화·서비스·코드·터미널"이면 추상 글자 카드 대신 **실제 작업 화면**(claude_code/terminal/notion) | (planner 판단 + 규칙 3이 뒷받침) |
| 5 | **영상 간 반복 금지("맨날 똑같은")** — 직전 영상 template 집합과 완전히 겹치면 reject. ledger: `tools/capcut_pipeline/.broll_usage_log.json` (ingest가 자동 기록) | ✅ reject |
| 9 | **non-generic reason 게이트** — overlay `reason`이 막연한 일반구('강조를 위해'·'시각적으로'·'임팩트'·'분위기')뿐이면 **렌더(느림/비쌈) 전에 자동 reject.** 정확한 한국어 구절 인용·UI·숫자·전후 비교·단계 키워드 등 **구체 사유 필수** (teach-test = "자막으로 못 하는 무엇을 보여주나"). 자세한 작성 규칙은 §reason 작성 규칙 | ✅ reject |

### 🎯 구도 규칙 (9:16 토킹헤드 — 얼굴/자막 침범 금지)

- overlay는 **상단(얼굴 위)** 고정. 화면 정중앙 = 인물 얼굴 → 카드로 덮지 말 것 (과거 "내 안의 DNA" 사고: 장식 카드가 얼굴 정통으로 덮음).
- 하단은 자막(y≈-0.234) + emphasis zone → overlay 내려오면 안 됨.
- emphasis position: overlay 있는 씬 = `lower`, 없는 씬 = `top`.

### 자가 점검 (plan Write 직전 — 위 코드 게이트 통과 전 필수)

1. 내 overlay 중 "글자만 있는 카드"가 있나? → text_only로 내려라.
2. 같은 type/template 두 번 썼나? → 하나를 다른 것으로.
3. overlay 전부 검은 카드인가? → 최소 1개를 실제 UI/데이터로.
4. 이 영상 주제가 기술/AI인데 ui_evidence를 안 썼나? → 1순위로 재검토.
5. 직전 영상이랑 똑같은 template 조합인가? → 최소 1개 교체.
6. ⛔ 무지개/파티클 장식 글자카드를 만들려 했나? → 만들지 않는다(원칙). kinetic_type_9x16 또는 text_only로 대체 (아래 §반-클리셰 v2).
7. 긴 씬(7s+)에 overlay를 끝까지 박제했나? → `start_offset_sec`/`display_dur_sec`로 짧게, 중간 강조는 emphasis로 (아래 §타이밍).
8. 영상 전체에서 accent 색을 2색 이상 섞었나? → **영상당 accent 1색** 고정 (아래 §accent 팔레트).
9. overlay `reason`이 막연한 일반구('강조'·'시각적'·'임팩트'·'분위기')뿐인가? → 구체 사유로 교체(렌더 전 자동 reject, Rule 9 / §reason 작성 규칙).

---

## ⛔⛔ 반-클리셰 v2 (2026-06-04 — overlay 타이밍·구도·신규 archetype·accent 단일화)

> 위 반-클리셰 원칙을 **타이밍·구도·신규 자산·색 변별력**으로 확장. 모든 신규 plan 필드는 **optional + default가 기존 동작 보존**(하위호환). 미지정 시 과거와 100% 동일하게 동작한다.

### 🆕 신규 plan 필드 (overlay item — 전부 optional, 하위호환)

`_claude_broll_plan.json`의 `scene.broll`(및 ingest 후 `broll_plan.json` items[])에 아래 필드를 **추가 가능**. 미지정 시 default가 기존 동작.

| 필드 | 타입 | default | 의미 |
|---|---|---|---|
| `start_offset_sec` | float | `0.0` | overlay 등장 시점(씬 시작 기준 초). `0`이면 현재처럼 씬 첫 프레임 등장. |
| `display_dur_sec` | float\|null | `null` | overlay 표시 길이(초). null이면 **motion MOV=intrinsic 길이**, static PNG=글자수 기반 자동(`len/13 + 0.7s`, 2.5~7s clamp). 항상 `min(씬 잔여길이)`로 clamp. |
| `position_y` | enum | `"top"` | 세로 위치 **슬롯**(자유 float 금지, 슬롯명만). 값: `"top"` / `"center"` / `"lower"`. |
| `overlay_h_ratio` | float | `0.55` | 가로 점유 비율(기존 `ratio`와 동일 의미). 기존 `ratio`도 하위호환으로 읽되 `overlay_h_ratio`가 우선. |
| `anchor_phrase` | string\|null | `null` | **speech-anchor.** 화자가 그 시점 말하는 정확한 구절. 지정 시 overlay_patcher가 `transcript.json` word 타임스탬프에서 그 구절을 찾아 `start_offset_sec`를 **실측 단어 경계로 자동 스냅**(LLM 추정 대체). 못 찾으면 기존 값 유지(graceful). 상세는 §speech-anchor. |

> 좌표 매핑(슬롯→`transform.y`)·zone 충돌 가드는 **overlay_patcher가 소유**. 플래너는 슬롯명/숫자만 의미에 맞게 적으면 됨. 셋 다 안 적으면 = 과거 동작.

### 🎯 speech-anchor — `anchor_phrase`로 등장 타이밍 자동 스냅 (overlay_patcher 구현)

overlay/emphasis 비트에 `"anchor_phrase": "화자가 그 시점 말하는 정확한 구절"`을 넣으면, overlay_patcher가 `transcript.json` word 타임스탬프에서 그 구절을 찾아 `start_offset_sec`를 **실측 단어 경계로 자동 스냅**한다(LLM 추정 타이밍 대체).

- ⚠️ **STT 원문에 실제 등장하는 표현으로 적어야 매칭됨** — 교정/영문복원 *전* 원문 표기(예: STT의 "디엔엘"으로, 영문복원 "DNA" 아님).
- 못 찾으면 기존 `start_offset_sec` 유지(graceful — 깨지지 않음).
- 좌표계는 **clean 타임라인(전역 배속 전)** 기준.

**예시 (긴 씬에서 overlay를 늦게 등장시키고 짧게)**:
```jsonc
{
  "scene_idx": 12,
  "decision": "overlay",
  "type": "ui_evidence",
  "broll": {
    "motion": true,
    "motion_template": "ui_evidence_terminal_16x9",
    "motion_params": { /* ... */ },
    "start_offset_sec": 1.8,     // 나레이션 핵심 비트에 맞춰 1.8s 뒤 등장
    "display_dur_sec": 3.5,      // 3.5s만 보이고 사라져 패턴 인터럽트(긴 박제 방지)
    "position_y": "top",          // 얼굴 위 상단 슬롯 (9:16 안전)
    "overlay_h_ratio": 0.55
  }
}
```

### 🎯 position_y 9:16 안전슬롯 가이드 (CE-02 — 얼굴/자막 회피)

CapCut 좌표: `transform.y` 양수=위쪽, 음수=아래쪽. 자막 y≈**-0.234**(하단). 정적 토킹헤드 가정 시 **얼굴 세이프존 = 정중앙 normalized -0.15 ~ +0.15**.

| 슬롯 | 위치 | 언제 | 주의 |
|---|---|---|---|
| `"top"` ✅ | 상단 — **얼굴 위** | **기본·권장.** 토킹헤드 9:16의 정석 슬롯 | 카드 높이 따라 살짝 내려도 얼굴존(-0.15) 침범 금지 |
| `"center"` ⚠️ | 화면 정중앙 | **비권장.** 얼굴 정통으로 덮음 | CE-03 가드가 경고 + 상단 push. "내 안의 DNA" 사고(장식 카드가 얼굴 덮음) 재발 방지 |
| `"lower"` | 자막 **바로 위** 빈 공간 | 얼굴을 비우고 싶고 자막과 겹치지 않을 때 | 자막존(-0.234) 침범 금지 — 카드 하단이 -0.20 위에 오게. emphasis 'lower'와 동시 사용 시 겹침 주의 |

**원칙**: 9:16 토킹헤드는 **`top`이 기본**. 같은 영상에서 모든 overlay가 한 자리(상단 22.5%)에만 박히면 구도가 단조 → **씬 의미에 따라 슬롯을 의도적으로 변주**(단 얼굴/자막 회피는 항상 우선). overlay_patcher가 카드 bbox로 얼굴/자막 zone 침범을 검사해 침범 시 상단 push + stderr 경고(CE-03).

### ⏱ 타이밍 — 긴 씬은 overlay 짧게, 중간 강조는 emphasis로 (CE-01)

- **문제**: 과거엔 overlay가 항상 씬 첫 프레임 고정 + 씬 전체 길이 재생이라, **긴 씬(7s+)에서 카드가 끝까지 박제**되어 '변화 없음' 신호 + title 겹침이 발생했다.
- **해법**:
  - overlay 등장을 나레이션 핵심 비트에 맞추려면 `start_offset_sec`로 늦게 등장.
  - 짧게 보이고 사라지는 패턴 인터럽트를 원하면 `display_dur_sec`로 명시(MOV는 intrinsic 길이가 기본이라 보통 자동으로 짧음, static PNG는 글자수 기반 자동).
  - **씬 중간 시점의 강조는 overlay가 아니라 `emphasis`(start_offset_sec/duration_sec)로.** overlay는 비디오라 씬 시작점 고정이 안전하고, 중간 시점 강조는 emphasis가 정공법(기존 메모리: overlay는 start_offset 미지원, 긴 씬 중간 강조는 emphasis).
- **하위호환**: 셋 다 미지정 시 = 씬 첫 프레임 등장 + (MOV intrinsic 또는 씬 전체) 길이로 과거와 동일.

### 🆕 신규 archetype cheat sheet (TL-02/03/04 + comparison)

기존 variant 표에 더해 아래가 추가된다. **언제 쓰나**를 정독하고, 사용 전 다른 motion과 동일하게 **frame_thumbs 3장(early/mid/end) Read 시각 검증**(catalog에 sample 등록 후).

| 신규 stem | aspect | 언제 쓰나 | 대체하는 클리셰 | 주의 |
|---|---|---|---|---|
| **`comparison_9x16`** ⭐ (2026-06-05) | 9:16 | **A vs B 다항목 대비** (소비 vs 빌더, Broke vs Rich 류). 2열 — 좌(부정/before, dim+붉은 accent) ↔ 우(긍정/after, 흰색+초록 accent), 각 열 제목 + 항목(첫 항목 pill), 중앙 VS 노드. 투명 오버레이(text-shadow 가독). 순차 등장(좌→우) | dual_icon(로고 2개뿐)·stat_card(숫자뿐)로 못 하던 **개념 대비 리스트**. "두 부류/습관/방식 대조" 씬 | params: `left_title`, `right_title`, `left_items[]`(2-3), `right_items[]`(2-3), `duration`. 좌=부정/우=긍정 의미 고정. substance로 인정됨(_SUBSTANCE_TEMPLATE_PREFIXES). 풀프레임 takeover라 overlay_h_ratio 0.9 전후 + position_y center 권장 |
| **`kinetic_type_9x16`** ⭐ | 9:16 | **감정/주장/결론 한 줄을 풀스크린으로 리듬있게.** 어절 mask-reveal(translateY 100%→0) + accent_words만 형광펜 underline(흰 텍스트 유지). 9:16 세로 영상의 **풀스크린 키네틱 타이포** | 무지개/파티클 장식 글자카드 + 감정 씬이 전부 text_only로 떨어지던 문제 | accent **1색**만. 다색 그라데이션 금지. 한국어 어미/조사 semantic wrap 준수. (v1은 swap 미포함 — 어절 reveal + underline만) |
| **`device_mockup_9x16`** ⭐ | 9:16 | **실제 스크린샷을 폰/브라우저 프레임에 삽입** (Ken Burns scale 1.0→1.08 + clip-path 리빌). 손으로 그린 fake-UI(ui_evidence)보다 물성·신뢰감 큼 | 합성 fake-UI의 "물성 부재" | params에 `device`("phone"\|"browser"), `image_path`(file:// 절대경로), `caption`, `camera_move`, `duration`. **실제 캡처 파일 있을 때만**, 없으면 ui_evidence/text_only로 폴백. **실사 사진 금지 정책 유지** — UI 스크린샷만 허용 |
| **brand SVG 레지스트리** (`brand_logos.js`) | 1:1/16:9 | `logo_marquee_16x9`/`icon_hero_1x1`/`orbiting_circles_1x1`가 params의 **brand key**로 진짜 SVG 로고를 주입 | "단일 글자 이니셜 색타일 = 색 스와치 보드처럼 촌스러움" | 초기 등록은 고빈도 3-4개(Claude/ChatGPT/Notion)만 정확한 path, 미등록 브랜드는 이니셜 타일 폴백. chroma blue(#0000FF) 근처색 회피 |

**ui_evidence vs device_mockup 선택 기준 (Step 4 보강)**: **실제 캡처 파일(스크린샷)이 있으면 `device_mockup_9x16`**(프레임에 삽입), **재현/합성이면 기존 `ui_evidence`**(손으로 그린 UI). image_path 미준비면 device_mockup 쓰지 말고 ui_evidence 또는 text_only로.

### 🆕 신규 archetype 2종 (TL-05/06, 2026-06-04)

| 신규 stem | aspect | 언제 쓰나 | 대체하는 클리셰 | 주의 |
|---|---|---|---|---|
| **`ui_evidence_comment_input_9x16`** ⭐ | 9:16 | **CTA('댓글에 X 남겨주세요')를 "한 사람이 입력창에 X를 타이핑 → 게시 버튼 활성화"로.** params: `label`/`placeholder`/`text`/`button_label`/`accent`/`duration` | `ui_evidence_youtube_comment`의 "이미 달린 가짜 댓글 3개 + 1.2천 social proof" (영상 주제와 무관·뻔함) | **CTA는 시청자가 *할 행동*을 보여줘야** — 남이 단 댓글 목록이 아님. `ui_evidence_` prefix라 substance 인정. **card_opacity 기본 1.0(불투명)** — 2026-06-09부터 UI 화면은 불투명(아래 § card_opacity) |
| **`dna_helix_9x16`** ⭐ | 9:16 | **"강점/유전/타고남" 은유를 DNA 이중나선으로** (흰+accent 두 가닥 stroke-draw + rungs 순차). params: `title`/`accent_word`/`sub`/`accent`/`duration` | 추상 은유를 글자카드로 때우던 것 | accent 1색. narration이 "DNA처럼/타고난" 명시할 때만 1:1. **`card_opacity:0`으로 나선만 떠서 인물 안 가림** |

### 🆕 신규 archetype 3종 (TL-07/08/09 — split_reveal·ratio_dots·vertical_timeline)

catalog 등록·user_approved·substance 인정 완료. **글자카드 아님 — substance로 인정**(broll_reviewer `_SUBSTANCE_TEMPLATE_PREFIXES`에 `split_reveal`/`ratio_dots`/`vertical_timeline` 추가). 공통: `.card` 미사용(자체 panel 배경 → **card_opacity override 무관**), accent **1색(보라)**, Pretendard, `shared.css`+`shared_motion.js`. (`split_reveal`·`vertical_timeline`은 **9:16 1080×1920 MOV** — 정사각 카드를 9:16 프레임 상단 band에 그려 얼굴 중앙·하단 자막 zone을 비운다. 모션 scale은 1.0 풀프레임 고정이고, 카드의 작은 크기·상단 위치는 템플릿 레이아웃이 담당.)

| 신규 stem | aspect | 언제 쓰나 | 대체하는 클리셰 | params |
|---|---|---|---|---|
| **`split_reveal_9x16`** ⭐ | 9:16 | **전→후 상태 전환 와이프.** 보라 디바이더가 좌→우로 쓸고 지나가며 BEFORE 텍스트→AFTER 텍스트로 swap. "혼란→정돈","능력부족→강점자리","과거→현재" 전환 비트. **정사각 카드를 9:16 상단 band에 배치(얼굴 안 가림). 모션 scale 1.0 풀프레임 — 카드 위치는 템플릿이 담당** | `comparison_9x16`(텍스트 2열 정적 대비)이 못 하는 **공간 와이프 전환** | `before_text`, `after_text`, `before_label`(기본"전"), `after_label`(기본"후"), `accent`, `duration` |
| **`ratio_dots_9x16`** ⭐ | 9:16 | **비율을 셀 수 있는 점 그리드.** total개 중 filled개가 accent로 켜짐. "10명 중 7명","6만 생각 중 80%" 류 심리 통계 | `stat_card`(단일 숫자)/`metric_ring`(퍼센트 링)이 못 하는 **'개수로 세기'** | `total`(기본10), `filled`(기본7), `headline`, `caption`, `accent`, `duration` |
| **`vertical_timeline_9x16`** ⭐ | 9:16 | **VO 동기 세로 단계 진행선.** 레일 head가 아래로 그려지며 도달 순간 dot 켜짐. "인식→수용→행동","1→2→3단계" 단계 설명. **정사각 카드를 9:16 상단 band에 배치(얼굴 안 가림). 모션 scale 1.0 풀프레임 — 카드 위치는 템플릿이 담당** | `graphic_insight`(정적 체크리스트)와 다른 **'흐르는' 진행** | `steps`(`["인식","수용","행동"]` 또는 `[{label}]`), `title`(선택), `accent`, `duration` |

> ℹ️ **`vertical_timeline_9x16`·`split_reveal_9x16`은 9:16 1080×1920 MOV** — 정사각 카드를 9:16 프레임 상단 band에 그려 얼굴 중앙·하단 자막 zone을 비운다. ⛔ 모션 scale은 1.0 풀프레임 고정(overlay_patcher 강제)이라 `position_y`/`overlay_h_ratio`로 카드를 작게/상단으로 옮기지 말 것(CapCut scale 의미와 충돌). "작은 정사각 카드 상단 배치"는 scale/position이 아니라 템플릿 레이아웃이 책임진다. 긴 씬 중간 박제 방지는 여전히 `start_offset_sec`/`display_dur_sec`로 제어.

### ⛔⛔ params는 template HTML `__params`를 직접 Read (catalog schema 불신) — RV-01 (2026-06-04)

> "B-ROLL 완전 이상해"(beam이 "A/B" 빈 라벨, youtube_comment가 "1200" 빈 댓글로 깨짐) 원인: `sample_catalog.json`의 `params_schema`가 불완전(youtube_comment 실제론 `comments[]` 배열, beam `left`/`right`는 `{symbol,label,bg,color}` 객체) + sample thumbnail(기본 params)만 보고 커스텀 렌더 미확인. → catalog schema 불신, HTML `__params` 직접 확인.

1. **params 작성 전**: `tools/motion_graphics/templates/<stem>.html`의 `const P = window.__params || {...}` 블록을 **Read해서 정확한 키·타입(문자열/객체/배열) 확인**. catalog `params_schema`는 참고만.
2. **ingest 렌더 후 (overlay_patcher 전, HARD)**: `output/<name>/broll_motion/scene_NNN_motion.mp4`에서 mid/end 프레임을 `ffmpeg ... -vf "select=eq(n\,135)"`로 추출 → **Read로 직접 시각 확인**. fallback 기본값("A"/"B")·빈 카드·깨진 숫자면 params 오류 → HTML `__params` 재확인 → plan 수정 → 기존 MOV 삭제 → ingest 재실행.
3. **신규 template 제작 시**: HTML 작성 → `render_motion.py`로 직접 렌더 + 프레임 Read 확인 → 만족하면 `out/sample_<stem>.mov`로 등록 → `build_catalog.py` → ingest. **substance로 인정받으려면 stem이 `ui_evidence_`/`line_chart`/`bar_chart`/`metric_ring`/`animated_beam`/`device_mockup` 등 `_SUBSTANCE_TEMPLATE_PREFIXES`로 시작해야 함.**

### 🎯 B-roll 선정 기준 — 추상 콘텐츠는 절제 (SEL-01, 2026-06-04)

> 사용자: "B-ROLL 선정 기준이 뭐야. 전혀 안 맞아." → 게이트(overlay 3개 하한선·substance 1개)를 맞추려고 **추상 자기계발/심리 콘텐츠에 억지 도식(beam 등)을 끼워넣은 게 화근.**

- **추상 개념/질문/결론/감정 씬** (회의-문서 대조, 게으름, 강점 차이, 빛남, "~어디지?") → **text_only + emphasis가 정답.** 억지 overlay/도식 금지 (근본 원칙: Silence > Noise).
- **CTA** → 가짜 social proof(댓글 목록·구독자 숫자)가 아니라 **시청자가 할 행동 자체**를 보여줌 (`ui_evidence_comment_input` 타이핑).
- **이 영상의 핵심 시각 모티프/키워드** (예: "강점은 DNA처럼" + CTA "디엔에이" → DNA 나선) → overlay 정당.
- **overlay 개수 하한선(3개)보다 콘텐츠 적합도가 우선.** 추상 영상은 overlay 1-2개가 정직할 수 있음 — type 다양성(Rule 4b)·substance(Rule 6) 충족하는 선에서. 억지 3번째는 "전혀 안 맞아"를 부른다.

### ✍️ reason 작성 규칙 — non-generic 게이트 (Rule 9)

overlay마다 `reason`은 **렌더 전에** broll_reviewer `_pre_filter_plan`이 검사한다. teach-test: **"자막(emphasis)으로 못 하는 무엇을 이 overlay가 보여주는가?"**에 구체적으로 답해야 통과.

- ⛔ **막연한 일반구만 = 자동 reject**: '강조를 위해', '시각적으로', '임팩트', '분위기', '눈길을 끌려고' 등.
- ✅ **구체 사유 필수** — 다음 중 하나 이상을 reason에 담는다:
  - **정확한 한국어 구절 인용** (narration의 실제 문장/단어)
  - **UI/플랫폼 지목** ("터미널 출력", "노션 회의록 화면")
  - **숫자/통계** ("47장→1개", "10명 중 7명")
  - **전후 비교 / 단계** ("혼란→정돈 전환", "인식→수용→행동 3단계")
- 예) ❌ `"임팩트 있게 강조"` → 🚫 reject. ✅ `"'47장 지원에 합격 1개' 숫자 대비 — 자막은 동시 표시 못 함"` → 통과.

### ⛔ 디자인 원칙 — 무지개/파티클 장식 글자카드 금지 (TL-01)

> **무지개 그라데이션·파티클 장식 글자카드는 만들지 않는다** (자막 중복·단일 accent 위반). 풀스크린 글자 강조는 **`kinetic_type_9x16`**, 단순 강조는 **`text_only` + emphasis**.

- 다색 그라데이션 sweep / 파티클 twinkle은 단일-accent design token과 정면 충돌하고, emphasis 자막과 정보가 중복이라 "무지개 글자카드" 클리셰가 된다.
- accent는 **영상당 1색** 고정. 풀스크린 키네틱 타이포가 필요하면 `kinetic_type_9x16`(흰 텍스트 + 1색 underline), 단순 강조면 `text_only` + emphasis.

### 🎨 accent 팔레트 토큰 + 영상당 1색 (DT-01)

기존 `--accent-purple: #B366FF`(11개 템플릿 참조)는 **그대로 유지**. 추가로 accent 토큰 세트를 도입해 **영상/주제별로 다른 1색**을 고를 수 있게 한다(시리즈 단조 탈출). 단 **영상 안에서는 accent 1색 고정**(다색 혼용 금지 — design token 원칙 유지).

| 토큰 | hex | 어울리는 주제 톤 |
|---|---|---|
| `--accent` (기본) = `--accent-purple` | `#B366FF` | 범용·프리미엄 (미지정 시 기본) |
| `--accent-blue` | `#0070F3` | 테크/툴/개발/SaaS (chroma #0000FF와 충분히 멀어 키잉 안전) |
| `--accent-green` | `#2AF598` | 성장/지표 상승/성공 |
| `--accent-amber` | `#FFB020` | 경고/주목/돈 |

- **선택 방법**: plan에 `video_accent`(예: `"blue"`) 1개를 적으면 신규 템플릿(kinetic_type 등)이 `--accent`로 바인딩. 미지정 시 보라(기존 동작 보존).
- **숫자는 항상 흰색**, accent는 화면당 1-2곳만(형광펜 underline 등). 다색 그라데이션 장식 글자카드는 애초에 만들지 않으므로(원칙) 단일-accent 토큰만 사용.

### 🔎 substance(실제 시각 정보) 정의 갱신 (SI-03)

"검은 카드만 금지"(Rule 3/6) 판정에서 **substance**(실제 시각 정보) 인정 기준:
- ✅ `motion_template`이 다음 prefix로 시작: `ui_evidence_`, `line_chart`, `bar_chart`, `metric_ring`, `animated_beam`, `orbiting_circles`, `logo_marquee`, `device_mockup`, `comparison`(A vs B 구조화 대비), **`split_reveal`** (전→후 와이프), **`ratio_dots`** (개수 비율), **`vertical_timeline`** (단계 진행).
- ✅ 또는 `type=="ui_evidence"`면서 실제 스크린샷 `image_path`가 있는 device_mockup 케이스.
- ❌ 손으로 그린 fake-UI 텍스트 카드(motion_template 없고 src_hint가 비거나 stub인 ui_evidence)는 substance **아님** — `type` 라벨만으로 자동 인정 제거.

> 즉 overlay 2개+ 영상에서 최소 1개는 위 substance 기준을 만족해야 "검은 카드만" reject를 피한다.

---

## 🧠 플래닝 절대 규칙 — LLM이 직접 설계 (2026-04-22 확립)

```
⛔ B-roll 플래닝은 규칙/정규식이 아니라 LLM(Claude Opus)이 직접 한다.

YES: Claude가 transcript + scenes + draft emphasis를 Read하고 씬별 narration을
     이해한 뒤, 6 타입 중 하나(또는 text_only/skip)를 선택해
     _claude_broll_plan.json을 Write.
NO:  plan_generator.py 정규식/규칙 매칭으로 자동 생성
     (deprecated skeleton 래퍼로만 유지).

이유: 대본 맥락 이해는 LLM만 가능. regex는 context-aware 판단이 없어 품질이
     들쭉날쭉(예: plan_generator가 "47:1 vs 6:4" stat 비교를 G5 list로 오분류 →
     overlay 0개 / "숫자 4"를 number_hero 이미지로 생성). SKILL.md 원칙을 LLM이
     직접 적용하는 것이 유일한 일관 품질 보장.
```

**호출 경로**: `/capcut` 커맨드의 Step 3-A가 이 스킬을 호출하면, Claude Code 세션의 현재 LLM이 직접 다음을 수행:
1. 이 SKILL.md 전체 Read
2. `output/<name>/subs/transcript.json`, `temp/<name>/scenes.json`, `draft_content.json` Read
3. **`broll_designer_context.md`의 Motion 카탈로그 섹션 정독** (scene_designer context가 자동 주입)
4. ⭐ **decision: overlay 후보별로 `tools/motion_graphics/out/thumbs/<stem>__{early,mid,end}.png` 3장을 Read 도구로 직접 시각 확인** (텍스트 cheat sheet만 보고 결정 금지)
5. 씬별 decision + type + motion_template + params 결정
6. `temp/<name>/_claude_broll_plan.json` Write (motion 사용 시 `sample_reviewed: true` + `sample_reviewed_notes` 필수)

`plan_generator.py`는 `--fallback-skeleton` 옵션에서만 호출 가능하며, 결과는 "모든 씬 skip + draft emphasis를 text_only로 매핑한 0-overlay skeleton" 뿐. 즉 실제 플래닝 지능은 전부 LLM이 담당.

---

## 🎬 Motion 카탈로그 시각 검증 (2026-05-13 신설)

⛔ **HARD 원칙**: motion template 선택은 cheat sheet 텍스트만 보고 결정 금지. **반드시 sample MOV / frame_thumbs PNG를 Read로 직접 보고 결정**.

**과거 사고 (반복 금지)**:
- ❌ cheat sheet "yt comment + CTA"만 보고 9:16 댓글 변형을 선택 → 사용자가 별로라 해당 변형은 카탈로그에서 제거됨. **현재 카탈로그에 없는 변형은 선택 금지** (2026-05-13)
- ❌ 같은 영상 3 overlay 중 2개가 같은 type 변형 → "맨날 똑같은 것만 써" 비판
- ❌ template별로 params 키가 다른데 일반 패턴 `title`로 통일 호출 → 빈 카드 렌더 (template마다 phrase/items/comments 등 키 이름 다름 — HTML `__params` 직접 확인 필수)

### 단일 진실 소스 (SoT)

**`tools/motion_graphics/sample_catalog.json`** (자동 빌드)
- 빌드 명령: `PYTHONIOENCODING=utf-8 python tools/motion_graphics/build_catalog.py`
- 출력: 각 template의 `template_path`, `aspect`, `params_schema`, `scenario_hints`, `sample_mov`, `frame_thumbs(early/mid/end PNG)`
- 자동 분류:
  - `user_approved: true` — sample MOV가 `tools/motion_graphics/out/`에 있음 → **사용 가능**
  - `no_sample_yet`(=forbidden) — sample 없음 (미생성/미등록) → **사용 시 ingest reject** (미래 신규 template이 아직 sample 미등록일 때를 위한 메커니즘)
- ℹ️ **현재 forbidden 템플릿 없음** (2026-06-09: 과거 forbidden 17종 HTML·샘플·카탈로그 엔트리 전부 제거). 카탈로그에 남은 stem은 전부 `user_approved`.

### LLM 결정 절차 (decision: overlay 시 의무)

```
Step A. broll_designer_context.md의 "Motion Template 카탈로그" 섹션 정독
        → user_approved 템플릿 중 시나리오 매칭 후보 2-3개 추리기
        → 카탈로그에 없는 stem은 절대 선택 금지 (ingest가 자동 reject)

Step B. 각 후보의 frame_thumbs PNG 3장을 Read 도구로 직접 확인:
          tools/motion_graphics/out/thumbs/<stem>__early.png
          tools/motion_graphics/out/thumbs/<stem>__mid.png
          tools/motion_graphics/out/thumbs/<stem>__end.png

Step C. 콘텐츠 톤 / 씬 narration ↔ 실제 시각 자산 비교
        → 같은 영상에서 같은 type 반복 금지 (다양성)
        → params_schema의 정확한 키 이름 확인 (template마다 phrase/title/items 등 다름)

Step D. plan에 필수 필드 작성:
          "motion_template": "<approved_stem>",
          "motion_params": { params_schema 키만 사용 },
          "sample_reviewed": true,
          "sample_reviewed_notes": "early=..., mid=..., chose because ..."
```

### 강제 검증 (ingest 자동)

`scene_designer.py ingest`가 plan 받은 후:
1. `motion_template` stem이 `_validate_motion_template` 통과 (catalog의 `user_approved`인지 확인)
   → 카탈로그에 없거나 no_sample_yet인 stem 사용 시 exit 2 + 대안 제안
2. ⛔ **VQ-03 strict (2026-06-04, 기본 ON)**: `broll.sample_reviewed != true` 또는 `sample_reviewed_notes`에 early/mid/end 키 3개(비공백·distinct)가 없으면 **reject(exit 2)**. `OMC_BROLL_STRICT=0`으로 warning 강등(점진 도입).
3. ⛔ **SI-04 (2026-06-04)**: `broll_review.json`의 `mode`가 `sdk`/`orchestrator_personas`/`in_session_claude_review`만 통과. in_session은 persona_scores ≥3 + 각 overall + distinct notes 필요(빈 self-pass 차단).

---

## ⛔ 근본 원칙 (THE ONLY REASON B-ROLL EXISTS)

```
⛔ B-roll의 유일한 존재 이유:
   "emphasis 텍스트로는 전달 불가능한 시각 자산"을 보여주기 위함.

B-roll 만들기 전 반드시 자문:
   (1) 이 이미지가 text_only + emphasis로 전달 불가능한가?
   (2) 실제 UI / 로고 / 말풍선 / 도식 없이는 메시지가 손상되는가?

위 질문 중 하나라도 NO면 → text_only. B-roll 제작 금지.

과거 실수 (반복 금지):
   ❌ "4개" 숫자 강조를 큰 타이포 이미지로 → emphasis로 해결됨
   ❌ "결정/액션/책임자/기간" 리스트를 split_stack 이미지로 → emphasis 순차로 해결됨
   ❌ 책상+메모장+펜 실사 사진 → 아무 의미 전달 안 함
   ❌ 검은 배경 위 흰 글자만 있는 "이미지" → 그건 그냥 emphasis 텍스트임
   ❌ "자이가르닉 효과"를 개념 도식으로 → 개념 키워드는 text_only
```

**이 원칙은 이 스킬의 모든 결정의 최상위 루트다. 아래 모든 타입·관문·페르소나 리뷰는 이 원칙의 하위 구현이다.**

---

## ⚡ 핵심 철칙 (9개)

1. **실사 사진 금지** — graphic · typography · screenshot **only**. 책상/종이/손글씨/펜/자연광/Kinfolk 톤 모두 banned.
2. **순수 텍스트 나열 이미지 금지** — 리스트·문장·개념은 emphasis 오버레이로.
3. **단일 숫자 이미지 금지** — "500만", "40%" 같은 단일 숫자는 emphasis로 충분.
4. **One-Object Rule** — 한 장에 hero 요소 **단 하나**.
5. **60% Negative Space** — hero는 프레임의 40% 이하.
6. **블루 크로마 배경 필수** — 모든 이미지는 `#0000FF` solid → chroma_remove가 alpha 처리.
7. **Pretendard-Only 한글** — serif·손글씨 금지.
8. **No Depth** — drop shadow >20px / glass-morphism / 3D bevel 금지.
9. **Silence > Noise** — 모호할 땐 **항상 덜** → text_only.

---

## 🎨 6 타입 체계 (split_stack·number_hero·symbol_moment 폐기)

`tools/capcut_pipeline/broll_prompts.py` 의 **`TYPES` dict가 SoT**. 프리셋 추가는 거기서 수정.

| # | 타입 | 언제 | aspect | 예시 narration |
|---|---|---|---|---|
| 1 | **`icon_hero`** | 브랜드/앱 단일 언급 | 16:9 | "노션에서", "카톡으로" |
| 2 | **`ui_evidence`** ⭐ | **특정 플랫폼 + 특정 데이터 증빙** (가장 자주 쓰임) | 9:16 or 16:9 | "@유니약사 278명", "터미널 출력" |
| 3 | **`message_object`** | 메시지/알림 맥락 (빈 말풍선 상징) | 16:9 | "카톡 왔어요" |
| 4 | **`stat_card`** | 숫자 before→after 극적 비교 | 16:9 | "5,500→6,900", "1시간 → 10분" |
| 5 | **`dual_icon`** | 양쪽 브랜드 대비 | 1:1 | "아이폰 vs 갤럭시" |
| 6 | **`graphic_insight`** | flat 다이어그램 (신중히) | 16:9 | "자이가르닉", "뇌는 4개만" |

---

## 🎬 Motion B-roll (Hyperframes-inspired, 2026-04-22 POC)

정적 PNG 대신 **GSAP timeline으로 애니메이션된 MOV**를 overlay로 삽입할 수 있습니다. 카운트다운 숫자, 메시지 타이핑, 순차 등장 등 "시간축에서의 연출"이 핵심인 순간에 사용.

- **파이프라인**: HTML+GSAP 템플릿 → Playwright headless Chrome → 프레임 캡처 → ffmpeg colorkey → ProRes 4444 alpha MOV → CapCut video overlay
- **구현**: [tools/motion_graphics/render_motion.py](../../../tools/motion_graphics/render_motion.py)
- **Hyperframes CLI는 사용하지 않음** — Playwright 단일 의존성으로 자체 구현 (독점 CLI 설치 리스크 회피)

### ⛔ card_opacity — UI 화면은 불투명, 장식 카드는 반투명 (2026-06-09 fix)

**원칙**: **"실제 UI 화면/디바이스/다이얼로그/알림 = 불투명(1.0)"** (화면은 실물 surface — 인물·배경 비치면 깨져 보임) vs **"영상 위에 띄우는 장식·데이터·텍스트 카드/심볼 = 반투명(0.62)"** (영상이 비쳐 레이어드 느낌). 판단: "실제 앱/기기의 *화면*인가?"(노션 문서·터미널·카톡 폰화면·댓글 모달·OS 토스트=불투명) vs "영상 위에 얹는 그래픽/차트/글자 카드인가?"(체크리스트·숫자카드·차트·키네틱 타이포·아이콘=반투명). (배경: 과거 ingest가 모든 모션에 `card_opacity=0.62`를 강제해 노션 흰 문서·터미널이 62%만 불투명 → 인물 비쳐 "깨진 화면"으로 보였음. catalog 샘플≠실제 출력이라 발견이 늦음.)

**수정 (3중)**:
1. `render_motion.render_html_to_png_sequence`: `card_opacity >= 1.0`이면 **`.card` 배경을 덮어쓰지 않는다** → 템플릿 고유 배경(노션 `#FFF`, 터미널 dark 등) 그대로 **불투명** 유지. `< 1.0`이면 반투명 dark로 강제(장식 카드용).
2. `scene_designer._default_card_opacity(stem)`: **템플릿별 명시적 분류** (`_OPAQUE_TEMPLATES` frozenset). prefix 추측이 아니라 stem 단위로 구분 — 신규 stem은 prefix fallback(목록 명시 등록 권장).
3. plan의 `broll.card_opacity`로 **per-scene override** (데이터 카드 불투명 `1.0`, 특정 화면 반투명 `0.6` 등).

| 분류 | card_opacity | 템플릿 (전수 명시 구분) |
|---|---|---|
| **불투명 1.0** (화면/디바이스/다이얼로그/알림) | 1.0 | `ui_evidence_*` 전부(notion·terminal·finder·claude_code(2)·slack(2)·discord(16x9)·instagram_dm·kakaotalk(9x16)·youtube_comment(16x9)·comment_input), `device_mockup_9x16`, `toast_notification_9x16`(자체 0.94) — **14개** |
| **반투명 0.62** (장식·데이터·텍스트 카드/심볼) | 0.62 | `kinetic_type`·`graphic_insight`(9x16)·`stat_card`(1x1)·`line_chart`·`bar_chart`·`metric_ring`·`comparison`·`animated_beam`·`logo_marquee`·`orbiting_circles`·`dna_helix`(자체 0)·`icon_hero/file` — **14개** |
| **자체 panel 배경 (override 무관)** | (무관) | `split_reveal_9x16`·`ratio_dots_9x16`·`vertical_timeline_9x16` — `.card` 미사용이라 `card_opacity` 값과 상관없이 자체 반투명 panel 배경 유지 — **3개** |

> 신규 UI 화면 템플릿 추가 시: `.card`(또는 화면 컨테이너)에 **솔리드 배경**을 주고, stem을 `ui_evidence_` 등 불투명 prefix로 시작하게 한다. `card_opacity` 0.62 override에 기대지 말 것.

### ⛔ Motion 템플릿은 **aspect별 variant로 작성이 정석**

Motion 템플릿은 HTML viewport 크기가 고정되므로, 사용하려는 영상 aspect와 일치하는 variant를 준비해야 합니다. **하나의 `type`에 대해 여러 aspect variant를 두고 기획 단계에서 선택**.

**파일명 컨벤션** (`tools/motion_graphics/templates/`):
```
<type>_<aspect>.html
```
예: `stat_card_1x1.html`, `graphic_insight_9x16.html`, `ui_evidence_kakaotalk_9x16.html`

**현재 가용 variants** (~30개. stat_card는 1x1만, graphic_insight는 9x16 풀프레임만. 신규: split_reveal·ratio_dots·vertical_timeline 3종 추가):

**공통 CSS 토큰**: `templates/shared.css` — 폰트(@font-face 5 weights), 색상 토큰(`--chroma-blue`, `--accent-purple`, `--brand-*` 등), 공통 status-bar 헬퍼, 이징 토큰(`--ease-pop` ↔ GSAP `back.out(1.8)` 등 페어링), type scale, theme 클래스. **모든 신규 템플릿은 `<link rel="stylesheet" href="shared.css">` 로 토큰 참조 필수**.

**Stat / Data (4개 — 중립 aspect)**
| Template | Aspect | Viewport | 용도 | 주요 motion |
|---|---|---|---|---|
| `stat_card_1x1.html` | 1:1 | 1080×1080 | 숫자 before→after 극적 비교 (compact 카드 — 9:16/1:1 영상 상단) | 세로 stack 카운트업/다운 + underline |
| `graphic_insight_9x16.html` | 9:16 | 1080×1920 | 풀프레임 체크리스트 (가독성 우선 — 9:16 영상에 크게) | 큰 글자(제목50/항목52px) + 행별 rounded chip(반투명 dark 가독 배경) + 보라 체크박스 순차 체크 |
| `line_chart_16x9.html` | 16:9 | 1920×1080 | 매출/지표 추세 시각화 (시간축) | SVG line draw + area fill + 숫자 카운트업 동기 |
| `bar_chart_16x9.html` ⭐ NEW | 16:9 | 1920×1080 | 카테고리 비교 시각화 (line은 추세, bar는 카테고리) | 5-6개 vertical bar grow up + 값 카운트업 + peak bar accent |

**Mobile UI 9:16 native (4개)**
| Template | Aspect | Viewport | 용도 | 주요 motion |
|---|---|---|---|---|
| `ui_evidence_kakaotalk_9x16.html` ★ | 9:16 | 1080×1920 | **카톡 모바일 native** | 4개 독립 말풍선 pop-in 순차 |
| `ui_evidence_instagram_dm_9x16.html` | 9:16 | 1080×1920 | 모바일 Instagram DM | 말풍선 순차 pop + 타이핑 (퍼플 그라데이션 outgoing) |
| `ui_evidence_slack_9x16.html` | 9:16 | 1080×1920 | 모바일 Slack 채널 | 메시지 3개 순차 fade-in |
| `toast_notification_9x16.html` ⭐ NEW | 9:16 | 1080×1920 | **시스템 토스트 알림** (앱 내 메시지 X — Sonner/Shadcn 풍 OS-level toast) | 우측 슬라이드 인 + variant별 좌측 색 보더 + progress bar drain. variant: success/info/error/warn |

**Desktop UI (16:9 native — 8개)**
| Template | Aspect | Viewport | 용도 | 주요 motion |
|---|---|---|---|---|
| `ui_evidence_youtube_comment_16x9.html` | 16:9 | 1920×1080 | 데스크톱 YouTube 댓글 + CTA | 댓글 3개 순차 + 첫 댓글 타이핑 |
| `ui_evidence_notion_16x9.html` | 16:9 | 1920×1080 | Notion 문서 UI (사이드바 + 제목 + bullets) | 제목 typewriter + bullet 순차 등장 |
| `ui_evidence_terminal_16x9.html` | 16:9 | 1920×1080 | macOS Terminal CLI | prompt+cmd 타이핑 + output 순차 + blinking cursor |
| `ui_evidence_finder_16x9.html` | 16:9 | 1920×1080 | macOS Finder 파일 탐색기 | 파일 행 순차 등장 + highlight row |
| `ui_evidence_slack_16x9.html` | 16:9 | 1920×1080 | Slack 워크스페이스 | 채널+메시지 3개 순차 fade-in |
| `ui_evidence_discord_16x9.html` | 16:9 | 1920×1080 | Discord 서버 (dark 테마) | server strip + 메시지 순차 등장 |
| `ui_evidence_claude_code_16x9.html` | 16:9 | 1920×1080 | Claude Code CLI 작업 세션 (Thinking + Read/Edit + 코드) | 사용자 msg + 이벤트 순차 + code block fade |
| `ui_evidence_claude_code_welcome_16x9.html` | 16:9 | 1920×1080 | Claude Code 시작 화면 (마스코트 + CLAUDE.md 안내) | 헤더 fade + 마스코트 pop+bob + 입력창 slide |

**Symbol / Brand / Card (3개 — 정사각 또는 소형)**
| Template | Aspect | Viewport | 용도 | 주요 motion |
|---|---|---|---|---|
| `icon_hero_1x1.html` | 1:1 | 1080×1080 | 브랜드 로고 hero (텍스트 심볼) | card pop-in + glow pulse + label fade |
| `icon_file_1x1.html` | 1:1 | 1080×1080 | 파일/문서 아이콘 (PDF/MD/DOCX 등 확장자 색상) | card pop + wobble + 파일명 fade |
| `metric_ring_1x1.html` | 1:1 | 1080×1080 | 원형 퍼센트 게이지 | SVG stroke-dasharray + 숫자 카운트업 동기 |

> 🆕 **brand SVG 레지스트리 (`brand_logos.js`, TL-04)**: `logo_marquee_16x9`·`icon_hero_1x1`·`orbiting_circles_1x1`는 params의 **brand key**(예: `"claude"`, `"chatgpt"`, `"notion"`)로 이 레지스트리에서 진짜 SVG 로고를 주입한다 → "단일 글자 이니셜 색타일(색 스와치 보드)" 클리셰 해소. **미등록 브랜드는 이니셜 타일로 폴백**(점진 개선). 초기엔 고빈도 3-4개만 정확한 path. 모든 로고는 chroma blue(#0000FF) 근처색 회피.

**Hero Text / Connection (21st.dev / Magic UI 영향)** ⭐ NEW
| Template | Aspect | Viewport | 용도 | 주요 motion |
|---|---|---|---|---|
| `kinetic_type_9x16.html` ⭐ NEW | 9:16 | 1080×1920 | **감정/주장/결론 풀스크린 키네틱 타이포** — 9:16 세로 영상의 절제된 타이포 연출 (무지개/파티클 장식 글자카드 대신 이걸로) | 어절 split → overflow:hidden mask-reveal(translateY 100%→0, stagger) + accent_words만 underline 형광펜(흰 텍스트·1색). params: lines[]/accent_words[]/duration |
| `device_mockup_9x16.html` ⭐ NEW | 9:16 | 1080×1920 | **실제 스크린샷을 폰/브라우저 프레임에 삽입** — 손그림 fake-UI보다 물성↑ | `<img src=file://...>` Ken Burns(scale 1.0→1.08) + clip-path inset 리빌. params: device(phone\|browser)/image_path/caption/camera_move/duration |
| `animated_beam_16x9.html` | 16:9 | 1920×1080 | **A → B 데이터 흐름 / 통합 / API 연결** (Magic UI Animated Beam) — 좌·우 두 노드 + 그 사이 SVG path beam draw + glowing dot이 path 따라 이동 | 좌 노드 pop → SVG bezier beam draw + dot path 따라 이동 → 우 노드 pop → dot pulse → footer fade |
| `orbiting_circles_1x1.html` | 1:1 | 1080×1080 | **에코시스템 / 통합 도구 군집** (Magic UI Orbiting Circles) — 중앙 hub + 내부 4 + 외부 6 위성이 반대 방향 회전 (위성 라벨은 카운터 회전으로 정자세 유지) | hub pop → 위성 stagger pop → 양 orbit 동시 회전 (timeline 전체 duration) |
| `logo_marquee_16x9.html` | 16:9 | 1920×1080 | **여러 도구·플랫폼 무한 스크롤 strip** (Magic UI Marquee) — 좌/우 edge fade mask + 두 줄 반대 방향 drift | 카드 pop + title fade + row 1 좌→ drift, row 2 우→ drift (선형, timeline 전체) + footer fade |

**Transition / Ratio / Steps (substance 인정, `.card` 미사용·자체 panel 배경. split_reveal·vertical_timeline·ratio_dots 모두 9:16 — 정사각 카드를 9:16 상단 band에 그림)** ⭐ NEW
| Template | Aspect | Viewport | 용도 | 주요 motion |
|---|---|---|---|---|
| `split_reveal_9x16.html` ⭐ NEW | 9:16 | 1080×1920 | **전→후 상태 전환 와이프** — "혼란→정돈","과거→현재" 전환 비트 (comparison의 정적 2열이 못 하는 공간 전환). 정사각 카드를 9:16 상단 band에 배치(얼굴 안 가림). 모션 scale 1.0 풀프레임 — 카드 위치는 템플릿 담당 | 보라 디바이더 좌→우 sweep + BEFORE 텍스트→AFTER 텍스트 swap. params: before_text/after_text/before_label("전")/after_label("후")/accent/duration |
| `ratio_dots_9x16.html` ⭐ NEW | 9:16 | 1080×1920 | **비율을 셀 수 있는 점 그리드** — "10명 중 7명","6만 중 80%" 심리 통계 (stat_card 단일숫자·metric_ring 퍼센트링이 못 하는 '개수로 세기') | total개 점 중 filled개가 accent로 순차 점등 + 숫자 카운트. params: total(10)/filled(7)/headline/caption/accent/duration |
| `vertical_timeline_9x16.html` ⭐ NEW | 9:16 | 1080×1920 | **VO 동기 세로 단계 진행선** — "인식→수용→행동","1→2→3단계" (graphic_insight 정적 체크리스트와 다른 '흐르는' 진행). 정사각 카드를 9:16 상단 band에 배치(얼굴 안 가림). 모션 scale 1.0 풀프레임 — 카드 위치는 템플릿 담당 | 레일 head 아래로 draw + 도달 순간 dot 점등 순차. params: steps([str] 또는 [{label}])/title(선택)/accent/duration |

⚠️ 필요한 aspect variant가 없으면 **기획 단계에서 신규 template 작성 요청**. 임의로 다른 aspect 파일 쓰면 CapCut이 스케일하며 비율 왜곡.

### 기획 단계 의사결정

Motion 사용 시 플래너가 `_claude_broll_plan.json`의 `broll`에 `motion:true` + `motion_template`(templates 디렉토리 파일 stem) + `motion_params`(template `window.__params` 키만)를 명시. 전체 plan 예시는 아래 §Phase 4 스키마 참조.

### 기획 단계 2-step 판단

**Step 1 — Type별 본질 aspect 우선 체크** (콘텐츠 자체가 선호하는 비율):

| Type | 본질 aspect | 이유 |
|---|---|---|
| `ui_evidence/kakaotalk` | **9:16** | 카카오톡은 모바일 앱 — 세로 폰 화면이 native |
| `ui_evidence/instagram_dm`, `/youtube_shorts` | **9:16** | 모바일 native |
| `ui_evidence/youtube_comment`, `/notion`, `/terminal`, `/finder`, `/claude_code` | **16:9** | 데스크톱/웹 native |
| `toast_notification` ⭐ | **9:16** | 모바일 OS 토스트 알림은 모바일 native |
| `icon_hero`, `icon_file`, `metric_ring` | **1:1** | 아이콘/로고/게이지는 정사각 본질 |
| `orbiting_circles` ⭐ | **1:1** | 회전 에코시스템은 정사각 본질 (대칭) |
| `stat_card` | **1:1** | compact 숫자 카드 — 9:16/1:1 영상 상단에 가독성 유지 (`stat_card_1x1`만 존재, 2026-06-10) |
| `graphic_insight` | **9:16** | 리스트/체크리스트는 9:16 풀프레임이라야 큰 글자로 읽힘 (`graphic_insight_9x16`만 존재, 2026-06-10) |
| `bar_chart`, `line_chart` | **영상 aspect에 맞춤** (중립) | 추상 다이어그램이라 콘텐츠 고유 비율 없음 |
| `animated_beam`, `logo_marquee` ⭐ | **16:9** | 가로 흐름·연결·strip은 가로 본질 |

**Step 2 — 영상 aspect × 연출 의도로 최종 선택**:

| 영상 aspect | 연출 의도 | 선택 |
|---|---|---|
| 16:9 가로 (YouTube 롱폼) | full-frame | type-본질 aspect 우선 (예: kakaotalk은 9:16을 작게 얹는 연출도 가능) |
| **9:16 세로 (Reels/Shorts)** | **compact 카드(stat_card·metric_ring·icon_*)** | **`_1x1`** — 영상 상단에 가독성 유지 (16:9 금지) |
| **9:16 세로 (Reels/Shorts)** | **리스트·비교(graphic_insight·comparison)** | **`_9x16` 풀프레임** — 큰 글자+행 chip이라야 읽힘 (16:9 금지) |
| **9:16 세로 (Reels/Shorts)** | **차트(bar/line_chart)** | **`_9x16` 권장** (없으면 `_16x9` 작게 — 여백 감안) |
| 9:16 세로 | **모바일 앱 재현** (KakaoTalk·Instagram 등) | **type-본질 aspect** (`_9x16`) ← 161755 scene 16 케이스 |
| 9:16 세로 | full-screen / 큰 카드 takeover | `_9x16` (폭 85~95%, transform y≈0.1로 하단 자막 공간) |
| 9:16 세로 | (예외) UI가 16:9 native(터미널·노션 등)인데 작은 목업으로 얹기 | `_16x9` 작게 — **단 위아래 투명여백 주의** |
| 1:1 정사각 | 중앙 카드 | `_1x1` |

**⚡ 핵심 원칙**:
1. **Type 본질 먼저**: "이 콘텐츠가 원래 어떤 형태로 소비되는가?" (KakaoTalk이면 무조건 세로 폰, Terminal이면 가로 데스크톱)
2. **영상 aspect = B-roll aspect가 기본** — 특히 리스트·비교 타입(graphic_insight·comparison)은 **9:16 영상이면 `_9x16` 풀프레임**으로.

> ⛔ **B-roll aspect 정책**
> ⛔ **모션 B-roll은 scale 1.0 풀프레임 고정(overlay_patcher 강제).** `position_y`/`overlay_h_ratio`로 모션 카드의 스케일/위치를 조정하지 말 것 — CapCut scale 의미와 충돌해 깨진다. **작은 정사각 카드를 상단에 배치하고 싶으면 1:1 MOV가 아니라 9:16 템플릿(split_reveal_9x16·vertical_timeline_9x16)이 9:16 프레임 상단 band에 정사각 카드를 그려서** 해결한다(얼굴 중앙·하단 자막 zone을 비움). "카드 상단 배치"는 scale/position이 아니라 템플릿 레이아웃이 책임진다.
> **16:9는 화면 native(notion·terminal·finder·slack·discord·claude_code 등 실제 데스크톱 UI 스크린샷)만.** 중립 16:9 글자/숫자 카드(stat_card·graphic_insight를 16:9로)를 세로 영상에 얹지 말 것.
> **lens_zoom(scene effect)은 B-roll overlay 표시 구간을 회피** — 겹치면 overlay까지 줌돼 어색.
> 이유(2026-05-29 실측): 9:16 세로 광고에 16:9 stat_card를 "상단 bar"로 얹었더니 16:9 material(1920×1080)의 **위아래 투명여백** 때문에 카드가 작게·이상하게 잡혀 사용자가 강하게 반발("세로에 가로 b-roll 넣으면 크기 이상하지"). 같은/정사각 비율이면 CapCut 코너 핸들로 비율 유지하며 자유롭게 키울 수 있음.
> `_16x9`를 세로 영상에 얹는 건 16:9 native UI를 **의도적 작은 목업**으로 보여줄 때만(그 경우에도 여백으로 작아짐 감안).

3. **모바일 앱 재현은 type 본질 우선** — KakaoTalk은 16:9 영상이어도 9x16 폰 목업이 본질.

### 렌더 CLI

```bash
PYTHONIOENCODING=utf-8 python tools/motion_graphics/render_motion.py \
  --template tools/motion_graphics/templates/stat_card_1x1.html \
  --params '{"top_label":"...","top_number":10,...,"duration":5.5}' \
  --out-base output/<name>/broll_motion/scene_010_motion \
  --fps 30 \
  --width 1080 --height 1080  # template aspect와 일치시킬 것
```

출력 2종:
- `*.mp4` — 블루 크로마 배경 보존 (CapCut에서 chroma key 수동 적용 시 사용)
- `*.mov` — ProRes 4444 with alpha (드래그 투입 즉시 투명 overlay, 기본 권장)

### overlay_patcher 동작

`overlay_patcher.py`는 파일 확장자(`.mov/.mp4/.webm`)로 video overlay를 자동 감지합니다:
1. ffprobe로 MOV 실제 duration 읽기
2. `material.type = "video"`, `source/target timerange` 모두 MOV 원본 길이로 clamp (stretch 방지)
3. 씬 duration이 MOV보다 길면 나머지 구간은 overlay 없이 메인 영상만

오버레이 **가로 점유**는 `overlay_h_ratio`(기존 `ratio`와 동의어, 기본 0.55), **세로 위치**는 `position_y` 슬롯(top/center/lower, 기본 top), **타이밍**은 `start_offset_sec`/`display_dur_sec`로 plan에서 명시(전부 optional·하위호환). 슬롯명→`transform.y` 매핑과 얼굴/자막 zone 충돌 가드는 overlay_patcher가 소유 — 플래너는 슬롯명만 적는다. 상세는 위 **§반-클리셰 v2**(신규 plan 필드 + position_y 안전슬롯) 참조. ⚠️ `uniform_scale.value=1.0` 불변(아래 scale math 경고).

### Phase 4 — scene_designer.py ingest 자동 통합

플래너가 `_claude_broll_plan.json`에 `broll.motion:true`를 명시하면 `scene_designer.py ingest`가 자동으로 `render_motion.py`를 호출해 MOV를 생성하고 `broll_plan.json` items의 `image_path`에 기록함(수동 MOV swap 불필요).

**Plan 스키마 (motion 케이스)**:
```jsonc
{
  "scene_idx": 10,
  "decision": "overlay",
  "reason": "회의 속 아젠다 10개 vs 뇌가 잡는 4개 — 카운트다운 연출 가치",
  "broll": {
    "type": "stat_card",
    "motion": true,
    "motion_template": "stat_card_1x1",   // tools/motion_graphics/templates/ 파일 stem
    "motion_params": {                      // template이 window.__params로 받는 값
      "top_label": "회의 속 아젠다",
      "top_number": 10,
      "top_suffix": "개",
      "bottom_label": "뇌가 잡는 개수",
      "bottom_number": 4,
      "bottom_suffix": "개",
      "duration": 5.5
    }
  }
}
```

**scene_designer ingest 동작**:
- `broll.motion:true` 감지 시:
  1. Template stem에서 aspect 파싱 (`_16x9` → 1920×1080, `_9x16` → 1080×1920, `_1x1` → 1080×1080)
  2. `render_motion.py` subprocess 호출: `--template`, `--params`, `--out-base=output/<name>/broll_motion/scene_NNN`, `--width`, `--height`
  3. 생성된 `.mov` 경로를 `broll_plan.json`의 item `image_path`에 기록 (+ image_width/image_height)
  4. 정적 이미지(기존 Gemini flow)는 그대로 `src_hint` 기반 PNG 생성

### ⭐ Motion 우선 원칙 (사용자 가중치)

**기본 정책**: overlay가 필요한 **모든 씬에서 motion을 1순위로 시도**. 정적 PNG는 motion이 매핑되지 않을 때만 fallback. 이유: 정적 이미지보다 시청 지속률·체감 품질이 높음(가만히 있는 화면은 지루함).

**결정 트리 (3단계)**:
```
overlay 필요?
├─ NO → text_only / skip
└─ YES →
    ├─ Step A. 가용 variant 중 시나리오에 매핑되는 motion 후보가 있는가?
    │   (cheat sheet + 전체 카탈로그 둘 다 검토)
    │
    │   ├─ YES (1개 이상 후보) → Step B. 후보 중 베스트 선택
    │   │   판단 기준 (LLM이 전체 맥락 종합 평가):
    │   │     ① 지루하지 않은가? — 카운트업·타이핑·순차 등 시간축 임팩트가 큰 것 선호
    │   │     ② 상황 적합도 — 나레이션 의도와 가장 자연스럽게 맞는가
    │   │     ③ 임팩트 — 첫 0.5초에 시청자 attention 끌 수 있는가
    │   │     ④ 본질 aspect — 콘텐츠 native form 일치 (KakaoTalk=9:16 등)
    │   │
    │   └─ NO (매핑되는 후보 없음) → Step C. 추가 제안 절차 (아래)
    │
    └─ 모호하면 motion 시도 (덜 어울려도 정적보다 임팩트)
```

**Step C — 카탈로그로 커버 안 되는 시나리오**: LLM이 plan에 두 옵션 중 하나로 명시(사용자가 보고 결정).

- **옵션 1 — 신규 motion template 작성 제안** (재사용 가치 있을 때): scene에 `motion_proposal` 객체 추가 — `{ "needed": true, "suggested_stem": "ui_evidence_google_sheets_16x9", "rationale": "...", "fallback_if_not_built": "png" }`. 신규 작성 전까지는 `broll.src_hint`(또는 `motion:false` PNG)도 함께 제공.
- **옵션 2 — 1회성·특수 → 정적 PNG 직행**: `broll: { "type": "...", "motion": false, "src_hint": "..." }`.

**판단 기준 — 신규 template vs PNG**:
| 신규 motion template 제안 (옵션 1) | 정적 PNG로 직행 (옵션 2) |
|---|---|
| 시나리오가 다른 영상에도 재사용 가치 있음 (예: 자주 등장하는 SaaS UI, 표/차트 종류) | 1회성·매우 특수한 콘텐츠 (실제 인물, 특정 사건 사진) |
| 시간축 연출이 가치 큼 (타이핑·순차·카운트) | 정적 묘사로 충분 (단순 심볼·로고 없는 추상) |
| 맥락 = 명확한 UI / 데이터 / 도식 | 맥락 = 분위기 / 추상 / 감정 |

**정적 PNG fallback 최종 케이스 (motion 미선택)**:
- 카탈로그에 매핑 없음 + 신규 작성 가치도 낮음 (1회성)
- 콘텐츠가 motion으로 표현 불가능한 시각 자산 (실제 인물 사진, 손글씨 등)
- 그 외에는 **비슷한 motion이라도 우선 선택** (정적 PNG는 마지막 수단)

### 🎯 시나리오 → motion variant cheat sheet

| 나레이션/콘텐츠 시나리오 | 1순위 motion variant | 비고 |
|---|---|---|
| **숫자 비교** (before→after, A vs B) | `stat_card_1x1` | 카운트업/다운 임팩트 큼. compact 카드 — 9:16/1:1 영상 상단 |
| **체크리스트 / 3가지 행동 / N가지 팁** | `graphic_insight_9x16` | 9:16 풀프레임 가독성 (큰 글자+행 chip) + 보라 체크박스 순차 체크 |
| **매출·성장·추세** (시간축) | `line_chart_16x9` | SVG 라인 draw + 카운트업 |
| **카테고리 비교** (월별·분기별·항목별 막대) ⭐ | `bar_chart_16x9` | line은 추세, bar는 카테고리 — vertical bar grow + peak accent |
| **퍼센트·진행률·달성률** | `metric_ring_1x1` | 원형 게이지 + 숫자 카운트 |
| **카톡 메시지** (모바일 native) | `ui_evidence_kakaotalk_9x16` | ★ 본질 9:16 |
| **카톡 그룹/회의방** | `ui_evidence_kakaotalk_9x16` | 4개 독립 말풍선 |
| **인스타 DM** | `ui_evidence_instagram_dm_9x16` | 퍼플 그라데이션 outgoing |
| **YouTube 댓글 + CTA** ("댓글에 X") | `ui_evidence_youtube_comment_16x9` | 데스크톱 댓글 |
| **노션 문서 / 회의록 / 요약 페이지** | `ui_evidence_notion_16x9` | 사이드바 + bullets |
| **터미널 / CLI / 명령어 시연** | `ui_evidence_terminal_16x9` | 컬러 prompt + typewriter |
| **Slack 채팅 / 워크스페이스** | `ui_evidence_slack_<aspect>` | 데스크톱 vs 모바일 선택 |
| **Discord 서버 / 커뮤니티** | `ui_evidence_discord_16x9` | 다크 테마 (데스크톱) |
| **Finder / 파일 탐색기 / 자료 정리** | `ui_evidence_finder_16x9` | macOS 네이티브 |
| **Claude Code (시작/안내)** | `ui_evidence_claude_code_welcome_16x9` | 마스코트 + CLAUDE.md 안내 |
| **Claude Code (작업/AI 코딩)** | `ui_evidence_claude_code_16x9` | Thinking + tool calls |
| **시스템 토스트 ("결제 완료")** ⭐ | `toast_notification_9x16` | OS-level toast slide-in + variant 색 보더 (앱 메시지 X) |
| **브랜드 로고 단독 언급** (Notion/Slack 등) | `icon_hero_1x1` | **brand key로 진짜 SVG**(TL-04, 미등록=이니셜 폴백) + 글로우 |
| **파일·PDF·문서 (확장자 강조)** | `icon_file_1x1` | 확장자별 색상 (PDF·MD·DOCX 등) |
| **개념 A vs B 다항목 대비** ⭐ ("버티는 사람 vs 만드는 사람", "소비 vs 생산") | `comparison_9x16` | 2열 대비: 좌(부정/dim+빨강 #FF6B6B) vs 우(긍정/흰+초록 #2AF598) + 중앙 VS 노드. 각 열 제목 + 첫 항목 pill + 항목 stagger. 9:16 중앙 밴드(상단 얼굴·하단 자막 투명 회피). params: `left_title/right_title/left_items[]≤4/right_items[]≤4/duration`. stat_card(숫자)로 못 하던 **개념 대비 리스트**. type=`dual_icon` 라벨 권장 |
| **결정적 한 줄/한 단어 강조** (감정 톤·결론) | `kinetic_type_9x16` 또는 text_only | 무지개/파티클 장식 글자카드는 안 만든다(자막 중복·단일 accent 위반, TL-01). 풀스크린은 kinetic, 단순 강조는 text_only+emphasis |
| **감정/주장 풀스크린 키네틱 타이포** (9:16) ⭐ NEW | `kinetic_type_9x16` | 어절 mask-reveal(translateY 100%→0) + accent_words 형광펜 underline. accent 1색·흰 텍스트 |
| **실제 스크린샷을 디바이스 프레임에** (9:16) ⭐ NEW | `device_mockup_9x16` | phone/browser 베젤 + 실제 캡처 Ken Burns. image_path(file://) 필수. 사진 금지·UI만 |
| **A → B 데이터 흐름 / API 통합** ⭐ | `animated_beam_16x9` | 좌·우 노드 + SVG bezier beam draw + glowing dot 따라 이동 |
| **에코시스템 / 통합 도구 군집** ⭐ | `orbiting_circles_1x1` | 중앙 hub + 위성 양방향 회전. 위성=**brand key SVG**(TL-04) |
| **지원 플랫폼 / 함께 쓰는 도구들** ⭐ | `logo_marquee_16x9` | 무한 스크롤 두 줄 반대 방향 + edge fade mask. 카드=**brand key SVG**(TL-04) |
| **전→후 상태 전환** ⭐ NEW ("혼란→정돈","과거→현재","능력부족→강점") | `split_reveal_9x16` | 보라 디바이더 좌→우 sweep + BEFORE→AFTER swap. comparison(정적 2열)이 못 하는 공간 와이프. **정사각 카드를 9:16 상단 band에 그림(얼굴 안 가림). 모션 scale 1.0 풀프레임 — 카드 위치는 템플릿 담당**. params: before_text/after_text/before_label("전")/after_label("후") |
| **개수 비율 / 심리 통계** ⭐ NEW ("10명 중 7명","6만 중 80%") | `ratio_dots_9x16` | total 중 filled개 accent 점등. stat_card(단일숫자)/metric_ring(퍼센트링)이 못 하는 '개수로 세기'. params: total(10)/filled(7)/headline/caption |
| **단계 진행 / VO 동기 흐름** ⭐ NEW ("인식→수용→행동","1→2→3단계") | `vertical_timeline_9x16` | 레일 head 아래로 draw + 도달 dot 점등. graphic_insight(정적)와 다른 '흐르는' 진행. **정사각 카드를 9:16 상단 band에 그림(얼굴 안 가림). 모션 scale 1.0 풀프레임 — 카드 위치는 템플릿 담당**. params: steps[]/title(선택) |

**aspect 선택 (씬에 맞는 \<aspect\>)**: 영상이 9:16이면 **중립 타입(stat_card·graphic_insight·bar/line_chart)과 모바일 native 콘텐츠(카톡/인스타), 그리고 신규 `kinetic_type_9x16`·`device_mockup_9x16`는 모두 `_9x16`** (영상과 같은 비율 = 크게 키워도 왜곡 없음). `_16x9`는 16:9 native UI(터미널·노션 등)를 작은 목업으로 얹을 때만 — **세로 영상에 16:9 중립 카드를 얹으면 위아래 투명여백으로 작게/이상하게 잡힘 (2026-05-29 사고)**. 영상이 1:1이면 `_1x1`. 자세한 2-step 판단은 위쪽 표 참고.

**가용 template 일치 확인**: 위 cheat sheet의 stem만 사용. `scene_designer ingest`가 `_list_motion_templates()` 로 자동 검증해 잘못된 stem이면 후보 제안과 함께 reject. 카탈로그에 없는 새 시나리오면 기획 단계에서 신규 template 요청.

---

### ⛔ 폐기된 타입 (사용 시 즉시 reject)

| 타입 | 폐기 이유 | 대체 |
|---|---|---|
| ~~`split_stack`~~ | 텍스트 나열은 emphasis 순차 전개로 표현 가능 | `decision: text_only` + 3개 emphasis |
| ~~`number_hero`~~ | 단일 숫자는 emphasis로 충분 | `decision: text_only` + emphasis "500만" |
| ~~`symbol_moment`~~ | 실사 photo를 유도함 (책상·커피·종이) | `decision: text_only` 또는 `graphic_insight` |
| ~~`screenshot`~~ / ~~`webtoon`~~ / ~~`atmospheric`~~ | 초기부터 제거됨 | — |

### 🔕 `text_only` — 이미지 없이 emphasis만 (가장 자주 쓰는 결정)

타입이 **아님**. broll_plan.json의 decision-level 옵션. 이미지 생성 skip, overlay_patcher가 emphasis 텍스트만 주입.

```json
{
  "scene_idx": 3,
  "decision": "text_only",
  "reason": "단일 숫자 — emphasis만으로 충분",
  "emphasis": {"text": "4개뿐", "accent_words": ["4"]}
}
```

**text_only를 선택해야 하는 경우**:
- 자명한 주장/결론 ("본문이 아니라 제목에 시간")
- CTA ("댓글에 X 남겨주세요")
- 개념/정의 키워드 ("자이가르닉 효과")
- 단일 숫자 강조 ("500만", "40%")
- 감정/분위기/추상 ("커피 한 잔", "아침에 일어나서")
- **3-4 item 리스트** ("결정·액션·책임자·기간") → emphasis 순차 전개

---

## 🟦 블루 크로마 파이프라인 (NEW 2026-04-21) ⭐

### 문제 → 해법

**과거 문제**: B-roll 이미지를 그대로 오버레이하면 **검은 배경 박스가 메인 영상을 가림**. 에디터가 영상 안 보여서 불편.

**해법**: 모든 B-roll 이미지를 `#0000FF` solid 블루 배경으로 생성 → `chroma_remove.py`가 블루 → alpha 투명 처리 → 메인 영상이 투명 영역에서 보임.

### 파이프라인 (자동)

```
1. Gemini 프롬프트에 "Solid #0000FF blue background" 자동 주입
   (broll_prompts.COMMON_PREFIX에 지시)
          ↓
2. scene_designer.py generate-images → *.png 생성 (블루 배경)
          ↓ (자동 실행)
3. chroma_remove.py 내부 호출
   - #0000FF 거리 < 100 → alpha 0 (완전 투명)
   - 100 ≤ 거리 < 130 → gradient alpha (edge softening)
   - 거리 ≥ 130 → opaque 유지
          ↓
4. overlay_patcher → CapCut draft 반영
   → 메인 영상이 투명 영역에서 보임 ✅
```

### 튜닝 (드물게 필요)

```bash
# 기본값으로 충분. fringe 이슈 시만 조정.
python tools/capcut_pipeline/chroma_remove.py \
  --dir output/<name>/broll_gemini \
  --threshold 100 \
  --edge-soften 30
```

### 🎬 Motion B-roll 투명/반투명 카드 (2026-05-29 — 검정 박스 해결) ⭐

정적 Gemini 이미지는 위 블루 크로마(불투명 카드)를 쓰지만, **Motion MOV는 진짜 alpha를 캡처**해 **카드 배경을 반투명**으로 만든다 → 메인 영상이 카드 뒤로 비쳐 보임 (검정 박스가 화면 가리는 문제 해결).

- **기본 동작**: `scene_designer.py ingest`가 motion 렌더 시 `render_motion.py --transparent --card-opacity 0.62` 자동 적용. 별도 설정 없이 모든 motion B-roll이 반투명.
- **plan override** (`_claude_broll_plan.json`의 `broll`):
  ```jsonc
  "broll": {
    "motion": true,
    "motion_template": "stat_card_1x1",
    "transparent": true,      // (기본 true) false면 불투명 검정 카드
    "card_opacity": 0.62      // 0.0(완전투명·텍스트만) ~ 1.0(불투명). 기본 0.62
  }
  ```
- **구현** (`render_motion.py --transparent`):
  1. body 블루 배경을 `transparent`로 override + `.card` 배경을 `rgba(13,13,15,card_opacity)`로 주입
  2. Playwright `omit_background=True`로 캡처 → PNG에 진짜 alpha 보존
  3. ProRes 4444 MOV 생성 시 **colorkey 생략** (PNG native alpha 직접 사용 → 반투명 보존)
- **투명도 가이드**: `0.6` 전후 권장 (영상 비침 + 텍스트 가독성 균형). 텍스트만 떠 있게 하려면 `0.0`이지만 밝은 영상 위에선 흰 텍스트 대비 부족 주의.

### 금지 사항

- ⛔ 다른 색 배경으로 이미지 생성 (#0A0A0B dark, 흰색 등) — chroma 처리 안 됨
- ⛔ `ui_evidence`는 플랫폼 native UI 존중 → 블루 크로마 적용 제외 고려 (scene_designer가 자동 판단)

---

## 🌳 DECISION_TREE

### Step 1 — **근본 원칙 관문** (모든 scene에 먼저 적용)

```
질문: "emphasis 텍스트로 전달 가능한가?"
  YES → decision: text_only. 끝. B-roll 금지.
  NO  → Step 2로.
```

이 질문을 **통과하지 못하면 아래 관문 G1~G7은 아무 의미 없다**. 반드시 먼저.

### Step 2 — 관문 G1-G7 (근본 원칙 통과 후만)

| 관문 | 조건 | DEFAULT 타입 | 예외 → `ui_evidence` |
|---|---|---|---|
| G1a | 브랜드/앱 단일 언급 | `icon_hero` | 특정 계정·content 언급 시 |
| G1b | 메시지/알림 맥락 | `message_object` | "이 대화 보세요" 수준 |
| G2a | 단일 숫자/통계 | **decision: `text_only`** + emphasis | 특정 프로필 지표면 |
| G2b | 정량 숫자 before→after | `stat_card` | — |
| G3 | CTA 버튼 언급 | `icon_hero` (플랫폼 로고만) | — |
| G4 | 교과서 정의 | **decision: `text_only`** | — |
| ~~G5~~ | ~~3-item 리스트~~ | **→ `text_only` + emphasis 순차** (split_stack 폐기) | — |
| G6 | 양쪽 명명 비교 | `dual_icon` | — |
| G7 | 개념·상태·진행도 시각화 (신중히) | `graphic_insight` 또는 **`text_only` 우선** | — |
| Atmos | 시간·의식·감정 (타이틀 후) | **decision: `text_only`** (실사 photo 금지) | — |

### Step 3 — 안티패턴 A1-A7 (1개라도 해당 = SKIP)

| # | 안티패턴 | 예시 |
|---|---|---|
| A1 | 타이틀/무음/오프닝 | scene 0-1 title 구간 |
| A2 | 추상 후킹 질문 | "왜 안 될까?" |
| A3 | 내러티브 setup | "어떤 사람이 있었어요" |
| A4 | 추상 결론/잠언 | "결국 중요한 건..." |
| A5 | 대명사/지시어만 | "이게 바로" |
| A6 | 필러/연결구 | "그런데", "사실" |
| A7 | NG 의심 테이크 | 반복·말더듬 |

### Step 4 — `ui_evidence` 판정 (3 AND)

다음 **모두 AND**면 `ui_evidence` 우선:
1. 특정 플랫폼 + 특정 데이터 지목 ("@유니약사 278명", "이 터미널 출력")
2. 데이터가 가짜면 narration 가치가 **없음** (진실성이 핵심)
3. 해당 플랫폼의 **고유 UI 언어**를 있는 그대로 표현 가능

**허용 플랫폼**: Instagram / macOS Finder / Terminal / VSCode / Claude Code / YouTube / Gmail / 노션 / 토스 / 카톡 (실제 대화) / Twitter-X / Discord

**금지**: 가상 SaaS 대시보드, 가짜 회사명, 모방 UI

---

## 🎭 3-Persona 리뷰 (필수 게이트)

**`scene_designer.py ingest` 전에 반드시 통과** — 미통과 시 ingest exit 2.

### ⛔ 자동 pre-filter (SDK 호출 전 즉시 reject)

다음은 page 페르소나 점수와 무관하게 **자동 reject**:
- `type: split_stack` (폐기)
- `type: number_hero` / `symbol_moment` (폐기)
- 순수 텍스트 나열 이미지 (src_hint에 "list" / "3 items" / "세로 스택")
- 단일 숫자 이미지 (src_hint가 `^\d+%?$` 패턴)

### 3 페르소나 (`templates/persona_reviewers.json` SoT)

| 페르소나 | 관점 |
|---|---|
| `gen_z_student` (20대) | 스크롤 멈춤력, 인스타 스럽게 세련됐는지 |
| `office_worker` (30대) | 5초 안에 이해되는지, 실용적인지 |
| `sns_expert` (40대) | narration↔시각 1:1, 억지 실사 setup 없는지 |

### 새 필수 scoring dimension: `visual_only_value`

*"이 이미지가 텍스트로 대체 불가능한 시각 가치를 제공하는가?"*

| 점수 | 의미 |
|---|---|
| 5 | 반드시 시각 자산. text로 대체 불가 (실제 UI 스크린샷, 브랜드 로고 등) |
| 3 | 시각 자산 있으면 좋지만 text_only로도 작동 |
| **1-2** | **text_only로 충분. B-roll 불필요 → REJECT** |

### PASS 기준

- 각 페르소나 `overall >= 4.0`
- 각 페르소나 `visual_only_value >= 4` (NEW)
- 각 페르소나 `rejects` 배열 비어 있음
- aggregate (3인 평균 overall) `>= 4.0`

### CLI

```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/broll_reviewer.py \
  --plan       temp/<name>/_claude_broll_plan.json \
  --transcript output/<name>/subs/transcript.json \
  --scenes     temp/<name>/scenes.json \
  --out        temp/<name>/broll_review.json
```

Exit codes: `0` PASS · `2` REJECT · `3` 입력 오류

---

## 🤖 자동 파이프라인 (end-to-end)

```
plan_generator.py
   ↓ 뼈대 생성 (DECISION_TREE 자동 적용)
_claude_broll_plan.json
   ↓
broll_reviewer.py (pre-filter + 3-persona)
   ↓ exit 0 (PASS) 만 통과
broll_review.json [pass: true]
   ↓
scene_designer.py ingest
   ↓ (게이트 확인)
broll_plan.json
   ↓
scene_designer.py generate-images
   ↓ Gemini (블루 #0000FF 배경 자동 주입)
output/<name>/broll_gemini/*.png
   ↓ (자동 호출)
chroma_remove.py (내부)
   ↓ 블루 → alpha 투명
*.png (RGBA, 투명 배경)
   ↓
overlay_patcher.py
   ↓ CapCut draft 반영
draft_content.json (3 스타일: overlay/dual/split)
```

---

## 🎬 영상 첫 제목(오프닝 타이틀 카드) — Step 3는 임시, **최종 확정은 커맨드 Step 5.5** (2026-06-05, 사용자 요청)

⛔ **여기 Step 3-A에서 쓰는 `title.text`는 임시(working) 타이틀**이다. 영상 맨 앞 타이틀 카드의 **최종 문구는 FX까지 끝난 Step 5 다음(`/capcut` 커맨드 Step 5.5)** 에 **전체 편집본을 보고 후킹 3안 추천 → 사용자 선택**으로 확정한다. 편집 전엔 완성 톤을 몰라 약한 훅이 나오기 쉽기 때문.

- **Step 3 (지금)**: 첫 씬 메시지에 맞는 무난한 임시 타이틀 1개만 넣고 진행 (plan에 `title` 채움). 과하게 고민하지 말 것 — 어차피 Step 5.5에서 교체.
- **Step 5.5 (커맨드)**: 완성 편집본 기준 후킹 3안(의문형/반전/숫자·약속/공포→해소 등 서로 다른 축, 각 ≤14자 + accent 1개 + 후킹 의도) 작성 → `AskUserQuestion`으로 제시 → 선택안을 `_claude_broll_plan.json`+`broll_plan.json`의 `title`에 반영 → overlay/fx `--mode clean` 재패치 → verify 3·5 재확인. (상세 절차는 `.claude/commands/capcut.md` Step 5.5)

> title.txt(Step 4 메타 제목, 인스타/검색용)와는 별개. 타이틀 카드 텍스트는 첫 씬 메시지와 일치(낚시 금지), 클릭베이트·반말 명령형 금지.

---

## 📄 `_claude_broll_plan.json` 스키마

```json
{
  "title": {
    "text": "영상 제목",
    "accent_words": ["핵심단어"],
    "duration_sec": 4.0
  },
  "video_accent": "blue",
  "scenes": [
    {"scene_idx": 0, "decision": "skip", "reason": "title"},
    {
      "scene_idx": 3,
      "decision": "text_only",
      "reason": "G2a 단일 숫자 — emphasis만으로 충분",
      "emphasis": {
        "text": "4개뿐",
        "accent_words": ["4"],
        "position": "lower",
        "start_offset_sec": 0.5,
        "duration_sec": 3.0
      }
    },
    {
      "scene_idx": 12,
      "decision": "overlay",
      "type": "ui_evidence",
      "src_hint": "Instagram mobile profile @yuni__yaksa | 45게시물/278팔로워/98팔로잉",
      "broll": {
        "start_offset_sec": 1.5,
        "display_dur_sec": 3.5,
        "position_y": "top",
        "overlay_h_ratio": 0.55,
        "anchor_phrase": "278명"
      },
      "emphasis": {"text": "278명", "accent_words": ["278"]}
    }
  ]
}
```

**valid decisions**: `skip` / `overlay` / `split` / `dual` / **`text_only`**
**valid types** (skip/text_only 제외): 위 **6종** (`icon_hero` / `ui_evidence` / `message_object` / `stat_card` / `dual_icon` / `graphic_insight`)

**신규 optional 필드** (미지정 시 default = 기존 동작, 하위호환):
- 최상위 `video_accent`(enum: `purple`(기본)/`blue`/`green`/`amber`) — 영상당 accent 1색. 미지정 시 보라(DT-01).
- overlay `broll`의 `start_offset_sec`(float, 0)/`display_dur_sec`(float\|null)/`position_y`(enum top/center/lower, top)/`overlay_h_ratio`(float, 0.55). 상세는 위 **§반-클리셰 v2** 표 참조.
- overlay/emphasis `broll`의 `anchor_phrase`(string\|null) — 화자가 그 시점 말하는 정확한 구절(STT 원문 표기). overlay_patcher가 transcript word 타임스탬프로 `start_offset_sec` 자동 스냅. 못 찾으면 기존 값 유지. 상세는 §speech-anchor.
- device_mockup 사용 시 `broll.motion_template:"device_mockup_9x16"` + `motion_params.image_path`(file:// 절대경로) 필수.

---

## 🎯 타입별 예시 (간결)

| 타입 | narration | src_hint |
|---|---|---|
| `icon_hero` | "노션에서 정리" | "Notion N logo, centered, symbol only" |
| `ui_evidence` ⭐ | "@유니약사 278명" | "Instagram mobile profile @yuni__yaksa, 45게시물/278팔로워/98팔로잉" |
| `message_object` | "카톡 왔어요" | "KakaoTalk yellow bubble, empty interior" |
| `stat_card` | "5,500 → 6,900" | "5,500 ↓ 6,900, unit 만원" |
| `dual_icon` | "아이폰 vs 갤럭시" | "iPhone silhouette vs Galaxy silhouette, vs separator" |
| `graphic_insight` | "자이가르닉 미완성 일감" | "6 checkbox, 2 checked, 4 open, flat vector" |

---

## 🎯 브랜드 로고 처리

`brand_registry.json` (16 브랜드 SoT) 참조.

**4 규칙**:
1. **Canonical name** — "KakaoTalk official chat bubble icon" (X: "yellow messaging app")
2. **공식 hex** — 반드시 정확 (`#FAE100` 카톡, `#000` 노션 등)
3. **Wordmark 배제** — `"symbol mark only, no wordmark text"`
4. **비율 고정** — `"20-25% of frame width"`

**등록 브랜드**: kakaotalk / notion / toss / coupang / daangn / baemin / naver / instagram / youtube / gmail / slack / discord / linkedin / twitter / chatgpt / claude

---

## 🈁 한국어 타이포 규칙

1. **이미지 내 max 6음절** — 초과 시 emphasis 오버레이로 분리
2. **Pretendard 명시** — Gemini가 geometric sans로 해석
3. **Serif/손글씨 금지**
4. **Text verbatim** — prompt 끝에 `Text to render verbatim: "500만"`
5. **형광펜 강조** — `"yellow highlighter swipe #FFE15C behind the number"`
6. **숫자는 흰색 only**
7. **확실치 않으면 text_only**

---

## 🖼 overlay_patcher 3 스타일 + scale math

> ⭐⭐ **모션 B-roll은 무조건 scale 1.0 (100%) (2026-06-05, 사용자 결정 — "자꾸 왜 확대해")**
> 모션 overlay(`.mov`/`.mp4`)는 **항상 `clip.scale=1.0` + `transform={0,0}`** 로 캔버스에 1:1로 얹는다. overlay_h_ratio/position_y로 0.55/0.92/0.98 스케일하던 동작 **폐기**(모션 한정). 이유: 모션 템플릿은 출력 해상도(예 1080×1920)에 맞춰 자체 레이아웃으로 제작(얼굴 zone 상단 비움·자막 zone 하단 비움)되므로 캔버스와 1:1이 정답. 9:16 풀프레임 = 화면 꽉 채움(100%), 16:9 = 가로 1920px라 9:16 캔버스(1080) 좌우 잘림(감안 — 작은 목업 필요하면 `_9x16` 변형 template 사용). 구현: `overlay_patcher.py`의 `is_video_overlay and style=="overlay"` 분기가 scale/transform override. **정적 PNG 카드(legacy)는 기존 floating 동작 유지.**

| 스타일 | 용도 | opacity | aspect 권장 |
|---|---|---|---|
| `overlay` (모션) | 모션 MOV — **scale 1.0 고정(100%, 중앙 1:1)** | 0.75 | **영상 aspect와 동일**(9:16 풀프레임 권장) |
| `overlay` (정적) | 정적 PNG floating (55% scale, legacy) | 0.75 | 영상 aspect와 동일 |
| `dual` | 좌우 2개 나란히 (각 42%) | 0.75 | 1:1 × 2 |
| `split` | 상단 덮기 + 메인 아래 | **1.0** (필수) | 16:9 |

> ⛔ **CapCut `uniform_scale` 규칙 (2026-05-29 — 세로 깨짐 버그 원인 확정)**
> overlay/dual의 크기는 **오직 `clip.scale.x = clip.scale.y`** 로만 잡고,
> **`uniform_scale = {on: true, value: 1.0}` 으로 고정**해야 한다.
> `uniform_scale.value`에 크기값(예: 0.37)을 넣으면 — `clip.scale`과 같은 값이어도 —
> CapCut이 첫 로드 시 value를 크기에 **이중 적용**해 overlay를 **세로로 길게 왜곡**시킨다.
> (증상: 처음 열면 세로로 길쭉 → UI에서 "균일한 크기 조정" 껐다 켜면 value가 1.0으로
>  리셋되며 정상화. 즉 value≠1.0 저장이 근본 원인.)
> `overlay_patcher.style_clip_and_uniform()`가 이미 `value:1.0`으로 고정함 — **수동 패치 시
>  절대 `uniform_scale.value`를 scale값으로 덮어쓰지 말 것.** 크기 조절은 `clip.scale`만.

**split 자동 수학** (이미지 aspect 기반):

| 이미지 비율 | 상단 차지 | transform.y | main_shift_y |
|---|---|---|---|
| 16:9 (1.78) | 31.6% | +0.684 | -0.316 |
| 1:1 (1.00) | 56.3% | +0.437 | -0.563 |
| 4:3 (1.33) | 42.2% | +0.578 | -0.422 |

### `--mode` 옵션

| mode | 동작 |
|---|---|
| `auto` (기본) | 동일 plan은 no-op, 다르면 `.clean_bak` 복구 후 재patch |
| `clean` | 항상 `.clean_bak` 복구 + 재patch |
| `force` | 감지 무시 강제 재patch |
| `reject` | 이미 patched면 에러 |

**상태 파일**: `.omc_patch_state.json` (plan_hash + log)

---

## 🚫 반복 실수 방지 (중요)

⛔ **"텍스트 나열 이미지는 만들지 말 것"** — 리스트·문장·단어 모음은 emphasis 순차 전개로.
⛔ **"텍스트 나열 이미지는 만들지 말 것"** — split_stack 폐기됨. src_hint에 "list of 3" 있으면 즉시 text_only로 전환.
⛔ **"텍스트 나열 이미지는 만들지 말 것"** — "결정·액션·책임자·기간" 같은 워크샵 개념은 절대 이미지 아님.
⛔ **"텍스트 나열 이미지는 만들지 말 것"** — graphic_insight도 텍스트 나열 금지. 도식만 허용.
⛔ **"텍스트 나열 이미지는 만들지 말 것"** — 페르소나 리뷰에서 visual_only_value ≤ 3이면 자동 reject.

⛔ **실사 photo setup 금지** — 책상/메모장/펜/Kinfolk tone/자연광 모두 banned.
⛔ **검은 배경 위 흰 텍스트만 있으면 reject** — 그건 이미지가 아니라 emphasis임.
⛔ **단일 숫자 이미지 금지** — "500만", "40%"는 text_only + emphasis로.

---

## 🔍 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| Gemini가 SaaS 대시보드 생성 | src_hint에 ban list 단어 없는지 확인. `validate_prompt()` 로 검사 |
| Gemini가 책상+종이 photo 생성 | src_hint에 실사 photo 용어 없는지 확인 |
| Korean 글자 깨짐 | 이미지 내 6음절 초과. emphasis로 분리 |
| 브랜드 로고 이상함 | `brand_registry.json` symbol_desc 확인 |
| `ui_evidence` 가짜 데이터 | src_hint에 **구체 data points** 명시 강화 |
| text_only인데 이미지 생성됨 | `decision: text_only` 확인. ingest 단계에서 type 필드 없어야 |
| 블루 크로마가 영상까지 투명하게 만듦 | main 영상에 #0000FF 픽셀 존재. threshold 낮추기 (70) |
| 블루 fringe 남음 | `--edge-soften 50` 으로 증가 |
| Gemini 이미지 캐시 안 바뀜 | `.hint_hash` 파일 삭제 후 재생성 |
| ingest exit 2 | `broll_review.json` 없음/REJECT. broll_reviewer.py 먼저 |
| plan에 `split_stack`/`symbol_moment`/`number_hero` 남음 | 폐기됨. `text_only` 또는 다른 6 타입으로 migration |
| **overlay가 처음 열 때 세로로 길게 찌그러짐** | `uniform_scale.value`가 1.0이 아님(크기값 들어감) → CapCut 이중 적용. `value:1.0` 고정 + `clip.scale`로만 크기. (UI "균일한 크기 조정" OFF→ON 토글하면 임시 정상화) |
| 세로(9:16) 영상에 16:9 카드가 작게/이상하게 잡힘 | aspect 불일치. 중립타입은 영상과 같은 aspect(1:1 권장, 프레임=카드). 16:9 카드 얹기 금지 |
| 검정 카드가 영상 가림 | motion은 `--transparent --card-opacity 0.62`(scene_designer 기본). plan `broll.card_opacity`로 농도 조절 |

---

## 🛠 scene_designer.py CLI

```bash
# 1. Context 생성
python tools/capcut_pipeline/scene_designer.py context \
  --scenes temp/<name>/scenes.json \
  --transcript output/<name>/subs/transcript.json \
  --out temp/<name>/broll_designer_context.md

# 2. 3-Persona Review (필수 게이트)
python tools/capcut_pipeline/broll_reviewer.py \
  --plan temp/<name>/_claude_broll_plan.json \
  --transcript output/<name>/subs/transcript.json \
  --scenes temp/<name>/scenes.json \
  --out temp/<name>/broll_review.json

# 3. Plan ingest (validation + broll_plan.json 생성)
python tools/capcut_pipeline/scene_designer.py ingest \
  --input temp/<name>/_claude_broll_plan.json \
  --scenes temp/<name>/scenes.json \
  --out temp/<name>/broll_plan.json

# 4. 이미지 자동 생성 (블루 크로마 배경 + 자동 alpha 처리)
python tools/capcut_pipeline/scene_designer.py generate-images \
  --plan temp/<name>/broll_plan.json \
  --out-dir output/<name>/broll_gemini
# ↑ 내부에서 chroma_remove.py 자동 호출
```

---

## 🗂 관련 파일

| 파일 | 역할 |
|---|---|
| [tools/capcut_pipeline/broll_prompts.py](../../../tools/capcut_pipeline/broll_prompts.py) | **SoT** — 6 타입 TYPES / COMMON_PREFIX / BANNED_PHRASES |
| [tools/capcut_pipeline/chroma_remove.py](../../../tools/capcut_pipeline/chroma_remove.py) | **NEW** — 블루 #0000FF → alpha 투명 처리 |
| [tools/capcut_pipeline/plan_generator.py](../../../tools/capcut_pipeline/plan_generator.py) | plan 뼈대 자동 생성 |
| [tools/capcut_pipeline/broll_reviewer.py](../../../tools/capcut_pipeline/broll_reviewer.py) | 3-Persona 게이트 (pre-filter + SDK/fallback) |
| [tools/capcut_pipeline/templates/persona_reviewers.json](../../../tools/capcut_pipeline/templates/persona_reviewers.json) | 페르소나 + visual_only_value scoring SoT |
| [tools/capcut_pipeline/templates/brand_registry.json](../../../tools/capcut_pipeline/templates/brand_registry.json) | 16 브랜드 hex + symbol_desc SoT |
| [tools/capcut_pipeline/scene_designer.py](../../../tools/capcut_pipeline/scene_designer.py) | DECISION_TREE + context/ingest/generate-images CLI + position_y 슬롯 emit |
| [tools/capcut_pipeline/overlay_patcher.py](../../../tools/capcut_pipeline/overlay_patcher.py) | 3 스타일 패치 + 멱등성 + position_y→transform.y 매핑 + zone 충돌 가드(CE-03) + `anchor_phrase`→transcript word 타임스탬프 스냅(speech-anchor) |
| [tools/motion_graphics/templates/kinetic_type_9x16.html](../../../tools/motion_graphics/templates/kinetic_type_9x16.html) | TL-02 — 풀스크린 키네틱 타이포(무지개/파티클 글자카드 대체) |
| [tools/motion_graphics/templates/device_mockup_9x16.html](../../../tools/motion_graphics/templates/device_mockup_9x16.html) | TL-03 — 실제 스크린샷 디바이스 목업 |
| [tools/motion_graphics/templates/brand_logos.js](../../../tools/motion_graphics/templates/brand_logos.js) | TL-04 — 진짜 브랜드 SVG 레지스트리(미등록=이니셜 폴백) |
| [tools/motion_graphics/templates/split_reveal_9x16.html](../../../tools/motion_graphics/templates/split_reveal_9x16.html) | TL-07 — 전→후 상태 전환 와이프, 9:16 상단 band 정사각 카드(substance) |
| [tools/motion_graphics/templates/ratio_dots_9x16.html](../../../tools/motion_graphics/templates/ratio_dots_9x16.html) | TL-08 — 개수 비율 점 그리드(substance) |
| [tools/motion_graphics/templates/vertical_timeline_9x16.html](../../../tools/motion_graphics/templates/vertical_timeline_9x16.html) | TL-09 — VO 동기 세로 단계 진행선, 9:16 상단 band 정사각 카드(substance) |
| [tools/motion_graphics/templates/shared.css](../../../tools/motion_graphics/templates/shared.css) | 공통 토큰 — accent 팔레트(`--accent`/blue/green/amber, DT-01) + 모션/스페이싱 토큰 |
| [tools/motion_graphics/templates/shared_motion.js](../../../tools/motion_graphics/templates/shared_motion.js) | 공통 모션 헬퍼 (split_reveal·ratio_dots·vertical_timeline 등이 사용) |

**Cross-ref**:
- [capcut-pipeline](../capcut-pipeline/SKILL.md) — prereq (STT + 씬 컷 + 드래프트)
- [capcut-fx](../capcut-fx/SKILL.md) — next step (filter·BGM·SFX·animations)
- [capcut-subtitle](../capcut-subtitle/SKILL.md) — emphasis 스타일 SoT

---

## ✅ 최종 체크리스트

- [ ] **근본 원칙**: 모든 B-roll scene이 "emphasis로 전달 불가능한 시각 자산"인가?
- [ ] `_claude_broll_plan.json`의 모든 scene에 `decision` 명시
- [ ] `decision: overlay/split/dual`인 경우만 `type` 필드 있음 (**6 타입** 중 하나)
- [ ] plan에 `split_stack` / `number_hero` / `symbol_moment` 없음 (폐기됨)
- [ ] `decision: text_only`는 이미지 생성 skip 확인
- [ ] **`broll_reviewer.py` PASS** (pre-filter 통과 + 3인 overall ≥ 4.0 + visual_only_value ≥ 4)
- [ ] `ui_evidence` 사용 시 3 AND 조건 충족
- [ ] Gemini 생성된 이미지가 블루 `#0000FF` 배경인지 확인
- [ ] `chroma_remove` 후 PNG가 RGBA + 투명 영역 존재하는지 확인
- [ ] 이미지에 **2+ 오브젝트** → 재생성 (One-Object)
- [ ] 이미지에 **책상/종이/펜/Kinfolk** → 즉시 재생성 (실사 금지)
- [ ] 이미지가 **순수 텍스트 나열** → 즉시 text_only로 전환
- [ ] 이미지가 **검은 배경 위 흰 글자만** → emphasis로 대체
- [ ] Korean 타이포 깨지면 emphasis 오버레이로 이동
- [ ] **무지개/파티클 글자카드 미사용 (원칙)** — 풀스크린은 kinetic_type_9x16, 단순 강조는 text_only+emphasis (TL-01)
- [ ] **9:16 토킹헤드: overlay `position_y` = top 기본**, center(얼굴 덮음) 비권장, lower는 자막 회피 확인 (CE-02)
- [ ] **긴 씬(7s+) overlay 박제 방지** — `start_offset_sec`/`display_dur_sec`로 짧게, 중간 강조는 emphasis (CE-01)
- [ ] **영상당 accent 1색** (`video_accent`) — 다색 혼용 금지, 숫자는 흰색 (DT-01)
- [ ] device_mockup 사용 시 `image_path`(file://) 존재 + **UI 스크린샷(실사 사진 아님)** 확인 (TL-03)
- [ ] **overlay `reason`이 막연한 일반구('강조'·'시각적'·'임팩트'·'분위기')가 아님** — 구체 사유(구절 인용·UI·숫자·전후·단계) (Rule 9)
- [ ] (선택) `anchor_phrase`는 **STT 원문 표기**로 작성 (교정/영문복원 전) — 실측 타이밍 스냅용 (speech-anchor)
- [ ] **B-roll aspect**: 모션은 scale 1.0 풀프레임 고정(position_y/overlay_h_ratio로 카드 조정 금지). 작은 정사각 카드 상단 배치는 9:16 템플릿(split_reveal_9x16·vertical_timeline_9x16)이 상단 band에 그려서 해결. 16:9는 화면 native UI만 — 세로 영상에 16:9 중립 글자카드 금지
- [ ] overlay_patcher 실행 전 CapCut 완전 종료
