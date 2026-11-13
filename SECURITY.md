# Security

Partsfinder keeps companies' CAD libraries apart, so security problems matter. Thank you for reporting them.

## Report a problem privately
Use **GitHub → Security → Report a vulnerability** on this repository (a private advisory), or email
**info@dzitservices.be**. Please do not open a public issue for a security problem. Include what you did, what you saw, and the version (Settings → About).
We answer within a week and tell you when a fix is out.

## What counts
Especially:
- a way for one company (or one group) to see, search, download or infer anything of another company, or a
  restricted part without the right group;
- data of a company marked "no AI", or a restricted part, reaching an AI;
- a way to read files outside the library through the API or the app;
- leaking an API key, a password or a session.

## How Partsfinder protects data
- Every database query filters on the caller's company; a part of another company answers 404, as if it does not exist.
- The API listens only on this pc unless keys or accounts are set; it refuses a network address without them.
- On this pc it answers only to 127.0.0.1 / localhost (no DNS rebinding) and refuses requests that a web page sends
  (an Origin other than its own address), so a website open in your browser cannot reach your library.
- Data packs: files are only downloaded over https from the open libraries' hosts (also after a redirect), and a
  pack is unpacked only when every path stays inside its folder.
- Passwords are stored as scrypt hashes only; sessions expire; sign-in attempts are throttled.
- The user's own AI key is stored encrypted by the operating system and kept in memory by the search engine,
  never in the database, a file or a log.
- Details: [docs/10_COMPANY_LIBRARIES.md](docs/10_COMPANY_LIBRARIES.md).
