"""
Headless onboard video test: with AC on track and the CSP app loaded, asks the app for different
colour curves, transports, qualities and cameras and saves one frame per test.

    python tools/onboard_probe.py <output folder> [seconds per test] [transports|views]

With "transports" as the third argument only shared/memory/file are tested for each quality, with
"views" only 1-4 onboards at once (AC FPS with more views).

For each test it prints the frames per second received, the game FPS, the render time reported
by the app, the frame size and the app status (path used: shared, memory or file;
yebis/hdr/ldr texture; shader). The images end up in the folder as PNG.
Best run while driving: FPS while parked in the pits say little.
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hub_core.ac.onboard_feed import (  # noqa: E402
    CAMERAS, DEFAULT_EXPOSURE, DEFAULT_TONEMAP, DEFAULT_TRANSPORT, QUALITIES, TONEMAP_FILMIC, TONEMAP_GAMMA,
    SECONDARY_QUALITY, TONEMAP_YEBIS, TRANSPORT_FILE, TRANSPORT_MEMORY, TRANSPORT_SHARED, VIEWS, OnboardFeed,
    ViewRequest, onboard_dir,
)

TONE_NAMES = {0: "none", 1: "gamma", 2: "filmic+gamma", 3: "yebis"}
TRANSPORT_NAMES = {TRANSPORT_FILE: "file", TRANSPORT_MEMORY: "memory", TRANSPORT_SHARED: "shared"}


def run(feed: OnboardFeed, seconds: float, enabled: bool = True, camera: int = 0, quality: int = 1,
        exposure: float = DEFAULT_EXPOSURE, tonemap: int = DEFAULT_TONEMAP, transport: int = DEFAULT_TRANSPORT,
        views: int = 1):
    _name, w, h, fps = QUALITIES[quality]
    _s, sw, sh, sfps = SECONDARY_QUALITY if views == 2 else QUALITIES[0]
    requests = [ViewRequest(enabled, camera, -1, w, h, fps)] + \
        [ViewRequest(enabled and k < views, [7, 3, 2][k - 1], -1, sw, sh, sfps) for k in range(1, VIEWS)]
    t0, got, last, game_fps, sizes = time.monotonic(), 0, None, [], []
    while time.monotonic() - t0 < seconds:
        feed.request(requests, exposure, tonemap, transport)
        frame = feed.new_frame()
        for k in range(1, views):
            feed.new_frame(k)
        if frame is not None:
            got += 1
            last = frame
            sizes.append(len(frame.data))
        inf = feed.info()
        if inf is not None and time.monotonic() - t0 > seconds / 3:   # steady-state FPS
            game_fps.append(inf.game_fps)
        time.sleep(0.01)
    avg = lambda v: sum(v) / len(v) if v else -1  # noqa: E731
    return got / seconds, last, feed.info(), avg(game_fps), avg(sizes) / 1024


def line(label: str, rate: float, inf, game_fps: float, kb: float) -> str:
    return (f"{label:44s} {rate:5.1f} fps video  AC {game_fps:5.0f} FPS  render "
            f"{inf.render_ms if inf else -1:5.1f} ms  {kb:6.0f} KB  status: {inf.status if inf else '-'}")


def save(out: Path, name: str, frame) -> None:
    if frame is None:
        return
    if frame.kind == "jpg":
        (out / f"{name}.jpg").write_bytes(frame.data)
        return
    try:
        from PyQt6.QtGui import QImage
    except ImportError:         # system python without the venv: no PNG, the measurements remain
        return
    fmt = QImage.Format.Format_RGBX8888 if frame.kind == "rgba" else QImage.Format.Format_RGB32
    QImage(frame.data, frame.width, frame.height, frame.stride, fmt).save(str(out / f"{name}.png"))


def main():
    # cmd expands %LOCALAPPDATA% but PowerShell does not: expand it here, otherwise it lands in the project
    out = Path(os.path.expandvars(sys.argv[1])) if len(sys.argv) > 1 else onboard_dir().parent / "onboard_probe"
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
    only = sys.argv[3] if len(sys.argv) > 3 else ""
    only_transports = only in ("transports", "views")
    out.mkdir(parents=True, exist_ok=True)
    feed = OnboardFeed()
    t0 = time.monotonic()
    while not feed.connect():
        if time.monotonic() - t0 > 20:
            sys.exit("DeltaSuite_Onboard_v6 mapping missing: AC not on track or CSP app not updated/loaded")
        time.sleep(1)
    print(f"connected (folder for the file path: {feed.folder})")

    rate, _, inf, gfps, kb = run(feed, seconds, enabled=False)
    print(line("video off", rate, inf, gfps, kb))

    for tonemap, exposure in () if only_transports else ((TONEMAP_FILMIC, 1.6), (TONEMAP_FILMIC, 1.3), (TONEMAP_GAMMA, 1.6),
                              (TONEMAP_YEBIS, 1.0), (TONEMAP_YEBIS, 1.6)):
        rate, frame, inf, gfps, kb = run(feed, seconds, exposure=exposure, tonemap=tonemap)
        print(line(f"T-cam {TONE_NAMES[tonemap]} exp. {exposure}", rate, inf, gfps, kb))
        save(out, f"tone{tonemap}_{exposure}", frame)

    for n in range(1, VIEWS + 1) if only != "transports" else ():
        rate, frame, inf, gfps, kb = run(feed, seconds, views=n)
        print(line(f"{n} {'view' if n == 1 else 'views'} at once", rate, inf, gfps, kb))
    if only == "views":
        feed.disconnect()
        return

    for q, (name, *_rest) in enumerate(QUALITIES):
        for transport in (TRANSPORT_SHARED, TRANSPORT_MEMORY, TRANSPORT_FILE):
            rate, frame, inf, gfps, kb = run(feed, seconds, quality=q, transport=transport)
            print(line(f"{name} {TRANSPORT_NAMES[transport]}", rate, inf, gfps, kb))
            if transport == TRANSPORT_SHARED and feed.shared_error:
                print(f"  shared texture unusable: {feed.shared_error}")
            elif transport == TRANSPORT_SHARED and feed._shared[0] is not None:
                print(f"  shared texture opened on GPU {feed._shared[0].adapter_index}")
            save(out, f"q{q}_{TRANSPORT_NAMES[transport]}", frame)

    f6 = feed.f6_cameras()      # the app counts them every 2 s, even with the video off
    names = [key for key, _name in CAMERAS] + [f"f6 {name}" for name in f6]
    print(f"F6 cameras found on the car: {', '.join(f6) or 'none'}")
    for cam, key in enumerate([] if only_transports else names):
        rate, frame, inf, gfps, kb = run(feed, seconds, camera=cam)
        print(line(f"camera {cam} {key}", rate, inf, gfps, kb))
        save(out, f"cam{cam}_{key}", frame)

    feed.disconnect()
    print(f"done: images in {out.resolve()}")


if __name__ == "__main__":
    main()
