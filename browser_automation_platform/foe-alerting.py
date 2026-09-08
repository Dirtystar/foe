"""Start the FoE Alerting control panel by double-clicking this file.

Why this exists next to the .bat: Windows **Smart App Control** blocks `.bat`, `.cmd`, `.ps1`
and friends outright when they carry the mark of the web (anything arriving by download, chat
or mail), and its dialog offers no "run anyway". `.py` is not on that list — double-clicking it
runs the signed python.exe, which Smart App Control trusts — so this is the launcher that works
without anyone having to unblock a file first.

Everything else matches ``foe-alerting.bat``: no install step, since the alerter imports
nothing outside the standard library. See docs/FOE_ALERTING_SETUP.md.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

MIN_PYTHON = (3, 11)
HERE = Path(__file__).resolve().parent
MAP_DATA = Path("dataset/api_samples/map_data.volcano_archipelago.sample.json")


def _stop(message: str) -> int:
    """Say what is wrong and keep the window open — a double-clicked script that vanishes
    tells the person nothing."""
    print("\n  " + message.replace("\n", "\n  ") + "\n")
    try:
        input("Stiskni Enter pro zavření...")
    except (EOFError, KeyboardInterrupt):
        pass
    return 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if sys.version_info < MIN_PYTHON:
        return _stop(
            f"Potrebuju Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} nebo novejsi, "
            f"tenhle je {sys.version.split()[0]}.\n"
            "Stahni novejsi z https://www.python.org/downloads/")

    os.chdir(HERE)
    src = HERE / "src"
    if not (src / "bap" / "alerting").is_dir():
        return _stop(
            "Nenasel jsem slozku src\\bap\\alerting vedle tohohle souboru.\n"
            "Rozbal cely ZIP a spust tenhle soubor az z rozbalene slozky.")
    sys.path.insert(0, str(src))

    if MAP_DATA.is_file() and not any(a.startswith("--map-data") for a in argv):
        argv += ["--map-data", str(MAP_DATA)]   # gives the labels list its province dropdown

    print("\n  Spoustim FoE Alerting panel...")
    print("  Adresa nize obsahuje pristupovy klic - ber ji jako heslo.")
    print("  Zavrenim tohohle okna panel vypnes.\n")

    try:
        from bap.alerting.__main__ import main as alert_main
    except Exception as exc:                     # noqa: BLE001 - anything at all, explained
        return _stop(f"Aplikace se nepodarilo nacist: {exc}")

    try:
        return alert_main(["ui", *argv])
    except KeyboardInterrupt:
        return 0
    except SystemExit as exc:                    # argparse and friends
        return int(exc.code or 0)
    except Exception as exc:                     # noqa: BLE001
        return _stop(f"Panel spadl: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
