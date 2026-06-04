# CapCut Pipeline Skill

**로컬 영상 → CapCut 드래프트 자동화 파이프라인**: probe → 씬 분할 → STT → 컷 → 드래프트 생성까지 `/capcut` 커맨드의 raw 흐름을 다룹니다.

`/capcut video.mp4` 실행 시 이 스킬을 먼저 로드하고, 후처리/B-roll/FX/배포는 sibling 스킬을 참조하세요.

---

## ⚡ Quick CLI Cheat Sheet

```bash
# ✅ 권장 NG 대응 3단계 플로우 (§ 1.4)
# Step 1 — STT + 재인코딩 컷 (드래프트 보류). 기본 엔진: ElevenLabs Scribe v1
PYTHONIOENCODING=utf-8 /capcut D:/videos/talk.mp4 --skip-draft

# Step 2 — capcut-subtitle 스킬로 transcript_wrapped.srt 교정 (타임스탬프 불변)

# Step 3 — 교정본으로 드래프트 생성 (scene-clip + group bind + offset + dur cap)
PYTHONIOENCODING=utf-8 /capcut D:/videos/talk.mp4 \
  --skip-stt --skip-wrap --skip-cut \
  --sub-offset-ms 600 --sub-max-duration-ms 5000
```

**Top 옵션**:
| 옵션 | 효과 |
|---|---|
| `--stt-engine elevenlabs` (기본) | ElevenLabs Scribe v1. 한국어 WER 5-8%, CPU 환경에서 Whisper보다 10배+ 빠름. `ELEVENLABS_API_KEY` 필요 |
| `--stt-engine whisper --model large-v3` | 오프라인·네트워크 장애 폴백 (CPU에서 매우 느림) |
| `--skip-draft` | STT/컷만 수행, 자막 교정 대기 |
| `--skip-stt --skip-wrap --skip-cut` | 재빌드 전용 (수 초) |
| `--sub-offset-ms 600` | phoneme-onset 편향 보정. Whisper 실측값 600ms, Scribe는 250-400ms 재튜닝 권장 |
| `--auto-broll` (기본 on) | scene_designer context 자동 생성 — 임의로 off 금지 |

---

## 🔧 전체 CLI 옵션 (§ 1)

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `--name NAME` | 파일명 | CapCut 드래프트 이름 |
| `--stt-engine ENGINE` | `elevenlabs` | `elevenlabs` (Scribe v1, 기본) / `whisper` (faster-whisper 로컬) |
| `--model SIZE` | `small` | `--stt-engine=whisper`일 때만 사용: `tiny`/`base`/`small`/`medium`/`large`/`large-v3` |
| `--max-chars N` | `18` | 자막 단어 단위 균등 분할 최대 글자수 |
| `--font-size N` | `14` | 자막 글꼴 크기 (CapCut UI 단위) |
| `--font-path PATH` | `ODITTABILITY.TTF` | 자막 폰트 TTF/OTF 절대경로 |
| `--font-title NAME` | `ODITTABILITY` | 폰트 디스플레이 이름 |
| `--stroke N` | `20` | 자막 외곽선 두께 |
| `--sub-y Y` | `-0.234` | 자막 Y 위치 (정규화) |
| `--min-silence SEC` | `0.6` | 씬 경계 최소 무음 길이 |
| `--noise DB` | `-30` | 무음 임계치 dB |
| `--min-scene SEC` | `1.5` | 병합 전 최소 씬 길이 |
| `--fps N` | `30` | CapCut 타임라인 fps |
| `--fast-cut` | off | 스트림 복사 (⛔ 자막 싱크 깨짐, 사용 금지) |
| `--skip-stt` | off | STT 생략 (기존 transcript 재사용) |
| `--skip-cut` | off | 씬 컷 생략 (기존 scene 파일 재사용) |
| `--skip-wrap` | off | `transcript_wrapped.srt` 재생성 생략 (⚡ 수동 교정본 보존) |
| `--skip-draft` | off | 드래프트 생성 생략 |
| `--sub-offset-ms N` | 엔진별 자동 | 자막 N ms 뒤로 밀기. **elevenlabs=300, whisper=600** (실측: Scribe word_start가 Whisper보다 중앙값 +330ms 늦음, 320단어 기준) |
| `--sub-max-duration-ms N` | **`5000`** | 자막 최대 표시 시간 cap |
| `--auto-broll` / `--no-auto-broll` | **기본 on** | ⛔ `--skip-draft` + `--no-auto-broll` 조합 금지 |
| `--title "..."` | "" | 영상 제목 (auto-broll context에 포함) |

