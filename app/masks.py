"""Per-singer masks from boxes. A box is (x0, y0, x1, y1) as fractions of the 16:9 generation frame."""
from PIL import Image, ImageDraw


def center_crop(img: Image.Image, width: int, height: int) -> Image.Image:
    """Same framing the workflow uses (ImageScale, crop center): scale to cover, crop the middle."""
    scale = max(width / img.width, height / img.height)
    img = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    left, top = (img.width - width) // 2, (img.height - height) // 2
    return img.crop((left, top, left + width, top + height))


def box_mask(box, width: int, height: int) -> Image.Image:
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError(f"box must be fractions with x0<x1 and y0<y1, got {box}")
    m = Image.new("RGB", (width, height), (0, 0, 0))
    ImageDraw.Draw(m).rectangle([round(x0 * width), round(y0 * height),
                                 round(x1 * width) - 1, round(y1 * height) - 1], fill=(255, 255, 255))
    return m


def preview(shot_path: str, boxes, width: int, height: int) -> Image.Image:
    """The framed shot with each singer's box drawn and numbered, so boxes can be checked by eye."""
    img = center_crop(Image.open(shot_path).convert("RGB"), width, height)
    d = ImageDraw.Draw(img)
    for i, (x0, y0, x1, y1) in enumerate(boxes, start=1):
        d.rectangle([x0 * width, y0 * height, x1 * width - 1, y1 * height - 1], outline=(255, 64, 64), width=3)
        d.text((x0 * width + 6, y0 * height + 4), str(i), fill=(255, 255, 255))
    return img


def orig_box_to_frame(box_px, orig_size, width: int, height: int):
    """A box in original image pixels to fractions of the centre cropped generation frame."""
    ow, oh = orig_size
    s = max(width / ow, height / oh)
    off_x, off_y = (ow * s - width) / 2, (oh * s - height) / 2
    x0, y0, x1, y1 = box_px
    clip = lambda v: min(max(v, 0.0), 1.0)
    return (clip((x0 * s - off_x) / width), clip((y0 * s - off_y) / height),
            clip((x1 * s - off_x) / width), clip((y1 * s - off_y) / height))
