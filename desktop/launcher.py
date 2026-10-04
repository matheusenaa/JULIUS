"""JULIUS para computador (modo local).

- Banco SQLite e documentos na pasta do usuário (funciona sem internet).
- Aplica migrations ao abrir (nunca apaga dados).
- Abre o app em janela própria (Edge/Chrome em modo aplicativo, ou o navegador padrão).
- Se a instalação estiver vinculada a um servidor online (Ajustes → Sincronização),
  sincroniza em segundo plano a cada SYNC_INTERVAL_SECONDS.

Gerar o executável: veja desktop/README.md.
"""

import logging
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

APP_NAME = "JULIUS"


def data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def bundle_dir() -> Path:
    """Pasta do backend: dentro do executável (PyInstaller) ou no repositório."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent / "backend"


def configure_env(data: Path) -> None:
    secret_file = data / "secret.key"
    if not secret_file.exists():
        secret_file.write_text(secrets.token_urlsafe(48), encoding="utf-8")
    os.environ.setdefault("APP_ENV", "development")  # http://127.0.0.1: cookies sem "Secure"
    os.environ.setdefault("SECRET_KEY", secret_file.read_text(encoding="utf-8").strip())
    os.environ.setdefault("DATABASE_URL", f"sqlite:///{(data / 'julius.db').as_posix()}")
    os.environ.setdefault("STORAGE_BACKEND", "local")
    os.environ.setdefault("STORAGE_DIR", str(data / "arquivos"))
    env_file = data / "julius.env"  # chaves de IA etc. (opcional)
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip())


def free_port(preferred: int = 8010) -> int:
    for port in [preferred, *range(8020, 8100)]:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("Nenhuma porta livre")


def migrate(root: Path) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(cfg, "head")


def open_window(url: str) -> None:
    """Janela de aplicativo (sem barra de endereço) quando Edge/Chrome existem."""
    candidates = [
        shutil.which("msedge"), shutil.which("chrome"), shutil.which("google-chrome"), shutil.which("chromium"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ]
    for exe in candidates:
        if exe and Path(exe).exists():
            subprocess.Popen([exe, f"--app={url}", "--window-size=1280,860"])  # noqa: S603
            return
    webbrowser.open(url)


def sync_loop(interval: int) -> None:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import SyncState, User
    from app.services.sync_client import SyncClient, SyncError

    log = logging.getLogger("julius.desktop")
    while True:
        time.sleep(interval)
        with SessionLocal() as db:
            for state in db.scalars(select(SyncState).where(SyncState.remote_token.is_not(None))).all():
                user = db.get(User, state.user_id)
                try:
                    SyncClient(db, user).sync()
                except SyncError as exc:
                    log.info("Sincronização adiada: %s", exc)
                except Exception:  # noqa: BLE001 — nunca derrubar o app por causa da sincronização
                    log.exception("Erro inesperado na sincronização")


def main() -> None:
    data = data_dir()
    logging.basicConfig(
        level=logging.INFO, filename=data / "julius.log", format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    configure_env(data)
    root = bundle_dir()
    sys.path.insert(0, str(root))
    os.chdir(root)
    migrate(root)

    import uvicorn

    from app.config import get_settings
    from app.main import app

    port = free_port()
    url = f"http://127.0.0.1:{port}"
    threading.Thread(target=sync_loop, args=(get_settings().sync_interval_seconds,), daemon=True).start()
    if not os.environ.get("JULIUS_NO_WINDOW"):  # usado em testes automatizados
        threading.Timer(1.5, open_window, args=(url,)).start()
    print(f"JULIUS rodando em {url} — feche esta janela para encerrar.")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
