# CapCut Subtitle Skill

**STT SRT 한국어 교정 + NG 4중 자막 후처리 파이프라인 + 강조(emphasis) 텍스트 스펙.**

이 스킬은 `/capcut` 의 `--skip-draft` 직후 교정 단계와, `build_draft()` 내부의 자막 JSON 패치, 그리고 강조 텍스트 작성 시 로드됩니다. `capcut-pipeline` 이 전체 흐름을, `capcut-fx` 가 시네마틱 효과를 담당합니다 — 이 스킬은 **텍스트/자막 트랙**만 다룹니다.

---

## 🇰🇷 Semantic Wrap (2026-05-13 — 한국어 의미 경계 우선)

⛔ 과거 wrap은 **글자수 18 균등 분할만** 해서 한국어 의미 경계 무시 → `"근데 그게 안 되니까 답답한" / "건데, 좋아하는 걸 찾으려고"` 같이 "답답한 건데"가 부자연스럽게 분리됐음. 2026-05-13 알고리즘 교체.

### `_semantic_break_score()` ([run_pipeline.py:194-237](../../../tools/capcut_pipeline/run_pipeline.py))

각 토큰 끝에서 끊으면 자연스러운지 0-10 점수:
| 점수 | 조건 | 예시 |
|---|---|---|
| 10 | 문장 종결 (`.`, `?`, `!`) | "됩니다." |
| 8 | 쉼표 (`,`) | "건데," |
| 5 | 연결어미 끝 | "되니까", "찾으려면", "지만", "는데" |
| 3 | 명사+조사 끝 | "강점이", "분야가", "대상을" |
| 0 | 어미/조사 매칭 없음 | "답답한", "좋아하는" (다음 단어와 묶임) |

### wrap_segments 동작

- `cur_chars >= max_chars * 0.4`(7자) 이상이면 자연 break 후보 활성
- score ≥ 3 + 충분히 길면 break
- 다음 토큰 추가 시 max_chars 초과 임박 (>= max_chars - 2)이면 강제 break
- 마지막 수단: 0점이라도 max_chars - 2 도달 시 break

### ⭐ look-ahead 보류 (2026-06-01 — 관형형 어미 조기 분리 방지)

⛔ 사용자 컴플레인: "자막 끊기는게 이상하잖아 문장 검사 안했어?" — `"신중하게 하고 싶은"` / `"마음,"` 처럼 관형형 어미 `"싶은"`(5점)이 **뒤의 명사구 `"싶은 마음,"`(쉼표 8점)을 보기 전에** 조기 분리됨. 욕구 나열(`"~하고 싶은 마음,"`) 반복 영상에서 특히 거슬림.

**수정** (`run_pipeline.py` `wrap_segments` `tok_score >= 3` 블록): 조사/연결어미(3~7점)에서 break 후보일 때, **max_chars 내에 더 좋은 break(쉼표/종결 8+)가 도달 가능하면 거기까지 보류**.

```python
elif tok_score >= 3 and cur_chars >= min_chars_to_break:
    should_break = True
    if tok_score < 8:  # 쉼표/종결(8+)이 아니면 look-ahead
        la_chars = cur_chars
        for j in range(i + 1, len(toks)):
            la_chars += toks[j]["span"]
            if la_chars > max_chars: break
            if _semantic_break_score(toks[j]["tok"]) >= 8:
                should_break = False  # 쉼표/종결까지 보류
                break
```

| Before | After |
|---|---|
| `신중하게 하고 싶은` / `마음, 새로움을` | **`신중하게 하고 싶은 마음,`** |
| `갈등을 조율하고 싶은` / `마음, 새로운 사람을` | **`갈등을 조율하고 싶은 마음,`** |

→ 욕구 나열이 의미 단위로 보존 (실측 82 → 72 cue).

### ⚠️ Step 2 교정 시 wrap 의미 단위도 점검 (필수)

자막 교정 단계에서 **텍스트 맞춤법뿐 아니라 줄바꿈(wrap) 끊김도 육안 점검**할 것. 끊김이 부자연스러우면(명사구·조사구 분리) 재wrap 필요. 단 재wrap은 cue 수를 바꾸므로 **불변 조건이 아닌 재처리 체인**을 탄다:

```bash
# 1) 개선 로직으로 재wrap (raw transcript.json → wrapped srt)
python -c "import sys; sys.path.insert(0,'tools/capcut_pipeline'); from pathlib import Path; from run_pipeline import write_wrapped_srt; write_wrapped_srt(Path('output/<name>/subs/transcript.json'), Path('output/<name>/subs/transcript_wrapped.srt'), 18)"
# 2) 맞춤법 교정 재적용 (텍스트 라인만)
# 3) transcript_wrapped.raw.srt 도 같은 구조로 재생성 (verify_step 2 통과)
# 4) 드래프트 재빌드: /capcut <video> --skip-stt --skip-wrap --skip-cut --sub-offset-ms 300
# 5) overlay_patcher --mode clean + capcut_fx_patcher --mode clean 재패치
```

### 효과 비교

| Before (글자수 균등, 46 cues) | After (의미 단위, 68 cues) |
|---|---|
| `근데 그게 안 되니까 답답한` / `건데, 좋아하는 걸 찾으려고` | `근데 그게 안 되니까` / **`답답한 건데,`** / `좋아하는 걸 찾으려고` |
| `살고 싶다면 이 3가지 중` / `하나에서 시작해야 됩니다.` | `살고 싶다면` / **`이 3가지 중 하나에서`** / `시작해야 됩니다.` |

cue 개수는 늘어나지만(작아진 단위) 의미 경계 보존 + 시청 가독성 ↑.

ng_cutter.py도 `write_wrapped_srt` 호출 → 자동 적용.

---

## ⛔ 불변 조건 (CORRECTION 단계, 절대 어길 수 없음)

| 규칙 | 이유 |
|---|---|
| **타임스탬프 절대 건드리지 않는다** | 씬 컷 매칭·자막 그룹 바인딩이 cue 절대시간에 의존 |
| **cue 번호·개수 유지** | 씬-자막 group bind 는 cue 순서대로 씬에 매핑됨 |
| **각 cue 텍스트는 해당 오디오에 충실** | 다른 테이크 문장으로 교체하면 립싱크 어긋남 |
| **NG 흔적(`...`, 반복 테이크)은 그대로 둔다** | 사용자가 CapCut 에서 NG 씬을 지울 때 group_id 로 자막도 함께 제거됨 |

위 4개 중 하나라도 위반하면 **전체 파이프라인 붕괴**. 검증 실패 시 반드시 `transcript_wrapped.raw.srt` 백업에서 복구하고 재시도.

---

## 📝 교정 워크플로우 (Claude Code 에이전트)

### 언제 실행되나
`/capcut --skip-draft` 로 파이프라인이 멈춘 직후 — STT + wrap 완료, 드래프트 아직 생성 전.

### 절차 (4 steps)

1. **백업 먼저**
   ```bash
   cp temp/<name>/transcript_wrapped.srt temp/<name>/transcript_wrapped.raw.srt
   ```

2. **Read 툴로 SRT 전체 읽기** — 별도 API 호출 금지. Claude Code 세션 내에서 직접 교정.

3. **Write 툴로 교정본을 `transcript_wrapped.srt` 에 기록** — 타임스탬프와 cue 번호 라인은 byte-for-byte 동일하게 유지, **텍스트 라인만 수정**.

4. **불변 조건 검증 (Python)**
   ```python
   import re
   TS = re.compile(r'^\d{2}:\d{2}:\d{2},\d{3} --> \d{2}:\d{2}:\d{2},\d{3}$')
   raw  = open('transcript_wrapped.raw.srt', encoding='utf-8').read().splitlines()
   fixed = open('transcript_wrapped.srt',     encoding='utf-8').read().splitlines()
   raw_ts   = [l for l in raw   if TS.match(l)]
   fixed_ts = [l for l in fixed if TS.match(l)]
   assert raw_ts == fixed_ts, 'timestamp changed — restore backup'
   raw_idx   = [l for l in raw   if l.strip().isdigit()]
   fixed_idx = [l for l in fixed if l.strip().isdigit()]
   assert raw_idx == fixed_idx, 'cue index changed — restore backup'
   print(f'[ok] {len(fixed_ts)} cues preserved')
   ```
   **검증 실패 → 백업 복구 후 재교정.** 성공하면 `--skip-stt --skip-wrap --skip-cut` 로 드래프트만 재생성.

