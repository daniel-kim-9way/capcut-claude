# /capcut — CapCut 자동 편집 오케스트레이터 (Claude Code 버전)

로컬 영상 → STT → 씬 분할 → 자막 교정 → B-roll → FX → 제목/캡션 → 업로드까지 자동화하는 **Claude Code 슬래시 커맨드**.

7단계를 머신 검증(`verify_step.py`)으로 강제하며, **NG 컷팅과 B-roll 플래닝은 Claude(Opus 4.7)가 transcript을 직접 읽고 판단**합니다 (규칙 매칭 X).

> Codex / 다른 에이전트 사용자는 별도 **`capcut-codex/`** 패키지를 사용하세요.

---

## ⚠️ 사전 요구사항

| 항목 | 버전 / 비고 |
|---|---|
| **OS** | Windows 10/11 (CapCut 드래프트 경로가 `%LOCALAPPDATA%` 기반) |
| **Claude Code** | 최신 버전 — `claude.ai/code` 또는 IDE 확장 |
| **추천 모델** | Claude Opus 4.7 (1M context — Step 1.5 / 3-A LLM 판단 품질) |
| **CapCut Desktop** | 최신 (드래프트가 `com.lveditor.draft` 폴더에 저장되어야 함) |
| **Python** | 3.11+ |
| **FFmpeg / FFprobe** | PATH 에서 호출 가능해야 함 (또는 `CAPCUT_FFMPEG_BIN` 으로 지정) |
| **Playwright Chromium** | `playwright install chromium` 1회 실행 |
| **Pretendard 폰트** | overlay_patcher emphasis 텍스트용 (선택) |

> macOS/Linux 는 검증되지 않았습니다.

---

## 🚀 설치

### 1) 패키지를 Claude Code 프로젝트 디렉터리에 풀기

```
<your-project>/
├── .claude/
│   ├── commands/capcut.md              ← 슬래시 커맨드 정의
│   └── skills/
│       ├── capcut-pipeline/SKILL.md
│       ├── capcut-subtitle/SKILL.md
│       ├── capcut-broll/SKILL.md
│       ├── capcut-fx/SKILL.md
│       ├── capcut-deliverables/SKILL.md
│       └── capcut-project/SKILL.md
├── tools/
│   ├── capcut_pipeline/                ← Python 도구 + templates/ (preset SoT)
│   ├── motion_graphics/                ← 40개 motion 템플릿 + 카탈로그
│   └── reels_pipeline/                 ← broll_generator + funnelmaster_uploader
├── BGM/                                ← 5개 mp3 + effect/1.wav
└── .env                                ← .env.example 복사 후 키 채우기
```

### 2) Python 의존성 설치

```bash
pip install -r requirements.txt
playwright install chromium
```

### 3) `.env` 작성

```bash
cp .env.example .env
# 그 다음 ELEVENLABS_API_KEY, GOOGLE_AI_API_KEY 채우기
```

### 4) FFmpeg 설치 확인

```bash
ffmpeg -version
ffprobe -version
```

PATH 에 없다면 `.env` 의 `CAPCUT_FFMPEG_BIN` 에 bin 디렉터리 절대경로 입력.

### 5) (선택) Motion 카탈로그 재빌드

`sample_catalog.json` + `out/thumbs/` (75 PNG) + `out/smoke_*.mp4` (7 미리보기) 까지 포함. **알파-투명 overlay MOV (총 ~109MB) 는 용량 문제로 제외** — 실제 모션 오버레이 합성 시 다음으로 재생성:

```bash
PYTHONIOENCODING=utf-8 python tools/motion_graphics/render_motion.py --template <template_stem> --params '...'
PYTHONIOENCODING=utf-8 python tools/motion_graphics/build_catalog.py
```

---

## 🎬 사용

Claude Code 세션에서:

```
/capcut <video.mp4> --title "영상 제목"
```

각 단계 완료 후 게이트:

```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/verify_step.py all --name <name>
```

**모든 Python 호출에 `PYTHONIOENCODING=utf-8` 프리픽스 필수** (Windows cp949 회피).

---

## 📂 7단계 파이프라인

| Step | 산출물 | 게이트 |
|---|---|---|
| 1 | 드래프트 + 씬 + STT (ElevenLabs Scribe 기본) | `verify_step.py 1` |
| 1.5 | NG/retake 컷팅 (**Claude 직접 판단**) | `ng_cutter.py` 자동 |
| 2 | 자막 맞춤법 교정 (cue 개수/타임스탬프 불변) | `verify_step.py 2` |
| 2.5 | 드래프트 재빌드 (교정 자막 반영) | `verify_step.py 2_5` |
| 3 | B-roll 6타입 + Motion + 블루 크로마 | `verify_step.py 3` |
| 4 | 제목 (20자) + IG 캡션 (400-600자) | `verify_step.py 4` |
| 5 | filter·BGM·SFX·effects·animations | `verify_step.py 5` |
| 6 | final.mp4 + (선택) FunnelMaster 업로드 | `verify_step.py 6` |

