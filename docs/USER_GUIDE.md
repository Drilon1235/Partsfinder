# Using Partsfinder

Partsfinder finds an **existing** CAD model before you draw a new one. You ask for a part in plain words, it checks
every requirement of your question against each part's own data, and it tells you honestly what fits, what is close
(and how far off), or that nothing in the library fits.

Not installed yet? See [INSTALL.md](INSTALL.md).

## 1. Ask for a part
Type in the search bar and press Enter. Write it the way you would say it to a colleague:

| You type | Partsfinder reads |
|---|---|
| `M8x30 socket head bolt 12.9` | thread M8, length 30 mm, property class 12.9 |
| `DIN 933 M10x50 A2-70` | standard (DIN 933 = ISO 4017), thread, length, stainless A2-70 |
| `bolt M8 length between 25 and 40 mm` | every M8 bolt from 25 to 40 mm long |
| `1/4-20 x 1 socket head cap screw` | inch thread 1/4-20, length 1" (25.4 mm) |
| `6205-2RS` / `bearing 25 mm bore, sealed, under 15 mm wide` | the bearing number, or the sizes it must have |
| `weld neck flange DN50 PN16` / `2 inch class 300` | EN 1092-1 or ASME B16.5 flanges (never mixed up) |
| `O-ring 20 x 2` / `retaining ring for 35 mm bore` / `parallel key 8x7x40` | size of the seal, ring or key |
| `spur gear module 2, 40 teeth` / `a spur gear pair for 3:1, centre distance 80 mm` | one gear, or two that mesh |
| `IPE 200`, `SHS 50x50x4`, `angle 50x50x5`, `round bar 20` | steel profiles by their designation |
| `SOIC-8`, `0603 resistor`, `pin header 2x20 2.54mm`, `JST XH 4 pin` | electronic packages and connectors |
| `NEMA 17 stepper 0.4 Nm`, `GT2 pulley 20 teeth 5 mm bore` | motor frame and torque, pulley profile and bore |
| `M8 bolt, nut and washer` / `1 M8 bolt and 1 Arduino` | several parts: each one is answered on its own |

You may also write in **Dutch, German or French** (*inbusbout M8x30*, *Kugellager 6205*, *Flansch DN50*): Partsfinder
says how it read your question (*Read as "socket head bolt M8x30"*). An electrical value such as *10k* or *100nF* is
set aside, because a 3D model does not show it: the package (*0603*) decides the shape.

Words like *preferably* or *ideally* make a wish, not a requirement: *M8x30 bolt, preferably A4* shows every M8x30 bolt,
the A4 ones first. *not galvanized*, *max 50 mm* and *at least 800 MPa* are requirements.

## 2. Read the answer
Above the results Partsfinder says in one sentence what it found. Each result has a label:
- **Fits**: every requirement of your question is met by the part's own data.
- **Close**: the part is what you asked for, but something deviates or is not stated. The card says what, in numbers
  (*length: 40 mm asked, 42 mm found*, *seal: not stated*).
- **No existing model found**: nothing in the library fits. Partsfinder never forces a bad match; draw the part, or
  add a library that has it.

Open a result for **Requirements from your question**: per requirement the value you asked, the value of the part
and whether it matches.

When your question leaves something open that defines the part (*a bolt*: which thread? which length?), Partsfinder
asks for it and shows the values that exist in your library. Click one to add it to the question.

## 3. Narrow down
- **Library to search** (left of the search bar): all libraries, or only some of your folders.
- **Filters**: library, category, material, standard, and **Fits within (any orientation)**: only parts that fit in a
  box of L × W × H. Filters also work without a question, to browse.
- **Search with a photo or drawing**: drop an image on the window, paste one, or use the image button next to the search bar. This needs
  the AI (your own key).
- **Search with your own CAD file**: drop a STEP or STL file. Partsfinder shows parts with about the same outer size
  and volume.

## 4. Work with a part
On a result:
- **Download** the CAD file (STEP, STL, ...), or open **Details** for the 3D view, all properties, the
  **Specifications** (strength, mass, load ratings, tolerance, each with where the value comes from), the licence
  and a link to the original file.
- **Datasheet**: a printable page with the specifications.
- **Compare**: click **Compare** on 2 to 4 results to see them side by side, with what is the same and what differs.
- **Similar shapes**: parts with about the same outer size and volume.
- **Used in**: the assemblies that contain the part. The library panel also lists **possible duplicates** (parts of
  the same kind with nearly the same size and volume).

## 5. Your own parts
- **Data packs** (Settings → Data packs): thousands of openly licensed standard parts, electronics and profiles.
  See [INSTALL.md](INSTALL.md#3-add-parts-the-data-packs).
- **Your own folders**: **Companies and people → General library → Import a folder**. Partsfinder reads STEP, STL and
  other CAD files and makes previews. A JSON file next to a CAD file adds a name, description and exact properties
  (thread, length, bearing number, ...) so they can be checked; see [03_DATAMODEL.md](03_DATAMODEL.md).
- Only import files you are allowed to use. Partsfinder never downloads catalogues of manufacturers or distributors.

## 6. The AI (optional, your own key)
Without a key Partsfinder answers with its own checks, in about 40 ms: exact sizes, standards and designations are
settled that way. For vague questions (*a bolt to hold a 40 kg motor bracket outdoors near the sea*) an AI can judge
the candidates. Add your Anthropic API key in **Settings → AI with your own key**. The key is stored encrypted on
your pc and only used for your own searches; Anthropic bills your own account. Parts of a company marked *no AI* and
restricted parts are never sent to the AI.

## 7. Sharing one library with colleagues (optional)
On your own pc you never need to sign in. To share a library on your network, make an administrator account in
**Settings → Accounts (optional)** (you choose the name and password; there is no default), then add companies and
people. Each company only sees the general library and its own parts. Step by step:
[11_GUIDE_COMPANY_LIBRARIES.md](11_GUIDE_COMPANY_LIBRARIES.md).

**Forgot the administrator password?** On the pc that holds the library: **Settings → Accounts → Forgot the
administrator password?** sets a new one. This only works on that pc itself, never over the network.

## 8. Privacy
Your CAD files, your library and your searches stay on your own pc. Nothing is sent anywhere, except your question
and the candidate parts to Anthropic when you use your own AI key, and the one-time download of a linked pack file from
its open library. A website in your browser cannot reach your library.