### 자주 나오는 STT 오류 패턴

| 유형 | 예시 (잘못 → 올바름) |
|---|---|
| **오인식** (동음이의) | `손등을 뗀` → `손도 못 댄` · `뇌과학에서` → `뇌가` · `미읽은` → `안 읽은` |
| **띄어쓰기** | `50 %` → `50%` · `내일은` → `내 일은` (문맥상) |
| **조사 오용** | `오후에 3시에도` → `오후 3시에도` |
| **비표준 표현** | 구어체 축약 → 표준어 복원 (단, 말투가 자연스러우면 유지) |

**판단 기준**: 오디오가 어떻게 들렸을지 추론해서 원 발화에 **가장 가까운 표준 표기**로 복원. 말투 자체는 건드리지 않음.

---

## 🧩 NG 대응 — 4중 자막 후처리 파이프라인 (⭐ 핵심)

`build_draft()` 가 드래프트 JSON 에 **아래 순서로 고정** 적용. 순서 바꾸면 바인딩 깨짐.

> **⚠️ 순서 절대 바꾸지 말 것**
> **scene-clip → group bind → offset → duration cap**
> scene-clip 이 cue.start 를 재정렬한 뒤에야 group bind 가 올바른 씬에 바인딩됨. scene-clip 이전에 offset 을 더하면 씬 겹침 판정이 틀어짐.

### 1️⃣ scene-clip — 크로스씬 cue 재정렬 (`_patch_subtitle_scene_clip`)

**문제**: Whisper 가 같은 문장의 여러 NG 테이크를 하나의 cue 로 묶으며 start 를 첫 테이크 시점으로 당김 → 자막이 실제 발화보다 훨씬 앞서고 여러 씬에 걸침.

**해결**: cue 가 2개 이상의 씬과 겹치면 **마지막 겹치는 씬의 시작점으로 `cue.start` 재정렬**. silencedetect 가 찾은 무음(=NG 쉬는 구간) 경계이므로 성공한 마지막 테이크는 반드시 마지막 씬 안에 있음.

로그: `[scene-clip] re-anchored 19 cross-scene subtitles to last overlapping scene`
실측 (142초 영상): 64 cue 중 **19개 (30%)** 가 크로스씬. NG 많을수록 증가.

### 2️⃣ group bind — 씬-자막 `group_id` 공유 (`_patch_scene_subtitle_groups`)

**문제**: CapCut 기본 동작상 자막 트랙과 비디오 트랙은 독립. NG 씬 삭제 시 자막만 남아 정렬 붕괴.

**해결**: 각 씬 video_segment 에 UUID 를 `group_id` 로 주입, 겹치는 text_segment 에 **같은 UUID 공유**. CapCut 이 "링크된 클립"으로 인식 → 씬 삭제 시 자막 동반 제거 + 리플 편집.

로그: `[group] bound N subtitles to M scenes via group_id`

### 3️⃣ offset — Whisper phoneme-onset bias 보정 (`_patch_subtitle_offset`)

**문제**: Whisper `word_timestamps=True` 는 단어 시작을 **phoneme onset** (숨소리·입벌림 포함) 기준으로 표시 → 실제 들리는 시점보다 **~150–600ms 이름**.

**해결**: 모든 text_segment `target_timerange.start` 에 `+sub_offset_ms` 가산 (duration 유지).

로그: `[offset] shifted 64 subtitles by +600ms`
**실측 적정값**: `sub_offset_ms=600` (영상에 따라 250–600ms 사이 조정).

### 4️⃣ duration cap — 문자수 기반 표시 시간 제한 (`_patch_subtitle_max_duration`)

**문제**: Whisper 가 단어 끝을 따라오는 무음/NG 까지 확장 → 짧은 구절이 5–7초 표시.

**해결**: cue 길이를 `max(1000ms, min(sub_max_duration_ms, chars × 250ms + 500ms))` 로 제한.

