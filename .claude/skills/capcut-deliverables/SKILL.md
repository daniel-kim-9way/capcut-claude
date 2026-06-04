# CapCut Deliverables Skill ⭐

**인스타 발행 + FunnelMaster 업로드용 메타데이터 파일 생성 + 4-step 나레이션 업로드**.

CapCut 드래프트에는 `--title` 플래그로 타이틀 텍스트만 들어가고, 실제 발행·반응 측정·공유 링크 발급에 필요한 **제목 + 캡션 + 스크립트 + 최종 영상**은 별도 `deliverables/` 폴더에 파일로 기록해야 합니다. 이 스킬은 (a) `title.txt` 후킹 한 줄, (b) `ig_caption.txt` 400~600자 본문 + 해시태그 5개, (c) FunnelMaster 나레이션 업로드 4-step을 담당합니다.

관련 스킬: [`capcut-pipeline`](../capcut-pipeline/SKILL.md) (드래프트 생성), [`capcut-fx`](../capcut-fx/SKILL.md) (FX 주입), [`capcut-subtitle`](../capcut-subtitle/SKILL.md) (자막 타이밍).

---

## 📁 출력 파일 위치

```
output/<name>/deliverables/
├── title.txt        # 영상 제목 (한 줄, 후킹)
├── ig_caption.txt   # 인스타 캡션 (400~600자 + 해시태그 5)
├── script.txt       # SRT 평문 (FunnelMaster 업로드용, Step 1에서 생성)
└── final.mp4        # CapCut 내보내기 (FunnelMaster 업로드용)
```

**언제 만드나**: STT + transcript 교정 완료 후, scene_designer plan과 병행. CapCut 내보내기 전에 `title.txt` / `ig_caption.txt` 2개는 미리 작성.

**누가**: Claude Code 메인이 `transcript_wrapped.srt`를 읽고 직접 작성 (별도 API 키 불필요).

---

## ⛔ `title.txt` 규칙

- **한 줄** — 말미 개행 없음 (빈 줄 금지)
- **10단어 / 20자 이하** — 첫 3초 스크롤 방어
- **후킹 요소 1개 이상 포함**:
  - 의문형 (`?`)
  - 구체 숫자 (`3가지`, `10배`, `500만 건`)
  - 반전/대조 (`~인데 사실은`, `~인 줄 알았죠`)
  - "비밀/공식/이유" 키워드
- **핵심 키워드 포함** (검색·추천 알고리즘 대응)
- 영상 첫 씬 narration과 메시지 일치 — **클릭베이트 금지**

✅ 좋은 예:
```
답장 빨라지는 이메일 제목 3가지
일잘하는 사람은 뇌를 이렇게 씁니다
```

❌ 나쁜 예:
```
이메일에 대해 이야기해 봅시다        ← 후킹 없음
충격! 이메일 하나로 인생 역전!!!    ← 금지 표현 + 클릭베이트
```

---

## ⚡ `ig_caption.txt` 규칙 (가장 중요)

**본문 길이**: 400~600자 (해시태그 제외)
**캡션은 대본의 가치를 더 깊게 전달하는 글** — 영상에서 다 못한 이야기를 보충하고, 읽는 사람에게 실질적 도움이 되어야 함.

### 1. 톤 & 어체 ⚠️ (위반 시 전면 재작성)

- **전문가가 진심을 담아 이야기하는 어조** — 차분, 신뢰, 진정성
- **기본 격식체** `~합니다 / ~입니다` + **공감·전환 혼용** `~거든요 / ~잖아요`
- **반말/평서형 절대 금지** — `~다 / ~있다 / ~않는다 / ~이다`
- **호칭**: `여러분` 고정 (절대 `당신` 금지. 변주 필요 시 `~하시는 분들`)
- **권장 전환구**: `왜냐하면~`, `그래서~`, `바로~`, `이게 바로~`
- **공감 표현**: `~하시는 분들 같아요`, `~하신 적 있으시죠?`, `~겪어보셨죠?`
- **진정성**: `제 경험으로는~`, `도움이 되셨으면 좋겠어요`

