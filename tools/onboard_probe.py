"""
Prova del video onboard senza interfaccia: con AC in pista e l'app CSP caricata, chiede ogni
telecamera e ogni qualità all'app e salva un fotogramma per ciascuna.

    python tools/onboard_probe.py <cartella di uscita> [secondi per prova]

Stampa per ogni prova i fotogrammi al secondo ricevuti, il tempo di render dichiarato dall'app e il
suo stato; nella cartella finiscono cam<N>_<nome>.jpg e q<N>.jpg da guardare.
"""

import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hub_core.onboard_feed import CAMERAS, QUALITIES, OnboardFeed  # noqa: E402


def run(feed: OnboardFeed, camera: int, w: int, h: int, fps: int, seconds: float):
    t0, got, last = time.monotonic(), 0, None
    while time.monotonic() - t0 < seconds:
        feed.request(True, camera, -1, w, h, fps)
        p = feed.new_frame()
        if p is not None:
            got += 1
            last = p
        time.sleep(0.02)
    return got / seconds, last, feed.info()


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "onboard_probe")
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
    out.mkdir(parents=True, exist_ok=True)
    feed = OnboardFeed()
    t0 = time.monotonic()
    while not feed.connect():
        if time.monotonic() - t0 > 20:
            sys.exit("Mapping DeltaSuite_Onboard_v1 assente: AC non in pista o app CSP non aggiornata/caricata")
        time.sleep(1)
    print(f"collegato, fotogrammi in {feed.folder}")

    _name, w, h, fps = QUALITIES[1]
    for cam, (key, name) in enumerate(CAMERAS):
        rate, last, inf = run(feed, cam, w, h, fps, seconds)
        print(f"telecamera {cam} {key:9s} {rate:5.1f} fps  render {inf.render_ms if inf else -1:6.1f} ms  "
              f"stato: {inf.status if inf else '-'}")
        if last is not None and last.is_file():
            shutil.copy(last, out / f"cam{cam}_{key}.jpg")

    for q, (name, w, h, fps) in enumerate(QUALITIES):
        rate, last, inf = run(feed, 0, w, h, fps, seconds)
        print(f"qualità {name:30s} {rate:5.1f} fps  render {inf.render_ms if inf else -1:6.1f} ms  "
              f"{inf.width if inf else 0}x{inf.height if inf else 0}  stato: {inf.status if inf else '-'}")
        if last is not None and last.is_file():
            shutil.copy(last, out / f"q{q}.jpg")

    feed.disconnect()
    print(f"fatto: immagini in {out.resolve()}")


if __name__ == "__main__":
    main()
