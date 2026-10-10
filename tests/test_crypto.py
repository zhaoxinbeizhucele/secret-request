import os
import pytest
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from secret_request.crypto import encode, decode, aad, decrypt, validate_envelope

def encrypt(key, rid, value):
    raw = os.urandom(32); nonce = os.urandom(12)
    return {"v":1, "wrapped_key":encode(key.public_key().encrypt(raw, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))), "nonce":encode(nonce), "ciphertext":encode(AESGCM(raw).encrypt(nonce, value.encode(), aad(rid)))}

@pytest.mark.parametrize("value", ["fake", " 测试🔒   ", "line1\r\nline2\n", "x"*65536], ids=["ascii", "unicode", "multiline", "maximum"])
def test_exact_roundtrip(key, value):
    assert decrypt(key, "test-id", encrypt(key,"test-id",value)) == value

def test_ciphertext_and_request_binding(key):
    envelope = encrypt(key,"one","fake")
    with pytest.raises(InvalidTag): decrypt(key,"other",envelope)
    ciphertext = bytearray(decode(envelope["ciphertext"])); ciphertext[0] ^= 1
    envelope["ciphertext"] = encode(ciphertext)
    with pytest.raises(InvalidTag): decrypt(key,"one",envelope)

@pytest.mark.parametrize("change", [{"v":True}, {"nonce":"bad"}, {"wrapped_key":"bad"}, {"ciphertext":"bad"}, {"extra":"fake"}])
def test_invalid_envelopes(key, change):
    with pytest.raises((ValueError, TypeError)): validate_envelope({**encrypt(key,"one","fake"), **change})

def test_nul_and_empty_fail(key):
    with pytest.raises(ValueError): decrypt(key,"one",encrypt(key,"one","a\x00b"))
    with pytest.raises(ValueError): decrypt(key,"one",encrypt(key,"one",""))
