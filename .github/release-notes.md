Partsfinder finds an existing CAD part before you draw a new one: ask in plain words, and every requirement is checked against the part's own data. Free and open source under the MIT licence: use it, change it, share it, sell it. By [DZ IT Services](https://dzitservices.be).

## Download
1. **`Partsfinder-Setup.exe`** below (the same installer as `Partsfinder-Setup-<version>.exe`): the app for Windows 10/11 (64-bit), with its search engine and language model included. Windows SmartScreen may ask you to confirm (*More info → Run anyway*): the installer is not code-signed yet.
2. In the app, **Settings → Data packs → Download and install** adds thousands of free parts in a click (or download a pack zip below and use **Install from a file…**).
3. Optional, your own Anthropic API key in **Settings → AI with your own key**. Everything works without it.

Step by step: **[Download and install](https://github.com/Drilon1235/Partsfinder/blob/main/docs/INSTALL.md)** · **[User guide](https://github.com/Drilon1235/Partsfinder/blob/main/docs/USER_GUIDE.md)**

## Data packs
| Pack | Parts | Licence |
|---|---|---|
| `standard-parts`: ISO/DIN/ASME bolts, nuts, washers, bearings, O-rings, retaining rings, keys, flanges, gears | ~5,800 | Apache-2.0 |
| `kicad-3d`: SMD and through-hole packages, connectors, switches, crystals, LEDs | ~6,200 | CC-BY-SA 4.0 + KiCad libraries exception |
| `freecad-library`: steel profiles, fasteners, motors, machine parts | ~2,500 | CC-BY 3.0 |
| `adafruit-cad-parts`: Adafruit boards and modules | ~490 | MIT |

Every part keeps its source, author and licence (shown in Details, with a link to the original file).

## What is new
- **Data packs in one click**: Settings → Data packs downloads and installs a pack from the newest release, checked against its checksum; a new, empty library points straight there.
- **MIT licence** (was AGPL-3.0): everyone may use, change and redistribute Partsfinder, also commercially.
- A **Download for Windows** button on the project page that always gets the newest installer.
- **No account needed** on your own pc; accounts are optional, for sharing a library on your network. Forgot the administrator password? Reset it on the pc that holds the library.
- **Your own AI key** set right in Settings, on the pc that runs the library.
- **Data packs**: ~15,000 openly licensed parts, installed and removed in the app.
- **Better search**, tested with ~120 real engineering questions: ranges (*M8 bolt between 25 and 40 mm*), inch threads (*1/4-20 x 1*), ASME flanges (*2 inch class 300*), O-rings, retaining rings for a shaft or a bore, parallel keys (*8x7x40*), sealed bearings, designations in the name (*IPE 200*, *SOIC-8*, *SHS 50x50x4*), spur gear pairs for a ratio, questions in Dutch, German and French, and the same part from two sources shown once.
- **Security**: a website in your browser cannot reach your library; pack files only come from the open libraries.

## Checksums (SHA-256)
| File | SHA-256 |
|---|---|
| Partsfinder-Setup.exe | <!-- installer --> |
| partsfinder-pack-standard-parts-2026-11-13.zip | `8edfbbeb52a2789b3a8e0d44e5b6f419bd41e8ced35832a8aba0ef9abeadd8a4` |
| partsfinder-pack-kicad-3d-2026-11-13.zip | `80d65ee5d4e53a78000842f1c941a3a578005014777ed2adaaf947d95b98caea` |
| partsfinder-pack-freecad-library-2026-11-13.zip | `56a160b95dfa964b028bbc9c091f8bc809fc82d2f6edbbd7e5409affeb1f963f` |
| partsfinder-pack-adafruit-cad-parts-2026-11-13.zip | `d53a6db1bd7fc16cd5ab5b78a67b3b69f61a58693f02ef217ca5148f067e3e21` |
