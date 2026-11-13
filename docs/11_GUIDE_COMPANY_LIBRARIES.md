# Guide: company libraries in Partsfinder

How to set up companies, let them sign in, and bring their own CAD files into their own library.
For the rules behind it see [10_COMPANY_LIBRARIES.md](10_COMPANY_LIBRARIES.md).

## 1. The idea in one minute

There are three kinds of parts:

| | Who sees it | How it gets there |
|---|---|---|
| **General library** | Everyone, also without signing in | The administrator imports a folder (Companies and people → General library) |
| **Company library** | Only that company's people, and the administrator | The company uploads its folders (My library), or the administrator does it for them |
| **Restricted parts** | Only people of that company who have the group (e.g. `nuclear`) | A `.partsfinderaccess` file in the folder |

Files named in a `.partsfinderignore` file are never read at all. A company can also be set to **no AI**: none of its
parts is ever sent to an outside AI.

There are two kinds of accounts:
- **Administrator** (you): manages companies, people and the general library, and sees everything.
- **Company account**: one per person at a company. Sees the general library plus its own company, and manages
  its own folders.

Without signing in, the app only shows the general library.

## 2. The first time: make the administrator account

1. Update (Sync Changes), close `api.bat` and the app, and start `app.bat`.
2. Top right, click **Sign in**. On a library without accounts it opens on the **Administrator** tab:
   **Create the administrator account**.
3. Type your username and a password (at least 8 characters) twice, and click **Create and sign in**.

This only works on the pc that runs the library, and only once: as soon as there is an account, everyone
signs in normally. Your name now shows top right; click it for the menu.

## 3. Administrator: companies and people

Top right → your name → **Companies and people**.

### Add a company
Under **Companies**, type the company's name (for example *Janssen Engineering*) and click **Add company**. It gets
its own, empty library and a short id made from the name (`janssen-engineering`), shown under the name.

### Add its people
Under **People**, fill in the form and click **Add person**. One account per person, so the log shows who did what.
- **Username**: for example `anna.peeters` (3-40 characters: letters, digits, `.`, `_`, `-`).
- **Password**: at least 8 characters. Give it to the person yourself.
- **Role**: *Company* for people of a company; *Administrator* only for someone who manages everything.
- **Company**: pick the company from the list (add the company first).
- **Also sees restricted folders** (optional): tick the restricted groups this person may see (they appear once a
  folder of the company is restricted, see "Restricted folders" below). Most people need none.

### Manage people
In each row:
- **New password**: type it in the row and press **Save** (or Enter). That person is signed out everywhere
  and signs in with the new one. This is also the answer to "I forgot my password".
- **Disable / Enable**: a disabled account cannot sign in and is signed out at once.
- **Remove**: removes the account; the company's parts stay.
The last administrator account cannot be disabled or removed.

### Restricted folders: who sees which folder
Open a company's **Library** (Companies → Library). Under each uploaded folder you see its subfolders, each with who
sees it (*Everyone at ...*). Click it and choose:
- **Everyone at the company** (the default),
- **Only people with one of these restricted groups**: tick one or more existing groups, or type a new one
  (one word, such as `nuclear`); people with any one of them see the folder,
- **Same as the folder above** for a subfolder: it follows the folder it is in.

The parts follow within seconds. Then give the right people that group: People → click the group cell of a person
(it says *none*) → tick → Save. The setting stays when the company sends the folder again with Update.
People of the company who have a group can do this themselves for that group (see "Upload a folder" below); people
without a group only see which folders are restricted.

### Companies
- **Library** (per row): opens that company's library. You upload, update and remove folders for them, and choose
  who sees which folder.
- **Delete** (per row): removes the company for good: all its parts, its accounts, its uploaded folders and its
  settings. You are asked to confirm; it cannot be undone.
