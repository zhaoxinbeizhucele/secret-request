import base64

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_SECRET_BYTES = 65536


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def decode(value: str) -> bytes:
    return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)


def new_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=3072)


def public_jwk(key) -> dict:
    numbers = key.public_key().public_numbers()
    return {"kty": "RSA", "e": "AQAB", "n": encode(numbers.n.to_bytes(384, "big"))}


def validate_jwk(jwk: dict):
    if set(jwk) != {"kty", "e", "n"} or jwk["kty"] != "RSA" or jwk["e"] != "AQAB":
        raise ValueError("invalid public key")
    modulus = decode(jwk["n"])
    if len(modulus) != 384 or modulus[0] < 128:
        raise ValueError("invalid public key size")
    return rsa.RSAPublicNumbers(65537, int.from_bytes(modulus, "big")).public_key()


def aad(request_id: str) -> bytes:
    return ("secret-request:v1:" + request_id).encode("ascii")


def validate_envelope(envelope: dict) -> dict:
    if not isinstance(envelope, dict) or set(envelope) != {"v", "wrapped_key", "nonce", "ciphertext"} or type(envelope["v"]) is not int or envelope["v"] != 1:
        raise ValueError("invalid envelope")
    if len(decode(envelope["wrapped_key"])) != 384 or len(decode(envelope["nonce"])) != 12:
        raise ValueError("invalid envelope lengths")
    if not 17 <= len(decode(envelope["ciphertext"])) <= MAX_SECRET_BYTES + 16:
        raise ValueError("invalid ciphertext size")
    return envelope


def decrypt(key, request_id: str, envelope: dict) -> str:
    validate_envelope(envelope)
    aes_key = key.decrypt(decode(envelope["wrapped_key"]), padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    if len(aes_key) != 32:
        raise ValueError("invalid encryption key")
    value = AESGCM(aes_key).decrypt(decode(envelope["nonce"]), decode(envelope["ciphertext"]), aad(request_id)).decode("utf-8")
    if not value or "\x00" in value:
        raise ValueError("empty or unsupported secret")
    return value
