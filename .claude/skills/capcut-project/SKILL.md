# CapCut Project Skill

CapCut 프로젝트를 프로그래밍으로 생성하는 방법.

---

## CapCut 프로젝트 구조

### 드래프트 폴더 위치

```
Windows: %LocalAppData%\CapCut\User Data\Projects\com.lveditor.draft\{draft_id}\
Mac:     ~/Movies/CapCut/User Data/Projects/com.lveditor.draft/{draft_id}/
```

### 필수 파일

| 파일 | 역할 |
|------|------|
| `draft_content.json` | 타임라인 (트랙, 세그먼트, 머티리얼) |
| `draft_meta_info.json` | 프로젝트 메타데이터 (이름, 생성일, 해상도) |

### 선택 파일

| 파일 | 역할 |
|------|------|
| `draft_cover.jpg` | 프로젝트 썸네일 |
| `Resources/` | 미디어 파일 복사본 |

---

## draft_content.json 핵심 스키마

### 최상위 구조

```json
{
  "id": "uuid",
  "name": "project-name",
  "fps": 30,
  "duration": 180000000,
  "canvas_config": {
    "width": 1920,
    "height": 1080,
    "ratio": "16:9"
  },
  "materials": {
    "videos": [],
    "audios": [],
    "texts": []
  },
  "tracks": []
}
```

### 시간 단위

**모든 시간은 마이크로초 (microseconds)**

```
1초    = 1,000,000
0.5초  = 500,000
7초    = 7,000,000
10분   = 600,000,000
```

---

## 트랙 타입

### Video Track (이미지/영상)

```json
{
  "type": "video",
  "name": "main_video",
  "render_index": 1,
  "segments": [
    {
      "id": "uuid",
      "material_id": "material_uuid",
      "target_timerange": {
        "start": 0,
        "duration": 7000000
      },
      "source_timerange": {
        "start": 0,
        "duration": 7000000
      },
      "clip": {
        "alpha": 1.0,
        "rotation": 0.0,
        "scale": { "x": 1.0, "y": 1.0 },
        "transform": { "x": 0.0, "y": 0.0 }
      }
    }
  ]
}
```

### Audio Track

```json
{
  "type": "audio",
  "segments": [
    {
      "material_id": "audio_uuid",
      "target_timerange": {
        "start": 0,
        "duration": 180000000
      },
      "volume": 1.0
    }
  ]
}
```

### Text Track (자막)

```json
{
  "type": "text",
  "segments": [
    {
      "material_id": "text_uuid",
      "target_timerange": {
        "start": 0,
        "duration": 3000000
      },
      "clip_settings": {
        "transform_y": -0.8
      }
    }
  ]
}
```

---

## 키프레임 애니메이션

### 줌인

```json
{
  "keyframes": [
    { "time": 0, "property": "scale", "value": 1.0 },
    { "time": 7000000, "property": "scale", "value": 1.2 }
  ]
}
```

### 팬 (좌→우)

```json
{
  "keyframes": [
    { "time": 0, "property": "position_x", "value": -0.05 },
    { "time": 7000000, "property": "position_x", "value": 0.05 }
  ]
}
```

### 켄 번즈 (줌 + 팬)

```json
{
  "keyframes": [
    { "time": 0, "property": "scale", "value": 1.0 },
    { "time": 7000000, "property": "scale", "value": 1.3 },
    { "time": 0, "property": "position_x", "value": 0.0 },
    { "time": 7000000, "property": "position_x", "value": 0.1 }
  ]
}
```

---

## 전환 효과

```json
{
  "id": "transition_uuid",
  "type": "fade",
  "duration": 500000
}
```

| 타입 | 설명 |
|------|------|
| `fade` | 페이드 인/아웃 |
| `slide_left` | 왼쪽으로 슬라이드 |
| `slide_right` | 오른쪽으로 슬라이드 |
| `blur` | 블러 전환 |
| `none` | 전환 없음 |

---

## 자막 스타일링

