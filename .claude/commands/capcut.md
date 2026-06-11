# /capcut — CapCut 자동 편집 오케스트레이터

로컬 영상 → STT → 씬 분할 → 드래프트 → B-roll → **FX** → 제목/캡션 → 내보내기.

이 커맨드는 **오케스트레이터**입니다. 세부 작업은 각 단계의 스킬 파일을 **반드시 Read하고** 그 안의 체크리스트를 따라 수행합니다.

---

## ⛔ 절대 규칙 — 단계 스킵 금지

1. 각 단계 시작에서 **`⛔ STOP. Call Read('...') NOW.`** 지시를 무시하지 말 것. 해당 스킬 SKILL.md를 Read 도구로 **직접 호출**한 후에만 진행. "기억에 있다"고 건너뛰지 말 것.
2. 각 단계 **완료 게이트**는 `verify_step.py` 로 **머신 검증**. `- [ ]` 마음속 체크 금지.
3. **FX 단계(Step 5)는 특히 빠지기 쉬움** — 5개 키(filter·bgm·sfx·scene_effects·**intro_video_animation**) 모두 포함 + `speed` 1.2. 코드가 exit 5로 막아준다. 현재 기본: title/outro typewriter·flash_warm 제거, 인트로는 첫 클립만 **사이드 슬라이드(side_slide)**, 전역 1.2배속.

과거 사고 기록:
- PROMPTER_20260417_161003에서 filter 누락 → 코드 게이트(`--verify-completeness`)로 차단됨
- `wc -c > 400` 한글 UTF-8 버그 → `verify_step.py` 가 Python `len()` 으로 대체

---

## 🧰 도우미 도구 (new)

| 도구 | 용도 |
|---|---|
| `tools/capcut_pipeline/verify_step.py <N> --name X` | 각 단계 머신 검증 (1~6 + 2.5) |
| `tools/capcut_pipeline/extract_fx_candidates.py --draft X --top-k 6 --out fx_plan.json` | fx_plan.json 자동 생성 (Step 5 추측 제거) |
| `tools/capcut_pipeline/capcut_fx_patcher.py ... --verify-completeness` | fx_plan 5-key 사전 검증 |
| `tools/capcut_pipeline/check_registry_drift.py` | preset 이름 SoT ↔ SKILL.md 일관성 체크 |

---

## 🎯 7단계 파이프라인 (반드시 순차 실행)

### Step 1 — 파이프라인 실행

⛔ **STOP. Call `Read('.claude/skills/capcut-pipeline/SKILL.md')` NOW.**

실행:
```bash
/capcut <video> --title "영상 제목" --model large-v3
```

내부: `python tools/capcut_pipeline/run_pipeline.py <video> --title "..." ...`

**게이트** (머신 검증):
```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/verify_step.py 1 --name <name>
```
→ `[step1] PASS: scenes=N, transcript_cues=M` 나와야 통과.

---

### Step 1.5 — NG/retake/묵음 자동 정리 (LLM 직접 판단)

⛔ **STOP. Call `Read('.claude/skills/capcut-pipeline/SKILL.md')` NOW. (§ Step 1.5 NG 정리 부분 중점)**

**철학**: silencedetect 씬 분할 위에 컷팅을 하지 않고, **Scribe word-level transcript을 LLM이 직접 보고 retake/NG/묵음을 식별** → keep_intervals만 판단 → ng_cutter가 cut + transcript shift + crossfade 자동 처리.

**핵심 규칙**: `drop_earlier_retake_keep_later` — 같은 발화 반복 시 **앞 take(NG)** drop, 뒤 take(polished) keep.

**하위 단계 (1.5-A ~ 1.5-D 순차)**:

#### 1.5-A. context 생성 (utterance 표 + retake hint)

```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/ng_detector.py analyze --name <name>
```
→ `temp/<name>/ng_context.md` 생성 — Scribe 문장 단위 utterance 표 + 자동 retake hint(⚠/✓) + 출력 스키마.

#### 1.5-B. **Claude(Opus 4.7)가 직접** keep_intervals.json 작성 ⭐

⛔ **절대 규칙**: NG 판단은 **LLM이 transcript 직접 읽고 판단**한다. 규칙 기반 매칭 금지 (MEMORY: `feedback_plan_by_llm_not_rules`).

**Claude 체크리스트**:

1. **Read `temp/<name>/ng_context.md`** — utterance 표 + 판단 rubric 정독
2. **retake hint 표시(⚠ EARLIER / ✓ LATER)** 우선 처리 — leading 3+ word match는 강력한 retake 시그널
3. **각 utterance 분류**:
   - 진짜 retake (앞 = NG) → drop earlier
   - filler ("어/음/그") → drop
   - frustration ("아 미치겠다", "하.") → drop
   - noise (괄호 audio_event) → drop
   - 그 외 → keep
4. **연속 keep utterance 묶기** — 자연스럽게 이어지는 문장은 한 interval로 통합
5. **`keep_intervals.json` Write** — 스키마: `{version:6, name, source_duration_sec, stt_engine, rule:"drop_earlier_retake_keep_later", keep_intervals:[{start,end,text,reason}]}`
6. **start/end는 raw Scribe word_start/word_end 그대로** — 어미 연장(+400ms) / breath buffer 수동 추가 금지 (ng_cutter 자동)
7. **의심 시 keep** — False Positive(좋은 take drop) 절대 금지

#### 1.5-C. plan 검증 + 리뷰

```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/ng_detector.py report --name <name>
```
→ `temp/<name>/ng_plan_review.md` 생성 — keep intervals 표 + drop 구간 + 통계.

스키마 에러(version, overlap, end > duration) 시 exit 2.

#### 1.5-D. ng_cutter로 실제 cut + transcript shift

```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/ng_cutter.py \
  --source <원본.mp4> --name <name>
```

**자동 처리** (LLM 신경 안 써도 됨):
- 각 keep interval **end +400ms** 연장 (Scribe word_end가 한국어 어미 vowel decay 직전 끝남, "~다/~요" 잘림 보정)
- 다음 NG word/interval과 **50ms safety margin** 자동 cap
- 각 cut clip **50ms audio fade-in/out** (boundary click 제거)
- **transcript timeline shift** to clean coordinate (per-interval segment split — cross-scene cue 방지)
- **scenes/scene_XX.mp4 재인코딩** (frame-accurate, audio AAC 192kbps, `-ss BEFORE -i` 고정)

