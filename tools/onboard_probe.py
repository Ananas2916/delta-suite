"""
Prova del video onboard senza interfaccia: con AC in pista e l'app CSP caricata, chiede all'app
telecamere, qualità ed esposizioni diverse e salva un fotogramma per ciascuna prova.

    python tools/onboard_probe.py <cartella di uscita> [secondi per prova]

Stampa per ogni prova i fotogrammi al secondo ricevuti, gli FPS del gioco, il tempo di render
dichiarato dall'app e il suo stato (via usata: memoria o file; texture hdr/ldr; shader). Nella
cartella finiscono tone<curva>_<esposizione>.jpg, cam<N>_<nome>.jpg e q<N>.jpg da guardare.
Meglio farlo girare mentre si guida: gli FPS da fermi ai box dicono poco.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hub_core.onboard_feed import (  # noqa: E402
    CAMERAS, DEFAULT_EXPOSURE, DEFAULT_TONEMAP, QUALITIES, OnboardFeed,
)

TONE_NAMES = {0: "nessuna", 1: "gamma", 2: "filmica+gamma"}


def run(feed: OnboardFeed, seconds: float, enabled: bool = True, camera: int = 0, quality: int = 1,
        exposure: float = DEFAULT_EXPOSURE, tonemap: int = DEFAULT_TONEMAP):
    _name, w, h, fps = QUALITIES[quality]
    t0, got, last, game_fps = time.monotonic(), 0, None, []
    while time.monotonic() - t0 < seconds:
        feed.request(enabled, camera, -1, w, h, fps, exposure, tonemap)
        data = feed.new_frame()
        if data is not None:
            got += 1
            last = data
        inf = feed.info()
        if inf is not None and time.monotonic() - t0 > seconds / 3:   # FPS a regime
            game_fps.append(inf.game_fps)
        time.sleep(0.02)
    avg_fps = sum(game_fps) / len(game_fps) if game_fps else -1
    return got / seconds, last, feed.info(), avg_fps


def line(label: str, rate: float, inf, game_fps: float) -> str:
    return (f"{label:40s} {rate:5.1f} fps video  AC {game_fps:5.0f} FPS  render "
            f"{inf.render_ms if inf else -1:5.1f} ms  stato: {inf.status if inf else '-'}")


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "onboard_probe")
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
    out.mkdir(parents=True, exist_ok=True)
    feed = OnboardFeed()
    t0 = time.monotonic()
    while not feed.connect():
        if time.monotonic() - t0 > 20:
            sys.exit("Mapping DeltaSuite_Onboard_v2 assente: AC non in pista o app CSP non aggiornata/caricata")
        time.sleep(1)
    print(f"collegato (cartella per l'eventuale via su file: {feed.folder})")

    def save(name: str, data):
        if data is not None:
            (out / name).write_bytes(data)

    rate, _, inf, gfps = run(feed, seconds, enabled=False)
    print(line("video spento", rate, inf, gfps))

    for tonemap in (0, 1, 2):
        for exposure in (1.0, 1.6, 2.5):
            rate, data, inf, gfps = run(feed, seconds, camera=0, exposure=exposure, tonemap=tonemap)
            print(line(f"T-cam {TONE_NAMES[tonemap]} esp. {exposure}", rate, inf, gfps))
            save(f"tone{tonemap}_{exposure}.jpg", data)

    for cam, (key, name) in enumerate(CAMERAS):
        rate, data, inf, gfps = run(feed, seconds, camera=cam)
        print(line(f"telecamera {cam} {key}", rate, inf, gfps))
        save(f"cam{cam}_{key}.jpg", data)

    for q, (name, *_rest) in enumerate(QUALITIES):
        rate, data, inf, gfps = run(feed, seconds, quality=q)
        print(line(f"qualità {name}", rate, inf, gfps))
        save(f"q{q}.jpg", data)

    feed.disconnect()
    print(f"fatto: immagini in {out.resolve()}")


if __name__ == "__main__":
    main()
