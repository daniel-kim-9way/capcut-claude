---
name: capcut-broll
description: CapCut B-roll 자동 설계 + 3-persona 리뷰 + 블루 크로마 이미지 생성 + overlay 패치. 6-type 분류학 (실사 사진·순수 텍스트 나열·단일 숫자 이미지 전면 금지) + flat editorial / typography / screenshot-only 미학 + `text_only` 의사결정 + 블루 크로마 파이프라인 + 3스타일 오버레이(overlay/dual/split) 단일 소스.
---

# CapCut B-roll Skill ⭐

---

## 🧠 플래닝 절대 규칙 — LLM이 직접 설계 (2026-04-22 확립)

```
⛔ B-roll 플래닝은 규칙/정규식이 아니라 LLM(Claude Opus 4.7)이 직접 한다.

YES: Claude가 transcript + scenes + draft emphasis를 Read하고
     씬별 narration을 이해한 뒤, 6 타입 중 하나(또는 text_only/skip)를
     선택해 _claude_broll_plan.json을 Write.

NO: plan_generator.py 정규식/규칙 매칭으로 자동 생성.
    (이 도구는 deprecated skeleton 래퍼로만 유지됨)

과거 사고 기록 (반복 금지):
  ❌ plan_generator.py가 "47 : 1  vs  6 : 4"(명백한 stat_card 후보)를
     G5 list로 오분류 → overlay 0개 생성 (2026-04-22)
  ❌ "숫자 4" 단일 숫자를 number_hero 이미지로 B-roll 생성 (2026-04-21)
  ❌ 동일 영상 재처리 시 규칙이 다르게 적용되어 들쭉날쭉한 품질

이유:
  - 대본 맥락 이해는 LLM만 가능. "이력서 47장→합격 1개" 와 "이력서 6장→합격 4개"
    는 본질이 stat/graphic_insight 비교인데, regex는 "콜론 2개 + vs"로 밖에 못 봄.
  - 규칙은 재현성은 있지만 context-aware 판단 없음 → 품질이 들쭉날쭉.
  - LLM(Opus 4.7)이 SKILL.md 원칙을 직접 적용하는 것이 유일한 일관된 품질 보장 방법.
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
- ❌ cheat sheet "yt comment + CTA"만 보고 `ui_evidence_youtube_comment_9x16` 선택 → 사용자가 별로라 sample 지운 forbidden template (2026-05-13)
- ❌ 같은 영상 3 overlay 중 2개가 같은 type 변형 → "맨날 똑같은 것만 써" 비판
- ❌ aurora template 호출 시 `phrase` 대신 일반 패턴 `title` 사용 → 빈 카드 렌더 (필드명 다른 template 존재)

### 단일 진실 소스 (SoT)

**`tools/motion_graphics/sample_catalog.json`** (자동 빌드)
- 빌드 명령: `PYTHONIOENCODING=utf-8 python tools/motion_graphics/build_catalog.py`
- 출력: 각 template의 `template_path`, `aspect`, `params_schema`, `scenario_hints`, `sample_mov`, `frame_thumbs(early/mid/end PNG)`
- 자동 분류:
  - `user_approved: true` — sample MOV가 `tools/motion_graphics/out/`에 있음 → **사용 가능**
  - `no_sample_yet`(=forbidden) — sample 없음 (사용자가 별로라 지웠거나 미생성) → **사용 시 ingest reject**

### LLM 결정 절차 (decision: overlay 시 의무)

```
Step A. broll_designer_context.md의 "Motion Template 카탈로그" 섹션 정독
        → user_approved 25개 중 시나리오 매칭 후보 2-3개 추리기
        → forbidden 목록은 절대 선택 금지

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
   → forbidden / no_sample_yet 사용 시 exit 2 + 대안 제안
2. `broll.sample_reviewed` 누락 시 warning 출력 (현재 strict-mode 미설정 — 추후 strict 전환 가능)