```json
{
  "id": "text_material_uuid",
  "content": "{\"text\": \"자막 텍스트\"}",
  "font_family": "Pretendard",
  "font_size": 48,
  "bold": true,
  "color": [1.0, 1.0, 1.0],
  "alignment": 1,
  "line_height": 1.2
}
```

---

## 추천 라이브러리: pyCapCut

```bash
pip install pycapcut
```

```python
import pycapcut as cc

# 프로젝트 생성
script = cc.Script(1920, 1080, fps=30)

# 이미지 추가
img_seg = cc.ImageSegment("scene_01.png", cc.trange("0s", "7s"))
img_seg.add_keyframe(cc.KeyframeProperty.scale, cc.tim("0s"), 1.0)
img_seg.add_keyframe(cc.KeyframeProperty.scale, cc.tim("7s"), 1.2)
script.add_segment(img_seg)

# 오디오 추가
audio_seg = cc.AudioSegment("narration.mp3", cc.trange("0s", "180s"))
script.add_segment(audio_seg, track_index=1)

# 자막 추가 (SRT에서)
script.import_subtitles_from_srt("narration.srt")

# 프로젝트 저장
script.dump("output/capcut_draft")
```

---

## CapCut 버전 호환성

- pyCapCut은 CapCut v5.9 이하에서 완전 호환
- v6+ 에서 draft_content.json 암호화 가능성
- pyCapCut 라이브러리가 버전 호환성 관리
- 문제 발생 시 CapCut 버전 다운그레이드 또는 라이브러리 업데이트 확인

---

## 실전 구현 참조 (CapCut 6.7 검증, 2026-04-16)

### 좌표계 (⚠️ 비디오 / 텍스트 트랙 동일)

**`clip.transform.{x,y}`** — 정규화 좌표 `-1 ~ +1`

| 축 | 값 | 의미 |
|---|---|---|
| x | `-1` | 화면 왼쪽 |
| x | `+1` | 화면 오른쪽 |
| y | **`+1`** | **화면 상단** |
| y | **`-1`** | **화면 하단** |

자막 기본값 `transform.y = -0.234` 는 **하단 근처** (양수=상단 규칙에 따름).

### uniform_scale 동작

| 설정 | 동작 |
|---|---|
| `{on: True, value: v}` | 이미지 **원본 비율 유지**, 화면 가로 대비 v 배율 |
| `{on: False}` + `scale.x != scale.y` | **비율 왜곡** (독립 stretch) — 주의 |

**규칙**: 이미지 원본 비율 유지 필요 시 반드시 `uniform_scale.on = True`.

### Split 레이아웃 수학

상단 1/3 영역에 **16:9 이미지** 배치 시:
```
image_h_norm = (1 / img_aspect) × (9/16)
             = (1/1.78) × 0.5625 ≈ 0.316

transform.y   = 1 - image_h_norm  ≈ +0.684   (상단 정렬)
main_shift_y  = -image_h_norm     ≈ -0.316   (메인 영상을 이미지 영역 아래로)
uniform_scale = {on: True, value: 1.0}
```

상단 1/2 영역에 **1:1 이미지** 배치 시:
```
image_h_norm = (1/1) × (9/16) = 0.5625
transform.y  = +0.4375
main_shift_y = -0.5625
```

### render_index 규칙

- 숫자 **클수록 앞(위) 렌더링**
- 세그먼트 레벨 필드 (트랙 레벨 아님)
- pycapcut 기본: 자막 `14000~`, 일반 비디오 `0~`
- 오버레이 추가 시: **기존 최대값 + 10 이상** 권장 (예: `20000~`)
- **텍스트 트랙도 비디오 트랙과 함께 render_index 로 순서 결정됨** (텍스트가 무조건 위/아래가 아님)

### 세그먼트 `extra_material_refs`

pycapcut 초기 출력: **`[speeds[0].id]`** 하나만 있음 (최소).

