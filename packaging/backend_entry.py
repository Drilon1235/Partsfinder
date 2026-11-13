"""Entry point of the bundled search engine (PyInstaller): the same as `python -m partsfinder.api`.

The installed app starts it as resources/backend/partsfinder-backend(.exe) --port 8731 (see app/main.js).
"""
import multiprocessing
import sys

from partsfinder.api import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