### 사례: PROMPTER_20260512_141123 v1 → v2 비교

| 항목 | v1 (cheat sheet only) | v2 (sample 시각 검증) |
|---|---|---|
| overlay 수 | 3 | 4 |
| 다른 motion type | 3 종 (graphic_insight 2번) | **4 종** (graphic_insight·aurora·sparkles·yt_comment) |
| forbidden 사용 | `ui_evidence_youtube_comment_9x16` ❌ | `_16x9` 변형 ✓ |
| params 정확도 | 일반 `title` 패턴 short cut | template별 정확한 키 (phrase, items, comments 등) |
| visual_only_value avg | 4.5 | **4.7** |

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

### ⛔ Motion 템플릿은 **aspect별 variant로 작성이 정석**

Motion 템플릿은 HTML viewport 크기가 고정되므로, 사용하려는 영상 aspect와 일치하는 variant를 준비해야 합니다. **하나의 `type`에 대해 여러 aspect variant를 두고 기획 단계에서 선택**.

**파일명 컨벤션** (`tools/motion_graphics/templates/`):
```
<type>_<aspect>.html
```
예: `stat_card_16x9.html`, `stat_card_9x16.html`, `ui_evidence_kakaotalk_16x9.html`

**현재 가용 variants** (2026-05-08 update — 39개, 21st.dev/Magic UI/Aceternity 패턴 12종 추가):

**공통 CSS 토큰**: `templates/shared.css` — 폰트(@font-face 5 weights), 색상 토큰(`--chroma-blue`, `--accent-purple`, `--brand-*` 등), 공통 status-bar 헬퍼, 이징 토큰(`--ease-pop` ↔ GSAP `back.out(1.8)` 등 페어링), type scale, theme 클래스. **모든 신규 템플릿은 `<link rel="stylesheet" href="shared.css">` 로 토큰 참조 필수**.

**Stat / Data (8개 — 중립 aspect)**
| Template | Aspect | Viewport | 용도 | 주요 motion |
|---|---|---|---|---|
| `stat_card_16x9.html` | 16:9 | 1920×1080 | 가로 bar 연출 (세로 영상 상단/하단) | 2-column 좌↓우 카운트업/다운 + underline |
| `stat_card_9x16.html` | 9:16 | 1080×1920 | 세로 영상 full-screen takeover | 세로 stack 카운트업/다운 |
| `stat_card_1x1.html` | 1:1 | 1080×1080 | 인스타 피드/정사각 영상 | 세로 stack 카운트업/다운 |
| `graphic_insight_16x9.html` | 16:9 | 1920×1080 | 체크리스트 다이어그램 (가로) | 3-4 아이템 순차 → 보라 체크박스 순차 체크 |
| `graphic_insight_1x1.html` | 1:1 | 1080×1080 | 정사각 체크리스트 | 동일 (정사각 레이아웃) |
| `line_chart_16x9.html` | 16:9 | 1920×1080 | 매출/지표 추세 시각화 (시간축) | SVG line draw + area fill + 숫자 카운트업 동기 |
| `bar_chart_16x9.html` ⭐ NEW | 16:9 | 1920×1080 | 카테고리 비교 시각화 (line은 추세, bar는 카테고리) | 5-6개 vertical bar grow up + 값 카운트업 + peak bar accent |
| `avatar_group_1x1.html` ⭐ NEW | 1:1 | 1080×1080 | "278명이 사용 중" 군집 + 숫자 (얼굴 + 카운트 동시) | 5 avatar stagger pop + "+N" badge + total 카운트업 |

