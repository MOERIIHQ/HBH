"""
HBH CLI entry point.

Usage:
    python -m hbh init
    python -m hbh status
    python -m hbh policy show
"""

from hbh.cli.main import run

if __name__ == "__main__":
    import sys
    sys.exit(run())