---

## 🎬 파이프라인 단계

실행 엔트리: `python tools/capcut_pipeline/run_pipeline.py "<video>" [options]`

| # | 단계 | 도구 | 결과 |
|---|---|---|---|
| 1 | probe | ffprobe | `temp/<name>/probe.json` |
| 2 | 씬 분할 | ffmpeg `silencedetect` | `temp/<name>/scenes.json`, `silence.log` |
| 3 | STT | faster-whisper | `output/<name>/subs/transcript.srt` + `.json` |
| 3b | wrap | 파이프라인 | `transcript_wrapped.srt` (균등 분할) |
| 3c | **교정** | Claude Code 에이전트 (§ 2) | `transcript_wrapped.srt` (맞춤법 수정) |
| 4 | 컷 | ffmpeg 재인코딩 | `output/<name>/scenes/scene_XX.mp4` |
| 5 | 드래프트 | pycapcut + NG 4중 후처리 | `%LocalAppData%\CapCut\...\<name>\draft_content.json` |
| 5a | **scene-clip** | `_patch_subtitle_scene_clip` | 여러 씬 걸친 cue를 마지막 씬 시작점으로 재정렬 |
| 5b | **group bind** | `_patch_scene_subtitle_groups` | 씬-자막 `group_id` 공유 (NG 씬 삭제 시 동반 제거) |
| 5c | **offset shift** | `_patch_subtitle_offset` | `+sub_offset_ms` 뒤로 밀기 |
| 5d | **duration cap** | `_patch_subtitle_max_duration` | 문자수 기반 budget 제한 |

⛔ **5a-5d 순서 고정**: scene-clip → group → offset → max-dur. 순서 섞지 말 것 (MEMORY: feedback_capcut_scene_subtitle_binding).

---

## ✅ 권장 기본 설정

- **`--stt-engine elevenlabs` (기본)** — Scribe v1. 한국어 WER 5-8%, CPU 환경에서 Whisper `large-v3` 대비 10배 이상 빠름. `ELEVENLABS_API_KEY` 필요. 시간당 $0.22.
- **`--stt-engine whisper --model large-v3`** — 오프라인 폴백. CPU에서 실시간의 0.4-0.7x로 매우 느림.
- **`--fast-cut` 사용 금지** — 키프레임 스냅으로 씬이 0.2-0.6s 겹치고 자막 싱크 어긋남. 기본 재인코딩 사용.
- **`--sub-offset-ms` 엔진별 자동** — elevenlabs=300, whisper=600 (실측: Scribe word_start가 Whisper보다 중앙값 +330ms 늦음, 320단어 비교 기준). 자막이 너무 늦으면 감소.
- **`--sub-max-duration-ms 5000` (기본값)** — scene-clip이 NG 대부분 해결. 추가 cap 필요 시 감소.
- **`--auto-broll` 기본 on 유지** — `--no-auto-broll` 임의로 붙이지 말 것 (MEMORY: feedback_capcut_auto_broll_default).

---

## 🧹 Step 1.5 — NG/retake/묵음 자동 정리 (word-level, LLM-driven)

silencedetect 씬 분할은 폐기됨. **Scribe word-level transcript을 LLM이 직접 보고 retake/NG/묵음을 식별 → keep_intervals 결정 → ng_cutter가 자동 cut + transcript shift**.

### 핵심 규칙

`drop_earlier_retake_keep_later` — 같은 발화 반복 시 **앞 take(NG)** drop, 뒤 take(polished) keep.

### 4단계 플로우