**Mobile UI 9:16 native (7개)**
| Template | Aspect | Viewport | 용도 | 주요 motion |
|---|---|---|---|---|
| `ui_evidence_kakaotalk_16x9.html` | 16:9 | 1920×1080 | 특수 맥락 (잘 안 씀) | 4줄 타이핑 |
| `ui_evidence_kakaotalk_9x16.html` ★ | 9:16 | 1080×1920 | **카톡 모바일 native** | 4개 독립 말풍선 pop-in 순차 |
| `ui_evidence_youtube_comment_9x16.html` | 9:16 | 1080×1920 | 모바일 YouTube 댓글 + CTA | 댓글 3개 순차 + 첫 댓글 타이핑 |
| `ui_evidence_instagram_dm_9x16.html` | 9:16 | 1080×1920 | 모바일 Instagram DM | 말풍선 순차 pop + 타이핑 (퍼플 그라데이션 outgoing) |
| `ui_evidence_slack_9x16.html` | 9:16 | 1080×1920 | 모바일 Slack 채널 | 메시지 3개 순차 fade-in |
| `ui_evidence_discord_9x16.html` | 9:16 | 1080×1920 | 모바일 Discord 채널 (dark) | 메시지 3개 순차 fade-in |
| `toast_notification_9x16.html` ⭐ NEW | 9:16 | 1080×1920 | **시스템 토스트 알림** (앱 내 메시지 X — Sonner/Shadcn 풍 OS-level toast) | 우측 슬라이드 인 + variant별 좌측 색 보더 + progress bar drain. variant: success/info/error/warn |

**Desktop UI (16:9 native — 10개)**
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
| `ui_evidence_code_editor_16x9.html` ⭐ NEW | 16:9 | 1920×1080 | **VSCode/Cursor 코드 에디터** (terminal CLI와 별개 — IDE 본질) | 타이틀바 + 파일 탭 + line number + VSCode dark+ syntax highlight + 첫 줄 typewriter, 나머지 stagger fade |
| `ai_chat_bubble_16x9.html` ⭐ NEW | 16:9 | 1920×1080 | **일반 AI 챗 UI** (ChatGPT/Claude 챗 등 — claude_code CLI 아닌 채팅 패턴) | 사용자 말풍선 typewriter → AI typing dots(3 cycles) → AI 응답 typewriter |

**Symbol / Brand / Card (9개 — 정사각 또는 소형)**
| Template | Aspect | Viewport | 용도 | 주요 motion |
|---|---|---|---|---|
| `message_object_16x9.html` | 16:9 | 1920×1080 | 빈 말풍선 심볼 ("카톡/DM 왔어요") | pop-in + wobble + 라벨 fade |
| `message_object_9x16.html` | 9:16 | 1080×1920 | 세로 영상용 빈 말풍선 심볼 | pop-in + wobble + 라벨 fade |
| `icon_hero_1x1.html` | 1:1 | 1080×1080 | 브랜드 로고 hero (텍스트 심볼) | card pop-in + glow pulse + label fade |
| `icon_claude_1x1.html` | 1:1 | 1080×1080 | Anthropic Claude starburst 로고 + 라벨 | card pop + starburst rotate + glow pulse |
| `icon_file_1x1.html` | 1:1 | 1080×1080 | 파일/문서 아이콘 (PDF/MD/DOCX 등 확장자 색상) | card pop + wobble + 파일명 fade |
| `dual_icon_1x1.html` | 1:1 | 1080×1080 | 두 브랜드 vs 비교 | 좌/우 slide-in + vs pulse |
| `dual_brand_1x1.html` | 1:1 | 1080×1080 | 진짜 SVG 로고 기반 dual brand 비교 | brand_registry 기반 SVG 좌/우 slide-in |
| `metric_ring_1x1.html` | 1:1 | 1080×1080 | 원형 퍼센트 게이지 | SVG stroke-dasharray + 숫자 카운트업 동기 |
| `ui_evidence_tweet_1x1.html` ⭐ NEW | 1:1 | 1080×1080 | **X (Twitter) 포스트 카드** (testimonial / 인용) | 카드 pop + 본문 typewriter + 리트윗·라이크 카운트업 + 하트 pop liked |
| `pricing_card_1x1.html` ⭐ NEW | 1:1 | 1080×1080 | **Pricing tier 카드** ("Pro 플랜에선") | 카드 pop + 가격 카운트업 + 체크 features stagger + CTA slide |

