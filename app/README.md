# Partsfinder (Electron app)

The Partsfinder window. You type the part you need, and the app shows existing models with preview, dimensions and the reasons why they fit or not.

## Start
**Windows:** double-click `app.bat` in the project folder. The first time it:
- installs Node.js (via winget) if missing,
- installs Electron (~100 MB).

After that the app starts right away.

**Mac:**
```
cd app
npm install
npm start
```

**Signing in:** "Sign in" top right. The very first time it makes the admin account (only on the pc that runs the
library). After that people sign in with their name and password; without signing in you see only the general library.
- **Administrator:** account menu → **Companies and people**: add or delete a company; add its people (username, password,
  company, and which restricted folders they also see, by ticking); give a new password, disable or remove them; tick
  "no AI" for a company whose parts may never go to the AI; open any company's library and choose per folder who sees
  it (everyone at the company, or only a restricted group); import a folder into the general library.
- **Which folders to search:** the folder button next to Library ("All folders") lets you tick the general library and each
  of your company's folders; questions then only look there. Remembered on this pc.
- **Company:** account menu → **My library**: the company's parts, how complete its data is, and its folders.
  **Upload a folder** sends a folder from this pc (STEP, STL, SolidWorks, ... and JSON next to them); **Update** sends it
  again (new, changed and removed files follow); **Remove** takes it out of the library. `.partsfinderignore` and `.partsfinderaccess`
  in the folder are respected; excluded files are never read.
- "Stay signed in" stores the sign-in encrypted by Windows. An API key (`PARTSFINDER_API_KEYS`) still works: "Use an API key instead".
See `docs/10_COMPANY_LIBRARIES.md`.

The app looks for the search engine at `http://127.0.0.1:8000`. If `api.bat` is already running it uses that. Otherwise the app starts the search engine itself (from `backend/.venv`) and stops it on exit.

**Settings** (gear icon top right): add your own Anthropic API key to switch on the AI. The app stores it encrypted by
the operating system (`anthropic-key.bin` in the app's data folder) and hands it to the search engine on this pc only.
Settings also shows the version, the licence and who made Partsfinder (click the logo top left).

## What you can do
- **Search bar** (bottom centre; Ctrl+K or / jumps to it): type a part with its requirements. Every search replaces the
  results below it: a header with your search, the verdict (*Found*, *Close match*, *Not in the library*) and how it
  was answered, then the parts as a **grid or a list** (toggle top right, remembered). The library's own checks
  answer first (~40 ms); when they cannot settle it and the AI is on (your own key, see Settings), the AI judges the
  candidates (a few seconds). The question stays in the search bar, selected: refine it, or just type to replace it.
  Nothing found is shown as an empty state with the reason;
  confirmations, warnings and import progress appear as notifications at the bottom right.
- **Library:** which library you search: the general library, plus your own company's parts when you are signed in
  as a company. The administrator can search as any company. A company never sees another company's parts.
- **Importing** is not in the top bar: a company uploads its folders under **My library**; the administrator manages
  companies, people and the general library under **Companies and people**.
- **Results side by side:** as many cards per row as fit. Each card shows the preview, the name, one short
  sentence, up to three defining values (e.g. thread and length, or inner/outer diameter and width) and one line
  on the requirements of your question ("Meets all 3 requirements" or the first deviation).
- **Details** (or click the name or the picture): opens the full sheet: description, the table *Requirement / Requested / This part*, the
  assessment, all specifications and the components of an assembly, with three buttons:
  - **View 3D model:** rotate (drag), pan (right-drag or Shift+drag), zoom (wheel), reset (double-click).
    Works for parts with a STEP or STL file; the first view of a large STEP takes a few seconds.
  - **Datasheet:** printable datasheet in its own window (Print / Save as PDF).
  - **Download:** save the CAD file; choose the format if there are several.
- **Parts, not designs:** the library holds parts. Ask for one thing; if no single model of it exists (e.g. a complete
  robot arm), Partsfinder says so. The library never decides which parts a design needs.
- **Download STEP** at the bottom of every card (with where it comes from and its size) saves the main CAD file right away.
- **Long parts** (profiles, shafts, tubes, threaded rod) show a short piece in the preview, marked *shortened*
  with the real length; the 3D view and the file are the real part.
- **Search with an image:** camera button in the search bar, or paste (Ctrl+V) or drop a photo or drawing.
- **Search with your own CAD file:** cube button in the search bar, or drop a STEP or STL file: parts with about the same outer size and volume (the file is measured and not kept).
- **Filters:** one button in the search bar opens a small panel with the most used filters (library, category, material, standard, fits within L × W × H); type in a field and its list narrows to what matches. Active filters stand above the results; click one to remove it. With filters and no question: every part that meets them.
- **Several parts in one question** ("an M8 bolt and an Arduino"): one section per requested part, each judged on its own.
  Optionally type extra requirements (e.g. "M8, 40 mm"). The AI identifies the part, then the normal checked
  search runs. Sizes are only used when readable on the part or typed by you. Needs the AI.
- **Compare:** click *Compare* on 2 to 4 cards (or in Details). A small tray at the bottom of the window shows what you picked; *Compare* there opens the comparison: the parts side by side with envelope, volume, mass, material, standards and all properties. Values that are the same for all parts are green, values that differ are amber, and a value one of the parts does not state is grey ("not stated": not counted as a difference); *Only differences* shows only the rows that really differ. Click a thumbnail in the tray (or × in the comparison) to remove a part.
- **Similar shapes** (in Details): parts with a similar shape (outer dimensions + volume).
- **Used in** (in Details): the assemblies the part is already used in.
- **Possible duplicates** (My library): parts of the same kind with the same outer size and volume.
- **Good suggestion / Does not fit** (in Details): feedback per result; stored locally (`POST /feedback`).

## Files
| File | What |
|---|---|
| `main.js` | Main process: starts/finds the search engine, signing in (the key never reaches the window), window, saving and importing |
| `preload.js` | The only functions the window may use |
| `rules.js` | The folder rules (.partsfinderignore, .partsfinderaccess) for uploading a folder, the same as the library's import |
| `renderer/` | The window itself (HTML, CSS, JavaScript, no frameworks); `renderer/fonts/`: IBM Plex Sans (SIL Open Font License, see the licence file there) |

The window has no access to Node or your files. Everything goes via `preload.js` to the main process.

For tests: `PARTSFINDER_API_URL` chooses another search engine, and `PARTSFINDER_NO_SPAWN=1` prevents the app from starting one itself.

## After an import
The app shows how complete the data is (description, material, properties...) and which parts may be duplicates (same dimensions and volume).