세그먼트 복제 시 반드시 새 `speed` material 을 생성하여 refs 에 연결:
```python
new_speed = deepcopy(speeds[0]); new_speed["id"] = new_uuid()
draft["materials"]["speeds"].append(new_speed)
new_seg["extra_material_refs"] = [new_speed["id"]]
```

### 텍스트 material — 부분 색상 (accent words)

`content.styles[]` 배열에 여러 개의 스타일을 `range` 로 구분하여 단어별 색상 지정:

```json
{
  "text": "전환율 15% 개선",
  "styles": [
    { "range": [0, 3],  "fill": { ... "color": [1, 1, 1] } },
    { "range": [4, 7],  "fill": { ... "color": [1, 0.84, 0.31] } },
    { "range": [8, 10], "fill": { ... "color": [1, 1, 1] } }
  ]
}
```

공백도 range 에 포함하되 빈 토큰은 `range` 추가 skip.

### CapCut 자동 저장 덮어쓰기 (⚠️ 트랩)

**CapCut 이 열린 상태에서 `draft_content.json` 을 수정하면**:
1. 내 수정은 파일에 쓰여짐
2. CapCut 은 메모리 상의 오래된 데이터 유지
3. CapCut 종료 / 자동저장 시 **내 수정을 덮어씀**

**규칙**:
- 패치 전 반드시 CapCut 프로세스 종료 확인 (`tasklist /FI "IMAGENAME eq CapCut.exe"`)
- 확인 후 닫을 때는 **"저장 안 함"** 선택

### Text 트랙 오버레이 순서

**텍스트 트랙 ≠ 무조건 위에 렌더링.** `render_index` 순서를 따름.
따라서 emphasis 텍스트를 B-roll 이미지보다 위에 보이려면:
- emphasis `render_index` > B-roll `render_index`
- 또는 **공간적으로 겹치지 않도록 배치** (권장)

---

## NG 영상 자막 4중 후처리 파이프라인 (`build_draft()` 내부, 순서 고정)

`tools/capcut_pipeline/run_pipeline.py`의 `build_draft()`가 pycapcut 저장 직후 **이 순서로** 실행. 순서 바꾸면 파이프라인 깨짐.

| 순서 | 함수 | 역할 | 로그 |
|---|---|---|---|
| 1 | `_patch_subtitle_scene_clip` | cue가 2+ 씬에 걸치면 **마지막 씬 start로 cue.start 재정렬**. Whisper가 NG 재테이크를 한 cue로 묶으면서 start를 첫 NG 시점까지 확장한 것 보정 | `[scene-clip] re-anchored N cross-scene subtitles` |
| 2 | `_patch_scene_subtitle_groups` | 각 video_segment에 UUID를 `group_id`로 주입, 겹치는 text_segment에 **같은 UUID** 공유 → CapCut이 "링크된 클립"으로 인식 | `[group] bound N subtitles to M scenes via group_id` |
| 3 | `_patch_subtitle_offset` | 모든 text_segment의 `target_timerange.start`에 `+sub_offset_ms` 가산 (duration 유지). Whisper phoneme-onset bias 보정 | `[offset] shifted N subtitles by +Xms` |
| 4 | `_patch_subtitle_max_duration` | `max(1000ms, min(max_ms, chars × 250ms + 500ms))`로 duration 제한. 단어 끝 silence-padding 보정 | `[max-dur] clipped N subtitles ...` |

### 불변 조건 (깨면 파이프라인 붕괴)

교정 단계에서 `transcript_wrapped.srt` 편집 시:
- **타임스탬프 변경 금지** (scene-clip이 cue의 절대시간에 의존)
- **cue 개수 변경 금지** (group bind는 cue 순서로 씬 매칭)
- **cue 번호 변경 금지**

교정은 **텍스트 내용만** — 맞춤법/띄어쓰기/STT 오인식 복원. Claude Code 세션 내 Read/Write로 처리, `ANTHROPIC_API_KEY` 불필요.

### Whisper word_timestamps 3대 편향 (보정 필수)

