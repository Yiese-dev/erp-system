"""Render all PlantUML sources in report/diagrams/*.puml to PNG via the public PlantUML server.

Usage: python scripts/render_diagrams.py
"""
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIAGRAM_DIR = ROOT / "report" / "diagrams"
SERVER = "https://www.plantuml.com/plantuml/png/~h"


def render(source: Path) -> None:
    target = source.with_suffix(".png")
    text = source.read_text(encoding="utf-8")
    hex_payload = text.encode("utf-8").hex()
    url = SERVER + hex_payload
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    last_error: Exception | None = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = response.read()
            if not data.startswith(b"\x89PNG"):
                raise ValueError("Response was not a PNG image")
            target.write_bytes(data)
            print(f"rendered {source.name} -> {target.name} ({len(data)} bytes)")
            return
        except Exception as error:  # noqa: BLE001 - retry any transient network failure
            last_error = error
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Failed to render {source.name}: {last_error}")


if __name__ == "__main__":
    sources = sorted(DIAGRAM_DIR.glob("*.puml"))
    if not sources:
        sys.exit(f"No .puml files found in {DIAGRAM_DIR}")
    for source in sources:
        render(source)
    print(f"Rendered {len(sources)} diagram(s).")