상세는 [.claude/commands/capcut.md](.claude/commands/capcut.md) 참조.

---

## 🧠 Claude 직접 판단 단계

다음 두 단계는 **Claude Opus 4.7 가 transcript 을 직접 읽고 판단**합니다. 정규식·규칙 기반 매칭은 폐기됨:

- **Step 1.5 NG 정리**: word-level transcript → `keep_intervals.json` Write — drop earlier retake, keep later
- **Step 3-A B-roll 플래닝**: 씬별 decision (overlay / text_only / skip) + 6타입 분류 + **Motion 우선 선택 + thumbs PNG 시각 검증 의무**

이 부분은 Claude Code 세션에서 슬래시 커맨드로 진행하면 자동으로 처리됩니다.

---

## 🎞️ Motion Graphics 카탈로그

`tools/motion_graphics/sample_catalog.json` 이 사용 가능한 모션 템플릿의 **Single Source of Truth (SoT)**.

- **40개 HTML+GSAP 템플릿** — stat_card, ui_evidence_kakaotalk, animated_beam, bar_chart, text_hero_aurora, toast_notification, ai_chat_bubble 등
- **75개 thumbnail PNG** — 각 템플릿 early/mid/end 3장 → Claude가 plan 작성 전 Read 직접 시각 확인 의무
- **`user_approved: true/false`** — 사용자가 샘플 MOV 삭제한 템플릿은 자동으로 forbidden 처리 (ingest reject)
- **`params_schema`** — 각 템플릿이 받는 파라미터 (text_hero=phrase, graphic_insight=items, yt_comment=comments 등 **템플릿마다 다름**)

새 템플릿 추가 후 또는 샘플 큐레이션 후:
```bash
PYTHONIOENCODING=utf-8 python tools/motion_graphics/build_catalog.py
```

---

## 🎵 BGM 5트랙

영상 톤에 맞춰 Claude 가 선택. 기본 `volume_db = -25`.

| 트랙 | 톤 | 적합 콘텐츠 |
|---|---|---|
| `BGM/Sunlit Cup.mp3` | 밝음·따뜻 | 라이프스타일·동기부여 |
| `BGM/After The Pause.mp3` | 잔잔·여운 | 회고·정리 |
| `BGM/Midnight Receipt.mp3` | 차분·지적 | 분석·인사이트 |
| `BGM/Shibuya Ledger.mp3` | 도시감·트렌디 | 비즈니스·SNS 트렌드 |
| `BGM/window.mp3` | 미니멀·잔잔 | 명상·집중 |

> **라이선스 주의**: 본인이 보유한 음원으로 교체하세요. 패키지에 포함된 mp3 의 라이선스를 직접 확인 후 사용.

---

## 🛠️ 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| `UnicodeEncodeError: 'cp949'` | `PYTHONIOENCODING=utf-8` 프리픽스 누락 (Windows) |
| `BGM path not found` | BGM/ 폴더 mp3 5개 존재 확인 |
| `verify_step.py 3` FAIL | `emphasis_track_present=False` → overlay_patcher 재실행 |
| `[FAIL]` from `--verify-completeness` | fx_plan.json 6키(filter·bgm·sfx·scene_effects·title_animation·outro_animation) 누락 — 채우고 재검증 |
| CapCut 드래프트 경로 못 찾음 | `.env` 의 `CAPCUT_DRAFT_ROOT` 명시 |
| Motion overlay 가 검은 박스로 보임 | smoke_*.mov 미포함 → `render_motion.py` 로 알파-투명 MOV 재생성 필요 |
| `pycapcut` import 에러 | `pip install pycapcut` |
| Playwright 렌더 실패 | `playwright install chromium` 실행했는지 확인 |
| Motion template forbidden 에러 | sample_catalog 에서 `user_approved: false` 인 template — 다른 variant 선택 |

---

## 📜 라이선스

- **API 키는 본인 발급분 사용** (`.env.example` 의 키 이름만 사용; `.env` 자체는 공유 금지)
- **BGM 음원**은 본인 보유분으로 교체 권장
- **Pretendard 폰트** 등 외부 자산은 각자 라이선스 확인

---

## 🙋 도움이 필요하면

1. [.claude/commands/capcut.md](.claude/commands/capcut.md) 의 "🚫 Anti-patterns" 섹션 먼저 확인
2. 각 Step 의 SKILL.md 파일에 상세 설명 (특히 [.claude/skills/capcut-broll/SKILL.md](.claude/skills/capcut-broll/SKILL.md) 의 Motion 우선 원칙)
3. `verify_step.py` 의 출력 메시지가 가장 정확한 진단
