import sys

if "--selftest" in sys.argv:
    from .selftest import run
    sys.exit(run())
from .app import main

main()
