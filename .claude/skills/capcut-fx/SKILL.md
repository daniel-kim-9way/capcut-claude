# CapCut FX Skill ⭐

**CapCut 드래프트에 시네마틱 FX를 주입**: 제목/CTA 애니메이션 · 강조 SFX · 씬 효과 · BGM · 색조 필터.

이 스킬은 `/capcut` 커맨드 실행 중 **반드시** 로드됩니다. 놓치면 영상이 평범해집니다.

---

## ⛔ 필수 구성요소 (5개 카테고리 — 하나라도 빠지면 안 됨)

fx_plan.json은 이 5개 키를 **모두** 포함해야 합니다. 의도적 생략 시 `null`로 명시 + 주석:

| 키 | 필수 타입 | 기본값 |
|---|---|---|
| `intro_video_animation` ⭐ | dict | `{scene_idx: 0, preset: "side_slide", duration_us: 400000}` — **첫 클립 사이드 슬라이드 인 효과** |
| `sfx` | list (≥3) | intro + title_reveal + 각 강조 지점 tick |
| `scene_effects` | list (≥3) | math_rush + lens_zoom ×n (자막정렬·≥1.5s, 겹침금지; **flash_warm 제거**) |
| `bgm` | dict | `{path: "BGM/....mp3", volume_db: -25}` |
| `filter` ⚡ | dict | `{preset: "natural_ii", intensity: 0.3}` ← **놓치기 쉬움** |

> ⛔ **현재 확정 규칙** (날짜는 최초 결정 시점):
> 1. **타자기 애니메이션(`title_animation`/`outro_animation` typewriter) 기본 미사용** (2026-06-08) — 둘 다 **선택**(plan에 넣으면 적용되나 완결성 게이트에서 요구 안 함). 시작 강조는 `intro_video_animation`(첫 클립 사이드 슬라이드)이 담당.
> 2. **시작 '미지근한 플래시(flash_warm)' 제거** (2026-06-08) — scene_effects는 lens_zoom 중심.
> 3. **전역 배속 기본 1.2** (2026-06-08, 기존 1.15에서 상향 — 아래 `speed`).
> 4. **타이틀/강조(emphasis) 자막은 상단(top)** 기본 (가운데 아님 — overlay_patcher title position 기본 `top`).

**⚠️ 코드 게이트 작동**: `capcut_fx_patcher.py`는 위 5개 키가 빠지면 **exit 5로 거부**합니다. `--allow-incomplete`로 우회 가능하지만 권장 안 함. (required 키 SoT 3중 동기: `templates/_registry.json` ↔ `extract_templates.REQUIRED_FX_KEYS_SPEC` ↔ `verify_step.REQUIRED_FX_KEYS`)

### ⭐ `intro_video_animation` — 첫 클립 인-애니메이션

```jsonc
"intro_video_animation": { "scene_idx": 0, "preset": "side_slide", "duration_us": 400000 }
```
- 메인 video 트랙의 클립(기본 첫 클립 scene 0)에 in-animation을 **비디오 세그먼트**로 주입 (텍스트 아님). **첫 클립에만** 적용 — 모든 클립에 넣지 않는다.
- **기본 preset = `side_slide`(사이드 슬라이드)** (2026-06-11, 기존 `zoom_in`에서 변경). `side_slide`는 `templates/animations.json`에 등록 (PROMPTER_20260608_173233 드래프트에서 추출, `resource_id 7241878375516606978`, `panel/material_type=video`, dur 0.4s). `zoom_in`(0.5s)도 등록돼 있어 **대체 선택지**로 사용 가능하나 기본은 side_slide.
- 시작 타자기/플래시를 대체하는 오프닝 강조. 구현: `patch_video_intro_animation()`. 로그 `[ok] intro_video_animation(side_slide) → main clip scene 0`.

### ⭐ `speed` — 전역 배속 (기본 1.2, optional 키)

`fx_plan.json`에 `"speed": 1.2` (기본값)를 넣으면, fx_patcher가 **모든 FX 적용 후 마지막에** CapCut "전체 선택 → N배속"과 **동일한 전역 압축**을 수행한다:

