"""Authenticated encryption and keyed identifiers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from keyring.backends.macOS import Keyring as MacOSKeyring

KEYRING_SERVICE = "com.lifetrack.app"
KEYRING_ACCOUNT = "history-master-key-v1"
# This byte sequence is the stable v1 database-format salt. Keep it unchanged so
# existing encrypted history remains readable after application renames.
KEY_DERIVATION_SALT = bytes.fromhex("66696e64747261636b2d706f632d7631")


class KeyStore:
    def get(self) -> bytes | None:
        raise NotImplementedError

    def set(self, value: bytes) -> None:
        raise NotImplementedError


class MacOSKeyringStore(KeyStore):
    def __init__(self) -> None:
        # Bypass keyring's fallback chain so the master key can never land in
        # a plaintext keyrings.alt file.
        self.backend = MacOSKeyring()

    def get(self) -> bytes | None:
        encoded = self.backend.get_password(KEYRING_SERVICE, KEYRING_ACCOUNT)
        return base64.urlsafe_b64decode(encoded.encode("ascii")) if encoded else None

    def set(self, value: bytes) -> None:
        encoded = base64.urlsafe_b64encode(value).decode("ascii")
        self.backend.set_password(KEYRING_SERVICE, KEYRING_ACCOUNT, encoded)


@dataclass(frozen=True)
class CryptoBox:
    encryption_key: bytes
    index_key: bytes

    @classmethod
    def from_master_key(cls, master_key: bytes) -> CryptoBox:
        if len(master_key) != 32:
            raise ValueError("Master key must be exactly 32 bytes")
        derived = HKDF(
            algorithm=hashes.SHA256(),
            length=64,
            salt=KEY_DERIVATION_SALT,
            info=b"local-history-keys",
        ).derive(master_key)
        return cls(derived[:32], derived[32:])

    @classmethod
    def load_or_create(cls, store: KeyStore | None = None) -> CryptoBox:
        selected_store = store or MacOSKeyringStore()
        master_key = selected_store.get()
        if master_key is None:
            master_key = os.urandom(32)
            selected_store.set(master_key)
        return cls.from_master_key(master_key)

    def encrypt_json(
        self, value: Mapping[str, Any], associated_data: bytes
    ) -> tuple[bytes, bytes]:
        nonce = os.urandom(12)
        plaintext = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        ciphertext = AESGCM(self.encryption_key).encrypt(
            nonce, plaintext, associated_data
        )
        return nonce, ciphertext

    def decrypt_json(
        self, nonce: bytes, ciphertext: bytes, associated_data: bytes
    ) -> dict[str, Any]:
        plaintext = AESGCM(self.encryption_key).decrypt(
            nonce, ciphertext, associated_data
        )
        decoded = json.loads(plaintext.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise TypeError("Encrypted value is not an object")
        return decoded

    def keyed_id(self, namespace: str, value: str, length: int = 20) -> str:
        digest = hmac.new(
            self.index_key,
            f"{namespace}\x00{value}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return digest[:length]