```bash
# 1.5-A. Scribe word-level utterance 컨텍스트 + retake hint 생성
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/ng_detector.py analyze --name <name>
# → temp/<name>/ng_context.md (utterance 표 + ⚠/✓ retake hint + 출력 스키마)

# 1.5-B. Claude(Opus 4.7)가 ng_context.md Read → keep_intervals.json Write
#   - 의심스러우면 keep (False Positive 금지)
#   - 연속 keep utterance는 한 interval로 묶음
#   - start/end는 raw Scribe word_start/word_end (어미 연장 수동 추가 금지)

# 1.5-C. 검증 + 사람이 읽을 review.md 생성
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/ng_detector.py report --name <name>
# → temp/<name>/ng_plan_review.md (keep table + drop gaps + 통계)

# 1.5-D. 실제 cut 적용 + transcript shift
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/ng_cutter.py \
  --source <원본.mp4> --name <name>
# → output/<name>/scenes/scene_XX.mp4 + subs/transcript.{json,srt}
```

### Drop 카테고리

| 카테고리 | 기준 |
|---|---|
| `retake` | 앞 utterance와 leading 3+ word match (ng_detector가 ⚠ 표시) |
| `filler` | 단독 "어/음/그/아" 1-2 단어 |
| `frustration` | "아 미치겠다", "왜 이렇게", "하." 등 좌절 발화 |
| `noise` | `(괄호)` audio_event ("(문 여는 소리)") |
| `incomplete` | 미완성 발화로 끝남 ("...같은", "그런데...") |

### ng_cutter 자동 처리 (LLM 신경 안 써도 됨)

| 처리 | 기본값 | 이유 |
|---|---|---|
| 어미 연장 | **+400ms** (next NG와 50ms safety cap) | Scribe word_end가 한국어 어미 vowel decay 직전 끝남 ("~다/~요" 잘림) |
| Audio fade | 50ms 삼각형 fade-in/out per clip | boundary click/pop 제거 |
| `-ss` 위치 | input seek (`-ss before -i`) | output seek + afade 조합은 ffmpeg aac 비트레이트 24kbps 붕괴 버그 |
| Transcript shift | actual cut duration 기반, per-interval segment split | cumulative drift 방지 + cross-scene cue 분리 |

### 철칙

- **LLM이 판단** — 규칙 기반 매칭 금지 (MEMORY: `feedback_plan_by_llm_not_rules`)
- **앞 retake drop** — 뒤 take가 polished, 앞이 NG (MEMORY: `feedback_capcut_ng_drop_earlier`)
- **연속 drop 흐름 검토** — review.md의 drop 구간 표 확인
- **의심 시 keep** — 좋은 take를 잃지 않는 것이 우선

### 실측 예시 (PROMPTER_20260417_161003, 262.4s / 344 단어)

- 62 utterances → 14 keep intervals → **96.5s (-63.2%)**
- Retake 기각: thesis V1, 부메랑 V1, 충격적 V1, 답장 V1/V2/V3, 받는사람 V1, 두번째 V1/V2/V3, 응답률 V1, 세번째 V1/V2/V3
- 자동 어미 연장 적용: 14/14 intervals 평균 +146ms (target 400ms, safety 50ms cap)

### 폴백

기존 silencedetect 출력은 `.silence_bak` 접미사로 자동 백업. word-level 결과 만족 못 하면 .silence_bak 파일 복원 가능.

---

## 🚨 NG 4중 자막 후처리 (개요)

Whisper가 내놓는 cue는 한국어에서 phoneme-onset early + silence-padded end 편향이 있고, 씬 컷 경계를 넘거나 한 cue가 여러 씬에 걸치는 NG가 빈발합니다. 파이프라인은 드래프트 생성 직후 **scene-clip → group bind → offset shift → duration cap** 네 단계를 고정 순서로 적용해 이를 해결합니다. scene-clip은 여러 씬에 걸친 cue를 마지막 씬 시작점으로 재정렬하고, group bind는 씬-자막 `group_id`를 공유해 NG 씬을 드래그로 지워도 자막이 동반 삭제되게 하며, offset은 `+600ms` 뒤로 밀고, duration cap은 문자수 기반 budget으로 표시 시간을 제한합니다. **자세한 파라미터 튜닝·STT 교정 워크플로우는 → `capcut-subtitle` 스킬 참조.**

---

## 🗂️ 관련 Python 파일

