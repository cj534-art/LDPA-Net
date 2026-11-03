#!/usr/bin/env python3
"""Crop paired remote-sensing images/masks into 512x512 PNG tiles.

Default stride is 512, with the final window aligned to the far edge.
Small sources are padded (image=0, mask=255). No resizing or split sampling.
See crop_512_README.md for label formats and reproducibility notes.
"""

import argparse
import json
from contextlib import ExitStack
from pathlib import Path

import numpy as np
from PIL import Image


SIZE = 512
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.tif', '.tiff', '.bmp'}


def axis_starts(length):
    if length <= SIZE:
        return [0]
    starts = list(range(0, length - SIZE + 1, SIZE))
    if starts[-1] != length - SIZE:
        starts.append(length - SIZE)
    return starts


def read_palette(path):
    """Read class_id: R,G,B lines; no implicit dataset-specific mapping."""
    if path is None:
        return None
    palette = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        index, values = line.split(':', 1)
        index = int(index.strip())
        color = tuple(int(value.strip()) for value in values.split(','))
        if len(color) != 3 or not 0 <= index <= 255 or any(not 0 <= v <= 255 for v in color):
            raise ValueError(f'Invalid palette entry: {line}')
        if color in palette:
            raise ValueError(f'Duplicate palette color: {color}')
        palette[color] = index
    if not palette:
        raise ValueError(f'Empty palette: {path}')
    return palette


def indexed_mask(mask, palette):
    values = np.asarray(mask)
    if values.ndim == 2 and np.issubdtype(values.dtype, np.integer):
        if values.min() < 0 or values.max() > 255:
            raise ValueError('Indexed labels must contain integer class IDs in 0..255')
        return Image.fromarray(values.astype(np.uint8))
    if mask.mode != 'RGB' or palette is None:
        raise ValueError('Masks must be integer class-ID images, or RGB with --palette')
    result = np.zeros(values.shape[:2], dtype=np.uint8)
    matched = np.zeros(values.shape[:2], dtype=bool)
    for color, index in palette.items():
        selected = np.all(values == color, axis=2)
        result[selected] = index
        matched |= selected
    if not matched.all():
        raise ValueError(f'RGB label color absent from palette: {values[~matched][0].tolist()}')
    return Image.fromarray(result)


def files_by_stem(directory):
    result = {}
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix.lower() in EXTENSIONS:
            if path.stem in result:
                raise ValueError(f'Duplicate filename stem: {path.stem} in {directory}')
            result[path.stem] = path
    return result


def run(args):
    if not args.images.is_dir() or (args.masks is not None and not args.masks.is_dir()):
        raise ValueError('Input image/mask directory does not exist')
    output = args.output.resolve()
    for source in (args.images, args.masks):
        if source is not None:
            source = source.resolve()
            if output == source or source in output.parents or output in source.parents:
                raise ValueError('Output and input directories must not contain each other')
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('Output must be a new or empty directory; existing data is never overwritten')
    images = files_by_stem(args.images)
    if not images:
        raise ValueError('No source images found')
    masks = files_by_stem(args.masks) if args.masks is not None else {}
    pairs = []
    for stem, image in images.items():
        mask = masks.get(stem + args.mask_suffix) if args.masks is not None else None
        if args.masks is not None and mask is None:
            raise ValueError(f'Missing matching mask for {image.name} (suffix={args.mask_suffix!r})')
        pairs.append((image, mask))
    palette = read_palette(args.palette)
    (output / 'images').mkdir(parents=True, exist_ok=True)
    if args.masks is not None:
        (output / 'masks').mkdir()
    total = 0
    with (output / 'samples.txt').open('w', encoding='utf-8') as ids, \
            (output / 'tiles.jsonl').open('w', encoding='utf-8') as manifest:
        for image_path, mask_path in pairs:
            with ExitStack() as stack:
                source = stack.enter_context(Image.open(image_path))
                image = source.convert('RGB')
                mask = None
                if mask_path is not None:
                    source_mask = stack.enter_context(Image.open(mask_path))
                    if source_mask.size != image.size:
                        raise ValueError(f'Image/mask size mismatch: {image_path.name}')
                    mask = indexed_mask(source_mask, palette)
                width, height = image.size
                count = 0
                for y in axis_starts(height):
                    for x in axis_starts(width):
                        name = f'{image_path.stem}_y{y:05d}_x{x:05d}_orig.png'
                        valid_width, valid_height = min(SIZE, width - x), min(SIZE, height - y)
                        box = (x, y, x + valid_width, y + valid_height)
                        tile = Image.new('RGB', (SIZE, SIZE), 0)
                        tile.paste(image.crop(box), (0, 0))
                        tile.save(output / 'images' / name)
                        if mask is not None:
                            label = Image.new('L', (SIZE, SIZE), args.ignore_index)
                            label.paste(mask.crop(box), (0, 0))
                            label.save(output / 'masks' / name)
                        ids.write(name + '\n')
                        manifest.write(json.dumps({
                            'tile': name, 'source_image': image_path.name,
                            'source_mask': mask_path.name if mask_path is not None else None,
                            'x': x, 'y': y, 'source_width': width, 'source_height': height,
                            'valid_width': valid_width, 'valid_height': valid_height,
                        }, ensure_ascii=False) + '\n')
                        count += 1
                total += count
                print(f'{image_path.name}: {count} tiles', flush=True)
    (output / 'preprocess.json').write_text(json.dumps({
        'tile_size': SIZE, 'stride': SIZE, 'edge_policy': 'align_last_window',
        'image_padding': 0, 'mask_padding': args.ignore_index,
        'image_mode': 'RGB', 'mask_mode': 'L' if args.masks is not None else None,
        'palette': {','.join(map(str, color)): index for color, index in palette.items()}
                   if palette is not None else None,
        'source_count': len(pairs), 'tile_count': total,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Done: {len(pairs)} source images -> {total} tiles in {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--images', required=True, type=Path)
    parser.add_argument('--masks', type=Path, help='Optional ground-truth directory')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--mask-suffix', default='', help='Additional mask stem suffix')
    parser.add_argument('--palette', type=Path, help='RGB mask mapping: class_id: R,G,B')
    parser.add_argument('--ignore-index', default=255, type=int)
    args = parser.parse_args()
    if not 0 <= args.ignore_index <= 255:
        parser.error('--ignore-index must be in 0..255')
    if args.masks is None and (args.palette is not None or args.mask_suffix):
        parser.error('--palette and --mask-suffix require --masks')
    try:
        run(args)
    except (ValueError, OSError) as error:
        parser.exit(1, f'Error: {error}\n')


if __name__ == '__main__':
    main()
