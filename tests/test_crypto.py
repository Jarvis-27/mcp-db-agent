"""Tests for src/auth/crypto.py — CredentialCipher encrypt/decrypt and key rotation."""

import pytest
from cryptography.fernet import Fernet

from src.auth.crypto import CredentialCipher, CredentialDecryptError


def make_key() -> str:
    return Fernet.generate_key().decode()


# ---------------------------------------------------------------------------
# Basic encrypt / decrypt round-trip
# ---------------------------------------------------------------------------


def test_encrypt_decrypt_roundtrip():
    key = make_key()
    cipher = CredentialCipher([key])
    plaintext = "postgresql://user:secret@db.example.com/prod"
    assert cipher.decrypt(cipher.encrypt(plaintext)) == plaintext


def test_encrypt_produces_different_tokens():
    """MultiFernet uses random IVs so two encryptions of the same value differ."""
    key = make_key()
    cipher = CredentialCipher([key])
    t1 = cipher.encrypt("secret")
    t2 = cipher.encrypt("secret")
    assert t1 != t2


def test_empty_string_roundtrip():
    key = make_key()
    cipher = CredentialCipher([key])
    assert cipher.decrypt(cipher.encrypt("")) == ""


# ---------------------------------------------------------------------------
# Wrong key raises CredentialDecryptError
# ---------------------------------------------------------------------------


def test_wrong_key_raises():
    key1 = make_key()
    key2 = make_key()
    cipher1 = CredentialCipher([key1])
    cipher2 = CredentialCipher([key2])
    token = cipher1.encrypt("secret")
    with pytest.raises(CredentialDecryptError):
        cipher2.decrypt(token)


def test_tampered_token_raises():
    key = make_key()
    cipher = CredentialCipher([key])
    token = cipher.encrypt("secret")
    bad_token = token[:-4] + "XXXX"
    with pytest.raises(CredentialDecryptError):
        cipher.decrypt(bad_token)


# ---------------------------------------------------------------------------
# Empty keys list
# ---------------------------------------------------------------------------


def test_empty_keys_raises():
    with pytest.raises(ValueError, match="At least one encryption key"):
        CredentialCipher([])


# ---------------------------------------------------------------------------
# Key rotation — MultiFernet rotation
# ---------------------------------------------------------------------------


def test_key_rotation_old_ciphertext_still_decryptable():
    """Ciphertext made with key1 is still decryptable after key2 is prepended."""
    key1 = make_key()
    key2 = make_key()

    # Encrypt with key1 only
    cipher_old = CredentialCipher([key1])
    token = cipher_old.encrypt("my-api-key")

    # New cipher: key2 is primary (encryption), key1 is fallback (decryption)
    cipher_new = CredentialCipher([key2, key1])
    assert cipher_new.decrypt(token) == "my-api-key"


def test_key_rotation_new_ciphertext_uses_new_key():
    """After rotation, new encryptions use the first (new) key."""
    key1 = make_key()
    key2 = make_key()

    cipher_rotated = CredentialCipher([key2, key1])
    token = cipher_rotated.encrypt("new-secret")

    # Old cipher with only key2 can decrypt the new token
    cipher_key2_only = CredentialCipher([key2])
    assert cipher_key2_only.decrypt(token) == "new-secret"

    # Old cipher with only key1 cannot decrypt the new token
    cipher_key1_only = CredentialCipher([key1])
    with pytest.raises(CredentialDecryptError):
        cipher_key1_only.decrypt(token)
