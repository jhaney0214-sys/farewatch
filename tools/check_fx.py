#!/usr/bin/env python3
"""Is the currency table still what the service publishes?

`fx.HISTORY_SYMBOLS` is a hand-written mirror of the ECB's reference-rate
vocabulary. The service enumerates its own list, so this is auditable rather
than a matter of trust - and it had drifted by one currency before anybody
looked.

    python tools/check_fx.py

Exit codes: 0 in step, 1 drifted, 2 could not check. **The third is not a
pass.** A service that cannot be reached tells you nothing about the table,
and reporting that as clean is the failure this workstation keeps re-learning.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from farewatch import fx  # noqa: E402


def main():
    try:
        stale, unlisted = fx.audit_history_symbols()
    except Exception as error:                                  # noqa: BLE001
        print("COULD NOT CHECK - %s: %s" % (type(error).__name__, error))
        print("This is not a pass. The table was not compared with anything.")
        return 2

    print("fx.HISTORY_SYMBOLS - %d symbols" % len(fx.HISTORY_SYMBOLS))
    if not stale and not unlisted:
        print("in step with %s" % fx.CURRENCIES_URL)
        return 0

    if stale:
        print("\nSTALE - asked for, no longer published: %s"
              % ", ".join(stale))
        print("  These silently vanish from the response. The service answers")
        print("  200 and omits them, so nothing errors and the trailing-year")
        print("  average simply has no entry - tailwind() returns None and")
        print("  calls it 'common and fine'.")
    if unlisted:
        print("\nUNLISTED - published, never asked for: %s"
              % ", ".join(unlisted))
        print("  Adding these costs one query parameter and buys history for")
        print("  destinations that currently get no tailwind reading at all.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