- 모든 트랙의 모든 세그먼트 `target_timerange`(start·duration)를 `1/speed`로 압축
- video/audio 세그먼트는 `seg.speed` + 참조 speed 머티리얼을 `speed`로 설정 (없으면 생성)
- `draft.duration`도 `1/speed`로 압축 → 영상·자막·B-roll·emphasis·SFX·BGM **전부 같은 비율**로 줄어 싱크 유지

```jsonc
"speed": 1.2   // 기본 1.2 (2026-06-08 상향, 기존 1.15). 배속 원치 않으면 1.0(no-op). extract_fx_candidates가 자동 생성.
```

- `extract_fx_candidates.py`가 `speed: 1.2`를 **자동 생성**한다. 다른 배속을 원하면 값만 수정.
- ⚠️ 오디오(나레이션·BGM·SFX)는 배속만큼 **피치가 약간 상승**한다(수동 select-all 배속과 동일한 동작, 사용자 수용). 재인코딩 불필요 — 드래프트 레벨.
- 필수 키와 **별개**(없거나 1.0이면 no-op). `--verify-completeness`는 speed를 검사하지 않음. `fx_patcher`의 코드 기본값도 `plan.get('speed', 1.2)`.
- 구현: `apply_global_speed()` ([capcut_fx_patcher.py](../../../tools/capcut_pipeline/capcut_fx_patcher.py)). 패치 로그에 `[ok] global_speed x1.2 → N segments compressed ...` 확인.

---

## 🤖 자동 후처리 (extract_fx_candidates / fx_patcher 내장 — plan 수동 작성 불필요)

아래 동작은 코드에 **이미 구현**돼 있어 fx_plan을 손대지 않아도 자동 적용된다. (모두 2026-06-11)

| 동작 | 무엇을 / 왜 |
|---|---|
| **closer-suppression** | 마지막 emphasis(보통 CTA "댓글에 X")의 **SFX(tick)를 자동 제거**해 마지막 멘트를 효과음 없이 조용히 닫아 여운을 준다. 단 그 시점의 **시각 강조 `lens_zoom`(scene_effect)는 유지**. |
| **lens_zoom 배치 (2026-06-11 개정)** | 모든 `lens_zoom`(emphasis + 컷 seam cover-the-cut)은 ① **자막 cue 경계에 시작·끝 스냅**(자막 바뀌는 타이밍에 끊김), ② **영상 cut(씬 경계)을 넘지 않게 그 씬 안에 가둠(컷에서 끊김, 자막보다 우선)** + 최소 1.8s clean(≥1.5s 최종)(과거 0.6s seam→0.5s 어색 폐기), ③ **겹침·인접(연속) 금지**(emphasis zoom 우선 배치 → 컷 seam은 interval 겹침 X **AND** 다른 lens_zoom과 `ZOOM_GAP=1.5s`(clean) 이상 떨어질 때만). `build_fx_plan`의 `get_subtitle_cue_bounds`+`_snap_zoom_to_cues`가 자동. ⚠️ 과거 SEAM_GUARD는 시작거리만 봐서 긴 emphasis zoom(5.63s) 안에 0.6s seam이 박히는 **중복 버그** 있었음 → interval 겹침 검사로 해소. [[feedback_capcut_lens_zoom_cue_aligned]] |
| **SFX de-dup** | 생성된 SFX 중 **0.05초 이내 중복 이벤트 자동 제거** — 인트로/타이틀/emphasis가 같은 시점을 동시 유발할 때 '띡띡' 겹침 방지. |
| **deterministic BGM** | `_pick_bgm_skeleton(seed)`가 `random.choice` 대신 **SHA1(영상명) % len** 결정론 픽 → 같은 영상 재실행 시 BGM 폴백이 안 바뀜(idempotent). 이는 **폴백**일 뿐 — LLM이 톤에 맞춰 `bgm.path`를 덮어쓰는 원칙은 그대로. |

> **향후 계획 (선택)**: voice-sidechain ducking — 현재 BGM은 flat −25dB. 중기적으로 주입 전 ffmpeg로 나레이션 대비 ~10dB pre-duck 옵션 추가 예정.

---

## 🔧 사용 가능 프리셋