### 2. ⛔ 금지 표현

`충격!` · `대박!` · `무조건` · `100%` · `반드시` · `인생이 바뀝니다` · 이모지 (불릿 `—` `·` 만 허용)

| ✅ 좋은 예 | ❌ 나쁜 예 |
|---|---|
| 결과가 10배 차이나는 이유가 있거든요. | 결과가 10배 차이납니다. |
| 겪어보신 분들 많으시죠? | 당신도 겪어봤을 겁니다. |
| 답장받는 분과 안 받는 분의 차이예요. | 답장 못 받으면 인생이 바뀝니다. |
| 세 가지만 기억해 주세요. | 무조건 이거 3개 외워! |

### 3. 구조 템플릿 (5블록)

```
[후킹 첫 줄 — 질문/반전/숫자. 영상 첫 3초의 변주, 복붙 금지]

[영상 핵심 메시지 요약 — 2~3문장]

[대본에서 다 못한 추가 정보·맥락·데이터·심리학 근거 — 3~4문장]

[실천 방법 또는 구체적 팁 — 2~3문장]

[CTA — 댓글에 "[키워드]" 남겨주시면 [구체 혜택] 보내드릴게요]

#해시태그1 #해시태그2 #해시태그3 #해시태그4 #해시태그5
```

- 2~3문장마다 **빈 줄** (벽글자 금지, "더 보기" 펼쳤을 때 가독성)
- 마지막 줄은 **CTA** (댓글/저장/팔로우/DM 유도)

### 4. 해시태그 5개 + SEO 키워드 5~6개

- **해시태그**: 본문 아래 공백 줄 후 한 줄로. 한글 우선. 업종 + 주제 + 타깃 조합.
  예: `#일잘러 #이메일잘쓰기 #업무효율 #직장인꿀팁 #생산성`
- **SEO 키워드**: 본문에 자연스럽게 녹이거나, 별도 메타로 보관 (검색·관련 콘텐츠 매칭).

### 5. AI 레이블 (선택)

AI 생성 아바타·TTS 사용 영상이면 본문 말미, 해시태그 위에:
```
※ 본 영상은 AI 기술로 제작되었습니다. (가상인물 포함)
```
실제 인물 촬영본(PROMPTER 류)은 생략.

---

## 📝 예시 (이메일 제목 3가지 — 권장 품질)

`title.txt`:
```
일잘하는 사람은 뇌를 이렇게 씁니다
```

`ig_caption.txt`:
```
같은 이메일을 써도 답장받는 사람과 안 받는 사람, 차이는 '뇌 쓰는 법'에 있거든요.

일잘하는 분들은 받는 사람 뇌가 어떻게 작동하는지부터 이해합니다. 본문을 열기도 전에 제목만으로 판단이 끝난다는 사실을 알고 있거든요. 그래서 본문이 아니라 제목에 시간을 쓰는 겁니다.

이메일 분석 서비스 부메랑이 500만 건의 업무 이메일을 분석한 결과가 있어요. 제목만 보고 안 여는 비율이 절반을 넘었고, 마감 날짜가 들어간 제목은 응답률이 2배 이상 높아졌습니다. 받는 사람 받은편지함에는 '기획서'라는 단어가 들어간 메일이 이미 10개쯤 쌓여있거든요. 제목에서 '이게 무엇인지, 언제까지 해야 하는지'가 끝나야 열립니다.

세 가지만 기억해 주세요. 첫째, 할 일을 꺾쇠로 표시 — [결정 요청], [공유], [리마인드]. 둘째, 마감 날짜를 제목에 박기 — "3월 15일까지 결정". 셋째, 구체적으로 쓰기 — '기획서 첨부'가 아니라 '프로젝트X 기획서 1차 초안'. 이게 바로 일잘러의 뇌 사용법이에요.

댓글에 "이메일 제목"이라고 남겨주시면 상황별 제목 공식 10개 정리해서 보내드릴게요.

#일잘러 #이메일잘쓰기 #업무효율 #직장인꿀팁 #생산성
```

---

## ✅ 검증 체크리스트

