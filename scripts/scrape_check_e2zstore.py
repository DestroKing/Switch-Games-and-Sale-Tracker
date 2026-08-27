"""Live scrape check for e2zSTORE. See scrape_check.py.

Replaces the old root-level ``test_e2zstore.py``.
"""

from __future__ import annotations

import sys

from scrape_check import main

if __name__ == "__main__":
    sys.exit(main(["e2zstore", *sys.argv[1:]]))
