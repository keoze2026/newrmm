"""Changed-region streaming.

Specification section 10, the mitigation for low-bandwidth performance:
"Changed-region streaming, adaptive quality/frame-rate."

Most of a desktop is still most of the time. Sending the whole screen every
frame spends bandwidth re-transmitting a wallpaper that has not moved; sending
only the tiles that changed is what makes the stream usable on a constrained
link, which section 8 requires at about 1 Mbps.

Wire format, little-endian, matching `console/src/lib/frames.ts`:

    keyframe   0x00 | width u16 | height u16 | jpeg bytes
    tile frame 0x01 | width u16 | height u16 | count u16 |
                     count x ( x u16 | y u16 | w u16 | h u16 | len u32 | jpeg )

A keyframe is sent when the stream starts, when an operator attaches, when too
much of the screen changed for tiles to be worth it, and periodically so a
viewer that missed an update cannot stay wrong for long.
"""
import io
import struct
import time

from PIL import Image

TILE = 128

KEYFRAME = 0x00
TILE_FRAME = 0x01

# Past this share of the screen, whole-frame JPEG beats many small ones: each
# tile carries its own JPEG header and loses the compressor's wider context.
FULL_FRAME_RATIO = 0.55

# A viewer that missed a tile would stay wrong until that region changed again.
KEYFRAME_INTERVAL = 10.0


class TileEncoder:
    """Turns successive frames into keyframes and tile updates."""

    def __init__(self, tile: int = TILE) -> None:
        self.tile = tile
        self._previous: bytes | None = None
        self._size: tuple[int, int] = (0, 0)
        self._last_keyframe = 0.0
        self._force_keyframe = True

        # Counters, reported to the operator as a bandwidth saving. The
        # comparison uses the size of the most recent whole frame rather than
        # re-encoding one per frame, which would cost exactly the work this
        # class exists to avoid.
        self.frames_sent = 0
        self.keyframes_sent = 0
        self.bytes_sent = 0
        self.bytes_if_full = 0
        self._reference_full_bytes = 0

    def request_keyframe(self) -> None:
        """Called when an operator attaches, or asks for a fresh frame."""
        self._force_keyframe = True

    def _changed_tiles(self, current: bytes, width: int, height: int) -> list[tuple[int, int, int, int]]:
        """Which tiles differ from the previous frame."""
        previous = self._previous
        if previous is None or len(previous) != len(current):
            return []

        stride = width * 3
        changed = []
        for top in range(0, height, self.tile):
            bottom = min(top + self.tile, height)
            for left in range(0, width, self.tile):
                right = min(left + self.tile, width)
                start_column = left * 3
                end_column = right * 3

                for row in range(top, bottom):
                    offset = row * stride
                    a = offset + start_column
                    b = offset + end_column
                    # One memcmp per row of the tile: the comparison stops at
                    # the first row that differs, which is the common case.
                    if current[a:b] != previous[a:b]:
                        changed.append((left, top, right - left, bottom - top))
                        break
        return changed

    def encode(self, image: Image.Image, quality: int) -> bytes:
        """Encode one frame, as a keyframe or as the tiles that changed."""
        width, height = image.size
        raw = image.tobytes()
        now = time.monotonic()

        size_changed = (width, height) != self._size
        stale = now - self._last_keyframe >= KEYFRAME_INTERVAL
        must_key = self._force_keyframe or size_changed or stale or self._previous is None

        tiles: list[tuple[int, int, int, int]] = []
        if not must_key:
            tiles = self._changed_tiles(raw, width, height)
            total = ((width + self.tile - 1) // self.tile) * ((height + self.tile - 1) // self.tile)
            if total and len(tiles) / total > FULL_FRAME_RATIO:
                must_key = True

        if must_key:
            payload = self._encode_keyframe(image, quality)
            self._last_keyframe = now
            self._force_keyframe = False
            self.keyframes_sent += 1
        elif not tiles:
            # Nothing moved. Say so cheaply rather than resending the screen.
            payload = struct.pack("<BHHH", TILE_FRAME, width, height, 0)
        else:
            payload = self._encode_tiles(image, tiles, quality)

        self._previous = raw
        self._size = (width, height)
        self.frames_sent += 1
        self.bytes_sent += len(payload)
        self.bytes_if_full += self._reference_full_bytes
        return payload

    def _encode_keyframe(self, image: Image.Image, quality: int) -> bytes:
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        jpeg = buffer.getvalue()
        # What a whole frame costs right now, used as the comparison for every
        # frame until the next keyframe refreshes it.
        self._reference_full_bytes = len(jpeg)
        return struct.pack("<BHH", KEYFRAME, *image.size) + jpeg

    def _encode_tiles(
        self, image: Image.Image, tiles: list[tuple[int, int, int, int]], quality: int
    ) -> bytes:
        width, height = image.size
        parts = [struct.pack("<BHHH", TILE_FRAME, width, height, len(tiles))]
        for left, top, tile_width, tile_height in tiles:
            region = image.crop((left, top, left + tile_width, top + tile_height))
            buffer = io.BytesIO()
            region.save(buffer, format="JPEG", quality=quality)
            jpeg = buffer.getvalue()
            parts.append(struct.pack("<HHHHI", left, top, tile_width, tile_height, len(jpeg)))
            parts.append(jpeg)
        return b"".join(parts)

    @property
    def saving(self) -> float:
        """Share of bandwidth saved against sending every frame whole."""
        if self.bytes_if_full <= 0:
            return 0.0
        return max(0.0, 1.0 - self.bytes_sent / self.bytes_if_full)
