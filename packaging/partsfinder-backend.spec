# PyInstaller spec for the bundled search engine (one folder, no console window of its own).
#   cd <repo> && pyinstaller --noconfirm packaging/partsfinder-backend.spec
# Result: dist/partsfinder-backend/ (the app's installer copies it to resources/backend).
# Build it with the CPU-only torch (see packaging/README.md): the CUDA build is several GB larger.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
sys.path.insert(0, str(ROOT / "backend"))     # so the hooks below can find partsfinder
datas, binaries, hiddenimports = [], [], []

# packages with data files, native libraries or imports PyInstaller cannot see
for pkg in ("partsfinder", "cadquery", "OCP", "casadi", "sqlite_vec", "trimesh", "sentence_transformers", "tokenizers"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules("uvicorn")
# every installed distribution's metadata, with its licence files: needed at run time by packages that check
# versions (transformers), and the licences of what we ship (BSD, MIT, Apache require them to come along)
from importlib.metadata import distributions
for name in sorted({d.metadata["Name"] for d in distributions() if d.metadata["Name"]}):
    try:
        datas += copy_metadata(name)
    except Exception:  # broken or duplicate metadata: skip it
        pass

a = Analysis(
    [str(ROOT / "packaging" / "backend_entry.py")],
    pathex=[str(ROOT / "backend")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest", "IPython", "jupyter", "notebook", "PyQt5", "PySide2", "PySide6", "tensorboard"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="partsfinder-backend",
    console=True,            # the app starts it hidden (windowsHide) and reads its output
    icon=str(ROOT / "app" / "build" / "icon.ico") if sys.platform == "win32" else None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="partsfinder-backend")