**`title.txt`**
- [ ] 한 줄, 말미 개행 없음
- [ ] 20자 이하
- [ ] 후킹 요소 1개 이상 (숫자/의문/반전/비밀)
- [ ] 핵심 키워드 포함
- [ ] 영상 첫 씬 메시지와 일치

**`ig_caption.txt`**
- [ ] 본문 400~600자 (해시태그 제외)
- [ ] 반말/평서형 없음 (`~다`, `~이다`, `~있다`, `~않는다` 전수 검색)
- [ ] 금지 표현 없음 (`충격`, `대박`, `무조건`, `100%`, `반드시`, `인생이 바뀝니다`)
- [ ] 이모지 0개 (`—`, `·` 불릿은 OK)
- [ ] 2~3문장마다 빈 줄
- [ ] 첫 줄 = 후킹 / 마지막 줄(해시태그 앞) = CTA
- [ ] 해시태그 정확히 5개 (본문 아래 공백 줄 후 한 줄)
- [ ] UTF-8 인코딩 + 줄바꿈 LF
- [ ] AI 레이블 필요 영상이면 추가

---

## 🚀 FunnelMaster 업로드 — 4-step

CapCut에서 NG 씬 정리 + 내보내기 후, 최종 영상을 **funnelmaster.kr**에 "나레이션" 타입으로 업로드. 반응 측정 · 공유 링크 발급 · 템플릿화 용도.

### ⚠️ 선행 조건

