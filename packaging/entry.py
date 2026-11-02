"""Start-up file for the packaged program (PyInstaller): the same as `python -m pmfstudio`."""
import sys

if "--update-from" in sys.argv:
    from pmfstudio.updater import cli_update
    sys.exit(cli_update(sys.argv))
if "--selftest" in sys.argv:
    from pmfstudio.selftest import run
    sys.exit(run())
from pmfstudio.app import main

main()
