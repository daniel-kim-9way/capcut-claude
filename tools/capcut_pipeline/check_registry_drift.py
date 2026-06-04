"""
check_registry_drift.py — CI-style preset-name drift detector.

Compares `templates/_registry.json` (single source of truth emitted by
extract_templates.py) against `.claude/skills/capcut-fx/SKILL.md`.

Rules enforced:
  1. Every preset name in `_registry.json` must appear somewhere in SKILL.md.
  2. Every preset name mentioned inside SKILL.md code blocks / backticks
     must exist in the registry (catches typos + stale names).

Exit codes:
  0 — consistent
  2 — registry missing or unreadable
  3 — drift detected (prints actionable diff)

Usage:
  python tools/capcut_pipeline/check_registry_drift.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


HERE = Path(__file__).parent
REGISTRY = HERE / 'templates' / '_registry.json'
# Walk up from tools/capcut_pipeline → repo root.
REPO_ROOT = HERE.parent.parent
SKILL_MD = REPO_ROOT / '.claude' / 'skills' / 'capcut-fx' / 'SKILL.md'


# Preset-name shape: lowercase letters + digits + underscore, 3+ chars.
# Matches things like `typewriter`, `bgm_good_mood`, `natural_ii`, `lens_zoom`.
PRESET_RE = re.compile(r'\b([a-z][a-z0-9]+(?:_[a-z0-9]+)+|typewriter)\b')

# Identifiers that *look* like presets but are reserved keys / python names /
# dict literals we shouldn't flag as "unknown preset".
IGNORED_TOKENS = {
    # fx_plan.json top-level required keys
    'title_animation', 'outro_animation', 'scene_effects',
    # plan fields
    'start_sec', 'duration_sec', 'duration_us', 'volume_db',
    'scene_idx', 'tolerance_ms',
    # patcher mode names
    'allow_incomplete', 'verify_completeness', 'show_schema',
    'fx_plan', 'fx_clean_bak', 'clean_bak',
    # file / state names
    'draft_content', 'animations_json', 'audios_json',
    'video_effects_json', 'filters_json',
    # doc scaffolding that happens to match shape
    'render_index', 'target_timerange', 'source_timerange',
    'broll_overlay', 'emphasis_text', 'main_video',
    'text_id', 'seg_id', 'anim_id', 'plan_hash',
    # skill lingo
    'category_hints', 'required_fx_keys', 'schema_version',
    'sfx_candidates', 'bgm_candidates', 'intro_sfx',
    'title_reveal_sfx', 'first_emphasis_sfx', 'punch_sfx',
    # python identifiers referenced in code blocks
    'main_segs', 'target_follow', 'sticker_animation',
    'capcut_fx_patcher', 'capcut_pipeline', 'extract_templates',
    'read_text',
    # placeholder variables used in example fx_plan snippets
    'emphasis_1', 'emphasis_2', 'first_emphasis', 'title_reveal_sec',
    'project_name',
}


def _read_registry() -> dict | None:
    if not REGISTRY.exists():
        print(f'[err] registry not found: {REGISTRY}', file=sys.stderr)
        print('       run: python tools/capcut_pipeline/extract_templates.py',
              file=sys.stderr)
        return None
    try:
        return json.loads(REGISTRY.read_text(encoding='utf-8'))
    except Exception as e:
        print(f'[err] registry unreadable: {e}', file=sys.stderr)
        return None


def _registry_preset_names(reg: dict) -> set[str]:
    names: set[str] = set()
    for group, lst in reg.get('presets', {}).items():
        for n in lst:
            names.add(n)
    return names


def _skill_md_tokens(text: str) -> set[str]:
    """Extract preset-shaped tokens from SKILL.md, restricted to content
    inside backticks (so ordinary prose words don't get flagged)."""
    tokens: set[str] = set()
    # inline code / fenced code: everything between ` ... ` or ``` ... ```
    for chunk in re.findall(r'`([^`]+)`', text):
        for m in PRESET_RE.findall(chunk):
            tokens.add(m)
    # Also scan fenced blocks (```...```)
    for chunk in re.findall(r'```[a-zA-Z]*\n(.*?)```', text, flags=re.DOTALL):
        for m in PRESET_RE.findall(chunk):
            tokens.add(m)
    return tokens


def main() -> int:
    reg = _read_registry()
    if reg is None:
        return 2
    if not SKILL_MD.exists():
        print(f'[err] SKILL.md not found: {SKILL_MD}', file=sys.stderr)
        return 2

    registry_presets = _registry_preset_names(reg)
    skill_text = SKILL_MD.read_text(encoding='utf-8')
    skill_tokens = _skill_md_tokens(skill_text)

    # Direction 1: registry presets not mentioned in SKILL.md
    missing_in_doc = sorted(
        p for p in registry_presets
        if not re.search(rf'\b{re.escape(p)}\b', skill_text)
    )

    # Direction 2: preset-shaped tokens in SKILL.md that aren't in registry
    unknown_in_doc = sorted(
        t for t in skill_tokens
        if t not in registry_presets and t not in IGNORED_TOKENS
    )

    if not missing_in_doc and not unknown_in_doc:
        print(f'[PASS] registry ↔ SKILL.md consistent '
              f'({len(registry_presets)} presets verified)')
        return 0

    print('[FAIL] registry / SKILL.md drift detected\n')
    if missing_in_doc:
        print(f'  presets in registry but NOT in SKILL.md ({len(missing_in_doc)}):')
        for p in missing_in_doc:
            # Hint where the preset came from.
            src = next(
                (g for g, lst in reg.get('presets', {}).items() if p in lst),
                '?',
            )
            print(f'    - {p}  (group: {src})')
        print()
    if unknown_in_doc:
        print(f'  preset-shaped tokens in SKILL.md but NOT in registry '
              f'({len(unknown_in_doc)}):')
        for t in unknown_in_doc:
            print(f'    - {t}')
        print()
        print('  → either add to templates/_registry.json via extract_templates.py,')
        print('    or add to IGNORED_TOKENS in this script if it is not a preset.')
    return 3


if __name__ == '__main__':
    sys.exit(main())