⚠️ **`-ss` 위치**: ng_cutter는 input seek (`-ss before -i`) 사용. output seek + afade 조합은 ffmpeg aac 인코더 버그로 비트레이트 24kbps 붕괴.

**게이트** (자동 검증):
- `output/<name>/scenes/scene_XX.mp4` 14개 (예시) 생성
- `output/<name>/subs/transcript.{json,srt}` clean timeline shifted
- `output/<name>/cleaned_timeline_map.json` (원본↔클린 매핑)
- 각 scene mp4의 audio bitrate ≥ 100 kbps (소스 ~128kbps 대비)

**기존 silencedetect 출력은 `.silence_bak` 접미사로 자동 백업** — fallback 가능.

---

### Step 2 — 자막 교정

⛔ **STOP. Call `Read('.claude/skills/capcut-subtitle/SKILL.md')` NOW.**

할 일:
- `output/<name>/subs/transcript_wrapped.raw.srt` 백업 → Claude가 맞춤법·띄어쓰기 교정 → `transcript_wrapped.srt` 재저장
- **불변 조건**: 타임스탬프 변경 금지, cue 개수 변경 금지

⚠️ **wrap(줄바꿈) 의미 단위도 육안 점검 필수** — 맞춤법만 보지 말 것. `"~하고 싶은"` / `"마음,"` 처럼 명사구·조사구가 부자연스럽게 쪼개지면 **재wrap** 필요 (SKILL.md "look-ahead 보류" + "Step 2 교정 시 wrap 점검" 섹션 참조). 재wrap은 cue 수를 바꾸므로 불변 게이트가 아니라 **재처리 체인**(재wrap → 교정 재적용 → raw.srt 재생성 → 드래프트 재빌드 → overlay/fx `--mode clean` 재패치)을 탄다.

**게이트** (머신 검증):
```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/verify_step.py 2 --name <name>
```
→ `[step2] PASS: N cues, timestamps_match=True` 나와야 통과.
(재wrap 시 `transcript_wrapped.raw.srt`도 새 cue 구조로 재생성해야 이 게이트 통과)

---

### Step 2.5 — 드래프트 재빌드 (⚠️ 누락 시 Step 3가 오래된 자막으로 패치됨)

교정된 자막이 드래프트에 반영되도록 파이프라인을 재실행:
```bash
/capcut <video> --skip-stt --skip-wrap --skip-cut --sub-offset-ms 600 --sub-max-duration-ms 5000
```

**게이트** (머신 검증):
```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/verify_step.py 2_5 --name <name>
```
→ `draft_content.json mtime > transcript_wrapped.srt mtime` 이어야 PASS.

이 단계를 건너뛰면 Step 3의 overlay_patcher가 **교정 전 자막**을 드래프트에 박는다. 필수.

---

### Step 3 — B-roll 자동 파이프라인 (⛔ 시각 자산 전용)

⛔ **STOP. Call `Read('.claude/skills/capcut-broll/SKILL.md')` NOW. 근본 원칙 확인.**

**핵심 철칙**: *"emphasis 텍스트로 전달 불가능한 시각 자산"만 B-roll. 나머지는 전부 text_only.*

B-roll 만들기 전 반드시 자문:
1. 이 이미지가 text_only + emphasis로 전달 불가능한가?
2. 실제 UI / 로고 / 말풍선 / 도식 없이는 메시지가 손상되는가?

→ **하나라도 NO면 `decision: text_only`. B-roll 제작 금지.**

**6-type 시스템** (실사 photo + 순수 텍스트 나열 + 단일 숫자 이미지 전면 금지): `icon_hero` / `ui_evidence` / `message_object` / `stat_card` / `dual_icon` / `graphic_insight`. `split_stack` · `symbol_moment` · `number_hero` **폐기**.

---

#### ⛔⛔ v2 반-클리셰 (코드 게이트로 강제 — "뻔한 글자 카드" 방지)

> `broll_reviewer._pre_filter_plan`이 **SDK 없이도 결정론적으로 강제**(위반 시 ingest 차단). 자세한 건 SKILL.md 최상단 "반-클리셰 원칙" + [[feedback_broll_v2_capabilities]].

1. **글자 카드 = 자막 중복 = 뻔함**: 무지개 그라데이션·파티클 장식 글자카드는 **만들지 않는다**(자막 중복 + 단일 accent 위반). 절제된 풀스크린 글자 강조가 필요하면 `kinetic_type_9x16`(어절 mask-reveal + 형광펜) 사용. 그 외 단순 글자 강조는 `decision: text_only` + emphasis.
2. **같은 type/template 2회 반복 금지** — 영상 내 단조 차단(reject).
3. **검은 카드만 금지** — overlay 2개+면 **최소 1개는 실제 시각 정보**(`ui_evidence`(claude_code/terminal/notion 등) / 데이터 차트(`line_chart`/`bar_chart`/`metric_ring`/`avatar_group`) / 신규 `device_mockup_9x16`). 전부 글자/체크박스 카드면 reject.
4. **기술·AI·툴·빌딩 주제 → `ui_evidence` 1순위** (추상 글자 카드 대신 실제 작업 화면). 실측: stat_card(데이터) + ui_evidence_claude_code(실제 빌딩) 2개가 글자 카드 3개보다 강력.
5. **영상 간 반복 금지** — `tools/capcut_pipeline/.broll_usage_log.json` ledger(ingest 자동 기록). 직전 영상과 template 조합 완전 겹치면 reject.

