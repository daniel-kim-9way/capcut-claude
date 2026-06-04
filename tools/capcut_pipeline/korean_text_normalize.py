"""한국어 자막 텍스트 정규화 유틸.

두 가지 작업:
1. **convert_korean_numbers**: 한글 숫자(사십칠, 열네, 십개월…) → digit (47, 14, 10개월)
   - Sino-Korean: 일/이/삼/사/오/육/칠/팔/구/십/백/천/만 (47, 100, 1000…)
   - Native Korean: 한/두/세/네/다섯/여섯/일곱/여덟/아홉/열/스물/서른… (1~99)
   - **counter** (개·명·번·회·년·달·개월…)가 따라올 때만 변환 — 관용구("한 번도", "두 번 다시") 보존
2. **split_words_at_sentences**: word list를 문장 종결("." / "?" / "!")에서 분리.
   wrap_segments가 한 cue에 여러 문장 합치는 문제 해결.
"""
from __future__ import annotations

import re
from typing import Iterable

# --- Sino-Korean (formal) ----------------------------------------------------
SINO_DIGIT = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5,
              "육": 6, "칠": 7, "팔": 8, "구": 9}
SINO_PLACE = {"십": 10, "백": 100, "천": 1000, "만": 10000}
SINO_CHARS = set(SINO_DIGIT) | set(SINO_PLACE)


def _parse_sino(s: str) -> int | None:
    """일/이/.../구 + 십/백/천/만 → int. Invalid면 None."""
    if not s or any(c not in SINO_CHARS for c in s):
        return None
    total = 0
    sub = 0  # 만 단위 누산기 (사십칠만 -> 47*10000)
    cur = 0
    for ch in s:
        if ch in SINO_DIGIT:
            cur = SINO_DIGIT[ch]
        else:  # SINO_PLACE
            place = SINO_PLACE[ch]
            if place == 10000:
                total += (sub + cur) * 10000
                sub = 0
                cur = 0
            else:
                sub += (cur if cur else 1) * place
                cur = 0
    return total + sub + cur


# --- Native Korean (vernacular) ---------------------------------------------
# 1-19: 하나(한), 둘(두), 셋(세), 넷(네), 다섯, 여섯, 일곱, 여덟, 아홉, 열, 열한…열아홉
# 20-90: 스물(스무), 서른, 마흔, 쉰, 예순, 일흔, 여든, 아흔
NATIVE_BASE = {
    "하나": 1, "한": 1, "둘": 2, "두": 2, "셋": 3, "세": 3, "넷": 4, "네": 4,
    "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9,
    "열": 10, "스물": 20, "스무": 20, "서른": 30, "마흔": 40,
    "쉰": 50, "예순": 60, "일흔": 70, "여든": 80, "아흔": 90,
}

# Compound natives: prefix(열/스물/...) + suffix(한/두/.../아홉)
# Ordered LONGEST-FIRST so '열한' matches before '열' alone.
NATIVE_COMPOUND: dict[str, int] = {}
for prefix in ("열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"):
    base = NATIVE_BASE[prefix]
    for suffix, sval in [("한", 1), ("두", 2), ("세", 3), ("네", 4),
                          ("다섯", 5), ("여섯", 6), ("일곱", 7), ("여덟", 8), ("아홉", 9)]:
        # 스무한x exists in colloquial but standard is 스물한 — keep just '스물'
        if prefix == "스무":
            continue
        NATIVE_COMPOUND[prefix + suffix] = base + sval

NATIVE_ALL: dict[str, int] = {**NATIVE_COMPOUND, **NATIVE_BASE}

# Counters that signal a quantity → convert to digit.
# 한/두 + 사람·번·달 같은 일상 숫자 단위만 — 관용 표현(한 번도, 두 번 다시)는 별도 보호
QUANTITY_COUNTERS = (
    "개월", "개", "명", "번째", "번", "회", "년", "달", "주",
    "마리", "권", "살", "벌", "잔", "장", "쪽", "편", "대",
    "시간", "분", "초", "위", "등", "가지", "여명",
)

# Idiom protection: these phrases stay even if they'd match.
# Pattern: phrase → keep verbatim
IDIOM_PROTECT = {
    "한 번도": "__IDIOM_HBD__",   # never
    "한번도": "__IDIOM_HBD2__",
    "두 번 다시": "__IDIOM_2BD__",  # never again
    "한 줄": "__IDIOM_1L__",       # 한 줄 (idiom: a line)
    "한줄": "__IDIOM_1L2__",
    # demonstrative + 번 compound (이번/저번/지난번/요번 = "this time/last time/...")
    "이번": "__IDIOM_TBN__",
    "저번": "__IDIOM_LBN__",
    "지난번": "__IDIOM_PBN__",
    "요번": "__IDIOM_RBN__",
}


