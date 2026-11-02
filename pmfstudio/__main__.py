import sys

if "--update-from" in sys.argv:
    from .updater import cli_update
    sys.exit(cli_update(sys.argv))
if "--selftest" in sys.argv:
    from .selftest import run
    sys.exit(run())
from .app import main

main()