| 그룹 | 프리셋 | 용도 | 기본 길이/강도 |
|---|---|---|---|
| **FILTER** ⚡ | `natural_ii` | 인물 톤 보정 ("천연 ll") | intensity 0.5, 전구간 |
| **BGM** | `bgm_good_mood` | 전구간 배경음 | 영상 전체, -18~-20dB |
| video in-anim ⭐ | `side_slide` | **첫 클립 사이드 슬라이드 인 효과** (시작 강조, intro_video_animation) | 0.4s |
| video in-anim | `zoom_in` | 첫 클립 줌1 (대체 선택지 — 기본은 side_slide) | 0.5s |
| text animation | `typewriter` | 제목/CTA 타자기 (⛔ 2026-06-08 기본 미사용 — 선택) | 1.4s |
| scene effect | ~~`flash_warm`~~ | ⛔ 시작 플래시 — 2026-06-08 기본 제거 | 1.87s |
| scene effect | `math_rush` | 타이틀 리빌 | 3.0s |
| scene effect | `lens_zoom` | 강조 지점 렌즈 줌 | 5.63s |
| SFX | `keyboard_typing` | 인트로 훅 | 1.87s |
| SFX | `mouse_click` | 타이틀 리빌 | 0.77s |
| SFX | `ui_notify` | 초반 강조 | 1.77s |
| SFX | `tick` | 강조 펀치 (반복) | 0.87s |

모든 프리셋은 CapCut 내장 라이브러리에서 로컬 캐시 참조. 새 프리셋 추가 시 `extract_templates.py`로 편집본에서 추출.

---

## 🎬 콤보 패턴 (160404 편집본의 디자인 언어)

필수 조합 — 각 시점마다 이 조합이 자동 발동되도록 fx_plan 구성:

| 시점 | filter | bgm | 씬효과 | SFX | 애니메이션 |
|---|---|---|---|---|---|
| **전구간** | `natural_ii` ⚡ | 로컬 BGM(-25dB) | — | — | `speed` 1.2 전역 |
| 0.00s | ↑ | ↑ | — (flash 제거) | `keyboard_typing`(선택) | ⭐ **`side_slide` on 첫 클립** (intro_video_animation) |
| ~2.5-3s | ↑ | ↑ | `math_rush` | `mouse_click` | — |
| 첫 강조 (6-8s 부근) | ↑ | ↑ | `lens_zoom` | `ui_notify` | — |
| 주요 emphasis 각각 | ↑ | ↑ | `lens_zoom` | `tick` | — |
| 컷 seam마다 | ↑ | ↑ | `lens_zoom`(자막정렬·≥1.5s, 자동) | — | — |
| 마지막 CTA | ↑ | ↑ | `lens_zoom`만 유지 | **SFX 없음** (closer-suppression 자동) | — (타자기 제거) |

⛔ 타이틀/강조(emphasis) 자막은 **상단(top)** 배치 기본 (가운데 금지). 타이틀 등장 시점에는 emphasis 자막을 **동시에 띄우지 말 것** (오프닝은 타이틀 + 첫 클립 사이드 슬라이드만; emphasis는 타이틀 사라진 뒤).

---

## 📝 fx_plan.json 작성 절차 (Claude Code용)

### Step 1 — 드래프트에서 정보 추출

```python
import json, os
from pathlib import Path
NAME = '<project_name>'
p = Path(os.environ['LOCALAPPDATA']) / f'CapCut/User Data/Projects/com.lveditor.draft/{NAME}/draft_content.json'
d = json.loads(p.read_text(encoding='utf-8'))

# (a) main 씬 timerange
main_segs = next(tr['segments'] for tr in d['tracks'] if tr.get('type') == 'video')
print(f'총 {len(main_segs)}씬, duration={(main_segs[-1]["target_timerange"]["start"] + main_segs[-1]["target_timerange"]["duration"])/1e6:.2f}s')

# (b) emphasis text 트랙 — 보통 마지막 text 트랙 (segs 10~20개)
# 제목 / 마감 / 핵심 수치 / CTA 등이 여기에 있음
```

### Step 2 — emphasis 지점 선별 (5~10개)

**우선순위**:
- 🔴 핵심 숫자·결과 ("500만 건", "2배 증가", "1,100만 원")
- 🟡 반전·대조 ("왜?", "충격적인")
- 🟢 리스트 시작·CTA ("3가지", "댓글에 X")
- ⚪ 스킵: 필러, 반복

