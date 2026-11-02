"""Start-up file for the packaged program (PyInstaller): the same as `python -m pmfstudio`."""
import sys

if "--selftest" in sys.argv:
    from pmfstudio.selftest import run
    sys.exit(run())
from pmfstudio.app import main

main()
