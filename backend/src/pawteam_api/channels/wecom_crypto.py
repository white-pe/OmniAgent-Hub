"""Enterprise WeChat callback signature and AES codec.

The implementation follows the callback protocol used by WeCom self-built apps:
SHA-1 over sorted fields, AES-256-CBC, and PKCS#7 padding with a 32-byte block.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


class WeComCryptoError(ValueError):
    pass


class WeComCrypto:
    def __init__(self, token: str, encoding_aes_key: str, receive_id: str) -> None:
        try:
            self.key = base64.b64decode(f"{encoding_aes_key}=")
        except Exception as exc:  # pragma: no cover - library-specific decoder errors
            raise WeComCryptoError("Invalid EncodingAESKey") from exc
        if len(self.key) != 32:
            raise WeComCryptoError("EncodingAESKey must decode to 32 bytes")
        self.token = token
        self.receive_id = receive_id

    def signature(self, timestamp: str, nonce: str, encrypted: str) -> str:
        joined = "".join(sorted((self.token, timestamp, nonce, encrypted)))
        return hashlib.sha1(joined.encode("utf-8"), usedforsecurity=False).hexdigest()

    def verify_signature(
        self, signature: str, timestamp: str, nonce: str, encrypted: str
    ) -> None:
        expected = self.signature(timestamp, nonce, encrypted)
        if not hmac.compare_digest(expected, signature):
            raise WeComCryptoError("Invalid msg_signature")

    def decrypt(self, encrypted: str) -> bytes:
        try:
            ciphertext = base64.b64decode(encrypted)
            decryptor = Cipher(
                algorithms.AES(self.key), modes.CBC(self.key[:16])
            ).decryptor()
            padded = decryptor.update(ciphertext) + decryptor.finalize()
            plain = self._unpad(padded)
        except WeComCryptoError:
            raise
        except Exception as exc:
            raise WeComCryptoError("Unable to decrypt callback payload") from exc
        if len(plain) < 20:
            raise WeComCryptoError("Decrypted callback payload is too short")
        length = struct.unpack(">I", plain[16:20])[0]
        message_end = 20 + length
        if message_end > len(plain):
            raise WeComCryptoError("Invalid callback message length")
        message = plain[20:message_end]
        received_id = plain[message_end:].decode("utf-8")
        if received_id != self.receive_id:
            raise WeComCryptoError("Callback receive ID does not match CorpID")
        return message

    def verify_and_decrypt(
        self,
        *,
        signature: str,
        timestamp: str,
        nonce: str,
        encrypted: str,
    ) -> bytes:
        self.verify_signature(signature, timestamp, nonce, encrypted)
        return self.decrypt(encrypted)

    def encrypt(self, message: bytes, *, random_bytes: bytes | None = None) -> str:
        prefix = random_bytes if random_bytes is not None else os.urandom(16)
        if len(prefix) != 16:
            raise WeComCryptoError("Random prefix must contain 16 bytes")
        plain = (
            prefix
            + struct.pack(">I", len(message))
            + message
            + self.receive_id.encode("utf-8")
        )
        encryptor = Cipher(
            algorithms.AES(self.key), modes.CBC(self.key[:16])
        ).encryptor()
        ciphertext = encryptor.update(self._pad(plain)) + encryptor.finalize()
        return base64.b64encode(ciphertext).decode("ascii")

    @staticmethod
    def _pad(value: bytes) -> bytes:
        padding = 32 - (len(value) % 32)
        return value + bytes((padding,)) * padding

    @staticmethod
    def _unpad(value: bytes) -> bytes:
        if not value:
            raise WeComCryptoError("Empty decrypted callback")
        padding = value[-1]
        invalid_bytes = value[-padding:] != bytes((padding,)) * padding
        if padding < 1 or padding > 32 or invalid_bytes:
            raise WeComCryptoError("Invalid PKCS#7 padding")
        return value[:-padding]