**상한 8개** — 더 많으면 시각 피로.

### Step 3 — fx_plan.json 조립

**⚡ 순서 중요**: 빠뜨리기 쉬운 것부터 위에 배치:

```json
{
  "_comment": "프로젝트명 + 주제",
  "filter": { "preset": "natural_ii", "intensity": 0.3 },
  "bgm": { "path": "BGM/Sunlit Cup.mp3", "volume_db": -25 },
  "intro_video_animation": { "scene_idx": 0, "preset": "side_slide", "duration_us": 400000 },
  "sfx": [
    {"preset": "keyboard_typing", "start_sec": 0.00, "duration_sec": 1.87},
    {"preset": "mouse_click",     "start_sec": <title_reveal_sec>, "duration_sec": 0.77},
    {"preset": "ui_notify",       "start_sec": <first_emphasis>,   "duration_sec": 1.77},
    {"preset": "tick",            "start_sec": <emphasis_1>,       "duration_sec": 0.87},
    {"preset": "tick",            "start_sec": <emphasis_2>,       "duration_sec": 0.87}
  ],
  "scene_effects": [
    {"preset": "math_rush",  "start_sec": <title_reveal_sec>, "duration_sec": 3.00},
    {"preset": "lens_zoom",  "start_sec": <first_emphasis>,   "duration_sec": 5.63},
    {"preset": "lens_zoom",  "start_sec": <emphasis_1>,       "duration_sec": 5.63}
  ],
  "speed": 1.2
}
```

### Step 4 — 검증 먼저 (필수)

```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/capcut_fx_patcher.py \
  --plan temp/<name>/fx_plan.json \
  --verify-completeness
```

**`[PASS]` 가 나와야만** Step 5로 진행. `[FAIL]` 이면 빠진 키 채우고 재검증.

### Step 5 — 패치 적용

```bash
PYTHONIOENCODING=utf-8 python tools/capcut_pipeline/capcut_fx_patcher.py \
  --draft "$LOCALAPPDATA/CapCut/User Data/Projects/com.lveditor.draft/<name>/draft_content.json" \
  --plan  "temp/<name>/fx_plan.json"
```

**완료 조건**: 로그에 다음 `[ok]` 모두 존재 확인:
- `[ok] intro_video_animation(side_slide) → main clip scene 0` ⭐
- `[ok] sfx[...]` 라인 **3개 이상** (마지막 CTA tick은 closer-suppression으로 자동 제거됨 / 0.05s 중복 de-dup 적용)
- `[ok] scene_effect[...]` 라인 **3개 이상** (flash_warm 없음; 컷 seam zoom 포함 모두 자막정렬·≥1.5s)
- `[ok] bgm <트랙명> duration=...`
- `[ok] filter natural_ii intensity=... dur=...` ⚡
- `[ok] global_speed x1.2 → N segments compressed ...`
- (title_animation/outro_animation은 plan에 명시한 경우에만 로그에 나타남 — 기본 미사용)

⚠️ `filter` 줄 안 보이면 fx_plan.json에 `filter` 키 빠진 것. Step 4 게이트 통과했는데 이게 나올 수는 없지만, 만약 `--allow-incomplete` 썼다면 여기서 걸러짐.

---

## 🧱 트랙 z-order (자막 왜곡 방지)

자동 배치되는 트랙 순서 (bottom→top):

```
[0] video  (main_video)         ← base
[1] filter                      ← main 바로 위 (render_index 10000)
[2] effect                      ← filter 위 (render_index 11001)
[3] text   (subtitles)          ← effect 위 → 자막 왜곡 안 됨
[4] video  (broll_overlay)
[5] video  (broll 추가)
[6] text   (emphasis_text)
[7] audio  (SFX)
[8] audio  (BGM)
```

패처의 `_ensure_track('effect'/'filter')`가 `main_video` 바로 뒤에 `insert`하므로 자동 보장. **직접 건드리지 말 것**.

---

## 🚨 모드 옵션

