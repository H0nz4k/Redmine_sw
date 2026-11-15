"""Optional three-APA102-LED state output for ReSpeaker/HENK.

Disabled unless HENK_LED_SPI_DEVICE is explicitly configured after mapping
physical SPI0 MOSI/SCLK to a verified /dev/spidevX.Y. Never alters GPIO mux.
"""
import importlib.util
import os
from pathlib import Path
import sys

STATE_COLORS = {
    "off": ("off", 0),
    "idle": ("green", 3),
    "wake": ("green", 3),
    "listening": ("green", 3),
    "thinking": ("yellow", 4),
    "speaking": ("cyan", 3),
    "success": ("green", 5),
    "error": ("red", 5),
}


def load_driver():
    path = Path(__file__).resolve().parents[1] / "scripts/respeaker-leds.py"
    spec = importlib.util.spec_from_file_location("respeaker_leds", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StatusLeds:
    def __init__(self, device=None, *, writer=None, debug=False):
        self.device = device if device is not None else os.environ.get("HENK_LED_SPI_DEVICE")
        self.driver = None
        self.writer = writer
        self.debug = debug
        self.last = None

    def set(self, state):
        if state not in STATE_COLORS:
            raise ValueError("Neznámý LED stav")
        if not self.device or self.last == state:
            return
        name, brightness = STATE_COLORS[state]
        try:
            if self.writer is not None:
                self.writer(state, name, brightness)
            else:
                if self.driver is None:
                    self.driver = load_driver()
                color = self.driver.COLORS[name]
                self.driver.write(self.device, [color] * 3, brightness)
            self.last = state
        except (OSError, ValueError, ImportError) as exc:
            # An LED error must never break audio, conversation or approval.
            if self.debug:
                print("LED nedostupné:", type(exc).__name__, str(exc), file=sys.stderr)
            self.device = None

    def off(self):
        self.set("off")
