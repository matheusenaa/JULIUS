"""Cliente de sincronização: instalação LOCAL (banco no PC) ↔ servidor ONLINE.

COMPUTADOR → banco local → (push) → servidor → banco online → (pull) → outros dispositivos

- Registro "sujo" = version != synced_version (alterado aqui e ainda não enviado).
- Se o mesmo registro mudou aqui E no servidor, nada é sobrescrito: vira SyncConflict
  e o usuário escolhe qual versão fica.
- No primeiro vínculo, categorias e contas padrão iguais (mesmo nome/tipo) são unidas
  às do servidor, para não aparecer "Alimentação" duas vezes.
"""

import logging
from datetime import datetime

import httpx
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import CategorizationRule, Category, SyncConflict, SyncState, User
from app.models.base import utcnow
from app.services.categorizer import normalize
from app.services.sync import ENTITIES, MODEL_BY_NAME, apply_fields, serialize

log = logging.getLogger("julius.sync")
COOKIE, CSRF = "julius_session", "julius_csrf"


class SyncError(Exception):
    pass


class SyncClient:
    def __init__(self, db: Session, user: User, http: httpx.Client | None = None):
        self.db, self.user = db, user
        self.state = db.scalar(select(SyncState).where(SyncState.user_id == user.id))
        self.http = http

    # ---------- HTTP ----------
    def _client(self) -> httpx.Client:
        if self.http is None:
            if not self.state:
                raise SyncError("Instalação não vinculada a um servidor.")
            self.http = httpx.Client(base_url=self.state.remote_url, timeout=30)
        return self.http

    def _csrf(self) -> str:
        c = self._client()
        if not c.cookies.get(CSRF):
            try:
                c.get("/api/health")
            except httpx.HTTPError as exc:
                raise SyncError("Sem conexão com o servidor online.") from exc
        return c.cookies.get(CSRF) or ""

    def _request(self, method: str, path: str, **kw) -> dict:
        c = self._client()
        if self.state and self.state.remote_token:
            c.cookies.set(COOKIE, self.state.remote_token)
        headers = {"X-CSRF-Token": self._csrf()} if method != "GET" else {}
        try:
            r = c.request(method, path, headers=headers, **kw)
        except httpx.HTTPError as exc:
            raise SyncError("Sem conexão com o servidor online.") from exc
        if r.status_code == 401:
            raise SyncError("A sessão no servidor online expirou. Vincule novamente.")
        if r.status_code >= 400:
            raise SyncError(r.json().get("error", {}).get("message", f"Erro {r.status_code}"))
        return r.json() if r.content else {}

    # ---------- Vínculo ----------
    def link(self, remote_url: str, email: str, password: str) -> dict:
        if self.http is None:
            self.http = httpx.Client(base_url=remote_url.rstrip("/"), timeout=30)
        self.state = self.state or SyncState(
            user_id=self.user.id, remote_url=remote_url.rstrip("/"), remote_email=email
        )
        self.state.remote_url, self.state.remote_email = remote_url.rstrip("/"), email
        c = self._client()
        r = c.post(
            "/api/auth/login",
            json={"email": email, "password": password},
            headers={"X-CSRF-Token": self._csrf()},
        )
        if r.status_code != 200:
            raise SyncError(
                r.json().get("error", {}).get("message", "Não foi possível entrar no servidor online.")
            )
        self.state.remote_token = c.cookies.get(COOKIE)
        self.state.last_pull_cursor = None
        self.db.add(self.state)
        self.db.commit()
        remote = self._request("GET", "/api/sync/pull")
        self._merge_defaults(remote["changes"])
        return self.sync(first_pull=remote)

    def _merge_defaults(self, changes: dict) -> None:
        """Une categorias/contas locais nunca sincronizadas às equivalentes do servidor."""
        remote_cats = changes.get("categories", [])
        by_id = {c["id"]: c for c in remote_cats}

        def key(name: str, kind: str, parent: str | None) -> tuple:
            return (normalize(name), kind, normalize(parent) if parent else None)

        remote_keys = {
            key(
                c["name"], c["kind"], by_id[c["parent_id"]]["name"] if c.get("parent_id") in by_id else None
            ): c
            for c in remote_cats
            if not c.get("deleted_at")
        }
        local = {c.id: c for c in self.db.scalars(select(Category).where(Category.user_id == self.user.id))}
        mapping: dict[str, dict] = {}
        for cat in local.values():
            if cat.synced_version is not None or cat.id in by_id:
                continue
            parent = local.get(cat.parent_id)
            match = remote_keys.get(key(cat.name, cat.kind, parent.name if parent else None))
            if match:
                mapping[cat.id] = match
        self._remap("categories", mapping, ["category_id", "parent_id"])

        remote_accs = [a for a in changes.get("accounts", []) if not a.get("deleted_at")]
        acc_mapping = {}
        model = MODEL_BY_NAME["accounts"]
        for acc in self.db.scalars(select(model).where(model.user_id == self.user.id)):
            if acc.synced_version is not None:
                continue
            match = next(
                (
                    a
                    for a in remote_accs
                    if normalize(a["name"]) == normalize(acc.name) and a["kind"] == acc.kind
                ),
                None,
            )
            if match and match["id"] != acc.id:
                acc_mapping[acc.id] = match
        self._remap("accounts", acc_mapping, ["account_id", "to_account_id"])

    def _remap(self, entity: str, mapping: dict[str, dict], fk_columns: list[str]) -> None:
        if not mapping:
            return
        model = MODEL_BY_NAME[entity]
        # 1. cria localmente a versão do servidor (marcada como sincronizada)
        for remote in sorted(mapping.values(), key=lambda r: r.get("parent_id") is not None):
            if self.db.get(model, remote["id"]) is None:
                self._insert(model, remote)
        self.db.flush()
        # 2. aponta tudo que referenciava a cópia local para a do servidor
        for local_id, remote in mapping.items():
            for _, other in ENTITIES:
                for col in fk_columns:
                    if col in other.__table__.columns:
                        self.db.execute(
                            update(other).where(getattr(other, col) == local_id).values({col: remote["id"]})
                        )
            if entity == "categories":
                self.db.execute(
                    update(CategorizationRule)
                    .where(CategorizationRule.category_id == local_id)
                    .values(category_id=remote["id"])
                )
        # 3. remove a cópia local duplicada (nenhum dado aponta mais para ela)
        for local_id in mapping:
            obj = self.db.get(model, local_id)
            if obj is not None:
                self.db.delete(obj)
        self.db.commit()

    def _insert(self, model, data: dict):
        obj = model(id=data["id"], user_id=self.user.id)
        obj._sync_apply = True
        apply_fields(obj, model, data)
        obj.version = obj.synced_version = data["version"]
        self.db.add(obj)
        return obj

    # ---------- Ciclo ----------
    def _open_conflicts(self) -> set[str]:
        return set(
            self.db.scalars(
                select(SyncConflict.entity_id).where(
                    SyncConflict.user_id == self.user.id, SyncConflict.resolved_at.is_(None)
                )
            )
        )

    def _conflict(self, entity: str, local, remote: dict) -> None:
        if local.id in self._open_conflicts():
            return
        self.db.add(
            SyncConflict(
                user_id=self.user.id,
                entity=entity,
                entity_id=local.id,
                local_data=serialize(local),
                remote_data=remote,
            )
        )

    def push(self) -> dict:
        blocked = self._open_conflicts()
        changes = []
        for name, model in ENTITIES:
            q = (
                select(model)
                .where(model.user_id == self.user.id)
                .where((model.synced_version.is_(None)) | (model.version != model.synced_version))
            )
            for obj in self.db.scalars(q):
                if obj.id not in blocked:
                    changes.append(
                        {
                            "entity": name,
                            "id": obj.id,
                            "base_version": obj.synced_version,
                            "data": serialize(obj),
                        }
                    )
        if not changes:
            return {"sent": 0, "applied": 0, "conflicts": 0, "rejected": 0}
        results = self._request("POST", "/api/sync/push", json={"changes": changes})["results"]
        counts = {"sent": len(changes), "applied": 0, "conflicts": 0, "rejected": 0}
        for res in results:
            model = MODEL_BY_NAME.get(res["entity"])
            obj = self.db.get(model, res["id"]) if model else None
            if obj is None:
                continue
            if res["status"] == "applied":
                obj._sync_apply = True
                obj.version = obj.synced_version = res["version"]
                counts["applied"] += 1
            elif res["status"] == "conflict":
                self._conflict(res["entity"], obj, res["server"])
                counts["conflicts"] += 1
            else:
                counts["rejected"] += 1
                log.warning(
                    "Registro rejeitado pelo servidor: %s %s — %s", res["entity"], res["id"], res.get("error")
                )
        self.db.commit()
        return counts

    def pull(self, payload: dict | None = None) -> dict:
        if payload is None:
            params = {"since": self.state.last_pull_cursor} if self.state.last_pull_cursor else {}
            payload = self._request("GET", "/api/sync/pull", params=params)
        counts = {"received": 0, "conflicts": 0}
        for name, model in ENTITIES:
            for remote in payload["changes"].get(name, []):
                local = self.db.get(model, remote["id"])
                if local is None:
                    self._insert(model, remote)
                    counts["received"] += 1
                    continue
                dirty = local.synced_version is None or local.version != local.synced_version
                if not dirty:
                    if remote["version"] != local.version or serialize(local) != remote:
                        local._sync_apply = True
                        apply_fields(local, model, remote)
                        local.version = local.synced_version = remote["version"]
                        counts["received"] += 1
                elif remote["version"] != local.synced_version:
                    self._conflict(name, local, remote)
                    counts["conflicts"] += 1
            self.db.flush()
        self.state.last_pull_cursor = payload["server_time"]
        self.db.commit()
        return counts

    def sync(self, first_pull: dict | None = None) -> dict:
        """Envia primeiro (para o servidor detectar conflitos), depois recebe."""
        try:
            pushed = self.push() if first_pull is None else {"sent": 0}
            pulled = self.pull(first_pull)
            if first_pull is not None:
                pushed = self.push()
            self.state.last_sync_at, self.state.last_error = utcnow(), None
            self.db.commit()
            return {"pushed": pushed, "pulled": pulled, "conflicts": len(self._open_conflicts())}
        except SyncError as exc:
            self.db.rollback()
            if self.state is not None:
                self.state.last_error = str(exc)[:300]
                self.db.commit()
            raise

    def resolve(self, conflict: SyncConflict, choice: str) -> None:
        model = MODEL_BY_NAME[conflict.entity]
        local = self.db.get(model, conflict.entity_id)
        remote = conflict.remote_data
        if choice == "remote":
            if local is None:
                self._insert(model, remote)
            else:
                local._sync_apply = True
                apply_fields(local, model, remote)
                local.version = local.synced_version = remote["version"]
        elif local is not None:
            # Fica a versão daqui: "conhecemos" a do servidor; o próximo envio vence o conflito
            local._sync_apply = True
            local.synced_version = remote["version"]
            local.version = remote["version"] + 1
        conflict.resolved_at, conflict.resolution = utcnow(), choice
        self.db.commit()


def parse_cursor(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