# Particles/suffixes that legitimately follow a number+counter compound.
# When counter is followed by one of these (or non-Hangul/end), we know
# we hit a real word boundary — not a compound word like 회사/회복/회수.
TRAILING_PARTICLES = (
    "을", "를", "이", "가", "은", "는", "의", "에", "에서", "서",
    "와", "과", "도", "만", "까지", "부터", "처럼", "같이", "짜리",
    "째", "들", "도", "씩", "마다", "보다", "조차", "라도", "이나",
    "만큼", "한", "쯤", "어치",
)


def _make_boundary_lookahead() -> str:
    """Counter 뒤에 와도 되는 패턴: 끝 / 공백 / 구두점 / 비한글 / 알려진 particle."""
    particles = "|".join(re.escape(p) for p in TRAILING_PARTICLES)
    # Lookahead: end-of-string OR non-Hangul OR a particle.
    # 가-힣 매칭이지만 particle list에 있으면 OK.
    return f"(?=$|[^가-힣]|{particles})"


def _replace_compound_natives(text: str) -> str:
    """열한 → 11, 스물세 → 23 등을 counter 따라올 때 digit으로."""
    counter_re = "|".join(re.escape(c) for c in QUANTITY_COUNTERS)
    boundary = _make_boundary_lookahead()
    # longest-first
    keys = sorted(NATIVE_COMPOUND.keys(), key=lambda k: -len(k))
    for k in keys:
        v = NATIVE_COMPOUND[k]
        pattern = f"{re.escape(k)} ?({counter_re}){boundary}"
        text = re.sub(pattern, f"{v}\\1", text)
    return text


def _replace_base_natives(text: str) -> str:
    """한/두/세/네/다섯/.../아흔 + counter → digit."""
    counter_re = "|".join(re.escape(c) for c in QUANTITY_COUNTERS)
    boundary = _make_boundary_lookahead()
    keys = sorted(NATIVE_BASE.keys(), key=lambda k: -len(k))
    for k in keys:
        v = NATIVE_BASE[k]
        pattern = f"{re.escape(k)} ?({counter_re}){boundary}"
        text = re.sub(pattern, f"{v}\\1", text)
    return text


def _replace_sino(text: str) -> str:
    """사십칠 → 47, 백십이 → 112 (counter 뒤따를 때만, compound 단어 보호)."""
    counter_re = "|".join(re.escape(c) for c in QUANTITY_COUNTERS)
    boundary = _make_boundary_lookahead()
    sino_chars = "".join(sorted(SINO_CHARS))
    # 단일 sino digit (이/일/삼/사…) + space + counter는 demonstrative 오인 위험
    # ("이 회사", "이 분", "사 분") → 다중 글자 sino만 space 허용, 단일은 space 금지.
    # 다중 글자 sino: 사십칠개 / 십이개 / 백이십명 (no-space ok)
    multi_pattern = re.compile(
        f"([{sino_chars}]{{2,8}}) ?({counter_re}){boundary}"
    )
    # 단일 글자 sino: NO space 허용 (이번/이회 같은 명확한 경우만)
    single_pattern = re.compile(
        f"([{sino_chars}])({counter_re}){boundary}"
    )

    def repl(m: re.Match) -> str:
        n = _parse_sino(m.group(1))
        if n is None:
            return m.group(0)
        return f"{n}{m.group(2)}"

    text = multi_pattern.sub(repl, text)
    text = single_pattern.sub(repl, text)
    return text


def convert_korean_numbers(text: str) -> str:
    """한글 숫자 + counter → digit + counter. 관용구는 보존."""
    if not text:
        return text
    # 1) idiom 보호 (sentinel 치환)
    for idiom, sentinel in IDIOM_PROTECT.items():
        text = text.replace(idiom, sentinel)
    # 2) 변환: compound native → base native → sino (longest-match 보장 위해 순서 중요)
    text = _replace_compound_natives(text)
    text = _replace_base_natives(text)
    text = _replace_sino(text)
    # 3) idiom 복원
    for idiom, sentinel in IDIOM_PROTECT.items():
        text = text.replace(sentinel, idiom)
    return text


# --- sentence splitting ------------------------------------------------------

SENTENCE_END = (".", "?", "!")


def split_words_at_sentences(words: list[dict]) -> list[list[dict]]:
    """word list를 문장 종결 단어에서 분리. 빈 그룹 자동 제거.

    각 word는 dict {start, end, word(str)} 형식.
    """
    groups: list[list[dict]] = []
    cur: list[dict] = []
    for w in words:
        cur.append(w)
        token = (w.get("word") or "").strip()
        if token.endswith(SENTENCE_END):
            groups.append(cur)
            cur = []
    if cur:
        groups.append(cur)
    return [g for g in groups if g]