로그: `[max-dur] clipped N subtitles (per-char=250ms, min=1000ms, max=5000ms)`
**주의**: scene-clip 이 대부분 duration 문제를 먼저 해결하므로 여기서 clip 되는 수는 보통 **0–3개** 가 정상. 10개 이상이면 scene-clip 이 제대로 안 돈 것.

---

## ✨ Emphasis 텍스트 스펙 (강조 자막)

CapCut **텍스트 트랙**으로 주입 (PIL 이미지 아님 → 사용자가 CapCut 에서 직접 편집 가능).

### 스타일 원칙

| 항목 | 권장값 | 비고 |
|---|---|---|
| **폰트 (font_name)** | **`Pretendard Black`** | ⛔ 기본값 (2026-06-04). 과거 `아네모네`는 **userFontData 미등록 → path 빈값 → CapCut System 폴백** 사고. 반드시 CapCut에 **설치·등록된** 폰트명만 쓸 것 |
| 기본 색 | `#FFFFFF` | 흰색 — 숫자·일반 텍스트 기본 |
| 강조 색 (accent) | `#FFD54F` | 연한 황금. 과한 단색(빨강/노랑 원색) 피할 것 |
| 폰트 크기 | `20` | 자막 기본 15 대비 약 1.3배 |
| 외곽선 | `0.04` | 자막과 동일하게 얇게 |
| 단어 간격 | 공백 **1개** | 2개 쓰면 CapCut 이 그대로 표시 (과한 간격) |

> ⛔ **폰트 적용 메커니즘 (System 폴백 방지)**: emphasis/title 텍스트는 `font_name`만 주면 `overlay_patcher.resolve_font_path_by_name()`이 **CapCut `userFontData` 레지스트리**(`%LOCALAPPDATA%/CapCut/User Data/Config/userFontData`)에서 경로를 역조회한다. **이름이 레지스트리 키와 정확히 일치해야** path가 채워지고, path가 비면 CapCut이 **System**으로 폴백한다. 레지스트리 키는 혼합 인코딩(`%UXXXX` 한글 + `%XX` URL, 예 `Pretendard%20Black`=공백) — `_decode_capcut_key`가 둘 다 디코드(2026-06-04 fix, 과거 `%20` 미처리로 "Pretendard Black"을 못 찾아 폴백). 새 폰트 쓰려면 먼저 CapCut에 설치(즐겨찾기) → userFontData에 등록 확인 후 그 표시 이름을 `font_name`으로.

### 위치 (position) 선택

| position | y | 용도 |
|---|---|---|
| `top` | +0.7 | 이미지 없는 씬 — 화면 상단 |
| `center` | +0.2 | 중앙 (이미지 있으면 겹침 주의) |
| `lower` | -0.1 | **split 이미지 있는 씬 — 사람 얼굴 위, 자막 바로 위** |
| `bottom` | -0.18 | 자막과 겹침 (잘 안 씀) |

### 부분 색상 (accent_words)

```json
{ "text": "전환율 15% 개선", "accent_words": ["15%"] }
```

→ `content.styles[]` 배열이 3개 생성되어 **`15%` 만 황금색**, 나머지는 흰색. 핵심 숫자·키워드 1개만 accent 처리 (디자인 토큰 규칙: 숫자는 흰색 기본, 형광펜 하이라이트식 accent 는 최소).

**우선순위** (상한 5–8개):
- 🔴 핵심 숫자·결과 ("500만 건", "2배")
- 🟡 반전·대조 ("왜?", "충격적인")
- 🟢 리스트 시작·CTA ("3가지", "댓글에 X")
- ⚪ 스킵: 필러·반복

z-order 는 `capcut-fx` 참조 — emphasis_text 는 `[6]` (broll 위, SFX 아래).

---

