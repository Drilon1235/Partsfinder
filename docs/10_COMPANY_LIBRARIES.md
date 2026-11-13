# Company libraries, restricted parts and confidential mode

The question this answers: how can a company add its own parts from a server share or NAS without other users or
companies seeing them, and what if some folders or parts must never be used (confidentiality, e.g. parts of a
nuclear reactor)?

## What must hold (the security rules)
1. Company A never sees anything of company B: no part, name, picture, file, 3D model, search hint,
   similar shape or statistic. (Already true; every query goes through `_visible()` / `_owned()`.)
2. A file that is excluded is **never read**: not opened, not hashed, not measured, not sent to an AI,
   not stored. Excluding it later removes what was stored before.
3. A restricted part is only visible to people who are given its group. Without the group it does not
   exist for them: not in search, not as "similar", not by id, not in statistics or quality reports.
4. Data of a restricted part, and every part of a confidential company, never goes to an outside AI
   (Claude, or any AI client using the library's tools). Searching them is done by the library's own
   code, which runs on the company's server.
5. Removing a folder removes everything that was stored about it: the parts, their search entries
   (text and vectors), pictures, 3D caches and feedback; deleted database pages are overwritten.
6. Fail closed: when something is unclear (an unreadable access file, no group given, an unreachable
   share, a request without a key on a network), the answer is "not visible / not imported / refused",
   never "visible".
7. Who searched for and downloaded what is logged, without storing keys.

## Levels of access
| Level | Who sees it | Set by |
|---|---|---|
| General library | everyone | parts imported without a company |
| Company | everyone of that company (its key) | importing into a company |
| Restricted (group) | only keys of that company that list the group | a `.partsfinderaccess` file in the folder |
| Excluded | nobody: never read | a `.partsfinderignore` file in the folder |

On top of that, a company can be **confidential**: none of its parts ever goes to an outside AI
(the library's own code still searches and checks them).

## How it is set up at a company
```
\\nas\cad\                         <- imported for company "acme" (sync every night)
    standard-brackets\             <- company level: every acme key sees these
    reactor-vessel\
        .partsfinderaccess               <- "nuclear": only keys with group nuclear
        internals\                 <- also nuclear (the nearest .partsfinderaccess counts)
    customer-x-confidential\
        .partsfinderignore               <- "*": nothing in here is ever read
    old\
        .partsfinderignore               <- "*.sldprt" / "drafts/": only these are skipped
```
- `.partsfinderignore`: one pattern per line, `#` for comments. A pattern without `/` matches a file or folder
  name at any depth below (`*.sldprt`, `drafts`); a pattern with `/` is matched from that folder
  (`old/2019/`); a trailing `/` means folders only; `*` matches everything. `!` (exceptions) is not
  supported and is refused, so a rule can never accidentally open something up. Excluded folders are
  not even walked.
- `.partsfinderaccess`: the first line that is not a comment is the group name (`a-z`, `0-9`, `-`, `_`, max
  40 characters), or `company` to go back to company level for a subfolder. An unreadable or invalid
  file skips that whole folder (reported as an error), it never imports it as unrestricted.
- Groups only exist in company libraries; the general library cannot have restricted parts.
- A JSON file next to a CAD file can never set the company or the group.

## Accounts (people sign in)
- People sign in with a name and a password (`POST /login`). An **admin** account sees and manages everything:
  companies, people, imports. A **company** account sees the general library, its own company and the
  restricted groups the admin gave it, and manages its own library: it uploads folders from its own pc,
  updates and removes them. Without signing in, a library with accounts shows only the general library.
- The first admin account is made in the app ("Sign in" → "Create the admin account"), only on the pc that runs
  the library and only while there is no account at all.
- Only a scrypt hash of each password is stored; a session token only as its SHA-256. Wrong passwords: after 5
  for one name (or 20 from one address) within 15 minutes, signing in waits 15 minutes. A new password or
  disabling an account ends all its sessions. The audit log names the account (`user:anna`).
- **Restricted folders in the app** (admin): in a company's Library every uploaded folder shows its subfolders
  with a dropdown: everyone at the company, only a restricted group (an existing one or a new one), or the same as
  the folder above. People get groups by ticking them (Companies and people → People). The setting is kept in the
  database and written into the folder as `.partsfinderaccess` after every upload, so it stays when the company sends the
  folder again. A company person with a restricted group can choose it too (when uploading, or per folder), but
  only groups they have, and never for a folder the administrator closed to them; without a group they see which
  folders are restricted but cannot change it. Deleting a company
  removes everything of it (parts, accounts, uploads, settings).
- In the app: "Sign in" top right, with a **Company** and an **Administrator** tab (on a new library the
  Administrator tab makes the first account). The account menu has **My library** (company) or **Companies and
  people** (admin: add a company by name; add people with their company and restricted folders, new password,
  disable, remove; "no AI" = confidential; open any company's library; import a folder into the general library).
  There are no "New company" or "Import folder" buttons in the top bar any more: managing is in that panel.
  "Stay signed in" stores the token encrypted by Windows. Step by step: [11_GUIDE_COMPANY_LIBRARIES.md](11_GUIDE_COMPANY_LIBRARIES.md).
- Uploading a folder (`/uploads/...`): the app walks the folder with the same rules as the import
  (`app/rules.js`): excluded files and folders are never opened, links are never followed, a rule that cannot
  be used skips its folder, and rules above the chosen folder count (a group set above it is sent along). The
  files go to a staging area and only replace the folder when the upload is complete; the import then runs
  with sync, so files removed from the folder leave the library. "Update" sends the same folder again.

## Keys
`PARTSFINDER_API_KEYS="k1=acme, k2=acme:nuclear, k3=acme:nuclear:aero, admin=*"`
- `k1`: acme, company level only. `k2`: acme including group nuclear. `admin`: everything, every company.
- Keys are compared in constant time; the audit log stores a fingerprint (`sha256`, first 12 characters),
  never the key.
- Without keys (one pc, the API only on 127.0.0.1): restricted parts are hidden unless
  `PARTSFINDER_LOCAL_GROUPS` lists their group. Starting the API on a network address without keys is refused.
- The test app (E1): when `/health` says `keys_required`, it asks for a key and checks it with `GET /me`; the bar
  shows who is signed in (company and groups, or Admin) and a click signs out. The key stays in the app's main
  process; every request carries it, also the previews (`<img>`) and the datasheet window, which load straight
  from the API. "Remember on this pc" stores it encrypted by Windows (`safeStorage`); when that is not
  available it is kept in memory only, never as plain text. A company key fixes the library to its own
  company. The environment variable `PARTSFINDER_API_KEY`
  signs in without asking.

## Outside AI
- Requests from an AI client (another AI that searches the library sends `X-Partsfinder-AI: 1`; this header
  can only *reduce* what is visible, so a client cannot misuse it) see no restricted parts and no parts
  of confidential companies.
- `/search` with AI: Claude only judges when the caller could not see more than an AI may. Otherwise the
  search is done by the library's code only (the default path in the app anyway).
- `/search/image` (sends data to Claude) is refused for a confidential company
  and for keys with groups; the app then shows the library's own answer.
- Import: files in a restricted folder, and all files of a confidential company, never get an AI
  description; without a JSON file they get a guess from the file name ("needs review").

## Sync from a share or NAS
`python -m partsfinder.ingest \\nas\cad --company acme --sync` (or `POST /ingest` with `"sync": true`),
scheduled with Windows Task Scheduler (`sync.bat`) e.g. every night:
- new files are imported, changed files (same path, new content) replace their part under the same id,
  unchanged files are skipped (only the access group is updated when a `.partsfinderaccess` changed);
- parts whose file is gone, or now excluded by `.partsfinderignore`, are removed completely (rule 5);
- safety: an unreachable folder stops the sync before anything changes; if no CAD file is found at all
  while the library has parts from that folder, or more than half of them (and more than 20) would be
  removed, nothing is removed unless `--allow-mass-removal` is given (a NAS that is half mounted must
  not empty the library).

## Removal
`python -m partsfinder.ingest --remove \\nas\cad\old --company acme` (or `POST /remove`, admin): removes
every part of that company whose file lies in that folder, with everything stored about it (rule 5).
The database runs with `secure_delete`, the text index is optimised and the write-ahead log is truncated
afterwards, so deleted content is not left behind in the database files.

## Audit log
Table `audit_log`: time, key fingerprint (or `local`), company, action (`search`, `search_image`,
`download`, `mesh`, `datasheet`, `ingest`, `remove`, `settings`), part id or folder, and the
question text for searches. `GET /audit` (admin) lists it per company. Part names are not stored, only ids.

## Not covered (yet)
- A company account cannot add people itself yet; the admin does. Single sign-on (Microsoft, Google) is not built.
- Uploaded folders live on the library's own disk (`data/companies/<company>/uploads/`); back that folder up
  with the database.
- The CAD files stay on the share; who may read the share itself is the company's own file permission.
- Vectors in the sqlite-vec index are removed with the part; their storage pages are reused, not wiped.