**Hero Text / Connection (5개 — 21st.dev / Magic UI 영향)** ⭐ NEW
| Template | Aspect | Viewport | 용도 | 주요 motion |
|---|---|---|---|---|
| `text_hero_aurora_16x9.html` | 16:9 | 1920×1080 | **결정적 한 줄 강조** (Magic UI Aurora Text) — emphasis로 표현 불가능한 다중 색 그라데이션 sweep이 핵심. 단순 텍스트 강조 시 text_only 우선 | label fade + 단어 stagger (back.out) + accent words 6색 aurora gradient sweep |
| `text_hero_sparkles_1x1.html` | 1:1 | 1080×1080 | **결정적 한 단어 / 짧은 구** (Magic UI Sparkles Text) — 14개 4-pointed star 파티클 twinkle. 성공·축하·결정 톤 | label fade + 단어 stagger + 14 star 파티클 stagger pop+rotate→shrink |
| `animated_beam_16x9.html` | 16:9 | 1920×1080 | **A → B 데이터 흐름 / 통합 / API 연결** (Magic UI Animated Beam) — 좌·우 두 노드 + 그 사이 SVG path beam draw + glowing dot이 path 따라 이동 | 좌 노드 pop → SVG bezier beam draw + dot path 따라 이동 → 우 노드 pop → dot pulse → footer fade |
| `orbiting_circles_1x1.html` | 1:1 | 1080×1080 | **에코시스템 / 통합 도구 군집** (Magic UI Orbiting Circles) — 중앙 hub + 내부 4 + 외부 6 위성이 반대 방향 회전 (위성 라벨은 카운터 회전으로 정자세 유지) | hub pop → 위성 stagger pop → 양 orbit 동시 회전 (timeline 전체 duration) |
| `logo_marquee_16x9.html` | 16:9 | 1920×1080 | **여러 도구·플랫폼 무한 스크롤 strip** (Magic UI Marquee) — 좌/우 edge fade mask + 두 줄 반대 방향 drift | 카드 pop + title fade + row 1 좌→ drift, row 2 우→ drift (선형, timeline 전체) + footer fade |

⚠️ 필요한 aspect variant가 없으면 **기획 단계에서 신규 template 작성 요청**. 임의로 다른 aspect 파일 쓰면 CapCut이 스케일하며 비율 왜곡.

### 기획 단계 의사결정

Motion 사용 시 플래너(Opus 4.7)가 `_claude_broll_plan.json`에 다음 중 하나로 명시:

```json
"broll": {
  "type": "stat_card",
  "motion": true,
  "motion_template": "stat_card_16x9",   // templates 디렉토리 파일 stem
  "motion_params": {
    "top_label": "회의 속 아젠다",
    "top_number": 10,
    "top_suffix": "개",
    "bottom_label": "뇌가 잡는 개수",
    "bottom_number": 4,
    "bottom_suffix": "개",
    "duration": 5.5
  }
}
```

### 기획 단계 2-step 판단

**Step 1 — Type별 본질 aspect 우선 체크** (콘텐츠 자체가 선호하는 비율):