- [tools/capcut_pipeline/run_pipeline.py](../../../tools/capcut_pipeline/run_pipeline.py) — 기본 파이프라인 엔트리
- [tools/capcut_pipeline/run_stt_elevenlabs.py](../../../tools/capcut_pipeline/run_stt_elevenlabs.py) — ElevenLabs Scribe STT (기본 엔진)
- [tools/capcut_pipeline/ng_detector.py](../../../tools/capcut_pipeline/ng_detector.py) — Step 1.5 NG/묵음 dry-run (analyze + report)
- [tools/capcut_pipeline/overlay_patcher.py](../../../tools/capcut_pipeline/overlay_patcher.py) — B-roll + emphasis 패치 (→ `capcut-broll`)
- [tools/capcut_pipeline/capcut_fx_patcher.py](../../../tools/capcut_pipeline/capcut_fx_patcher.py) — FX 패처 (→ `capcut-fx`)
- [tools/capcut_pipeline/extract_templates.py](../../../tools/capcut_pipeline/extract_templates.py) — 편집본 → 프리셋 추출
- [tools/capcut_pipeline/gemini_broll_sample.py](../../../tools/capcut_pipeline/gemini_broll_sample.py) — Gemini B-roll 생성 샘플

**산출물 경로**:
```
output/<name>/
├── scenes/scene_XX.mp4
├── subs/{transcript.srt,transcript.json,transcript_wrapped.srt}
└── deliverables/                    → capcut-deliverables 스킬

temp/<name>/
├── probe.json / silence.log / scenes.json / scene_files.json
├── _claude_broll_plan.json          → capcut-broll (⚠️ LLM-authored, NOT rule-based)
├── broll_plan.json
└── fx_plan.json                     → capcut-fx

%LocalAppData%\CapCut\User Data\Projects\com.lveditor.draft\<name>\
├── draft_content.json               (패치 대상)
├── draft_content.json.bak
├── draft_content.json.overlay_bak
└── draft_meta_info.json
```

**환경 설정** (§ 7):
```env
GOOGLE_AI_API_KEY=...   # Gemini B-roll 생성 시 필요
```
- 폰트: `C:\Users\<user>\AppData\Local\Microsoft\Windows\Fonts\ODITTABILITY.TTF`
- 드래프트 루트: `%LocalAppData%\CapCut\User Data\Projects\com.lveditor.draft\<name>\`

---

## 🔗 Sibling Skills (사용 시점)

| 스킬 | 사용 시점 |
|---|---|
| [`capcut-subtitle`](../capcut-subtitle/SKILL.md) | STT 교정, NG 4중 후처리 상세, `--sub-offset-ms` 튜닝 |
| [`capcut-broll`](../capcut-broll/SKILL.md) | `--auto-broll` context, Gemini B-roll 생성, overlay patcher |
| [`capcut-fx`](../capcut-fx/SKILL.md) | fx_plan.json 작성, title animation / SFX / scene effect / BGM / filter |
| [`capcut-deliverables`](../capcut-deliverables/SKILL.md) | `output/<name>/deliverables/` title/caption/script/final.mp4 |
| [`capcut-project`](../capcut-project/SKILL.md) | CapCut JSON 스키마 레퍼런스 |

---

## ✅ 체크리스트 (실행 전 확인)

- [ ] 입력 영상 경로가 존재하고 읽기 가능한지
- [ ] CapCut이 **완전히 종료** 상태인지 (`tasklist /FI "IMAGENAME eq CapCut.exe"`)
- [ ] `PYTHONIOENCODING=utf-8` 프리픽스 사용 (⛔ Windows 콘솔 `cp949` 에러 방지)
- [ ] `--model large-v3` 또는 `--skip-stt`로 기존 transcript 재사용 결정
- [ ] `--fast-cut` 사용 안 함 (자막 싱크 보장)
- [ ] `--auto-broll` 기본 on 유지 (명시적 off 필요한 경우 아님)
- [ ] NG 대응이 필요하면 3단계 플로우 (`--skip-draft` → 교정 → `--skip-stt --skip-wrap --skip-cut`)
- [ ] 드래프트 생성 후 CapCut에서 열고 재생 확인 → 저장은 **"저장 안 함"**
