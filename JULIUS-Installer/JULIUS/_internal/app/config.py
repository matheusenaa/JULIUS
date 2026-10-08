# -*- coding: utf-8 -*-
"""Configuração lida de variáveis de ambiente / arquivo .env.

Nenhum segredo tem valor padrão utilizável em produção: se APP_ENV=production
e SECRET_KEY não estiver definido, a aplicação se recusa a iniciar.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: Literal["development", "test", "staging", "production"] = "development"
    secret_key: str = Field(default="dev-insecure-change-me", min_length=16)

    # SQLite local por padrão; em produção: postgresql+psycopg://user:pass@host/db
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'data' / 'julius.db').as_posix()}"

    # Fuso usado para "hoje" (o servidor na nuvem roda em UTC). "local" = fuso da máquina.
    timezone: str = "America/Sao_Paulo"

    session_days: int = 30
    allow_registration: bool = True

    # Rate limits (tentativas por janela). Aumente só em ambiente de teste.
    login_limit_per_15min: int = 8
    register_limit_per_hour: int = 5
    ai_limit_per_minute: int = 30

    # Origens extras permitidas (apenas para desenvolvimento com o Vite em outra porta)
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    # IA: gemini | openai | none
    ai_provider: Literal["gemini", "openai", "none"] = "none"
    ai_model: str = ""
    gemini_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    ai_timeout_seconds: float = 30.0
    # Instruções do seu agente (ex.: texto de um Gem do Gemini): arquivo .md/.txt lido pelo backend
    ai_agent_instructions_file: str = ""

    # Busca na web para o agente (opcional) - provedores gratuitos
    web_search_enabled: bool = False
    web_search_provider_order: str = "tavily,serper,brave,duckduckgo"
    tavily_api_key: str = ""
    serper_api_key: str = ""
    brave_api_key: str = ""
    google_search_api_key: str = ""
    google_cse_id: str = ""

    max_upload_mb: int = 8
    # Onde guardar arquivos de documentos: "db" (no banco) ou "local" (pasta STORAGE_DIR)
    storage_backend: Literal["db", "local"] = "db"
    storage_dir: str = ""

    # Instalação local (desktop): sincroniza com um servidor online (opcional)
    sync_interval_seconds: int = 120

    @property
    def is_production(self) -> bool:
        return self.app_env in ("production", "staging")

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @model_validator(mode="before")
    @classmethod
    def _empty_env_falls_back_to_default(cls, data: object) -> object:
        """`VAR=` (vazio) no .env é tratado como "não definido".

        Sem isso, `SECRET_KEY=` ou `DATABASE_URL=` vazio quebrava a inicialização
        em instalação nova, porque o valor vazio vence o padrão da classe.
        """
        if isinstance(data, dict):
            return {
                key: value
                for key, value in data.items()
                if not (isinstance(value, str) and value.strip() == "")
            }
        return data

    @model_validator(mode="after")
    def _check_production(self) -> "Settings":
        if self.is_production and self.secret_key.startswith("dev-insecure"):
            raise ValueError("SECRET_KEY precisa ser definido em produção.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