| Type | 본질 aspect | 이유 |
|---|---|---|
| `ui_evidence/kakaotalk` | **9:16** | 카카오톡은 모바일 앱 — 세로 폰 화면이 native |
| `ui_evidence/instagram_dm`, `/youtube_shorts` | **9:16** | 모바일 native |
| `ui_evidence/youtube_comment`, `/notion`, `/terminal`, `/finder`, `/code_editor`, `/claude_code` | **16:9** | 데스크톱/웹 native |
| `ui_evidence/tweet`, `pricing_card`, `avatar_group` ⭐ | **1:1** | 카드형 콘텐츠는 정사각 본질 |
| `toast_notification` ⭐ | **9:16** | 모바일 OS 토스트 알림은 모바일 native |
| `ai_chat_bubble` ⭐ | **16:9** | 일반 AI 챗 UI는 데스크톱 챗 패턴이 native (모바일 변형 필요 시 신규 9x16 작성) |
| `icon_hero`, `dual_icon`, `dual_brand`, `icon_claude`, `icon_file`, `metric_ring` | **1:1** | 아이콘/로고/게이지는 정사각 본질 |
| `orbiting_circles` ⭐ | **1:1** | 회전 에코시스템은 정사각 본질 (대칭) |
| `stat_card`, `graphic_insight`, `bar_chart`, `line_chart` | **영상 aspect에 맞춤** (중립) | 추상 타이포/다이어그램이라 콘텐츠 고유 비율 없음 |
| `text_hero_aurora`, `animated_beam`, `logo_marquee` ⭐ | **16:9** | 가로 흐름·문장 강조·strip은 가로 본질 |
| `text_hero_sparkles` ⭐ | **1:1** | 단어 강조 + 파티클 burst는 정사각이 균형 |
| `message_object` (빈 말풍선 상징) | **16:9** or `_9x16` | 맥락 따라 |

**Step 2 — 영상 aspect × 연출 의도로 최종 선택**:

| 영상 aspect | 연출 의도 | 선택 |
|---|---|---|
| 16:9 가로 (YouTube 롱폼) | full-frame | type-본질 aspect 우선 (예: kakaotalk은 9:16을 작게 얹는 연출도 가능) |
| 9:16 세로 (Reels/Shorts) | **상단/하단 bar 오버레이** (아바타 공존) | `_16x9` — 가로로 긴 bar처럼 얹힘 |
| 9:16 세로 | **모바일 앱 재현** (KakaoTalk·Instagram 등) | **type-본질 aspect** (`_9x16`) ← 161755 scene 16 케이스 |
| 9:16 세로 | full-screen takeover (stat_card 등 중립 타입) | `_9x16` |
| 1:1 정사각 | 중앙 카드 | `_1x1` (미구현) |

**⚡ 핵심 원칙**:
1. **Type 본질 먼저**: "이 콘텐츠가 원래 어떤 형태로 소비되는가?" (KakaoTalk이면 무조건 세로 폰, Terminal이면 가로 데스크톱)
2. **영상 맥락 다음**: 영상 aspect와의 조합 연출 결정 (얹힌다 / 전체 교체 / 작은 폰 목업)
3. **9:16 영상이라고 무조건 9x16 template이 정답은 아님** — stat_card 같은 중립 타입은 16x9로 상단 bar 연출이 가능. 반대로 KakaoTalk은 16x9 영상이어도 9x16 폰 목업이 본질에 맞음.

### 렌더 CLI

```bash
PYTHONIOENCODING=utf-8 python tools/motion_graphics/render_motion.py \
  --template tools/motion_graphics/templates/stat_card_16x9.html \
  --params '{"top_label":"...","top_number":10,...,"duration":5.5}' \
  --out-base output/<name>/broll_motion/scene_010_motion \
  --fps 30 \
  --width 1920 --height 1080  # template aspect와 일치시킬 것
```

출력 2종:
- `*.mp4` — 블루 크로마 배경 보존 (CapCut에서 chroma key 수동 적용 시 사용)
- `*.mov` — ProRes 4444 with alpha (드래그 투입 즉시 투명 overlay, 기본 권장)

### overlay_patcher 동작

`overlay_patcher.py`는 파일 확장자(`.mov/.mp4/.webm`)로 video overlay를 자동 감지합니다:
1. ffprobe로 MOV 실제 duration 읽기
2. `material.type = "video"`, `source/target timerange` 모두 MOV 원본 길이로 clamp (stretch 방지)
3. 씬 duration이 MOV보다 길면 나머지 구간은 overlay 없이 메인 영상만

