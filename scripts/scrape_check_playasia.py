"""Live scrape check for Play-Asia. See scrape_check.py.

Replaces the old root-level ``test_playasia.py``, which carried its own copy
of the store profile and its own pagination logic -- so it passed while the
collector, using different selectors on the same site, returned one page.
"""

from __future__ import annotations

import sys

from scrape_check import main

if __name__ == "__main__":
    sys.exit(main(["playasia", *sys.argv[1:]]))
