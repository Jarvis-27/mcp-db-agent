"""Credential encryption/decryption using MultiFernet for key rotation support."""

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class CredentialDecryptError(Exception):
    """Raised when decryption fails (wrong key, tampered data, etc.)."""


class CredentialCipher:
    """Thin wrapper around MultiFernet.

    Accepts a list of base64-encoded Fernet keys (comma-separated list from
    settings.credential_encryption_keys). The first key is used for encryption;
    all keys can decrypt, enabling zero-downtime key rotation.

    Raises ValueError if keys is empty.
    """

    def __init__(self, keys: list[str]) -> None:
        if not keys:
            raise ValueError(
                "At least one encryption key is required. "
                'Generate one with: python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
        self._fernet = MultiFernet([Fernet(k.encode()) for k in keys])

    def encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext string. Returns a base64 token string."""
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a ciphertext token. Raises CredentialDecryptError on failure."""
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except (InvalidToken, Exception) as exc:
            raise CredentialDecryptError("Failed to decrypt credential") from exc