오버레이 크기·위치는 기존 `item.ratio` (기본 0.55) 로 컨트롤. 세로 영상의 상단 바 연출 등 세밀 조정은 ratio와 clip transform y를 plan에서 명시.

### 폐기 이유 없음 — POC 검증 필요

Motion 체계는 161755 POC에서 **재생 정상·품질 OK** 확인됨 (scene 10 stat_card 16:9 가로 bar + scene 16 kakaotalk 9:16 세로 폰).

### Phase 4 — scene_designer.py ingest 자동 통합 (2026-04-24)

Opus 4.7이 `_claude_broll_plan.json`에 `broll.motion:true` 를 명시하면 `scene_designer.py ingest`가 자동으로 `render_motion.py` 를 호출해 MOV를 생성하고 `broll_plan.json` items의 `image_path`에 기록함. 사용자가 수동 MOV swap할 필요 없음.

**Plan 스키마 (motion 케이스)**:
```jsonc
{
  "scene_idx": 10,
  "decision": "overlay",
  "reason": "회의 속 아젠다 10개 vs 뇌가 잡는 4개 — 카운트다운 연출 가치",
  "broll": {
    "type": "stat_card",
    "motion": true,
    "motion_template": "stat_card_16x9",   // tools/motion_graphics/templates/ 파일 stem
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

### ⭐ Motion 우선 원칙 (2026-04-25 — 사용자 가중치 변경 + 맥락 판단 보강)

**기본 정책**: overlay가 필요한 **모든 씬에서 motion을 1순위로 시도**. 정적 PNG는 motion이 매핑되지 않을 때만 fallback. 이유: 정적 이미지보다 시청 지속률·체감 품질이 높음. 가만히 있는 화면은 지루함.

**결정 트리 (3단계)**:
```
overlay 필요?
├─ NO → text_only / skip
└─ YES →
    ├─ Step A. 39개 variant 중 시나리오에 매핑되는 motion 후보가 있는가?
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

**Step C — 39개로 커버 안 되는 시나리오의 추가 제안 절차**:

LLM이 plan에 다음 중 하나로 명시 (사용자가 plan을 보고 결정 가능하게):

```jsonc
// 옵션 1: 신규 motion template 작성 제안 (시나리오가 재사용 가치 있을 때)
{
  "scene_idx": 14,
  "decision": "overlay",
  "reason": "구글 스프레드시트 셀 데이터 입력 시연 — 39개 카탈로그에 sheet UI 없음",
  "motion_proposal": {
    "needed": true,
    "suggested_stem": "ui_evidence_google_sheets_16x9",
    "rationale": "재사용 가치: 데이터·표·계산 시연 등 다른 영상에서도 자주 등장 가능",
    "fallback_if_not_built": "png"   // 신규 작성 안 하면 PNG로 진행
  },
  "broll": {
    // 신규 template 작성 전까지는 PNG src_hint도 함께 제공 (혹은 motion=false PNG로 plan)
    "type": "ui_evidence",
    "src_hint": "Google Sheets cell B7 with 형광펜 highlight on number 47..."
  }
}

// 옵션 2: 1회성·매우 특수 → 정적 PNG로 직행
{
  "scene_idx": 8,
  "decision": "overlay",
  "reason": "특정 인물 실루엣 — motion 가치 낮고 1회성. 신규 template 작성 가치 없음",
  "broll": {
    "type": "ui_evidence",
    "motion": false,
    "src_hint": "..."
  }
}
```