- **no AI**: some searches send part names and descriptions to Claude (Anthropic's AI) to judge which parts fit.
  Tick **no AI** and nothing of that company ever leaves the library's pc: its searches are answered by the
  library's own checks, and photo search is off for it. Use it for customers with secret designs.

### General library
**Import a folder** under General library: choose a folder with standard parts (bolts, bearings, profiles...).
Everyone sees these, also without signing in. The import runs in the background; its progress and result show
in a notification at the bottom right.

## 4. Company: signing in and My library

### Signing in
Top right → **Sign in** → the **Company** tab (it opens there) → username and password from the administrator →
**Sign in**. Tick **Stay signed in** to not sign in again on this pc for 30 days (stored encrypted by Windows).

After signing in:
- **Library** (top bar) shows *Janssen Engineering + general*: every search looks in your own parts and the general library.
- **All folders** (next to it): tick which folders your questions look through: the general library, each of your
  company's folders, or only some of them. "Everything" switches all back on.
- Your own parts show **Your company** on the card; restricted parts show their group.

Wrong password five times in a row: wait 15 minutes. Forgot it: ask the administrator for a new one.

### Upload a folder
Your name → **My library** → **Upload a folder** → choose a folder on your pc.
- Everything in it and in its subfolders is sent: CAD files (STEP, STP, STL, IGES, SolidWorks, Inventor, CATIA,
  Creo, DWG/DXF, ...) and a JSON file next to a CAD file. Other files are skipped.
- STEP and STL files are measured and get a preview; other formats are stored and can be downloaded.
- **A folder for your group only**: if the administrator gave you a restricted group (for example `nuclear`),
  clicking Upload a folder first asks **Who sees the folder you upload?** Choose *Only people with one of your
  restricted groups*, tick the group, and click **Choose the folder...**. Later you can change it by clicking who
  sees a folder (*Everyone at ...*) in My library. You can only choose groups you have yourself, and you cannot
  change a folder the administrator restricted to a group you do not have.
- When it is done you see what happened, for example *"Main CAD: 112 new, 0 updated, 0 unchanged.
  3 left out by .partsfinderignore"*.

### Update and Remove
- **Update** sends the same folder again (the app remembers where it is on this pc). New files are added, changed
  files replace the old version (same part), and files you deleted from the folder leave the library.
- **Remove** takes the folder out of the library: all its parts and everything stored about them. The files on
  your pc are not touched.

### How complete is the data
Partsfinder can only check requirements that are in the data. The percentages show how many of your parts have a
description, a material, dimensions, properties and a preview. A JSON file next to a CAD file fills them in:

```json
{
  "name": "Wall bracket 100 x 40",
  "description": "Galvanised wall bracket for 40 mm profiles, two M8 holes.",
  "category_path": "connections/bracket/wall-bracket",
  "material": "steel galvanized",
  "properties": {"hole_diameter_mm": 9, "thickness_mm": 5}
}
```
(Save it as `Wall bracket 100.json` next to `Wall bracket 100.step`. More fields: [03_DATAMODEL.md](03_DATAMODEL.md).)

**Strength, load and tolerance.** *Specifications* in Details of a part also show mass, strength, load, tolerance and
hardness, each with where the value comes from. Some follow by themselves: the mass from the measured volume and
the material (an estimate), the strength of a bolt from its property class (8.8 = at least 800 MPa) or of a named
grade (S235, 1.4404, 6082-T6). The rest your JSON file can state, in `properties`:

```json
"properties": {"max_load_kg": 80, "tolerance": "ISO 2768-mK", "hardness_hrc": 58,
               "load_rating_kn": 14.8, "static_load_rating_kn": 7.8, "tensile_strength_mpa": 520}
```
Then people can search on it: *shelf bracket that holds 50 kg*, *hex bolt M8x30 at least 1000 MPa*, *bearing 6205
load rating 14 kN*, *plate ISO 2768-m*. A part that does not state a value never shows as *Fits* for it.

**Possible duplicates.** Under the percentages, My library lists parts of the same kind with the same outer size and
volume (*Mounting plate 120x80 = Plate 120x80 copy*). Check them: keeping one model means nobody searches or draws
it twice. Equal sizes do not always mean the same part.

### Searching: filters, several parts, your own CAD file
- **Filters** (the button in the search bar) opens a small panel with the filters people use most: which library,
  category, material, standard and the outer size it must fit within. Type in a field and its list narrows to what
  matches (*8.8*, *4017*, *bolts*); for material you can also keep what you typed (*steel* = every steel). Only parts
  that meet every filter are shown.
  The active filters stand above the results; click one to remove it. With filters and no question you get every
  part that meets them. Anything else (thread, length, strength, load) you simply type in the question.
- **Several parts in one question** (*an M8 bolt and an Arduino*, *M8 bolt, nut and washer*): every part is searched
  and judged on its own, each in its own section. A value you did not give (the length of the bolt, which Arduino)
  is open: every value fits it.
- **Your own CAD file**: the cube button in the search bar, or drop a STEP or STL file on the window. The library
  measures its outer size and volume, shows the parts with about the same shape and keeps nothing of the file.
- **Used in**: Details of a part lists the assemblies it is already used in, so you can reuse it with confidence.

## 5. Keeping files out, or for a few people only

- **Keep files out**: only what is in the folder you upload reaches the library. Leave files out of that folder (or
  move them to a folder you do not upload) and they are never read.
- **For a few people only**: someone with that group chooses it when uploading (section 4), or the administrator
  opens the company's Library and clicks the setting next to a folder
  (*Everyone at ...*): **Only people with one of these restricted groups**, tick one or more groups or type a new one,
  Save. People with any one of those groups see the folder. Then tick the same group for those people under
  Companies and people.

*For IT people*: the same can be done with two small text files in a folder on a share: `.partsfinderignore` (files never
read; `*` = everything in that folder) and `.partsfinderaccess` (the group or groups, for example `nuclear, aero`).

## 6. Every night from a share or NAS (administrator)

For a company whose files are on a server share, the administrator can keep the library in step without
uploading by hand. On the pc that runs the library:

```
sync.bat "\\nas\cad" janssen-engineering
```
Schedule it with Windows Task Scheduler: Create Basic Task → Daily → Start a program → `sync.bat`, arguments
`"\\nas\cad" janssen-engineering`. New, changed and removed files follow. If the share cannot be reached, or more than half of the
parts would disappear, nothing is removed. The log of the last run is in `backend\sync_log.txt`.

## 7. Who did what (administrator)

Every search, download, datasheet, upload and account change is logged with the account name (`user:anna`),
never with a password. In PowerShell on the library's pc:
```
curl.exe -H "Authorization: Bearer <your session or admin key>" "http://127.0.0.1:8000/audit?company_id=janssen-engineering"
```

## 8. Good to know

| You see | What it means / what to do |
|---|---|
| "Sign in to search a company library" | You are not signed in: only the general library is open. |
| "Wrong username or password" | Check both; after five tries wait 15 minutes, or ask for a new password. |
| "No CAD files to upload in this folder" | The folder has no CAD files, or `.partsfinderignore` leaves them all out. Nothing was changed. |
| "An import is already running" | One import at a time; try again when it is done. |
| "AI paused until 18:00" | The Claude account's limit is reached; the library's own checks keep answering. |
| A part is missing for a colleague | Check the folder's `.partsfinderaccess`: does their account have that group? |

- Uploaded folders are stored on the library's pc in `data\companies\<company>\uploads\`. Back up that folder
  together with `backend\partsfinder.db`.
- Passwords are stored only in scrambled form (scrypt); nobody, also not the administrator, can read them. They
  are never in the code, in git or in a log. When you remove an account or give a new password, the old scrambled
  form is wiped from the database files too.
- Signing out clears the search results and the sign-in form, so the next person at the pc sees nothing of yours.

## 9. Try it in five minutes

1. Make the administrator account (section 2).
2. Companies and people: add the company *Janssen Engineering*, then the people `anna` and `bert` for it.
3. Make a test folder with a few STEP files, a subfolder `reactor` with a `.partsfinderaccess` that says `nuclear`, and a
   subfolder `secret` with a `.partsfinderignore` that says `*`.
4. Sign out, sign in as anna (Company tab), My library → Upload a folder → the test folder.
5. Sign in as the administrator, Companies and people → People → bert's group cell (*none*) → tick `nuclear` → Save.
6. Search for a part from `reactor`: anna does not find it. Sign in as bert: he does. Nobody finds the parts in
   `secret`: they were never read.
7. In the company's Library, click the setting of the folder `brackets` → *Only people with one of these restricted
   groups* → type `aero` → Save: now neither anna nor bert finds the brackets until you tick `aero` for them.
8. Sign out: without signing in, none of Janssen Engineering's parts show up.
