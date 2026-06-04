"""
12개 기존 motion graphics 템플릿을 shared.css로 마이그레이션 (2026-04-25).

각 템플릿에서 다음을 수행:
  1. <head>에 <link rel="stylesheet" href="shared.css" /> 추가
  2. @font-face 블록(Pretendard 5 weights) 제거
  3. `html, body { ... }` 블록에서 margin/padding/background/overflow/font-family 제거
     (width/height만 남김 — shared.css가 나머지 처리)

각 파일은 .pre_shared 백업 1회 생성. 이미 마이그레이션된 파일은 idempotent (skip).

Usage:
  python tools/motion_graphics/migrate_to_shared.py [--dry-run]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

TEMPLATES = [
    "stat_card_16x9.html",
    "stat_card_9x16.html",
    "ui_evidence_kakaotalk_16x9.html",
    "ui_evidence_kakaotalk_9x16.html",
    "ui_evidence_youtube_comment_9x16.html",
    "ui_evidence_instagram_dm_9x16.html",
    "icon_hero_1x1.html",
    "dual_icon_1x1.html",
    "graphic_insight_16x9.html",
    "ui_evidence_youtube_comment_16x9.html",
    "ui_evidence_notion_16x9.html",
    "ui_evidence_terminal_16x9.html",
]

LINK_TAG = '<link rel="stylesheet" href="shared.css" />'


def migrate_file(path: Path, dry_run: bool = False) -> str:
    """Returns one of: 'skipped', 'migrated', 'no-op'."""
    src = path.read_text(encoding="utf-8")

    # idempotent: shared.css link already present → skip
    if LINK_TAG in src:
        return "skipped"

    new = src

    # 1. @font-face 블록 제거 (Pretendard 5 weights — non-greedy multi-line match)
    new = re.sub(
        r"@font-face\s*\{[\s\S]*?Pretendard[\s\S]*?\}\s*",
        "",
        new,
    )

    # 2. <link> 추가 — gsap script 직전에
    new = re.sub(
        r'(<script src="https://cdn\.jsdelivr\.net/npm/gsap)',
        LINK_TAG + "\n" + r"\1",
        new,
        count=1,
    )

    # 3. html, body 블록 → width/height만 남기기
    #    매칭 패턴: html, body { ...margin... padding... width ... height ... background ... overflow ... font-family ... }
    def replace_body_block(match: re.Match) -> str:
        block = match.group(0)
        # width, height 만 추출
        w_match = re.search(r"width:\s*(\d+)px", block)
        h_match = re.search(r"height:\s*(\d+)px", block)
        if not w_match or not h_match:
            return block  # 안전: 이상하면 원본 유지
        w = w_match.group(1)
        h = h_match.group(1)
        return f"html, body {{ width: {w}px; height: {h}px; }}"

    new = re.sub(
        r"html,\s*body\s*\{[^}]*\}",
        replace_body_block,
        new,
        count=1,
    )

    # 빈 줄 3개 이상 → 2개로 정리
    new = re.sub(r"\n{3,}", "\n\n", new)

    if new == src:
        return "no-op"

    if not dry_run:
        bak = path.with_suffix(".html.pre_shared")
        if not bak.exists():
            bak.write_text(src, encoding="utf-8")
        path.write_text(new, encoding="utf-8")

    return "migrated"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="변경 사항만 출력")
    args = ap.parse_args()

    here = Path(__file__).resolve().parent / "templates"
    print(f"[migrate] base dir: {here}")
    print(f"[migrate] dry_run={args.dry_run}")
    print()

    counts = {"migrated": 0, "skipped": 0, "no-op": 0, "missing": 0}
    for name in TEMPLATES:
        path = here / name
        if not path.exists():
            print(f"  [missing] {name}")
            counts["missing"] += 1
            continue
        result = migrate_file(path, dry_run=args.dry_run)
        marker = {"migrated": "✓", "skipped": "↻", "no-op": "·"}.get(result, "?")
        print(f"  {marker} {result:9s} {name}")
        counts[result] = counts.get(result, 0) + 1

    print()
    print(f"[summary] {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
