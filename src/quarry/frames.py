"""Choose which frames of a video to keep: settled moments, and no repeats of one picture.

Sampling on a fixed clock has two faults that showed up in a check of 153 articles written
from frames. The tick lands where it lands: on a counter or chart mid-animation, whose
half-drawn value is then read as the final one, or on a blurred transition. And a long clip
forces the spacing wide to stay under the frame cap, so brief on-screen states are missed
and the writer invents the steps in between, while a clip that holds one slide for ten
seconds spends five frames on it.

Lecture-capture tools segment on visual change and take a late frame from each stable
stretch. That works for slides and screen recordings, but measured on 24 stored reels it
does not transfer as is: most reels are hand-held footage in which every half second
differs from the last, so "a new state" fires constantly. ``select`` therefore keeps the
clock for coverage and uses change only where it is reliable:

1. Small grayscale thumbnails are scored against their predecessor. The frame is cut into a
   grid and the score is the largest change in any cell, so a caption line changing in one
   corner counts as much as a full cut.
2. The clip is cut into windows of ``interval`` seconds, and from each window the *most
   settled* thumbnail is taken (the lowest score, the later one on a tie): the moment the
   picture had stopped moving, not wherever the tick fell.
3. A pick is dropped when nothing changed since the previous pick (every score in between
   is below ``lo``): it is another photograph of the same picture.
4. If more than ``max_frames`` remain, the picks that differ least from their predecessor
   go first. Both kinds of drop are counted and reported.

So the frame cap now bites on distinct pictures, and a long static clip keeps its budget
for the parts that change.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field

SIZE = 48  # thumbnail edge in pixels
GRID = 6  # cells per edge
FPS = 2.0  # thumbnails per second
LO = 6.0  # largest cell change (mean absolute difference, 0-255) still counted as unchanged


@dataclass
class Selection:
    times: list[float] = field(default_factory=list)
    windows: int = 0  # time windows the clip was cut into
    unchanged: int = 0  # picks dropped because the picture had not changed
    over_cap: int = 0  # picks dropped to respect the frame cap
    settled: int = 0  # kept picks taken at a moment the picture was still

    def describe(self) -> str:
        parts = [f"{len(self.times)} frames from {self.windows} windows"]
        if self.times:
            parts.append(f"{self.settled} taken while the picture was still")
        if self.unchanged:
            parts.append(f"{self.unchanged} repeats of an unchanged picture left out")
        if self.over_cap:
            parts.append(
                f"frame cap reached: {self.over_cap} more left out, smallest changes first; "
                "brief on-screen states may be missing"
            )
        return "; ".join(parts)


def scores(thumbs: list[bytes], size: int = SIZE, grid: int = GRID) -> list[float]:
    """Change of each thumbnail against the previous one: the largest mean absolute
    difference in any grid cell. The first frame scores 0."""
    cell = size // grid
    out = [0.0]
    for prev, cur in zip(thumbs, thumbs[1:], strict=False):
        best = 0.0
        for gy in range(grid):
            for gx in range(grid):
                total = 0
                for y in range(gy * cell, (gy + 1) * cell):
                    row = y * size
                    a = prev[row + gx * cell : row + (gx + 1) * cell]
                    b = cur[row + gx * cell : row + (gx + 1) * cell]
                    total += sum(abs(p - q) for p, q in zip(a, b, strict=False))
                best = max(best, total / (cell * cell))
        out.append(best)
    return out


def select(
    change: list[float],
    *,
    fps: float = FPS,
    interval: float = 2.0,
    max_frames: int = 40,
    lo: float = LO,
) -> Selection:
    """Pick frame times from per-thumbnail change scores (see the module docstring)."""
    n = len(change)
    sel = Selection()
    if n == 0:
        return sel
    width = max(1, round(max(interval, 1 / fps) * fps))
    picks: list[int] = []
    for start in range(0, n, width):
        window = range(start, min(start + width, n))
        # the stillest moment; on a tie the later one (after any animation has finished)
        picks.append(min(window, key=lambda k: (change[k], -k)))
    sel.windows = len(picks)

    kept: list[tuple[int, float]] = []  # (index, how much changed since the previous kept pick)
    for k in picks:
        if not kept:
            kept.append((k, 255.0))  # the opening picture is always kept
            continue
        moved = max(change[kept[-1][0] + 1 : k + 1], default=0.0)
        if moved < lo:
            sel.unchanged += 1
            continue
        kept.append((k, moved))

    cap = max(max_frames, 0)
    if cap and len(kept) > cap:
        keep = sorted(sorted(kept, key=lambda p: p[1], reverse=True)[:cap])
        sel.over_cap = len(kept) - len(keep)
        kept = keep
    sel.settled = sum(1 for k, _ in kept if change[k] < lo)
    sel.times = [round(k / fps, 2) for k, _ in kept]
    return sel


def thumbnails(video: str, fps: float = FPS, size: int = SIZE) -> list[bytes]:  # pragma: no cover
    """Small grayscale frames of ``video``, ``fps`` per second, as raw bytes."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    done = subprocess.run(
        [ffmpeg, "-v", "error", "-nostdin", "-i", video, "-an",
         "-vf", f"fps={fps},scale={size}:{size},format=gray", "-f", "rawvideo", "-"],
        capture_output=True,
        check=True,
    )  # fmt: skip
    frame = size * size
    data = done.stdout
    return [data[i : i + frame] for i in range(0, len(data) - frame + 1, frame)]


def extract(
    video: str, times: list[float], dest_dir: str
) -> list[tuple[float, str]]:  # pragma: no cover
    """Write a 720-pixel-wide JPEG for each time. Returns ``(time, path)`` for those written."""
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    out = []
    for i, t in enumerate(times):
        path = os.path.join(dest_dir, f"frame_{i:03d}.jpg")
        subprocess.run(
            [ffmpeg, "-v", "error", "-nostdin", "-y", "-ss", f"{t:.2f}", "-i", video,
             "-frames:v", "1", "-vf", "scale=720:-2", path],
            capture_output=True,
        )  # fmt: skip
        if os.path.exists(path) and os.path.getsize(path) > 0:
            out.append((t, path))
    return out