## 🔍 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| 검증에서 `timestamp changed` | Write 로 저장할 때 타임스탬프 라인 건드림 → raw 백업 복구 후 재교정 |
| 검증에서 `cue index changed` | cue 추가/삭제함 → 절대 금지, raw 복구 |
| NG 씬 삭제했는데 자막만 남음 | group bind 누락 → 로그에서 `[group] bound ...` 확인, 0 이면 scene-clip 이 먼저 돌았는지 체크 |
| 자막이 발화보다 빠르게 뜸 | `sub_offset_ms` 가 0 또는 너무 작음 → 600ms 로 상향 |
| 짧은 구절이 5초 이상 떠 있음 | duration cap 미적용 또는 scene-clip 누락. `_patch_subtitle_max_duration` 로그 확인 |
| 한 cue 가 여러 씬에 동시 걸침 | scene-clip 실패. silencedetect 씬 경계가 너무 촘촘한지 확인, `sub_offset_ms` 가 씬 duration 보다 크면 안 됨 |
| 교정했는데 드래프트에 반영 안 됨 | `--skip-stt --skip-wrap --skip-cut` 없이 재실행하면 STT 가 raw 를 덮어씀. 플래그 확인 |
| emphasis `15%` 가 황금색 안 됨 | `accent_words` 배열의 문자열이 `text` 내 부분문자열과 **정확히 일치** 해야 함 (공백·기호 포함) |
| emphasis 가 얼굴 가림 | split 씬이면 `position: "lower"` (y=-0.1), 이미지 없는 씬이면 `top` (y=+0.7) |
| **핵심 자막(emphasis/title) 폰트가 CapCut에서 System으로 뜸** | `font_name`이 `userFontData`에 미등록(예: `아네모네`)이라 path 빈값 → System 폴백. ① `font_name`을 **설치·등록된** 이름으로(기본 `Pretendard Black`), ② 레지스트리 키에 공백/특수문자(`%20` 등) 있으면 `_decode_capcut_key`가 디코드하는지 확인. 검증: `resolve_font_path_by_name("Pretendard Black")`이 .otf 경로 반환해야 함. draft text material의 `font_path`가 비어있으면 폴백 중. 폰트 변경 후 `overlay_patcher --mode clean` 재패치 |

---

## 🗂️ 관련 파일

- [tools/capcut_pipeline/run_pipeline.py](../../../tools/capcut_pipeline/run_pipeline.py)
  - `_patch_subtitle_scene_clip` (L428)
  - `_patch_subtitle_max_duration` (L477)
  - `_patch_subtitle_offset` (L523)
  - `_patch_scene_subtitle_groups` (L549)
  - `_patch_fonts` (L597) / `_patch_strokes` (L634)
- [tools/capcut_pipeline/run_pipeline.py](../../../tools/capcut_pipeline/run_pipeline.py) — 드래프트 빌더 본체 (`build_draft()` + 4패치 호출 + STT + SRT wrap 통합)
- [tools/capcut_pipeline/run_stt_elevenlabs.py](../../../tools/capcut_pipeline/run_stt_elevenlabs.py) — Scribe STT (기본 엔진)
- [tools/capcut_pipeline/overlay_patcher.py](../../../tools/capcut_pipeline/overlay_patcher.py) — emphasis text 트랙 주입

**Cross-refs**:
- 전체 파이프라인 흐름 → `capcut-pipeline`
- 시네마틱 FX (title/outro 애니메이션, SFX, filter) → `capcut-fx`

---

## ✅ 최종 체크리스트

- [ ] 교정 전 `transcript_wrapped.raw.srt` 백업 생성
- [ ] Write 후 **타임스탬프 라인 byte-identical** 검증 통과
- [ ] Write 후 **cue 번호·개수 동일** 검증 통과
- [ ] NG 흔적(`...`, 반복 테이크)은 교정하지 않고 그대로 둠
- [ ] 드래프트 재생성 로그에 4개 패치 모두 확인: `[scene-clip]` → `[group]` → `[offset]` → `[max-dur]`
- [ ] `[scene-clip]` 재정렬 수 > 0 (NG 있으면), `[max-dur]` clip 수 ≤ 3
- [ ] emphasis 총 5–8개 이하, accent_words 는 text 부분문자열과 정확히 일치
- [ ] split 씬 emphasis 는 `position: "lower"` 확인
- [ ] CapCut 열어 자막 타이밍·위치 스팟 체크 후 **"저장 안 함"** 으로 닫기
