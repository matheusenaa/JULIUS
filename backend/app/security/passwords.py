from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# Parâmetros padrão do argon2-cffi seguem a recomendação RFC 9106 (Argon2id)
_hasher = PasswordHasher()

# Hash fixo usado quando o e-mail não existe: mantém o tempo de resposta igual
# e impede descobrir quais e-mails estão cadastrados.
_DUMMY_HASH = _hasher.hash("julius-dummy-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)
