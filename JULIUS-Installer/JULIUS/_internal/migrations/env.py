from logging.config import fileConfig

from alembic import context

from app.config import get_settings
from app.db import make_engine
from app.models import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _url() -> str:
    # Permite que os testes passem uma URL própria via config.attributes
    return config.attributes.get("database_url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection") or make_engine(_url())
    if hasattr(connectable, "connect"):
        with connectable.connect() as connection:
            _run(connection)
    else:
        _run(connectable)


def _run(connection) -> None:
    sqlite = connection.dialect.name == "sqlite"
    if sqlite:
        # O modo batch do SQLite recria tabelas; com FKs ativas ele não consegue
        # recriar tabelas referenciadas. Desliga durante a migration e verifica no fim.
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        # Fecha a transação implícita aberta pelo PRAGMA; senão o Alembic entende que
        # há uma transação externa e não confirma a migration.
        connection.commit()
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite não suporta ALTER TABLE completo; o modo batch recria a tabela com segurança
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
        if sqlite:
            broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if broken:
                raise RuntimeError(f"Migration deixaria chaves estrangeiras inválidas: {broken[:5]}")
    if sqlite:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
