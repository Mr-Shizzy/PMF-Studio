PMF Studio %VERSION%
====================

Make PSP movies, boot movies and AT3 sounds. No installer, nothing else to download.

To start:   unzip this folder anywhere (a memory stick works too) and double-click  PMF Studio.exe
To remove:  delete the folder. PMF Studio saves nothing anywhere else on your computer.

Keep the folder together: PMF Studio.exe needs the "tools" and "_internal" folders next to it.
You can move or rename the folder whenever you like.

Windows may say "Windows protected your PC" the first time, because this program isn't signed by a paid certificate.
Choose "More info", then "Run anyway". The release page lists the SHA-256 of the zip so you can check your download.

You can drag files (a movie, an EBOOT.PBP, a PMF, a sound, a folder) onto the window or onto PMF Studio.exe.
Check for updates downloads a new version when there is one, checks it and tests it, then restarts into it. It asks first,
keeps your settings and saved files, and puts the old version back if anything goes wrong.

Your saved files go to the Output folder beside the program unless you choose another one in Options.
Settings are kept in "PMF Studio settings.json" beside the program.

If something doesn't work, run  PMF Studio.exe --selftest  from a Command Prompt: it checks every helper program and writes
selftest_result.txt next to the program.

Licence: PMF Studio is free software under the GNU General Public License, version 3 (see LICENSE). Other people's programs inside the tools folder have their own
licences: see THIRD_PARTY_NOTICES.txt. Not made by or connected to Sony. Contains no game content.
