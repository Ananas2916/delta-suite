"""
Prova del video onboard senza interfaccia: con AC in pista e l'app CSP caricata, chiede all'app
curve di colore, trasporti, qualità e telecamere diverse e salva un fotogramma per ciascuna prova.

    python tools/onboard_probe.py <cartella di uscita> [secondi per prova] [trasporti]

Con "trasporti" come terzo argomento si provano solo condivisa/memoria/file per ogni qualità.

Stampa per ogni prova i fotogrammi al secondo ricevuti, gli FPS del gioco, il tempo di render
dichiarato dall'app, il peso del fotogramma e lo stato dell'app (via usata: condivisa, memoria o file;
texture yebis/hdr/ldr; shader). Le immagini finiscono nella cartella come PNG.
Meglio farlo girare mentre si guida: gli FPS da fermi ai box dicono poco.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hub_core.onboard_feed import (  # noqa: E402
    CAMERAS, DEFAULT_EXPOSURE, DEFAULT_TONEMAP, DEFAULT_TRANSPORT, QUALITIES, TONEMAP_FILMIC, TONEMAP_GAMMA,
    TONEMAP_YEBIS, TRANSPORT_FILE, TRANSPORT_MEMORY, TRANSPORT_SHARED, OnboardFeed,
)

TONE_NAMES = {0: "nessuna", 1: "gamma", 2: "filmica+gamma", 3: "yebis"}
TRANSPORT_NAMES = {TRANSPORT_FILE: "file", TRANSPORT_MEMORY: "memoria", TRANSPORT_SHARED: "condivisa"}


def run(feed: OnboardFeed, seconds: float, enabled: bool = True, camera: int = 0, quality: int = 1,
        exposure: float = DEFAULT_EXPOSURE, tonemap: int = DEFAULT_TONEMAP, transport: int = DEFAULT_TRANSPORT):
    _name, w, h, fps = QUALITIES[quality]
    t0, got, last, game_fps, sizes = time.monotonic(), 0, None, [], []
    while time.monotonic() - t0 < seconds:
        feed.request(enabled, camera, -1, w, h, fps, exposure, tonemap, transport)
        frame = feed.new_frame()
        if frame is not None:
            got += 1
            last = frame
            sizes.append(len(frame.data))
        inf = feed.info()
        if inf is not None and time.monotonic() - t0 > seconds / 3:   # FPS a regime
            game_fps.append(inf.game_fps)
        time.sleep(0.01)
    avg = lambda v: sum(v) / len(v) if v else -1  # noqa: E731
    return got / seconds, last, feed.info(), avg(game_fps), avg(sizes) / 1024


def line(label: str, rate: float, inf, game_fps: float, kb: float) -> str:
    return (f"{label:44s} {rate:5.1f} fps video  AC {game_fps:5.0f} FPS  render "
            f"{inf.render_ms if inf else -1:5.1f} ms  {kb:6.0f} KB  stato: {inf.status if inf else '-'}")


def save(out: Path, name: str, frame) -> None:
    if frame is None:
        return
    if frame.kind == "jpg":
        (out / f"{name}.jpg").write_bytes(frame.data)
        return
    from PyQt6.QtGui import QImage
    fmt = QImage.Format.Format_RGBX8888 if frame.kind == "rgba" else QImage.Format.Format_RGB32
    QImage(frame.data, frame.width, frame.height, frame.stride, fmt).save(str(out / f"{name}.png"))


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "onboard_probe")
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
    only_transports = len(sys.argv) > 3 and sys.argv[3] == "trasporti"
    out.mkdir(parents=True, exist_ok=True)
    feed = OnboardFeed()
    t0 = time.monotonic()
    while not feed.connect():
        if time.monotonic() - t0 > 20:
            sys.exit("Mapping DeltaSuite_Onboard_v4 assente: AC non in pista o app CSP non aggiornata/caricata")
        time.sleep(1)
    print(f"collegato (cartella per la via su file: {feed.folder})")

    rate, _, inf, gfps, kb = run(feed, seconds, enabled=False)
    print(line("video spento", rate, inf, gfps, kb))

    for tonemap, exposure in () if only_transports else ((TONEMAP_FILMIC, 1.6), (TONEMAP_FILMIC, 1.3), (TONEMAP_GAMMA, 1.6),
                              (TONEMAP_YEBIS, 1.0), (TONEMAP_YEBIS, 1.6)):
        rate, frame, inf, gfps, kb = run(feed, seconds, exposure=exposure, tonemap=tonemap)
        print(line(f"T-cam {TONE_NAMES[tonemap]} esp. {exposure}", rate, inf, gfps, kb))
        save(out, f"tone{tonemap}_{exposure}", frame)

    for q, (name, *_rest) in enumerate(QUALITIES):
        for transport in (TRANSPORT_SHARED, TRANSPORT_MEMORY, TRANSPORT_FILE):
            rate, frame, inf, gfps, kb = run(feed, seconds, quality=q, transport=transport)
            print(line(f"{name} {TRANSPORT_NAMES[transport]}", rate, inf, gfps, kb))
            save(out, f"q{q}_{TRANSPORT_NAMES[transport]}", frame)
            if transport == TRANSPORT_SHARED and feed.shared_error:
                print(f"  texture condivisa non usabile: {feed.shared_error}")
            elif transport == TRANSPORT_SHARED and feed._shared is not None:
                print(f"  texture condivisa aperta sulla GPU {feed._shared.adapter_index}")

    for cam, (key, _name) in enumerate([] if only_transports else CAMERAS):
        rate, frame, inf, gfps, kb = run(feed, seconds, camera=cam)
        print(line(f"telecamera {cam} {key}", rate, inf, gfps, kb))
        save(out, f"cam{cam}_{key}", frame)

    feed.disconnect()
    print(f"fatto: immagini in {out.resolve()}")


if __name__ == "__main__":
    main()
