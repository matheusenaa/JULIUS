# PyInstaller: gera dist/JULIUS (pasta com JULIUS.exe). Rode a partir da raiz do repositório.
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 — SPECPATH é definido pelo PyInstaller
BACKEND = ROOT / "backend"

a = Analysis(  # noqa: F821
    [str(ROOT / "desktop" / "launcher.py")],
    pathex=[str(BACKEND)],
    datas=[
        (str(BACKEND / "app"), "app"),
        (str(BACKEND / "migrations"), "migrations"),
        (str(BACKEND / "alembic.ini"), "."),
        (str(BACKEND / "static"), "static"),
    ],
    hiddenimports=[
        "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto", "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on", "argon2", "email_validator", "multipart", "tzdata", "pypdf", "openpyxl", "fpdf",
        "sqlalchemy.dialects.sqlite",
    ],
    excludes=["psycopg", "tkinter", "pytest"],
)
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="JULIUS", console=True,  # noqa: F821
          icon=str(ROOT / "frontend" / "public" / "favicon.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="JULIUS")  # noqa: F821