**판단 기준 — 신규 template vs PNG**:
| 신규 motion template 제안 (옵션 1) | 정적 PNG로 직행 (옵션 2) |
|---|---|
| 시나리오가 다른 영상에도 재사용 가치 있음 (예: 자주 등장하는 SaaS UI, 표/차트 종류) | 1회성·매우 특수한 콘텐츠 (실제 인물, 특정 사건 사진) |
| 시간축 연출이 가치 큼 (타이핑·순차·카운트) | 정적 묘사로 충분 (단순 심볼·로고 없는 추상) |
| 맥락 = 명확한 UI / 데이터 / 도식 | 맥락 = 분위기 / 추상 / 감정 |

**정적 PNG fallback 최종 케이스 (motion 미선택)**:
- 39개 카탈로그에 매핑 없음 + 신규 작성 가치도 낮음 (1회성)
- 콘텐츠가 motion으로 표현 불가능한 시각 자산 (실제 인물 사진, 손글씨 등)
- 그 외에는 **비슷한 motion이라도 우선 선택** (정적 PNG는 마지막 수단)

### 🎯 시나리오 → motion variant cheat sheet

| 나레이션/콘텐츠 시나리오 | 1순위 motion variant | 비고 |
|---|---|---|
| **숫자 비교** (before→after, A vs B) | `stat_card_<aspect>` | 카운트업/다운 임팩트 큼 |
| **체크리스트 / 3가지 행동 / N가지 팁** | `graphic_insight_<aspect>` | 보라 체크박스 순차 체크 |
| **매출·성장·추세** (시간축) | `line_chart_16x9` | SVG 라인 draw + 카운트업 |
| **카테고리 비교** (월별·분기별·항목별 막대) ⭐ | `bar_chart_16x9` | line은 추세, bar는 카테고리 — vertical bar grow + peak accent |
| **퍼센트·진행률·달성률** | `metric_ring_1x1` | 원형 게이지 + 숫자 카운트 |
| **N명이 사용 중 / 커뮤니티 규모** ⭐ | `avatar_group_1x1` | 5 avatar stagger + "+N" badge + total 카운트업 |
| **카톡 메시지** (모바일 native) | `ui_evidence_kakaotalk_9x16` | ★ 본질 9:16 |
| **카톡 그룹/회의방** | `ui_evidence_kakaotalk_9x16` | 4개 독립 말풍선 |
| **인스타 DM** | `ui_evidence_instagram_dm_9x16` | 퍼플 그라데이션 outgoing |
| **X (Twitter) 인용 / testimonial** ⭐ | `ui_evidence_tweet_1x1` | 카드 pop + 본문 typewriter + likes 카운트업 + 하트 liked |
| **YouTube 댓글 + CTA** ("댓글에 X") | `ui_evidence_youtube_comment_<aspect>` | 영상 aspect에 맞춤 |
| **노션 문서 / 회의록 / 요약 페이지** | `ui_evidence_notion_16x9` | 사이드바 + bullets |
| **터미널 / CLI / 명령어 시연** | `ui_evidence_terminal_16x9` | 컬러 prompt + typewriter |
| **VSCode/Cursor IDE 코드 시연** ⭐ | `ui_evidence_code_editor_16x9` | line number + dark+ syntax highlight + 첫 줄 typewriter |
| **Slack 채팅 / 워크스페이스** | `ui_evidence_slack_<aspect>` | 데스크톱 vs 모바일 선택 |
| **Discord 서버 / 커뮤니티** | `ui_evidence_discord_<aspect>` | 다크 테마 |
| **Finder / 파일 탐색기 / 자료 정리** | `ui_evidence_finder_16x9` | macOS 네이티브 |
| **Claude Code (시작/안내)** | `ui_evidence_claude_code_welcome_16x9` | 마스코트 + CLAUDE.md 안내 |
| **Claude Code (작업/AI 코딩)** | `ui_evidence_claude_code_16x9` | Thinking + tool calls |
| **일반 AI 챗 ("GPT한테 물어봤더니")** ⭐ | `ai_chat_bubble_16x9` | 사용자 → typing dots → AI 응답 typewriter |
| **시스템 토스트 ("결제 완료")** ⭐ | `toast_notification_9x16` | OS-level toast slide-in + variant 색 보더 (앱 메시지 X) |
| **브랜드 로고 단독 언급** (Notion/Slack 등) | `icon_hero_1x1` | 텍스트 심볼 + 글로우 |
| **Anthropic Claude 언급** | `icon_claude_1x1` | starburst 로고 |
| **파일·PDF·문서 (확장자 강조)** | `icon_file_1x1` | 확장자별 색상 (PDF·MD·DOCX 등) |
| **두 브랜드 vs 비교** ("노션 vs 옵시디언") | `dual_icon_1x1` | 좌/우 slide-in |
| **두 브랜드 진짜 SVG 로고 비교** | `dual_brand_1x1` | brand_registry 기반 |
| **메시지 알림 상징** ("카톡 왔어요") | `message_object_<aspect>` | 빈 말풍선 + wobble |
| **결정적 한 줄 강조** (감정 톤·결론) ⭐ | `text_hero_aurora_16x9` | 단어 stagger + 6색 aurora gradient sweep — emphasis로는 표현 불가능한 다중 그라데이션 |
| **결정적 한 단어 (성공·축하·결정)** ⭐ | `text_hero_sparkles_1x1` | 단어 stagger + 14 star 파티클 twinkle |
| **A → B 데이터 흐름 / API 통합** ⭐ | `animated_beam_16x9` | 좌·우 노드 + SVG bezier beam draw + glowing dot 따라 이동 |
| **에코시스템 / 통합 도구 군집** ⭐ | `orbiting_circles_1x1` | 중앙 hub + 위성 양방향 회전 |
| **지원 플랫폼 / 함께 쓰는 도구들** ⭐ | `logo_marquee_16x9` | 무한 스크롤 두 줄 반대 방향 + edge fade mask |
| **Pricing tier ("Pro 플랜에선")** ⭐ | `pricing_card_1x1` | 카드 pop + 가격 카운트업 + 체크 features stagger + CTA |

