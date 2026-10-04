"""Comandos de manutenção.

    python -m app.cli backup [pasta]   # cópia consistente do SQLite (pode rodar com o app ligado)
"""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

from app.config import BACKEND_DIR, get_settings


def backup(target_dir: str | None = None) -> Path:
    s = get_settings()
    if not s.is_sqlite:
        raise SystemExit(
            "Banco PostgreSQL: use o backup do provedor (Neon guarda histórico automaticamente) "
            "ou `pg_dump`. Para seus dados em formato aberto, use Ajustes → Backup completo (JSON)."
        )
    source = Path(s.database_url.removeprefix("sqlite:///"))
    if not source.exists():
        raise SystemExit(f"Banco não encontrado: {source}")
    out_dir = Path(target_dir) if target_dir else BACKEND_DIR.parent / "backups"
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"julius-{datetime.now():%Y%m%d-%H%M%S}.db"
    with sqlite3.connect(source) as src, sqlite3.connect(dest) as dst:
        src.backup(dst)  # API de backup online do SQLite: cópia consistente
    with sqlite3.connect(dest) as check:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise SystemExit("Backup gerado falhou na verificação de integridade.")
    return dest


def main(argv: list[str]) -> None:
    if len(argv) >= 1 and argv[0] == "backup":
        print(f"Backup salvo em: {backup(argv[1] if len(argv) > 1 else None)}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
