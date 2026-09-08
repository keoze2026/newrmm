"""Changed-region streaming (specification section 10)."""
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw  # noqa: E402

from rmm_agent.tiles import KEYFRAME, TILE_FRAME, TileEncoder  # noqa: E402

SIZE = (640, 480)


def desktop(seed: int = 0) -> Image.Image:
    """A picture with enough variety to behave like a real screen."""
    image = Image.new("RGB", SIZE, (30, 40, 60))
    draw = ImageDraw.Draw(image)
    for i in range(0, SIZE[0], 40):
        draw.line((i, 0, i, SIZE[1]), fill=(60 + (i + seed) % 120, 90, 140))
    draw.rectangle((50, 50, 300, 200), fill=(200, 210, 220))
    return image


def header(payload: bytes) -> tuple[int, int, int]:
    kind, width, height = struct.unpack_from("<BHH", payload, 0)
    return kind, width, height


def test_the_first_frame_is_a_keyframe():
    encoder = TileEncoder()
    payload = encoder.encode(desktop(), 60)
    kind, width, height = header(payload)
    assert kind == KEYFRAME
    assert (width, height) == SIZE


def test_an_unchanged_screen_costs_almost_nothing():
    """The whole point: a still desktop must not be re-sent every frame."""
    encoder = TileEncoder()
    image = desktop()
    keyframe = encoder.encode(image, 60)

    second = encoder.encode(image, 60)
    kind, _, _ = header(second)
    assert kind == TILE_FRAME
    count = struct.unpack_from("<H", second, 5)[0]
    assert count == 0, "a still screen reported changed tiles"
    assert len(second) == 7, f"an empty update should be 7 bytes, got {len(second)}"
    assert len(second) < len(keyframe) / 100


def test_a_small_change_sends_only_that_region():
    encoder = TileEncoder()
    image = desktop()
    keyframe = encoder.encode(image, 60)

    changed = image.copy()
    ImageDraw.Draw(changed).rectangle((10, 10, 60, 60), fill=(255, 0, 0))
    update = encoder.encode(changed, 60)

    kind, _, _ = header(update)
    assert kind == TILE_FRAME
    count = struct.unpack_from("<H", update, 5)[0]
    assert 1 <= count <= 4, f"a 50x50 change touched {count} tiles"
    assert len(update) < len(keyframe) / 3, (
        f"update {len(update)} bytes against a {len(keyframe)} byte keyframe"
    )


def test_the_changed_tile_covers_the_change():
    encoder = TileEncoder()
    image = desktop()
    encoder.encode(image, 60)

    changed = image.copy()
    ImageDraw.Draw(changed).rectangle((300, 300, 340, 340), fill=(255, 255, 0))
    update = encoder.encode(changed, 60)

    count = struct.unpack_from("<H", update, 5)[0]
    assert count >= 1
    x, y, w, h = struct.unpack_from("<HHHH", update, 7)
    assert x <= 300 and y <= 300
    assert x + w >= 340 and y + h >= 340


def test_a_wholly_different_screen_falls_back_to_a_keyframe():
    """Past a point, many small JPEGs cost more than one big one."""
    encoder = TileEncoder()
    encoder.encode(desktop(), 60)

    other = Image.new("RGB", SIZE, (250, 250, 250))
    payload = encoder.encode(other, 60)
    kind, _, _ = header(payload)
    assert kind == KEYFRAME


def test_a_resized_screen_forces_a_keyframe():
    encoder = TileEncoder()
    encoder.encode(desktop(), 60)
    payload = encoder.encode(desktop().resize((800, 600)), 60)
    kind, width, height = header(payload)
    assert kind == KEYFRAME
    assert (width, height) == (800, 600)


def test_requesting_a_keyframe_produces_one():
    """An operator attaching mid-stream has no picture to patch."""
    encoder = TileEncoder()
    image = desktop()
    encoder.encode(image, 60)
    assert header(encoder.encode(image, 60))[0] == TILE_FRAME

    encoder.request_keyframe()
    assert header(encoder.encode(image, 60))[0] == KEYFRAME


def test_bandwidth_saving_is_reported_and_real():
    encoder = TileEncoder()
    image = desktop()
    encoder.encode(image, 60)
    for _ in range(30):
        encoder.encode(image, 60)

    assert encoder.saving > 0.9, f"only {encoder.saving:.0%} saved on a still screen"
    assert encoder.frames_sent == 31
    assert encoder.keyframes_sent == 1