**aspect 선택 (씬에 맞는 \<aspect\>)**: 영상이 9:16이고 모바일 native 콘텐츠(카톡/인스타) → `_9x16` / 영상이 9:16이고 데스크톱 콘텐츠를 bar 형태로 얹기 → `_16x9` / 영상이 1:1이거나 정사각 카드 연출 → `_1x1`. 자세한 2-step 판단은 위쪽 표 참고.

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

## 📄 `_claude_broll_plan.json` 스키마

```json
{
  "title": {
    "text": "영상 제목",
    "accent_words": ["핵심단어"],
    "duration_sec": 4.0
  },
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
      "emphasis": {"text": "278명", "accent_words": ["278"]}
    }
  ]
}
```

**valid decisions**: `skip` / `overlay` / `split` / `dual` / **`text_only`**
**valid types** (skip/text_only 제외): 위 **6종** (`icon_hero` / `ui_evidence` / `message_object` / `stat_card` / `dual_icon` / `graphic_insight`)

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

| 스타일 | 용도 | opacity | aspect 권장 |
|---|---|---|---|
| `overlay` | 1개 이미지 상단 floating (55% scale) | 0.75 | 16:9 |
| `dual` | 좌우 2개 나란히 (각 42%) | 0.75 | 1:1 × 2 |
| `split` | 상단 덮기 + 메인 아래 | **1.0** (필수) | 16:9 |

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
| [tools/capcut_pipeline/scene_designer.py](../../../tools/capcut_pipeline/scene_designer.py) | DECISION_TREE + context/ingest/generate-images CLI |
| [tools/capcut_pipeline/overlay_patcher.py](../../../tools/capcut_pipeline/overlay_patcher.py) | 3 스타일 패치 + 멱등성 |

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
- [ ] overlay_patcher 실행 전 CapCut 완전 종료
