# Download and install Partsfinder

Partsfinder is a normal desktop app: you download one installer, run it, and open Partsfinder from the Start menu.
You do not need Python, a terminal or any `.bat` file (those are only for developers who work on the source code).

## What you need
- Windows 10 or 11, 64-bit.
- About 2 GB of free disk space for the app, plus space for the data packs you add (about 1.5 GB with all four).
- No internet connection is needed to search. Internet is only used for the optional AI, and the first time you open
  a part from a linked data pack (its file is downloaded once from the open library it comes from).
- On a Mac there is no installer yet; see [From the source code](#from-the-source-code-developers).

## 1. Download the installer
Click **[Download Partsfinder for Windows](https://github.com/Drilon1235/Partsfinder/releases/latest/download/Partsfinder-Setup.exe)**:
it always downloads the newest version (`Partsfinder-Setup.exe`).

Or go to the **[latest release](https://github.com/Drilon1235/Partsfinder/releases/latest)** and, under **Assets**, click
**`Partsfinder-Setup-<version>.exe`** (the same installer, with the version in its name).

## 2. Install
1. Double-click the downloaded `Partsfinder-Setup.exe`.
2. **Windows SmartScreen** may say *"Windows protected your PC"*, because the installer is not code-signed yet.
   Click **More info → Run anyway**. (Only do this for an installer you downloaded from the release page above.)
3. Accept the licence (GNU AGPL v3), choose where to install it (the default is fine) and click **Install**.
4. Open **Partsfinder** from the Start menu or the desktop shortcut.

The first start takes a few seconds longer while the search engine loads its language model. Everything it needs is
included, so it also works offline from the first start.

## 3. Add parts: the data packs
A new installation starts with an empty library. The fastest way to fill it is with the free **data packs**:
thousands of openly licensed CAD models, ready to install.

| Pack | What is in it | Licence | Size |
|---|---|---|---|
| `standard-parts` | ~5,800 standard parts: ISO/DIN/ASME bolts, nuts, washers, bearings, O-rings, retaining rings, keys, flanges, gears | Apache-2.0 | 186 MB |
| `kicad-3d` | ~6,200 electronic components: SMD and through-hole packages, connectors, switches, crystals, LEDs | CC-BY-SA 4.0 + KiCad exception | 78 MB |
| `freecad-library` | ~2,500 parts of the FreeCAD library: steel profiles, fasteners, motors, machine parts | CC-BY 3.0 | 29 MB |
| `adafruit-cad-parts` | ~490 Adafruit boards and modules | MIT | 8 MB |

1. Download the packs you want from the **Assets** of the same
   [release](https://github.com/Drilon1235/Partsfinder/releases/latest)
   (`partsfinder-pack-<name>-<date>.zip`). Keep them as `.zip`; do not unpack them.
2. In Partsfinder, click the **gear icon** (Settings) → **Data packs** → **Install a data pack…** and choose the zip.
3. Wait until the progress bar is done (the standard parts take a few minutes). Repeat for the other packs.

Each part keeps its own licence and a link to its original file; you see both in a part's **Details**. Installing a
newer version of a pack updates its parts; **Remove** in the same list takes a pack out again.

## 4. Optional: the AI with your own key
Partsfinder answers most questions with its own checks. For vague questions it can also let an AI judge the
candidates. That AI runs on **your own** Anthropic API key:
1. Make a key at [console.anthropic.com](https://console.anthropic.com/) (Anthropic bills your own account; a search
   costs about a tenth of a cent with the default model).
2. In Partsfinder: **Settings → AI with your own key**, paste the key and click **Save key**.

The key is stored encrypted by Windows and only given to the search engine on your own pc. You can remove it at any
time in the same place. Without a key, everything works with the library's own checks.

## Updating
Download the installer of the new version from the [releases](https://github.com/Drilon1235/Partsfinder/releases)
and run it over the old one. Your library, packs, settings and key are kept.

## Where your data is, and uninstalling
- Your library, installed packs and settings: `%APPDATA%\Partsfinder` (paste that in the Explorer address bar).
- Uninstall via **Windows Settings → Apps → Installed apps → Partsfinder → Uninstall**. Your library in
  `%APPDATA%\Partsfinder` is kept, so a reinstall finds it again; delete that folder to remove it too.

## Check the download (optional)
The release notes list a SHA-256 checksum per file. In PowerShell:
```
Get-FileHash .\Partsfinder-Setup-0.2.0.exe -Algorithm SHA256
```
The result must be the same as in the release notes.

## Something does not work?
- *"The search engine is not reachable"*: close Partsfinder completely and open it again. A program that already uses
  port 8731 on your pc can block it.
- Questions, bugs and ideas: [open an issue](https://github.com/Drilon1235/Partsfinder/issues). Security problems:
  see [SECURITY.md](../SECURITY.md) (privately, or by email to info@dzitservices.be).

## From the source code (developers)
Only needed to work on Partsfinder itself.

**Windows**
1. Download the repository (green **Code** button → *Download ZIP*, or `git clone`).
2. Double-click `scripts\windows\setup_windows.bat`: it installs Python 3.12 when needed, makes a virtual environment,
   installs the packages and runs the tests (about 10 minutes the first time).
3. Double-click `scripts\windows\app.bat`: the first time it installs Node.js and the app's packages, then opens the app.

**Mac**: `bash scripts/setup_mac.sh`, then `cd app && npm install && npm start`.

The other scripts in `scripts\windows\` start only the API (`api.bat`), build a demo library (`engineering.bat`) or
run the checks (`check.bat`). To build the installer yourself, see [packaging/README.md](../packaging/README.md).
