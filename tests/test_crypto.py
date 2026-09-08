import pytest
from cryptography.exceptions import InvalidTag

from ilifetrack.crypto import CryptoBox, KeyStore


class MemoryKeyStore(KeyStore):
    def __init__(self):
        self.value = None

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def test_load_or_create_reuses_key():
    store = MemoryKeyStore()
    first = CryptoBox.load_or_create(store)
    second = CryptoBox.load_or_create(store)
    assert first == second
    assert store.value is not None


def test_authenticated_encryption_detects_tampering():
    box = CryptoBox.from_master_key(b"m" * 32)
    aad = b"point:device:123"
    nonce, ciphertext = box.encrypt_json({"latitude": 31.2304}, aad)
    assert box.decrypt_json(nonce, ciphertext, aad) == {"latitude": 31.2304}

    tampered = ciphertext[:-1] + bytes([ciphertext[-1] ^ 1])
    with pytest.raises(InvalidTag):
        box.decrypt_json(nonce, tampered, aad)


def test_keyed_ids_are_stable_and_namespaced():
    box = CryptoBox.from_master_key(b"k" * 32)
    assert box.keyed_id("device", "abc") == box.keyed_id("device", "abc")
    assert box.keyed_id("device", "abc") != box.keyed_id("point", "abc")
