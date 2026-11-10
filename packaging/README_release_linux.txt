PMF Studio %VERSION%  (Linux, experimental)
===========================================

Make PSP movies, boot movies and AT3 sounds. Nothing to install and nothing else to download.

To start:   unpack this folder anywhere (a memory stick works too), open a terminal in it and run   ./"PMF Studio"
            (or double-click "PMF Studio" in your file manager and choose "Run").
To remove:  delete the folder. PMF Studio saves nothing anywhere else on your computer.

Keep the folder together: "PMF Studio" needs the "tools" and "_internal" folders next to it.
You can move or rename the folder whenever you like.

This is the first Linux version and it is experimental. It was tested on Ubuntu 24.04 (inside Windows) and by comparing the files it makes
with the Windows version (they are identical). It was not tried on other distributions or on a physical Linux desktop.
What is different from the Windows version:
  - The player (Make > Player) plays sound through PulseAudio or PipeWire (the sound server almost every desktop has; the program uses
    its libpulse-simple library). With no sound server the picture still plays, silently.
  - Dragging files onto the window uses the X11 drag-and-drop protocol, which file managers use (on Wayland desktops through XWayland).
    If it does not work on your desktop, use the Browse buttons, and tell us (Options > Run self-test > Copy report shows its state).
  - Dropping files on the program's icon: file managers can't do that with a program file, so the program writes a launcher,
    "PMF Studio.desktop", in its own folder (the first time it runs, and again if you move the folder). Drop files on it, or choose it under
    "Open with", and the program starts with those files. You can also run   ./"PMF Studio" movie.pmf
  - While a long job runs the computer is kept from sleeping (a lock taken with systemd-inhibit; the report in Options says
    whether it worked on your system) and the helper programs run at a lower priority (nice 10), as on Windows.
  - The window's letters: the Python this program is packed with can only draw one plain bitmap font, so PMF Studio carries its own Tk with
    font support and the open font Selawik (tools/fonts; Microsoft's stand-in for the Windows font Segoe UI, with the same letter widths), so the
    window looks like the Windows one. The libraries that needs (X11, FreeType, fontconfig and a few more) are copied into the _internal folder.
    On a high-resolution screen the window follows the desktop's own DPI setting (Xft.dpi).
  - The program needs a graphical desktop (X11 or Wayland with XWayland).
Everything that makes files (gameboot, C-Intro, EBOOT icon, shrinking game movies, AT3 tools, Extract) works as on Windows.

Check for updates downloads a new version when there is one, checks it and tests it, then restarts into it. It asks first,
keeps your settings and saved files, and puts the old version back if anything goes wrong. The AppImage replaces its own file (the new
file takes the old file's name; the old one is kept beside it until the new version has run for a few seconds).
(An AppImage from before this was added, such as the 0.2 beta, can't: download the next AppImage by hand once.)

Your saved files go to the Output folder beside the program unless you choose another one in Options.
Settings are kept in "PMF Studio settings.json" beside the program. (For the AppImage: beside the .AppImage file.)

If something doesn't work, open Options and press "Run self-test": it checks every helper program, and "Copy report" gives you text
for a bug report that leaves out your folder names and user name. From a terminal:   ./"PMF Studio" --selftest

Licence: PMF Studio is free software under the GNU General Public License, version 3 (see LICENSE). Other people's programs inside the tools folder have their own
licences: see THIRD_PARTY_NOTICES.txt. Not made by or connected to Sony. Contains no game content.
