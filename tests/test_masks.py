import pytest

from app.masks import box_mask, center_crop
from PIL import Image


def test_box_mask_pixels():
    m = box_mask((0, 0, 0.5, 1), 832, 480)
    assert m.getpixel((10, 10)) == (255, 255, 255) and m.getpixel((600, 10)) == (0, 0, 0)


def test_bad_box_rejected():
    with pytest.raises(ValueError):
        box_mask((0.6, 0, 0.4, 1), 832, 480)


def test_center_crop_size():
    assert center_crop(Image.new("RGB", (1000, 1000)), 832, 480).size == (832, 480)
