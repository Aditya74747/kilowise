"""GreenLedger: make cost, energy and CO2 of an SME's digital estate visible, and cut it safely."""

__version__ = "0.1.0"


def main() -> None:  # entry point: `uv run greenledger ...`
    from .cli import main as _main

    _main()
