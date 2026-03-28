from __future__ import annotations

import argparse
import io
import random
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from PIL import Image
from PIL import ImageDraw
from PIL import ImageEnhance
from PIL import ImageFilter
from PIL import ImageOps

from app.config import get_settings
from app.database import init_db
from app.image_utils import analyze_image
from app.repositories import get_repository
from app.services.contest import create_guest
from app.services.contest import get_event
from app.storage import get_storage


TAG_PREFIX = "LOAD_TEST:"
TABLE_NAMES = {
    ("groom", "friend"): ["A卓", "B卓", "C卓", "D卓"],
    ("bride", "friend"): ["E卓", "F卓", "G卓", "H卓"],
    ("groom", "family"): ["新郎親族卓"],
    ("bride", "family"): ["新婦親族卓"],
}
GROUP_LABELS = {
    ("groom", "friend"): "新郎友人",
    ("bride", "friend"): "新婦友人",
    ("groom", "family"): "新郎親族",
    ("bride", "family"): "新婦親族",
}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


@dataclass(slots=True)
class Runtime:
    repository: object
    storage: object


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return

    runtime = init_runtime()
    if args.command == "seed":
        seed_dataset(
            runtime,
            tag=args.tag,
            count=args.count,
            source_dir=Path(args.source_dir).expanduser() if args.source_dir else None,
            seed=args.seed,
        )
        return
    if args.command == "status":
        print_status(runtime, tag=args.tag)
        return
    if args.command == "cleanup":
        cleanup_dataset(runtime, tag=args.tag, assume_yes=args.yes)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create or clean up tagged load-test guests and submissions.",
    )
    subparsers = parser.add_subparsers(dest="command")

    seed_parser = subparsers.add_parser("seed", help="Create tagged guests and submissions.")
    seed_parser.add_argument("--tag", required=True, help="Tag used to identify the dataset.")
    seed_parser.add_argument("--count", type=int, default=70, help="Number of guests/submissions.")
    seed_parser.add_argument(
        "--source-dir",
        help="Optional directory of real images to reuse for more realistic Gemini tests.",
    )
    seed_parser.add_argument("--seed", type=int, default=20260419, help="Random seed.")

    status_parser = subparsers.add_parser("status", help="Show counts for a tagged dataset.")
    status_parser.add_argument("--tag", required=True, help="Tag used to identify the dataset.")

    cleanup_parser = subparsers.add_parser("cleanup", help="Delete a tagged dataset.")
    cleanup_parser.add_argument("--tag", required=True, help="Tag used to identify the dataset.")
    cleanup_parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    return parser


def init_runtime() -> Runtime:
    settings = get_settings()
    storage = get_storage()
    storage.ensure_ready()
    if settings.data_backend.lower() == "sqlite":
        init_db()
    repository = get_repository()
    get_event(repository, settings)
    runtime = Runtime(repository=repository, storage=storage)
    preflight_runtime(runtime)
    return runtime


def preflight_runtime(runtime: Runtime) -> None:
    print("Preflight: checking backend connectivity...", flush=True)

    if hasattr(runtime.repository, "events"):
        try:
            runtime.repository.events.document("primary").get(timeout=10)
            print("Preflight: Firestore reachable.", flush=True)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(
                "Firestore preflight failed. "
                "Run `gcloud auth application-default login` and "
                "`gcloud auth application-default set-quota-project \"$PROJECT_ID\"`, then retry. "
                f"Details: {exc}",
            ) from exc

    if hasattr(runtime.storage, "bucket"):
        try:
            runtime.storage.bucket.reload(timeout=10)
            print("Preflight: GCS bucket reachable.", flush=True)
        except Exception as exc:  # noqa: BLE001
            raise SystemExit(
                "GCS preflight failed. "
                "Check ADC auth and bucket access, then retry. "
                f"Details: {exc}",
            ) from exc


def dataset_marker(tag: str) -> str:
    return f"{TAG_PREFIX}{tag}"