| `--mode` | 동작 |
|---|---|
| `auto` (기본) | applied면 no-op, different면 `.fx_clean_bak` 복구 후 재적용 |
| `clean` | 항상 `.fx_clean_bak` 복구 + 재적용 (코드 변경 반영 시) |
| `force` | 복구 없이 강제 재적용 (중복 누적 위험, 디버깅용) |
| `reject` | different면 에러로 중단 (CI 안전) |

**상태 파일** (draft와 같은 디렉토리):
- `draft_content.json.fx_clean_bak` — FX 전 스냅샷
- `.omc_fx_patch_state.json` — plan_hash + log

---

## 🔍 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| `[FAIL] fx_plan.json is incomplete` | 필수 키 빠짐. Step 4 메시지대로 채우기 |
| `[skip] identical fx_plan already applied` | 동일 plan 이미 적용됨. `--mode clean` 으로 강제 재적용 |
| `[warn] title_animation: no text segment near scene N` | scene_idx 근처 2초 안에 text 없음. `scene_idx`를 인접 씬으로 변경, 또는 `tolerance_ms: 3000` spec 추가 |
| CapCut 열었더니 효과 없음 | CapCut 자동저장이 덮어씀. 열기 전 `tasklist /FI "IMAGENAME eq CapCut.exe"` 확인, 닫을 때 "저장 안 함" |
| 자막이 렌즈 줌에 왜곡됨 | z-order 이슈. 패처가 자동 처리해야 함. 발생 시 드래프트의 track 순서 확인 |
| `UnicodeEncodeError: cp949` | Windows 콘솔 인코딩. 명령 앞에 `PYTHONIOENCODING=utf-8` 반드시 |
| BGM 너무 작음 | `bgm.volume_db` 를 -18 ~ -15 로 상향. -15 이상은 보이스 깔림 위험 |
| **BGM이 느리게 재생됨** (2026-04-22 수정됨) | 과거 버그: `target_timerange.duration`을 영상 전체 길이로 강제해 `source`(원본 157s) < `target`(영상 207s)일 때 CapCut이 자동 stretch. **해결**: `patch_sfx`가 BGM일 때 `duration_us`를 원본 길이로 clamp → `source==target`, speed=1.0. 영상이 BGM보다 길면 영상 끝부분은 무음. 루프/페이드를 원하면 추가 구현 필요 |
| lens_zoom이 씬 경계 넘음 | 의도된 동작 (5.63s). 줄이고 싶으면 `duration_sec` 축소 |
| filter 적용됐는데 자막 색 변함 | filter가 text 트랙 위에 위치. 트랙 순서 재확인 (자동 배치 정상이면 [1] filter 위치) |

---

## 🗂️ 관련 파일

- [tools/capcut_pipeline/capcut_fx_patcher.py](../../../tools/capcut_pipeline/capcut_fx_patcher.py) — 패처 본체
- [tools/capcut_pipeline/extract_templates.py](../../../tools/capcut_pipeline/extract_templates.py) — 편집본→템플릿 추출
- [tools/capcut_pipeline/templates/](../../../tools/capcut_pipeline/templates/) — 프리셋 JSON
  - `animations.json` / `audios.json` / `video_effects.json` / `filters.json`

---

## ✅ 최종 체크리스트 (완료 전 확인)

- [ ] fx_plan.json에 5개 키 모두 존재 (`intro_video_animation`, `sfx`, `scene_effects`, `bgm`, `filter`) + `speed`(기본 1.2)
- [ ] `--verify-completeness` 로 `[PASS]` 확인
- [ ] flash_warm 없음 / typewriter 없음 (기본 제거)
- [ ] 마지막 CTA에 SFX 없음 (closer-suppression) / 컷 seam zoom 자막정렬·≥1.5s 자동
- [ ] CapCut 완전 종료 확인 (`tasklist`)
- [ ] `PYTHONIOENCODING=utf-8` 프리픽스 사용
- [ ] 패치 로그에 `intro_video_animation`·`sfx`·`scene_effect`·`bgm`·`filter`·`global_speed` `[ok]` 존재
- [ ] CapCut 열어 재생 확인 → 첫 클립 사이드 슬라이드 인 효과 + filter 색조 + 타이틀/강조 상단 배치 체크
- [ ] 확인 후 **"저장 안 함"** 으로 닫기
