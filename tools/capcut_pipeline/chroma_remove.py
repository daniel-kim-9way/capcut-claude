"""
블루 크로마 배경 제거 — #0000FF 근처 픽셀을 alpha=0으로 변환.

사용법:
  python chroma_remove.py --dir output/<name>/broll_gemini
  python chroma_remove.py --file path/to/image.png

Gemini가 블루 크로마 배경 + UI를 생성 → 이 스크립트가 알파 처리.
CapCut은 그냥 투명 PNG로 인식해서 오버레이 시 블루 영역은 메인 영상이 보임.

임계값:
  blue-dominant: R < 80, G < 100, B > 200 → alpha 0
  중간 톤 (블루 반투명 fringe): 점진적 alpha (edge smoothing)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
    import numpy as np
except ImportError:
    print('[err] Pillow/numpy required: pip install Pillow numpy', file=sys.stderr)
    sys.exit(1)


def remove_blue_chroma(
    img_path: Path,
    out_path: Path | None = None,
    *,
    blue_hex: str = '#0000FF',
    threshold: int = 100,  # 블루 거리 임계값 (유클리드, 0-441)
    edge_soften: int = 30,  # 가장자리 softening 거리
) -> dict:
    """블루 크로마 픽셀을 alpha=0으로. fringe는 gradient alpha."""
    img = Image.open(img_path).convert('RGBA')
    arr = np.array(img, dtype=np.int32)

    # 타겟 블루
    br, bg, bb = int(blue_hex[1:3], 16), int(blue_hex[3:5], 16), int(blue_hex[5:7], 16)

    # 유클리드 거리 (RGB)
    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    dist = np.sqrt((r - br) ** 2 + (g - bg) ** 2 + (b - bb) ** 2)

    # 3-tier mask:
    # - dist < threshold: fully transparent (alpha=0)
    # - threshold <= dist < threshold + edge_soften: gradient (alpha 0→255)
    # - dist >= threshold + edge_soften: opaque (alpha preserved)
    opaque_mask = dist >= (threshold + edge_soften)
    transparent_mask = dist < threshold
    edge_mask = ~opaque_mask & ~transparent_mask

    new_alpha = a.astype(np.int32)
    new_alpha[transparent_mask] = 0
    # edge: linear ramp
    edge_dist = dist[edge_mask]
    edge_alpha = ((edge_dist - threshold) / edge_soften * 255).astype(np.int32)
    new_alpha[edge_mask] = np.clip(edge_alpha, 0, 255)
    # opaque: keep original a

    arr[..., 3] = np.clip(new_alpha, 0, 255)
    out_img = Image.fromarray(arr.astype(np.uint8), 'RGBA')
    out_path = out_path or img_path
    out_img.save(out_path, 'PNG')

    total = arr.shape[0] * arr.shape[1]
    transparent_px = int(transparent_mask.sum())
    edge_px = int(edge_mask.sum())
    return {
        'path': str(out_path),
        'total_pixels': total,
        'transparent_pixels': transparent_px,
        'edge_pixels': edge_px,
        'transparent_pct': round(transparent_px / total * 100, 1),
    }


def main():
    parser = argparse.ArgumentParser(description='블루 크로마 배경 제거 (alpha 투명화)')
    parser.add_argument('--dir', help='디렉토리 내 모든 *.png 처리')
    parser.add_argument('--file', help='단일 파일 처리')
    parser.add_argument('--blue', default='#0000FF', help='크로마 색상 hex (기본: #0000FF)')
    parser.add_argument('--threshold', type=int, default=100, help='블루 거리 임계값 (0-441)')
    parser.add_argument('--edge-soften', type=int, default=30, help='가장자리 softening 거리')
    args = parser.parse_args()

    files = []
    if args.dir:
        d = Path(args.dir)
        if not d.is_dir():
            print(f'[err] not a dir: {d}', file=sys.stderr)
            sys.exit(2)
        files = sorted(d.glob('*.png'))
    elif args.file:
        f = Path(args.file)
        if not f.is_file():
            print(f'[err] not a file: {f}', file=sys.stderr)
            sys.exit(2)
        files = [f]
    else:
        parser.error('--dir or --file required')

    for f in files:
        try:
            stats = remove_blue_chroma(
                f, blue_hex=args.blue, threshold=args.threshold, edge_soften=args.edge_soften
            )
            print(f'[ok] {f.name} → {stats["transparent_pct"]}% transparent '
                  f'({stats["transparent_pixels"]}/{stats["total_pixels"]} px)')
        except Exception as e:
            print(f'[err] {f.name}: {e}', file=sys.stderr)


if __name__ == '__main__':
    main()