def is_load_test_guest(guest) -> bool:
    return bool(guest is not None and guest.notes and TAG_PREFIX in guest.notes)


def tagged_guests(repository, tag: str) -> list:
    marker = dataset_marker(tag)
    return [guest for guest in repository.list_guests() if guest.notes and marker in guest.notes]


def non_test_submissions(repository) -> list:
    guests = {guest.id: guest for guest in repository.list_guests()}
    submissions = repository.list_submissions()
    return [
        submission
        for submission in submissions
        if not is_load_test_guest(guests.get(submission.guest_id) or submission.guest)
    ]


def seed_dataset(runtime: Runtime, *, tag: str, count: int, source_dir: Path | None, seed: int) -> None:
    foreign_submissions = non_test_submissions(runtime.repository)
    if foreign_submissions:
        examples = ", ".join(
            f"{submission.guest_name_snapshot}({submission.id})"
            for submission in foreign_submissions[:5]
        )
        raise SystemExit(
            "Non-test submissions already exist. "
            "Load-test seeding is blocked to avoid mixing rehearsal data with real submissions. "
            f"Found {len(foreign_submissions)} non-test submission(s): {examples}",
        )
    existing = tagged_guests(runtime.repository, tag)
    if existing:
        raise SystemExit(
            f"Dataset '{tag}' already exists with {len(existing)} guests. "
            f"Run cleanup first: uv run python scripts/load_test_dataset.py cleanup --tag {tag}",
        )

    image_factory = ImageFactory(source_dir=source_dir, seed=seed, tag=tag)
    created = 0
    eligible_count = 0
    ineligible_count = 0
    combos = [
        ("groom", "friend"),
        ("bride", "friend"),
        ("groom", "family"),
        ("bride", "family"),
    ]

    for index in range(count):
        side, group_type = combos[index % len(combos)]
        label = GROUP_LABELS[(side, group_type)]
        table_names = TABLE_NAMES[(side, group_type)]
        eligible = (index % 9) != 0
        guest = create_guest(
            runtime.repository,
            name=f"{label} テスト{index + 1:03d}",
            display_name=f"{label}{index + 1:03d}",
            side=side,
            table_name=table_names[(index // len(combos)) % len(table_names)],
            group_type=group_type,
            eligible=eligible,
            notes=f"{dataset_marker(tag)} index={index + 1}",
        )
        image_bytes, mime_type, original_filename = image_factory.render(index)
        store_submission(
            runtime,
            guest_id=guest.id,
            guest_label=guest.label,
            invite_token=guest.invite_token,
            image_bytes=image_bytes,
            mime_type=mime_type,
            original_filename=original_filename,
        )
        created += 1
        if eligible:
            eligible_count += 1
        else:
            ineligible_count += 1

    print(
        f"Created {created} guests/submissions for tag '{tag}'. "
        f"Eligible={eligible_count}, ineligible={ineligible_count}.",
    )
    print("Recommended next step:")
    print("  1. Open /admin and run Gemini judging once.")
    print("  2. If you want recovery testing, close/reload mid-run and resume without force.")
    print(f"  3. Cleanup later with: uv run python scripts/load_test_dataset.py cleanup --tag {tag} --yes")


def print_status(runtime: Runtime, *, tag: str) -> None:
    guests = tagged_guests(runtime.repository, tag)
    guest_ids = {guest.id for guest in guests}
    submissions = [item for item in runtime.repository.list_submissions() if item.guest_id in guest_ids]
    judged = sum(1 for item in submissions if item.judging_state == "judged" and item.score is not None)
    failed = sum(1 for item in submissions if item.judging_state == "failed")
    pending = sum(1 for item in submissions if item.judging_state == "pending")
    print(
        f"Tag '{tag}': guests={len(guests)}, submissions={len(submissions)}, "
        f"judged={judged}, failed={failed}, pending={pending}",
    )


def cleanup_dataset(runtime: Runtime, *, tag: str, assume_yes: bool) -> None:
    guests = tagged_guests(runtime.repository, tag)
    if not guests:
        print(f"No dataset found for tag '{tag}'.")
        return
    if not assume_yes:
        answer = input(f"Delete {len(guests)} guests/submissions for tag '{tag}'? [y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Cancelled.")
            return

    for guest in guests:
        if guest.submission is not None:
            runtime.storage.delete_image(guest.submission.storage_key)
        runtime.repository.delete_guest(guest.id)
    print(f"Deleted {len(guests)} guests/submissions for tag '{tag}'.")


def store_submission(
    runtime: Runtime,
    *,
    guest_id: str,
    guest_label: str,
    invite_token: str,
    image_bytes: bytes,
    mime_type: str,
    original_filename: str,
) -> None:
    metrics = analyze_image(image_bytes)
    storage_key = f"submissions/{invite_token}/{metrics.sha256[:20]}.jpg"
    runtime.storage.save_image(key=storage_key, data=image_bytes, content_type=mime_type)
    runtime.repository.upsert_submission(
        guest_id=guest_id,
        guest_name_snapshot=guest_label,
        caption=None,
        storage_key=storage_key,
        original_filename=original_filename,
        mime_type=mime_type,
        sha256=metrics.sha256,
        width=metrics.width,
        height=metrics.height,
        file_size_bytes=len(image_bytes),
    )


class ImageFactory:
    def __init__(self, *, source_dir: Path | None, seed: int, tag: str) -> None:
        self.random = random.Random(seed)
        self.tag = tag
        self.source_images = self._load_source_images(source_dir)

    def _load_source_images(self, source_dir: Path | None) -> list[Path]:
        if source_dir is None:
            return []
        if not source_dir.exists():
            raise SystemExit(f"Source dir not found: {source_dir}")
        files = sorted(path for path in source_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
        if not files:
            raise SystemExit(f"No images found in {source_dir}")
        return files

    def render(self, index: int) -> tuple[bytes, str, str]:
        if self.source_images:
            return self._render_from_source(index)
        return self._render_synthetic(index)

    def _render_from_source(self, index: int) -> tuple[bytes, str, str]:
        source_path = self.source_images[index % len(self.source_images)]
        variant_seed = self.random.randint(0, 10_000_000)
        variant_random = random.Random(variant_seed + index)
        with Image.open(source_path) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
        target_size = self._target_size(index)
        image = ImageOps.fit(image, target_size, method=Image.Resampling.LANCZOS)
        if variant_random.random() < 0.35:
            image = ImageOps.mirror(image)
        image = image.rotate(variant_random.uniform(-2.5, 2.5), resample=Image.Resampling.BICUBIC)
        image = ImageOps.fit(image, target_size, method=Image.Resampling.LANCZOS)
        image = ImageEnhance.Brightness(image).enhance(variant_random.uniform(0.92, 1.08))
        image = ImageEnhance.Color(image).enhance(variant_random.uniform(0.9, 1.12))
        image = ImageEnhance.Contrast(image).enhance(variant_random.uniform(0.94, 1.1))
        draw = ImageDraw.Draw(image, "RGBA")
        self._draw_badge(draw, image.size, index)
        return self._encode_jpeg(image), "image/jpeg", f"load-test-{index + 1:03d}.jpg"

    def _render_synthetic(self, index: int) -> tuple[bytes, str, str]:
        variant_random = random.Random(self.random.randint(0, 10_000_000) + index)
        size = self._target_size(index)
        image = Image.new("RGB", size, color=(250, 243, 233))
        draw = ImageDraw.Draw(image, "RGBA")

        top = self._color_triplet(variant_random)
        bottom = self._color_triplet(variant_random, base=160)
        for y in range(size[1]):
            blend = y / max(1, size[1] - 1)
            color = tuple(int(top[i] * (1 - blend) + bottom[i] * blend) for i in range(3))
            draw.line((0, y, size[0], y), fill=color)

        for _ in range(18):
            radius = variant_random.randint(18, 90)
            x = variant_random.randint(-40, size[0] + 40)
            y = variant_random.randint(-20, size[1] // 2)
            fill = (*self._color_triplet(variant_random, base=200), variant_random.randint(28, 72))
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)

        horizon = int(size[1] * variant_random.uniform(0.58, 0.72))
        draw.rectangle((0, horizon, size[0], size[1]), fill=(70, 60, 55, 180))

        subject_y = horizon - variant_random.randint(40, 80)
        left_x = int(size[0] * variant_random.uniform(0.34, 0.44))
        right_x = int(size[0] * variant_random.uniform(0.56, 0.66))
        self._draw_person(draw, left_x, subject_y, size, variant_random, attire="light")
        self._draw_person(draw, right_x, subject_y, size, variant_random, attire="dark")

        for _ in range(24):
            confetti_x = variant_random.randint(0, size[0])
            confetti_y = variant_random.randint(0, int(size[1] * 0.78))
            confetti_w = variant_random.randint(6, 20)
            confetti_h = variant_random.randint(3, 10)
            draw.rounded_rectangle(
                (
                    confetti_x,
                    confetti_y,
                    confetti_x + confetti_w,
                    confetti_y + confetti_h,
                ),
                radius=2,
                fill=(*self._color_triplet(variant_random), 210),
            )

        image = image.filter(ImageFilter.GaussianBlur(radius=variant_random.uniform(0.0, 0.4)))
        draw = ImageDraw.Draw(image, "RGBA")
        self._draw_badge(draw, image.size, index)
        return self._encode_jpeg(image), "image/jpeg", f"load-test-{index + 1:03d}.jpg"

    def _target_size(self, index: int) -> tuple[int, int]:
        modes = [(1600, 1200), (1200, 1600), (1400, 1400)]
        return modes[index % len(modes)]

    def _draw_person(self, draw: ImageDraw.ImageDraw, x: int, y: int, size: tuple[int, int], rng: random.Random, *, attire: str) -> None:
        body_height = int(size[1] * rng.uniform(0.18, 0.24))
        body_width = int(size[0] * rng.uniform(0.09, 0.12))
        head_radius = int(body_width * 0.22)
        suit = (245, 240, 235, 255) if attire == "light" else (60, 55, 78, 255)
        accent = (210, 185, 150, 255) if attire == "light" else (120, 120, 160, 255)
        draw.rounded_rectangle(
            (x - body_width // 2, y - body_height, x + body_width // 2, y),
            radius=body_width // 6,
            fill=suit,
        )
        draw.ellipse((x - head_radius, y - body_height - head_radius * 2, x + head_radius, y - body_height), fill=(243, 214, 190, 255))
        draw.rectangle((x - 6, y - body_height + 20, x + 6, y - 8), fill=accent)
        bouquet_y = y - int(body_height * 0.45)
        draw.ellipse((x - 22, bouquet_y - 16, x + 22, bouquet_y + 16), fill=(232, 168, 182, 220))

    def _draw_badge(self, draw: ImageDraw.ImageDraw, size: tuple[int, int], index: int) -> None:
        text = f"{self.tag}-{index + 1:03d}"
        x0 = 18
        y0 = size[1] - 52
        draw.rounded_rectangle((x0, y0, x0 + 180, y0 + 30), radius=10, fill=(24, 24, 24, 150))
        draw.text((x0 + 10, y0 + 7), text, fill=(255, 255, 255, 220))

    def _encode_jpeg(self, image: Image.Image) -> bytes:
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=90, optimize=True)
        return buffer.getvalue()

    def _color_triplet(self, rng: random.Random, *, base: int | None = None) -> tuple[int, int, int]:
        if base is None:
            return (
                rng.randint(80, 245),
                rng.randint(80, 245),
                rng.randint(80, 245),
            )
        return (
            rng.randint(base - 40, min(255, base + 40)),
            rng.randint(base - 40, min(255, base + 40)),
            rng.randint(base - 40, min(255, base + 40)),
        )


if __name__ == "__main__":
    main()
