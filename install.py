"""Proof Kit installer. Run it from your project's root folder:

    python path/to/proof-kit/install.py --dry-run   # preview: shows the checks it found, changes nothing
    python path/to/proof-kit/install.py             # install
    python path/to/proof-kit/install.py --help      # all options

Works with Python 3.9+ on Windows, macOS and Linux. Standard library only.
"""
import sys
from pathlib import Path

if sys.version_info < (3, 9):
    sys.exit("Proof Kit needs Python 3.9 or newer. You have " + sys.version.split()[0] + ".")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from proof_kit.proof_init import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
