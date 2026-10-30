"""Draws the Lip Service icon: puffy rainbow chrome lips (a bubbled 3-d look) on a dark rounded square.
Usage: python -I tools/make_icon.py <preview.png> [<icon.ico>]"""
import colorsys
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

S = 1024  # drawn big, shrunk for smooth edges


def bez(p0, p1, p2, p3, n=120):
    t = np.linspace(0, 1, n)[:, None]
    p0, p1, p2, p3 = map(np.array, (p0, p1, p2, p3))
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


def to_px(pts):
    return [(S * (0.5 + 0.40 * x), S * (0.50 - 0.40 * y)) for x, y in np.asarray(pts, dtype=float)]


def lips_outline():
    return np.vstack([
        bez((-1, 0), (-0.75, 0.22), (-0.5, 0.5), (-0.28, 0.46)),
        bez((-0.28, 0.46), (-0.18, 0.46), (-0.08, 0.34), (0, 0.30)),
        bez((0, 0.30), (0.08, 0.34), (0.18, 0.46), (0.28, 0.46)),
        bez((0.28, 0.46), (0.5, 0.5), (0.75, 0.22), (1, 0)),
        bez((1, 0), (0.7, -0.45), (0.35, -0.62), (0, -0.62)),
        bez((0, -0.62), (-0.35, -0.62), (-0.7, -0.45), (-1, 0)),
    ])


def mouth_line():
    return bez((-1, 0), (-0.45, -0.16), (0.45, -0.16), (1, 0), n=400)


def blur(arr, r):
    """Gaussian blur in floating point (an 8 bit blur leaves faint steps that show up as wrinkles in the shading)."""
    fy = np.fft.fftfreq(arr.shape[0])[:, None]
    fx = np.fft.fftfreq(arr.shape[1])[None, :]
    kernel = np.exp(-2 * (np.pi ** 2) * (r ** 2) * (fx ** 2 + fy ** 2))
    return np.real(np.fft.ifft2(np.fft.fft2(arr) * kernel))


def main():
    outline, line = to_px(lips_outline()), to_px(mouth_line())
    mask_img = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask_img).polygon(outline, fill=255)
    m = np.asarray(mask_img) > 0
    ys, xs = np.mgrid[0:S, 0:S]
    line_y = np.interp(np.arange(S), [p[0] for p in line], [p[1] for p in line])
    upper = (ys < line_y[xs]) & m
    lower = (~(ys < line_y[xs])) & m

    # puffy height: each lip is inflated on its own, so a soft crease forms where they meet
    height = np.zeros((S, S))
    for part in (upper, lower):
        p = part.astype(float)
        h = 0.45 * blur(p, 16) + 0.35 * blur(p, 40) + 0.20 * blur(p, 90)
        height += h * part
    height = height ** 0.85
    gy, gx = np.gradient(height * 150.0)
    nx, ny, nz = -gx, -gy, np.ones_like(gx)
    norm = np.sqrt(nx ** 2 + ny ** 2 + nz ** 2)
    nx, ny, nz = nx / norm, ny / norm, nz / norm

    hue = (xs / S * 1.15 + ys / S * 0.35) % 1.0
    rgb = np.zeros((S, S, 3))
    for hv in np.unique(np.round(hue, 3)):
        sel = np.round(hue, 3) == hv
        rgb[sel] = colorsys.hsv_to_rgb(hv, 0.85, 1.0)

    light = np.array([-0.35, -0.55, 0.75]); light /= np.linalg.norm(light)
    diffuse = np.clip(nx * light[0] + ny * light[1] + nz * light[2], 0, 1)
    half = light + np.array([0, 0, 1.0]); half /= np.linalg.norm(half)
    spec = np.clip(nx * half[0] + ny * half[1] + nz * half[2], 0, 1) ** 55
    # chrome reflection of a bright sky above and a bright floor below
    env = np.interp(ny, [-1, -0.45, 0.0, 0.35, 1.0], [1.0, 0.9, 0.32, 0.5, 1.0])
    fres = (1 - nz) ** 1.6

    col = rgb * (0.40 + 0.75 * diffuse[..., None])
    col = col * (1 - 0.35 * env[..., None]) + (0.35 * env[..., None]) * (0.55 * rgb + 0.45)
    col += 0.95 * spec[..., None] + 0.25 * fres[..., None] * rgb
    col = np.clip(col, 0, 1)

    # soft crease line between the lips
    ml = Image.new("L", (S, S), 0)
    ImageDraw.Draw(ml).line(line, fill=255, width=8)
    creases = np.asarray(ml.filter(ImageFilter.GaussianBlur(6))) / 255.0
    col = col * (1 - 0.65 * creases[..., None])

    lips = Image.fromarray((col * 255).astype(np.uint8), "RGB").convert("RGBA")
    lips.putalpha(mask_img.filter(ImageFilter.GaussianBlur(2.0)))

    # rounded square with a pink to cyan edge
    base = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(base).rounded_rectangle([20, 20, S - 20, S - 20], radius=210, fill=(10, 10, 18, 255))
    tt = (xs + ys) / (2 * S)
    ex = np.zeros((S, S, 4), dtype=np.uint8)
    ex[..., 0] = 255 * (1 - tt) + 25 * tt; ex[..., 1] = 43 * (1 - tt) + 230 * tt; ex[..., 2] = 214 * (1 - tt) + 255 * tt; ex[..., 3] = 255
    ring = Image.new("L", (S, S), 0)
    rd = ImageDraw.Draw(ring)
    rd.rounded_rectangle([20, 20, S - 20, S - 20], radius=210, fill=255)
    rd.rounded_rectangle([44, 44, S - 44, S - 44], radius=190, fill=0)
    base.paste(Image.fromarray(ex), (0, 0), ring)

    # faint rainbow glow behind the lips, then a soft contact shadow under them
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    glow_rgb = Image.fromarray((rgb * 255).astype(np.uint8), "RGB").convert("RGBA")
    glow_rgb.putalpha(mask_img.filter(ImageFilter.GaussianBlur(40)).point(lambda v: int(v * 0.35)))
    base.alpha_composite(glow_rgb)
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sh = Image.new("L", (S, S), 0)
    sh.paste(mask_img, (0, 26))
    shadow.putalpha(sh.filter(ImageFilter.GaussianBlur(26)).point(lambda v: int(v * 0.55)))
    base.alpha_composite(shadow)
    base.alpha_composite(lips)

    img = base.resize((512, 512), Image.LANCZOS)
    img.save(sys.argv[1])
    if len(sys.argv) > 2:
        img.save(sys.argv[2], sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print("saved", sys.argv[1:])


main()