**신규 archetype (v2 승인):**
- `comparison_9x16` ⭐ — **A vs B 다항목 대비**(소비 vs 빌더, Broke vs Rich 류). 2열(좌 부정/우 긍정) 제목+항목(첫 항목 pill)+중앙 VS 노드, 순차 등장, 투명 오버레이. params: `left_title`, `right_title`, `left_items[]`, `right_items[]`, `duration`. dual_icon(로고뿐)·stat_card(숫자뿐)로 못 하던 개념 대비 리스트. substance로 인정. 풀프레임 takeover(overlay_h_ratio ~0.9 + position_y center 권장).
- `kinetic_type_9x16` — 풀스크린 키네틱 타이포(어절 mask-reveal + accent 형광펜 밑줄). params: `lines[]`, `accent_words[]`, `duration`. aurora/sparkles 대체재.
- `device_mockup_9x16` — 실제 스크린샷을 폰/브라우저 프레임에 삽입(Ken Burns). params: `device`("phone"|"browser"), `image_path`(file:// 절대경로), `caption`, `duration`. **실사사진 reject**, image_path 없으면 graphic_insight/text_only 폴백. ui_evidence(손으로 그린 재현 UI) vs device_mockup(실제 캡처) 구분.
- `split_reveal_9x16` ⭐ — 전→후 와이프(좌 before / 우 after가 와이프로 전환). before→after 상태 변화 시각화. 상세는 capcut-broll SKILL.
- `ratio_dots_9x16` — 비율을 점 격자로 ("10명 중 7명" → 채운 점 7 / 빈 점 3). 분수·비율 강조. 상세는 capcut-broll SKILL.
- `vertical_timeline_9x16` — 세로 단계 타임라인 ("인식→수용→행동" 류 순차 단계). 프로세스·여정. 상세는 capcut-broll SKILL.
- `brand_logos.js` — 진짜 SVG 로고 레지스트리. `logo_marquee`/`icon_hero`/`orbiting_circles`가 `brand` key로 소비(미등록은 이니셜 폴백).
- **모션 공통 런타임**: 모든 motion template은 `shared.css` + `shared_motion.js`(`livingHold`=카드 정지 구간에도 미세 호흡으로 "얼지" 않게, `choreographedExit`=부드러운 퇴장) 사용.

**🎯 구도 규칙 (9:16 토킹헤드 — 얼굴/자막 침범 금지):** overlay는 상단(얼굴 위) 기본. `position_y` 슬롯(`top`/`center`/`lower`)으로 씬별 지정 — `center`는 얼굴 위라 비권장(코드가 경고+상단 push).

⛔ **타이틀·강조(emphasis) 자막은 상단(`top`) 기본 — 가운데 금지.** 타이틀 기본 position도 `top`(overlay_patcher 기본값). emphasis는 `top`이 원칙이고, 같은 시점에 상단 overlay가 있으면 `start_offset_sec`로 **시점을 분리**(겹치면 lower로 잠깐 내릴 수 있으나 center 금지). 단순 시점차(동시 노출 X)면 `lower` 말고 `top`으로 — 중간에 자막 뜨는 인상 방지.

⛔ **`top` 슬롯 y값 = 0.55** (overlay_patcher `emphasis_position_y` 기본값). 0.7은 인스타 **계정명/팔로우 버튼(상단 ~10%)에 가려짐**; 0.55가 계정명 아래 안전 마진. 타이틀(2줄)은 더 내려 y≈0.5.

⛔ **시작(타이틀 등장) 구간엔 emphasis 자막을 동시에 띄우지 말 것.** 오프닝은 **타이틀 + 첫 클립 사이드 슬라이드**만. scene 0 emphasis는 타이틀이 사라진 뒤(`start_offset_sec`를 타이틀 duration 이후로) 시작. 타이틀과 emphasis가 화면에 겹치면 안 됨.

---

**하위 단계 (3-A ~ 3-D 순차)**:

#### 3-A. **Claude(Opus 4.7)가 직접** `_claude_broll_plan.json` 작성 ⭐

⛔ **절대 규칙**: B-roll 플래닝은 **LLM(현재 세션의 Claude)이 대본을 직접 읽고 판단**한다. 정규식/규칙 기반 매칭(`plan_generator.py`)은 폐기됨. 과거 자동 규칙이 "47:1 vs 6:4" 같은 명백한 stat_card 후보를 놓치고, "숫자 4" 같은 단일 숫자를 B-roll로 분류하는 등 품질이 들쭉날쭉했기 때문.

**Claude가 수행할 체크리스트**:

0. ⭐ **sample 카탈로그 빌드 확인**:
   ```bash
   PYTHONIOENCODING=utf-8 python tools/motion_graphics/build_catalog.py
   ```
   → `sample_catalog.json` + `out/thumbs/` PNG 생성 (전부 user_approved, forbidden 0개). 이미 최신이면 idempotent. ⚠️ **신규 template을 추가했으면** playwright 있는 절대경로 인터프리터(`$LOCALAPPDATA/Programs/Python/Python313/python.exe`)로 sample MOV 렌더 후 build_catalog 재실행해야 user_approved 반영 (안 하면 stale).
1. **Read `.claude/skills/capcut-broll/SKILL.md`** — 6 타입(icon_hero/stat_card/message_object/dual_icon/ui_evidence/graphic_insight), 근본 원칙, 블루 크로마, **"Motion 카탈로그 시각 검증" 섹션 필수 정독**.
2. **Read** 다음 소스 4개:
   - `temp/<name>/broll_designer_context.md` — Motion 카탈로그(user_approved 전체, forbidden 없음) + 씬별 narration이 자동 주입됨. 정독 의무.
   - `output/<name>/subs/transcript.json` — word-level 타이밍
   - `temp/<name>/scenes.json` — 씬 경계
   - `$LOCALAPPDATA/CapCut/User Data/Projects/com.lveditor.draft/<name>/draft_content.json` — 기존 emphasis 텍스트 + 타이밍
2.5. ⭐ **motion 후보 시각 확인** (HARD 의무):
   - overlay 후보 결정 전 각 motion의 frame_thumbs PNG 3장을 Read 도구로 직접 확인:
     ```
     tools/motion_graphics/out/thumbs/<stem>__early.png
     tools/motion_graphics/out/thumbs/<stem>__mid.png
     tools/motion_graphics/out/thumbs/<stem>__end.png
     ```
   - cheat sheet 텍스트 설명만 보고 결정 금지 (과거 실패 사례: forbidden _9x16 youtube_comment 선택, 같은 type 반복, params 일반화 short cut)
   - ⛔ **params는 `sample_catalog.json`의 `params_schema`만 믿지 말 것** — catalog schema가 불완전/부정확할 수 있음 (예: youtube_comment는 catalog상 `comments_count`만 보이지만 실제론 `comments[]` 배열을 받고, beam `left/right`는 문자열이 아니라 `{symbol,label,bg,color}` 객체). **반드시 `tools/motion_graphics/templates/<stem>.html`의 `window.__params = {...}` 기본값 블록을 Read해서 정확한 키·타입(문자열/객체/배열) 확인** 후 motion_params 작성.
3. **씬별 판단 루프** (각 씬에 대해):
   - 나레이션이 담긴 구체적 브랜드/데이터/UI/수치비교/CTA를 명시하는가?
   - emphasis 텍스트만으로 전달 가능한가? → YES면 `text_only`
   - 그렇지 않고 시각 자산이 필수인가? → `overlay` + 적절한 type + 구체적 src_hint
   - 둘 다 아니면 → `skip`
4. **src_hint 작성 원칙** (overlay인 경우):
   - VERBATIM 콘텐츠 명시 (예: KakaoTalk 말풍선 속 4개 bullet를 정확히 적어줌)
   - `SOLID FLAT CHROMA BLUE #0000FF (RGB 0,0,255) — NOT sky blue, NOT pale blue` 문구 반드시 포함
   - 한글은 Pretendard Medium/Bold, 숫자는 "SOLID FILLED white #FFFFFF" 명시 (outline-only 렌더링 방지)
5. **`_claude_broll_plan.json` Write** — 스키마:
   ```jsonc
   {
     "scenes": [
       {
         "scene_idx": N,
         "decision": "overlay" | "text_only" | "skip",
         "reason": "...",              // ⛔ 구체적 시각 근거 必. "강조"/"시각적" 같은 막연한 사유는 렌더 전 자동 reject
         "broll": {                     // overlay일 때만
           "type": "stat_card" | "ui_evidence" | ...,
           "brand_key": "kakaotalk",    // optional
           "src_hint": "...",           // 정적 이미지용 Gemini 프롬프트
           "anchor_phrase": "...",      // optional. 화자가 실제로 말하는 구절 → overlay 타이밍이 실측 단어 경계로 자동 스냅(speech-anchor)

           // --- motion (Hyperframes-inspired) ---  (optional; 선택 시 아래 필드)
           "motion": true,              // true면 정적 PNG 대신 GSAP MOV 생성
           "motion_template": "stat_card_1x1",  // sample_catalog.json의 user_approved stem만. B-roll은 1:1 또는 9:16 풀프레임 선호(16:9 중립카드 지양)
           "motion_params": { ... },    // 각 template의 params_schema 키만 (phrase/title/items 다름)
           "sample_reviewed": true,     // ⭐ HARD: frame_thumbs 3장 Read 후 true
           "sample_reviewed_notes": "early=..., mid=..., end=...",  // ⛔ early/mid/end 키 3개 必(비공백·distinct). 누락 시 VQ-03 strict reject

           // --- v2 구도/타이밍 (optional, default=기존동작) ---
           "position_y": "top",         // "top"(얼굴 위·기본) | "center"(비권장) | "lower"(자막 위). 자유 float 금지
           "overlay_h_ratio": 0.55,     // 가로 점유 비율(기존 ratio)
           "start_offset_sec": 0.0,     // overlay 등장 시점(씬 시작 기준). 긴 씬은 늦게 등장
           "display_dur_sec": null,     // 표시 길이(null=motion intrinsic). 박제 방지
           "justification": "..."       // text_hero류 글자 카드를 굳이 쓸 때만 필수(없으면 reject)
         },
         "emphasis": { ... }
       }
     ],
     "title": { ... }
   }
   ```
   - **품질 > 개수 (v2)**: 억지로 overlay 3-5개 채우지 말 것. **substance 있는(실제 UI/데이터) overlay 2개가 뻔한 글자 카드 3개보다 낫다.** 단 overlay가 2개+면 그 중 최소 1개는 실제 시각 정보여야 함(반-클리셰 규칙 3). 스크립트에 데이터/UI/빌딩 소재가 1개뿐이면 overlay 1개 + 나머지 text_only도 정상.
   - **emphasis 하한선 (HARD)**: skip이 아닌 **모든 씬에 `emphasis` 객체 필수**. `text_only` = 이미지 skip, emphasis는 유지. 빈 text_only = 즉시 reject (MEMORY: `feedback_capcut_emphasis_per_scene`). 긴 씬(20초+)은 `start_offset_sec`로 emphasis 다중 배치.
   - **자가 카운트 게이트** (plan Write 직후): (a) overlay 중 substance(실제 UI/데이터) ≥ 1? (b) 같은 type/template 반복 없음? (c) text_hero(aurora/sparkles) 안 씀? (d) emphasis 카운트 = (전체 씬 - skip 씬)? 모두 YES여야 다음 단계.
   - ⭐ **Motion 우선 원칙**: overlay가 필요한 모든 씬에서 **motion을 1순위로 검토**. SKILL.md 시나리오→variant cheat sheet에 매핑되는 motion이 있으면 무조건 motion 사용 (정적 PNG보다 시청 지속률 높음, 덜 지루함).
   - 🎯 **승인된 variant 중 베스트 선택 — LLM이 전체 맥락 종합 평가** (3-step):
     - **Step A. 후보 추리기**: cheat sheet + user_approved 카탈로그에서 시나리오에 매핑되는 모든 motion 후보 나열
     - **Step B. 베스트 선택 판단 기준** (4축 종합):
       - ① **지루하지 않음** — 카운트업·타이핑·순차 등장 등 시간축 임팩트 큰 것 선호
       - ② **상황 적합도** — 나레이션 의도와 가장 자연스럽게 맞는 것
       - ③ **임팩트** — 첫 0.5초에 시청자 attention 끌 수 있는 것
       - ④ **본질 aspect** — 콘텐츠 native form 일치 (KakaoTalk=9:16 native 등)
     - **Step C. 매핑 안 되는 시나리오 — 추가 제안 절차** (plan에 명시):
       - **옵션 1: 신규 motion template 제안** (재사용 가치 있을 때) → `motion_proposal: { needed: true, suggested_stem: "...", rationale: "...", fallback_if_not_built: "png" }`
       - **옵션 2: 정적 PNG 직행** (1회성·매우 특수) → `broll.motion: false` + `src_hint`
       - 판단 기준: **재사용 가치 + 시간축 가치 + 명확한 UI/데이터** → 신규 제안. **1회성·추상·실사** → PNG.
   - **motion template aspect 선택**: 2-step 판단 (SKILL.md 참조) — ① type 본질 aspect (KakaoTalk=9:16 native 등) ② 영상 × 연출 의도. 승인 variant + 시나리오→variant cheat sheet + 신규 제안 절차는 SKILL.md "⭐ Motion 우선 원칙" 섹션 참고.
6. **자가 검증**: 내 계획이 SKILL.md의 "⛔ 근본 원칙"을 위반하지 않는가? 6 타입만 썼는가? src_hint가 "책상+펜+노트" 같은 실사 photo를 유도하지 않는가? motion 선택이 정말 시간축 연출이 필요한 경우인가?

**판단 우선순위 (가장 강력한 후보)**:
- 수치 before→after 대비 → `stat_card` (예: "이력서 20개 → 합격 0개")
- 다중 수치 테이블 → `graphic_insight` 2-row 비교 카드 (예: "A: 47→1 vs B: 6→4")
- 실제 플랫폼 UI가 CTA를 구체화할 때 → `ui_evidence` (예: YouTube 댓글창)
- 브랜드 단일 언급 → `icon_hero`
- 2-3 브랜드 병렬 언급 → `ui_evidence` (3-icon row) 또는 `dual_icon`
- 메시지 알림 상징 → `message_object`

**폴백 (정말 급한 경우만)**: `plan_generator.py`는 이제 **skeleton 전용 래퍼**로 강등됨 — `--fallback-skeleton` 옵션으로만 실행 가능하며 모든 씬을 `skip`으로 초기화한 뒤 draft의 emphasis만 `text_only`로 매핑해 반환. Opus 직접 플래닝이 원칙.

#### 3-B. 3-Persona 자동 리뷰 (필수 게이트)

```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/broll_reviewer.py \
  --plan       temp/<name>/_claude_broll_plan.json \
  --transcript output/<name>/subs/transcript.json \
  --scenes     temp/<name>/scenes.json \
  --out        temp/<name>/broll_review.json
```

**자동 pre-filter** (SDK 없이도 **항상 도는** 결정론 게이트 — v2 강화):
- 폐기 type (`split_stack`/`number_hero`/`symbol_moment`), 순수 텍스트 나열, 단일 숫자
- 무지개/파티클 장식 글자카드 패턴 (만들지 않음 — kinetic_type/text_only로)
- **같은 type/template 2회 반복**
- **overlay 2개+인데 substance(실제 UI/데이터) 0개** (검은 카드만)
- **자막-overlay 텍스트 중복**(VQ-02)
- **영상 간 반복**(ledger, 직전 N영상과 완전 겹침)

**PASS 기준**: 각 페르소나 overall ≥ 4.0, **visual_only_value ≥ 4**, rejects 빈 상태, aggregate ≥ 4.0.

⚠️ **SDK 미설치 시** reviewer는 placeholder(pass=false)로 빠진다. 이때 **세션 Claude가 직접 3-persona 평가**해 `broll_review.json`을 `mode:"in_session_claude_review"` + `persona_scores`(3인 이상, 각 overall + 비공백 distinct notes) + `pass:true`로 작성 ([[feedback_capcut_proofread_agent]]). ⛔ pre_filter가 reject(critical_issues 있음)면 그건 먼저 plan 수정. SI-04 게이트가 빈 self-pass(persona_scores 누락)를 차단.

**strict 게이트** (scene_designer ingest, 기본 ON, `OMC_BROLL_STRICT=0`으로 점진 강등):
- VQ-03: motion broll의 `sample_reviewed_notes`에 early/mid/end 키 3개(비공백·distinct) 필수.
- SI-04: `broll_review.json` mode = sdk/orchestrator_personas/in_session_claude_review만 통과.

→ exit `0` (PASS)만 다음 단계. `2` (REJECT)면 `broll_review.json`/stderr 읽고 plan 수정 후 재실행.

#### 3-C. scene_designer ingest + generate-images (자동 chroma_remove 포함)

```bash
# broll_review.json PASS 확인 후 통과
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/scene_designer.py ingest \
  --input  temp/<name>/_claude_broll_plan.json \
  --scenes temp/<name>/scenes.json \
  --out    temp/<name>/broll_plan.json

PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/scene_designer.py generate-images \
  --plan    temp/<name>/broll_plan.json \
  --out-dir output/<name>/broll_gemini
```

⭐ **블루 크로마 파이프라인** (자동):
- Gemini 프롬프트에 `Solid #0000FF blue background` 자동 주입
- 이미지 생성 후 `chroma_remove.py`가 자동 호출 → 블루 → alpha 투명 처리
- overlay 시 메인 영상이 투명 영역에서 보임 (이전 "검은 박스 덮음" 문제 해결)

⚠️ `broll_review.json` 없거나 `"pass": false`면 ingest exit 2. 긴급시 `--skip-review` (권장 X).
⚠️ plan에 `split_stack`·`symbol_moment`·`number_hero` 있으면 에러 + migration 메시지.

#### 3-C.5 ⭐ 렌더된 MOV **실제 시각 검증** (HARD 의무 — overlay_patcher 전 필수)

⛔ **frame_thumbs(sample) 검증은 template 기본 params 결과일 뿐**, 내가 넣은 커스텀 motion_params로 렌더된 실제 MOV와 다르다. ingest가 생성한 `output/<name>/broll_motion/scene_NNN_motion.mp4`에서 **프레임을 직접 추출해 Read로 시각 확인**한다.

```bash
# 각 motion MOV의 mid/end 프레임 추출 (n은 fps×초; 30fps면 mid≈90, end≈150)
for f in output/<name>/broll_motion/scene_*_motion.mp4; do
  b=$(basename "$f" .mp4)
  ffmpeg -y -i "$f" -vf "select=eq(n\,135)" -vframes 1 "temp/<name>/_check/${b}_end.png" 2>/dev/null
done
```

→ 추출한 PNG를 **Read로 직접 본다**. 체크:
- 텍스트/라벨이 내가 의도한 값으로 나왔는가? (fallback 기본값 "A"/"B", 빈 카드, 깨진 숫자면 params 오류 — HTML `__params` 다시 확인 후 plan 수정 → 기존 MOV 삭제 → ingest 재실행)
- 9:16 영상에 카드가 인물/자막 안 가리는가? (가리면 `card_opacity` 낮추거나 위치 조정)

⚠️ sample thumbnail만 보고 진행하면 깨진 채 패치된다(예: beam이 "A/B" 노드 + 빈 라벨, youtube_comment가 "1200" + 빈 댓글). **커스텀 렌더 실제 확인 없이 overlay_patcher 진행 금지.**

#### 3-D. overlay_patcher 적용 (CapCut 완전 종료 후)

```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/overlay_patcher.py \
  --draft "$LOCALAPPDATA/CapCut/User Data/Projects/com.lveditor.draft/<name>/draft_content.json" \
  --plan  "temp/<name>/broll_plan.json" \
  --image-dir "output/<name>/broll_gemini"
```

**게이트** (머신 검증):
```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/verify_step.py 3 --name <name>
```
→ `[step3] PASS: broll_images=N, text_tracks=2+, patch_state=found, emphasis_track_present=True`

**⚠️ emphasis text track 체크**: 이 gate가 실패하면 Step 5의 Python 스크립트가 KeyError로 죽는다. overlay_patcher 로그 확인 + 재실행.

---

### Step 4 — 제목 + 인스타 캡션 생성

⛔ **STOP. Call `Read('.claude/skills/capcut-deliverables/SKILL.md')` NOW.** (§ title.txt + ig_caption.txt 부분 중점)

할 일:
- `output/<name>/deliverables/title.txt` — 20자 이하 후킹 제목 (Python `len()` 기준)
- `output/<name>/deliverables/ig_caption.txt` — 400~600자 (Python `len()` 기준), 격식체+공감체, 5 해시태그

⚡ **캡션 첫 줄 = 후킹 (가장 중요)**: 인스타/페북은 캡션 **첫 1줄(30~40자)만 노출**하고 나머지는 `… 더 보기`로 접는다. 첫 줄이 캡션 전체 클릭률을 결정하므로 **궁금증 갭(진짜 이유 따로 있다 / 사실은 ~가 아니다)·통념 반전·강한 공감**으로 시작해 "더 보기를 누르고 싶게" 만들 것. 답/결론은 첫 줄에서 감추고 본문에서 풀기. 영상 훅·제목과 다른 변주(복붙 금지). 첫 문장 뒤 빈 줄. (상세 규칙·예시는 capcut-deliverables SKILL §0 첫 줄 후킹)

**게이트** (머신 검증, 한글 UTF-8 안전):
```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/verify_step.py 4 --name <name>
```
→ `[step4] PASS: title=N자, ig_caption=M자, hashtags=5, emoji=0, banned=0`

**⚠️ `wc -c`는 한글에서 바이트×3로 오계산**됨. 반드시 `verify_step.py` 사용.

---

### Step 5 — ⭐ FX 자동화 (filter · BGM · SFX · scene_effects · animations)

⛔ **STOP. Call `Read('.claude/skills/capcut-fx/SKILL.md')` NOW. 전체 읽기. 놓침 방지.**

**`extract_fx_candidates.py`가 자동 처리** (LLM 신경 안 써도 됨): (a) **마지막 CTA는 효과음 없이 조용히**(closer-suppression — 시각 zoom은 유지), (b) **BGM 폴백이 영상명 기반 결정론**(재실행 안정; LLM이 톤으로 덮어쓰는 건 그대로 우선), (c) **컷 seam에 micro zoom 자동**(cover-the-cut), (d) **SFX 0.05s 중복 자동 제거**.

권장 flow:

**5-A. fx_plan.json 자동 생성** (⚡ 추측 제거):
```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/extract_fx_candidates.py \
  --draft "$LOCALAPPDATA/CapCut/User Data/Projects/com.lveditor.draft/<name>/draft_content.json" \
  --top-k 12 \
  --out temp/<name>/fx_plan.json
```
→ emphasis 자동 선별 + 5개 필수 키(+intro_video_animation, speed 1.2) 완성된 fx_plan.json 생성. 사용자가 타이밍 미세조정 가능.

**⛔ 자동 생성 후 LLM 자가 검증 (HARD)**:
- ⭐ **BGM 정책**: 로컬 5트랙 중 영상 톤에 맞는 1개를 `path` 모드로 직접 주입. `volume_db = -25`. CapCut 라이브러리 preset 사용 금지. (LLM이 안 고르면 영상명 기반 결정론 폴백.)
  ```jsonc
  "bgm": {
    "path": "BGM/Sunlit Cup.mp3",      // 5개 중 영상 톤에 맞춰 LLM이 선택
    "display_name": "Sunlit Cup",      // 선택, 로그용
    "volume_db": -25
  }
  ```
  **5트랙 톤 매핑 cheat sheet**:
  | 트랙 | 톤 | 적합 콘텐츠 |
  |---|---|---|
  | `BGM/Sunlit Cup.mp3` | 밝음·따뜻·아침 | 라이프스타일·동기부여·긍정 인사이트 |
  | `BGM/After The Pause.mp3` | 잔잔·여운 | 회고·정리·차분한 전달 |
  | `BGM/Midnight Receipt.mp3` | 차분·지적·도시 야경 | 분석·인사이트·진지한 톤 |
  | `BGM/Shibuya Ledger.mp3` | 도시감·트렌디·세련 | 비즈니스·SNS 트렌드·도시 라이프 |
  | `BGM/window.mp3` | 미니멀·잔잔·여백 | 명상·집중·내면 회고 |
  - **LLM 선택 절차**: ① 영상 대본 톤 파악 → ② 5트랙 중 1순위 선택 → ③ 같은 영상 시리즈에서 직전 사용 트랙은 피하기 (다양성). 모호하면 `Sunlit Cup` 또는 `Midnight Receipt`가 무난.
  - 절대 `preset: bgm_good_mood` 등 audios.json preset 쓰지 말 것 — fx_patcher가 자동으로 path 모드 처리함.
- **SFX 시점 분포**: 0-5s에 50%↑ 클러스터링 안 되어야 함. emphasis pop / overlay reveal 시점에 1:1 매칭하도록 재배치 (MEMORY: `feedback_capcut_sfx_match_reveals`).
- **SFX 개수** ≈ emphasis 개수 + B-roll 개수 (씬당 1-2개). 3개만 있고 나머지 본편 무음이면 즉시 재작성.
- **SFX 종류 매핑** (semantic):
  - 첫째/둘째/세 가지/N번째 → `tick`
  - 댓글/구독/DM/CTA → `ui_notify`
  - vs/대비/→ 비교 → `mouse_click`
  - 키워드 pop / 숫자 강조 → `ui_notify`
  - 0초 인트로 → `keyboard_typing` (선택; 타자기 애니메이션은 제거됐으니 사이드 슬라이드와 어울리는 짧은 pop이면 충분)
- ⭐ **`intro_video_animation`**: 첫 클립에만 사이드 슬라이드 인 효과 `{scene_idx:0, preset:"side_slide", duration_us:400000}`. extract가 자동 포함(기본 preset=side_slide). 시작 강조는 **타자기/플래시가 아니라 이 사이드 슬라이드**가 담당. (모든 클립 아님 — 첫 클립만. zoom_in도 선택 가능하나 기본은 side_slide)
- ⛔ **scene_effects에서 `flash_warm` 시작 효과 제거**. 이제 lens_zoom 중심:
  - `graphic_insight` reveal → `math_rush` 1.5s
  - `stat_card`·`dual_icon`·`message_object` reveal → `lens_zoom`
  - 주요 emphasis 각각 → `lens_zoom`
  - (시작 0초 flash_warm 넣지 말 것 — intro_video_animation 사이드 슬라이드가 대체)
- ⭐ **타이틀·강조(emphasis) 자막은 상단(top) 기본** (가운데 금지). 타이틀이 뜨는 시작 구간엔 emphasis 자막을 **동시에 띄우지 말 것** (오프닝 = 타이틀 + 첫 클립 사이드 슬라이드만).
- 재발 금지: SFX를 0-3s에 전부 클러스터링하거나 BGM을 -18dB로 두는 것(voice 마스킹).

**5-B. 완결성 검증**:
```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/capcut_fx_patcher.py \
  --plan temp/<name>/fx_plan.json --verify-completeness
```
→ `[PASS]` 필수. `[FAIL]` 시 누락 키 채우고 재검증.

**5-C. CapCut 완전 종료 확인**:
```bash
tasklist /FI "IMAGENAME eq CapCut.exe"   # 결과 없음이면 OK
```

**5-D. 패치 적용**:
```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/capcut_fx_patcher.py \
  --draft "$LOCALAPPDATA/CapCut/User Data/Projects/com.lveditor.draft/<name>/draft_content.json" \
  --plan  "temp/<name>/fx_plan.json"
```

**게이트** (머신 검증):
```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/verify_step.py 5 --name <name>
```
→ `[step5] PASS: fx_log_keys=5, filter_effects=1, audios=..., video_effects=...` (필수 키 = intro_video_animation·sfx·scene_effects·bgm·filter).

**코드 3중 보호**:
1. `extract_fx_candidates.py` 기본으로 5개 키 + speed 1.2 + intro_video_animation 생성
2. `--verify-completeness` exit 5 로 거부
3. `verify_step.py 5` 로 패치 후 검증

**⭐ 전역 배속 (기본 1.2)**: `extract_fx_candidates.py`가 fx_plan에 `"speed": 1.2`를 자동 포함한다. fx_patcher가 **마지막에** 모든 트랙(영상·자막·B-roll·SFX·BGM)을 `1/speed`로 압축 = CapCut "전체 선택 → 1.2배속". 재인코딩 불필요(드래프트 레벨, 피치 약간 상승). 배속 원치 않으면 fx_plan의 `speed`를 `1.0`으로. 패치 로그에 `[ok] global_speed x1.2 → ...` 확인. (상세 → capcut-fx SKILL.md § speed)

---

### Step 5.5 — ⭐ 영상 첫 제목 최종 확정 (전체 편집본 보고 3안 추천 → 사용자 선택)

⛔ **FX까지 끝난 "완성된 편집본"을 기준으로** 영상 맨 앞 타이틀 카드 문구를 최종 확정한다. Step 3에서 넣은 타이틀은 **임시(working)** — 전체 흐름(자막·B-roll·FX·톤)을 다 본 뒤가 가장 강한 훅을 뽑기 좋다.

**절차**:
1. **완성된 편집본 파악** — 전체 자막(`transcript_wrapped.srt`)·B-roll·emphasis·톤을 종합해 영상의 핵심 메시지/후킹 포인트를 정리. (가능하면 CapCut 재생 또는 scene별 narration 재확인)
2. **진짜 후킹되는 제목 3안 작성** — 서로 결이 다른 후킹 축으로:
   - ① 의문형 ("AI가 내 일을 뺏을까?") ② 반전/대조 ("버티는 사람 vs 만드는 사람") ③ 구체 숫자/약속 ("AI로 역량 3배 키우는 법") ④ 공포→해소 ("불안한 자리에서 만드는 자리로")
   - 각 안: `text`(≤14자 권장, 스크롤 방어) + `accent_words` 1개 + 한 줄 후킹 의도
   - 금지: 클릭베이트(`충격!`/`대박!`), 반말 명령형(`~해라`), 비후킹 모호문구. 첫 씬 메시지와 일치(낚시 금지).
3. **`AskUserQuestion`으로 3안 제시** → 사용자가 1개 선택(또는 직접 입력).
4. **선택안을 맨 앞 타이틀 카드에 반영**:
   - `temp/<name>/_claude_broll_plan.json`의 `title.text`/`accent_words` 수정
   - `temp/<name>/broll_plan.json`의 `title` 도 동일하게 수정 (ingest 산출물)
   - overlay 재패치(clean) → 타이틀 카드 텍스트 갱신:
     ```bash
     PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/overlay_patcher.py \
       --draft "$LOCALAPPDATA/CapCut/User Data/Projects/com.lveditor.draft/<name>/draft_content.json" \
       --plan  "temp/<name>/broll_plan.json" --mode clean
     ```
   - 이어서 fx 재패치(clean) — `title_animation`(typewriter)이 새 타이틀 텍스트에 다시 걸리도록:
     ```bash
     PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/capcut_fx_patcher.py \
       --draft "$LOCALAPPDATA/CapCut/User Data/Projects/com.lveditor.draft/<name>/draft_content.json" \
       --plan  "temp/<name>/fx_plan.json" --mode clean
     ```
   - 재패치 후 `verify_step.py 3` + `5` 재검증 PASS 확인.

⚠️ **title.txt(Step 4 메타 제목)와는 별개**(이건 인스타/검색용). 단 톤은 일관되게. 필요하면 선택한 첫 제목에 맞춰 title.txt도 함께 손볼 수 있음.

> 왜 Step 5 다음인가: 편집 전(Step 3)엔 완성 톤을 모른 채 제목을 찍어야 해서 약한 훅이 나오기 쉬움. **전체 편집본을 보고 3안→선택**하면 1회 왕복으로 첫 3초 스크롤 방어력이 크게 오른다.

---

### Step 6 — 최종 확인 + 내보내기

⛔ **STOP. Call `Read('.claude/skills/capcut-deliverables/SKILL.md')` NOW.** (§ script.txt 생성 부분 중점)

할 일:
1. CapCut 열어 재생 확인 → NG 씬 정리 → 내보내기 → `output/<name>/deliverables/final.mp4`
2. (선택) SRT → plain `script.txt` 변환

**게이트** (머신 검증):
```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/verify_step.py 6 --name <name>
```
→ `[step6] PASS: final.mp4=XX MB`

---

## 🏁 전체 검증 (한 번에)

```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/verify_step.py all --name <name>
```
→ 7개 단계(1/2/2_5/3/4/5/6) 모두 순차 검증 + 종합 리포트.

---

## 🚫 Anti-patterns (즉시 실패)

| ❌ 하지 말 것 | ✅ 올바른 방식 |
|---|---|
| 스킬 파일 Read 없이 "기억대로" 진행 | **각 Step의 `⛔ STOP. Call Read(...) NOW.` 지시대로 읽기** |
| Step 2 끝나고 바로 Step 3로 넘어감 | **Step 2.5 재빌드 필수** (draft mtime > SRT mtime) |
| `wc -c > 400`으로 캡션 길이 검증 | **`verify_step.py 4`** (Python `len()` 기준) |
| fx_plan.json 수동 타이밍 추측 | **`extract_fx_candidates.py`** 로 자동 생성 |
| fx_plan.json에 filter/bgm 누락 | 5개 키(intro_video_animation·sfx·scene_effects·bgm·filter) 모두 포함 + `--verify-completeness` |
| `--fast-cut` 사용 | 기본 (재인코딩) — 자막 싱크 유지 |
| CapCut 열린 채 patcher 실행 | `tasklist` 로 먼저 확인 |
| `--skip-draft --no-auto-broll` 조합 | `--skip-draft`만 |
| 자막 타임스탬프 수정 | 타임스탬프 **불변** — 텍스트만 수정 |
| 추상 질문/내러티브/결론 씬에 B-roll | DECISION_TREE 안티패턴 A1~A7 엄수 |
| `overlay_patcher` 여러 번 실행 (`--mode force`) | 기본 `--mode auto` (멱등) |
| `PYTHONIOENCODING=utf-8` 빠뜨림 (Windows) | **모든 python 호출에 프리픽스** |
| `--allow-incomplete` 일상 사용 | 코드 게이트 우회 금지 |
| `- [ ]` 체크박스 마음속 체크 | `verify_step.py` 로 머신 검증 |

---

## 📂 빠른 파일 레퍼런스

**입출력 위치**:
```
Input:   <video>.mp4
Temp:    temp/<name>/
  ├─ probe.json, silence.log, scenes.json, scene_files.json
  ├─ broll_designer_context.md
  ├─ _claude_broll_plan.json, broll_plan.json
  └─ fx_plan.json                              ⭐ Step 5
Output:  output/<name>/
  ├─ scenes/scene_XX.mp4
  ├─ broll_gemini/*.png
  ├─ subs/transcript*.srt / transcript.json / transcript_wrapped.raw.srt (백업)
  └─ deliverables/
      ├─ title.txt, ig_caption.txt             ⭐ Step 4
      ├─ script.txt                            ⭐ Step 6 (선택)
      └─ final.mp4                             ⭐ Step 6
Draft:   %LocalAppData%\CapCut\User Data\Projects\com.lveditor.draft\<name>\
  ├─ draft_content.json
  ├─ .clean_bak / .overlay_bak / .fx_clean_bak (각 patcher의 백업)
  └─ .omc_patch_state.json / .omc_fx_patch_state.json (멱등성 상태)
Registry: tools/capcut_pipeline/templates/_registry.json  (preset SoT)
```

**스킬 맵**:

| 단계 | 스킬 | 주요 내용 |
|---|---|---|
| Step 1 | [capcut-pipeline](../skills/capcut-pipeline/SKILL.md) | CLI 옵션, 파이프라인 stages, NG 4중 자막 개요 |
| Step 2 | [capcut-subtitle](../skills/capcut-subtitle/SKILL.md) | 자막 교정 불변 조건, 4중 후처리 상세, emphasis 텍스트 |
| Step 2.5 | [capcut-pipeline](../skills/capcut-pipeline/SKILL.md) | `--skip-stt --skip-wrap --skip-cut` 재실행 |
| Step 3 | [capcut-broll](../skills/capcut-broll/SKILL.md) | DECISION_TREE, scene_designer, overlay_patcher, Gemini |
| Step 4 | [capcut-deliverables](../skills/capcut-deliverables/SKILL.md) | title/caption 톤 규칙 |
| Step 5 ⭐ | [capcut-fx](../skills/capcut-fx/SKILL.md) | filter·bgm·sfx·effects·animations 주입 |
| Step 6 | [capcut-deliverables](../skills/capcut-deliverables/SKILL.md) | 최종 확인 + 내보내기 + script.txt 변환 |
| 참조 | [capcut-project](../skills/capcut-project/SKILL.md) | CapCut JSON 스키마 레퍼런스 |

---

## 🔧 환경 요구사항

```env
GOOGLE_AI_API_KEY=...       # Gemini B-roll 이미지 생성 (Step 3)
```

**Windows (bash)**:
- CapCut 드래프트: `$LOCALAPPDATA/CapCut/User Data/Projects/com.lveditor.draft/<name>/`
- 폰트: `~/AppData/Local/Microsoft/Windows/Fonts/ODITTABILITY.TTF`
- **모든 Python 명령에 `PYTHONIOENCODING=utf-8` 프리픽스** (cp949 회피)

---

## ✅ 전체 완료 체크리스트 (verify_step.py all --name <name> 로 자동 검증)

- [ ] Step 1: 드래프트 생성 + 씬 컷 + STT → `verify_step.py 1`
- [ ] Step 2: 자막 교정 (cue 개수·타임스탬프 불변) → `verify_step.py 2`
- [ ] Step 2.5: 드래프트 재빌드 → `verify_step.py 2_5`
- [ ] Step 3: B-roll plan + 이미지 + overlay 패치 + emphasis track 존재 → `verify_step.py 3`
- [ ] Step 4: title.txt(20자) + ig_caption.txt(400-600자) → `verify_step.py 4`
- [ ] **Step 5: fx_plan.json 5키(intro_video_animation·sfx·scene_effects·bgm·filter) + speed 1.2 + `[PASS]` + 패치 로그 `[ok]`** ⭐ → `verify_step.py 5`
- [ ] Step 6: 영상 내보내기 (final.mp4) → `verify_step.py 6`

**모든 게이트 PASS 전 완료 선언 금지.**

---

## 📦 보관 파일

이전 1400줄 통합 문서는 `capcut.md.old_*`에 보관. 2번 이상 성공 사이클 후 삭제 예정.