- `title.txt`, `ig_caption.txt` 이미 작성됨
- 최종 영상을 `output/<name>/deliverables/final.mp4`로 저장
- `.env`의 `FUNNELMASTER_API_KEY` 유효 (발급: https://funnelmaster.kr/settings/ai)

### ⛔ Windows cp949 경고 — `PYTHONIOENCODING=utf-8` 필수

Windows 기본 콘솔은 **cp949**라, Python이 응답 JSON을 `print` 할 때 em-dash(`—`) · middot(`·`) · 화살표(`→`) 등에서 `UnicodeEncodeError: 'cp949' codec can't encode character ...` 로 종료됨. **업로드는 이미 서버에서 완료된 상태**지만 stdout 직렬화 단계에서 터지면서 exit 1이 반환되어 마치 실패처럼 보임. 모든 명령에 프리픽스 필수:

```bash
export PYTHONIOENCODING=utf-8          # 세션 전체
# 또는
PYTHONIOENCODING=utf-8 python ...      # 명령당
```

### Step 1 — SRT → 평문 `script.txt`

`transcript_wrapped.srt`의 타임스탬프 제거하고 본문만 합침. CapCut에서 NG 씬을 삭제했어도 SRT는 원본이므로 NG 테이크 반복 문자열 남아있을 수 있음 — 필요 시 수동 편집.

```bash
python -c "
import pathlib
srt = pathlib.Path('output/<name>/subs/transcript_wrapped.srt').read_text(encoding='utf-8')
lines = []
for block in srt.strip().split('\n\n'):
    parts = block.split('\n')
    if len(parts) >= 3:
        lines.append(' '.join(parts[2:]).strip())
plain = ' '.join(lines)
pathlib.Path('output/<name>/deliverables/script.txt').write_text(plain, encoding='utf-8')
print(f'wrote {len(plain)} chars')
"
```

### Step 2 — 나레이션 생성 (title + caption + script → `generation_id`)

```bash
PYTHONIOENCODING=utf-8 python tools/reels_pipeline/funnelmaster_uploader.py narration \
  --topic   "$(cat output/<name>/deliverables/title.txt)" \
  --script  "@output/<name>/deliverables/script.txt" \
  --caption "@output/<name>/deliverables/ig_caption.txt"
```

응답 JSON에서 `id` (또는 `generation_id`) **메모** — 예: `367`. 이후 재사용.

⚡ **`[FM] Narration created: generation_id=...` 로그 먼저 찍혔으면 서버 생성 완료**. 뒤에 `UnicodeEncodeError`가 나도 실패 아님 — 같은 ID를 Step 3에 그대로 넘겨도 됨.

### Step 3 — 영상 파일 업로드

```bash
PYTHONIOENCODING=utf-8 python tools/reels_pipeline/funnelmaster_uploader.py video \
  --gen-id 367 \
  --video  "output/<name>/deliverables/final.mp4"
```

내부 timeout 300초 — 50MB 이상 업로드 대응. 실패 시 같은 명령 재시도 (같은 `gen-id` 재사용). 파일명에 공백·괄호 있으면 **반드시 큰따옴표**.

### Step 4 — 상태 확인 + 전체 URL 조립

```bash
PYTHONIOENCODING=utf-8 python tools/reels_pipeline/funnelmaster_uploader.py status --gen-id 367
```

응답의 `video_url`은 Rails active_storage 상대 경로(`/rails/active_storage/blobs/redirect/...`). 브라우저 열기용 전체 URL:

```bash
PYTHONIOENCODING=utf-8 python tools/reels_pipeline/funnelmaster_uploader.py status --gen-id 367 \
  | python -c "import sys, json; d=json.load(sys.stdin); print('https://funnelmaster.kr' + d['video_url'])"
```

---

## 🔍 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| `UnicodeEncodeError: cp949 can't encode '—'` | Windows 콘솔. `PYTHONIOENCODING=utf-8` 프리픽스. 로그에 `generation_id=` 먼저 찍혔으면 업로드는 성공 — 다음 Step 진행 가능 |
| Step 2 응답에 `generation_id` 안 보임 | 인코딩 에러로 stdout 잘림. 서버 로그(stderr)에 `[FM] Narration created: generation_id=N` 찾기. 또는 `PYTHONIOENCODING=utf-8` 다시 실행 |
| Step 3 timeout | 300초 초과 — 영상이 너무 큼. CapCut에서 비트레이트 낮춰 재내보내기, 또는 같은 `gen-id`로 재시도 |
| Step 4 `video_url`이 `/rails/active_storage/...`로 시작 | 정상. 상대 경로. `https://funnelmaster.kr` 접두사 붙여 전체 URL 조립 |
| 401 Unauthorized | `.env`의 `FUNNELMASTER_API_KEY` 만료/무효. https://funnelmaster.kr/settings/ai 재발급 |
| `upload --project <dir>` 서브커맨드 쓰고 싶음 | ⛔ **쓰지 말 것**. `create-reels` 전용 구조 (`final_reel.mp4` 고정 파일명, `scene_plan_reels.json` 필수). CapCut 출력엔 맞지 않음 — `narration` + `video` 2단계 수동 호출이 정답 |
| 이모지/`충격!`/반말 섞임 | 검증 체크리스트 전수 확인. 위반 시 `ig_caption.txt` 전면 재작성 |

---

## 🗂️ 관련 파일

- [tools/reels_pipeline/funnelmaster_uploader.py](../../../tools/reels_pipeline/funnelmaster_uploader.py) — 업로더 본체 (narration/video/status 서브커맨드)
- [output/<name>/subs/transcript_wrapped.srt](../../../output/) — Step 1 입력
- [output/<name>/deliverables/](../../../output/) — 4개 출력 파일 위치
- [.claude/commands/capcut.md](../../commands/capcut.md) § 2-C, § 5-C — 원본 스펙

---

## ✅ 최종 체크리스트 (업로드 직전)

- [ ] `output/<name>/deliverables/`에 4개 파일: `title.txt`, `ig_caption.txt`, `script.txt`, `final.mp4`
- [ ] `title.txt` 검증 체크리스트 통과
- [ ] `ig_caption.txt` 검증 체크리스트 통과 (특히 반말·금지표현·이모지 전수 확인)
- [ ] `final.mp4` 재생 가능 (길이 · 자막 · B-roll 정상)
- [ ] `.env` `FUNNELMASTER_API_KEY` 유효
- [ ] 모든 `python` 명령에 `PYTHONIOENCODING=utf-8` 프리픽스
- [ ] Step 2 응답 `generation_id` 메모
- [ ] Step 4 `video_url` 전체 URL로 브라우저 재생 확인