1. **Phoneme-onset early start** (100-600ms) — 단어 시작을 음소 onset에 맞춰 빠르게. `sub-offset-ms` (실측 권장 600)로 보정.
2. **Silence-padded end** — 단어 끝을 뒤 silence까지 확장. `sub-max-duration-ms` (권장 5000)로 상한.
3. **Multi-take consolidation** — NG 재테이크를 한 segment로 병합. scene-clip으로 해결.

---

## B-roll `type` 선택 — screenshot vs webtoon (⭐)

`_build_capcut_broll_prompt` (scene_designer.py)가 type별로 다른 Gemini 프롬프트 생성:

| narration 유형 | type | 근거 |
|---|---|---|
| UI·앱·문서·차트·대시보드로 표현 가능 | `screenshot` | 실제 Korean SaaS 느낌 UI (Gmail/네이버메일/Notion/Toss 수준) |
| 사람의 감정·행동·상황 묘사 | `webtoon` | 한국 웹툰 스타일 일러스트 (표정·자세·분위기) |
| 추상·은유·상상적 이미지 | `webtoon` | UI로 표현 불가능한 장면 |

### screenshot 품질 — 장난감 UI 피하는 법

Gemini는 빈약한 힌트에 clip-art 같은 목업을 생성. **src_hint 디테일이 품질 좌우**:
- 구체적 한글 레이블 5개+ (사이드바, 상단 메뉴, 섹션 제목)
- 가상 한국 데이터 풍부 (발신자 5명+, 제목 5개+, 시간·날짜)
- 실제 제품 레퍼런스 ("Gmail/네이버 메일 같은")
- 다크 모드 또는 미드톤 (흰 mockup 금지)

빈약한 힌트 = 장난감 결과. type을 webtoon으로 바꾸지 말고 **src_hint를 풍부하게**.

### Opacity 기본값 (style이 결정)

`scene_designer.py ingest`에서 자동 설정, 개별 override는 예외적으로만:

| style | opacity | 이유 |
|---|---|---|
| `split` | **1.0 (불투명)** | 상단 영역을 100% 덮는 레이아웃. 투명도 주면 아래 메인 영상 비쳐 부자연스러움 |
| `overlay` | 0.75 (반투명) | 메인 영상 위에 floating. 반투명으로 녹아들기 |
| `dual` | 0.75 (반투명) | 좌/우 floating 2개 패널 |

### Emphasis 폰트 = "아네모네" (기본값)

scene_designer.py ingest가 모든 emphasis에 `font_name: "아네모네"` 자동 주입. 자막 트랙(`ODITTABILITY`)과 구분되어 시각적 계층 생성.

---

## 권장 CLI 값 (실측)

`run_pipeline.py`의 기본값은 **안전한 보수값**. 실전 권장값은:

| 플래그 | 기본값 | 권장값 | 이유 |
|---|---|---|---|
| `--model` | `small` | **`large-v3`** | 한국어 WER 3-4배 감소 (첫 다운로드 3GB, 이후 캐시) |
| `--fast-cut` | off | **off 유지** | 스트림 복사는 키프레임 스냅으로 씬 0.2-0.6s 겹침 (비추천) |
| `--sub-offset-ms` | **`600`** (기본) | 필요시 250-600 조정 | Whisper phoneme-onset bias 실측 보정값 |
| `--sub-max-duration-ms` | **`5000`** (기본) | 필요시 감소 | scene-clip이 duration 문제 대부분 해결하므로 완화값 |

### 권장 NG 대응 플로우

```bash
# Step 1: STT/컷 (large-v3 권장)
python tools/capcut_pipeline/run_pipeline.py <video> --model large-v3 --skip-draft

# Step 2: Claude Code가 transcript_wrapped.srt 교정 (타임스탬프·cue수 불변)

# Step 3: 교정본으로 드래프트 + B-roll context 생성
python tools/capcut_pipeline/run_pipeline.py <video> --skip-stt --skip-wrap --skip-cut \
        --sub-offset-ms 600 --sub-max-duration-ms 5000
```
