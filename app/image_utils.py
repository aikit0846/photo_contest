from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

from PIL import Image
from PIL import ImageFilter
from PIL import ImageOps
from PIL import ImageStat
from PIL import UnidentifiedImageError


@dataclass(slots=True)
class ImageMetrics:
    width: int | None
    height: int | None
    brightness: float
    contrast: float
    saturation: float
    sharpness: float
    entropy: float
    sha256: str


def analyze_image(image_bytes: bytes) -> ImageMetrics:
    file_hash = hashlib.sha256(image_bytes).hexdigest()
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            normalized = ImageOps.exif_transpose(img).convert("RGB")
            width, height = normalized.size

            grayscale = normalized.convert("L")
            hsv = normalized.convert("HSV")
            edges = grayscale.filter(ImageFilter.FIND_EDGES)

            brightness = ImageStat.Stat(grayscale).mean[0]
            contrast = ImageStat.Stat(grayscale).stddev[0]
            saturation = ImageStat.Stat(hsv).mean[1]
            sharpness = ImageStat.Stat(edges).mean[0]
            entropy = float(grayscale.entropy())

            return ImageMetrics(
                width=width,
                height=height,
                brightness=brightness,
                contrast=contrast,
                saturation=saturation,
                sharpness=sharpness,
                entropy=entropy,
                sha256=file_hash,
            )
    except UnidentifiedImageError:
        return ImageMetrics(
            width=None,
            height=None,
            brightness=128.0,
            contrast=64.0,
            saturation=64.0,
            sharpness=64.0,
            entropy=5.0,
            sha256=file_hash,
        )


def clamp_score(value: float, minimum: float = 0.0, maximum: float = 20.0) -> float:
    return round(max(minimum, min(maximum, value)), 1)
