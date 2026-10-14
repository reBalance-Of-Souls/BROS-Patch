"""The invite-only beta's cryptography: codes, keys and file encryption (format BROSBETA1).

Standard library only (hashlib, hmac, secrets), so the public launcher needs nothing installed. The same format is
implemented a second time, independently, in the keygen (Zig, keygen/src/main.zig); test_beta_crypto.py checks that
the two agree byte for byte. Change one, change both, and bump the format.

PRIMITIVES
  X25519         RFC 7748 (checked against its test vectors).
  XOF            SHAKE256 (FIPS 202).
  MAC            HMAC-SHA256 (RFC 2104).

  kdf(label, *parts, n)  SHAKE256( "BROSBETA1" 00 label 00 || for each part: u32be(len) part ), first n bytes.

  SIV seal (deterministic authenticated encryption; no nonce, so it cannot be misused by a repeated one):
      mk  = kdf("siv-mac", key)            ek = kdf("siv-enc", key)
      tag = HMAC-SHA256(mk, u64be(len(ad)) || ad || plaintext)[:taglen]
      ct  = plaintext XOR keystream(ek, tag)
      out = tag || ct
  keystream(ek, tag): 1 MiB chunks; chunk i = SHAKE256("BROSBETA1" 00 "ks" 00 || ek || tag || u64be(i)).
  Open recomputes the keystream from the tag, decrypts, and accepts only if the tag matches (constant-time compare).

KEYS
  master (32 random bytes, only in the keygen)
    auth key   K_priv = kdf("auth-priv", master, n=32)          K_pub  = X25519(K_priv, 9)
    slot i     seed_i = kdf("slot-seed", master, u16be(i), n=16)
               S_priv = kdf("slot-priv", seed_i, n=32)           S_pub  = X25519(S_priv, 9)
  install      I_priv = 32 random bytes, made once per install    I_pub  = X25519(I_priv, 9)

CODES (Crockford base32: 0-9 A-Z without I L O U; '-' and spaces ignored, O read as 0, I and L as 1)
  request     01 || I_pub || kdf("req-check", 01 || I_pub, n=2)                       35 bytes, 56 characters
  activation  01 || u16be(slot) || SIV(key, ad = 01 || u16be(slot) || I_pub, seed_slot, taglen 12)
                                                                                      31 bytes, 50 characters
              key = kdf("act-key", X25519(K_priv, I_pub), K_pub, I_pub)  -- the launcher computes the same
              shared secret as X25519(I_priv, K_pub).

PER BUILD
  build key B (32 random bytes); build id (16 random bytes); E_priv random, E_pub = X25519(E_priv, 9)
  keyring entry for slot i:  SIV(kdf("ring-key", X25519(E_priv, S_pub_i), E_pub, S_pub_i, build_id),
                                 ad = build_id || u16be(i), B, taglen 16)                      48 bytes
  keyring file:  "BBKR1" 00 || build_id || E_pub || u16be(count) || count x (u16be(slot) || entry)
  manifest file: "BBMF1" 00 || build_id || SIV(kdf("manifest-key", B, build_id), ad = "BBMF1" || build_id, json)
  blob:          SIV(file_key, ad = "BBBLOB1", file bytes, taglen 16); file_key travels in the manifest;
                 blob id = sha256(blob) hex
"""

import hashlib
import hmac
import os
import secrets
import time

MAGIC = b"BROSBETA1"
CHUNK = 1 << 20

# ---------------------------------------------------------------------------------------------------------------------
# KDF and SIV
# ---------------------------------------------------------------------------------------------------------------------


def kdf(label, *parts, n=32):
    h = hashlib.shake_256()
    h.update(MAGIC + b"\x00" + label.encode("ascii") + b"\x00")
    for p in parts:
        h.update(len(p).to_bytes(4, "big") + p)
    return h.digest(n)


def _keystream_chunk(ek, tag, index, size):
    return hashlib.shake_256(MAGIC + b"\x00ks\x00" + ek + tag + index.to_bytes(8, "big")).digest(size)


def _xor(a, b):
    n = len(a)
    return (int.from_bytes(a, "little") ^ int.from_bytes(b, "little")).to_bytes(n, "little")


def _keys(key):
    if len(key) != 32:
        raise ValueError("SIV key must be 32 bytes")
    return kdf("siv-mac", key), kdf("siv-enc", key)


def _mac_start(mk, ad):
    m = hmac.new(mk, digestmod=hashlib.sha256)
    m.update(len(ad).to_bytes(8, "big") + ad)
    return m


def siv_seal(key, ad, pt, taglen=16):
    mk, ek = _keys(key)
    m = _mac_start(mk, ad)
    m.update(pt)
    tag = m.digest()[:taglen]
    out = bytearray(tag)
    for i in range(0, len(pt), CHUNK):
        c = pt[i:i + CHUNK]
        out += _xor(c, _keystream_chunk(ek, tag, i // CHUNK, len(c)))
    return bytes(out)


class OpenError(Exception):
    """A tag did not match: wrong key, wrong code, or damaged data."""


def siv_open(key, ad, sealed, taglen=16):
    if len(sealed) < taglen:
        raise OpenError("too short")
    mk, ek = _keys(key)
    tag, ct = sealed[:taglen], sealed[taglen:]
    pt = bytearray()
    m = _mac_start(mk, ad)
    for i in range(0, len(ct), CHUNK):
        c = ct[i:i + CHUNK]
        p = _xor(c, _keystream_chunk(ek, tag, i // CHUNK, len(c)))
        m.update(p)
        pt += p
    if not hmac.compare_digest(m.digest()[:taglen], tag):
        raise OpenError("authentication failed")
    return bytes(pt)


def seal_file(key, ad, src_path, dst_path, taglen=16):
    """Two passes over the source (MAC, then encrypt), written to dst_path.tmp and moved into place.
    Returns (sha256 of the plaintext, sha256 of the sealed output, sealed size)."""
    mk, ek = _keys(key)
    m = _mac_start(mk, ad)
    ph = hashlib.sha256()
    with open(src_path, "rb") as f:
        for c in iter(lambda: f.read(CHUNK), b""):
            m.update(c)
            ph.update(c)
    tag = m.digest()[:taglen]
    oh = hashlib.sha256(tag)
    ph2 = hashlib.sha256()
    size = taglen
    tmp = dst_path + ".tmp"
    with open(src_path, "rb") as f, open(tmp, "wb") as o:
        o.write(tag)
        i = 0
        for c in iter(lambda: f.read(CHUNK), b""):
            ph2.update(c)
            e = _xor(c, _keystream_chunk(ek, tag, i, len(c)))
            o.write(e)
            oh.update(e)
            size += len(e)
            i += 1
    if ph2.digest() != ph.digest():
        raise ValueError("the file changed between the two passes of seal_file: %s" % src_path)
    replace_retry(tmp, dst_path)
    return ph.hexdigest(), oh.hexdigest(), size


def replace_retry(src, dst, attempts=12):
    """os.replace, retried: on Windows an antivirus scanning a file it just saw written holds it open for a moment,
    and the move fails with 'Access is denied' (seen on this project's VM, 2026-10-14)."""
    for i in range(attempts):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.05 * (i + 1))


def open_stream(key, ad, read, dst_path, total, taglen=16, want_sha256=None, tmp_path=None):
    """Decrypt `total` sealed bytes delivered by read(n) into dst_path, through a temporary file (tmp_path, by
    default dst_path.bbtmp; it must be on the same drive). The temporary file is moved into place only when the tag
    matches and, if given, the plaintext's sha256 is want_sha256; otherwise it is removed and OpenError raised.
    Returns the plaintext's sha256."""
    mk, ek = _keys(key)
    tag = read(taglen)
    if len(tag) != taglen:
        raise OpenError("truncated")
    left = total - taglen
    m = _mac_start(mk, ad)
    ph = hashlib.sha256()
    tmp = tmp_path or (dst_path + ".bbtmp")
    ok = False
    try:
        with open(tmp, "wb") as o:
            i = 0
            while left > 0:
                c = read(min(CHUNK, left))
                if not c:
                    raise OpenError("truncated")
                if len(c) != min(CHUNK, left):
                    # read() may return less than asked; keep chunk boundaries exact
                    while len(c) < min(CHUNK, left):
                        more = read(min(CHUNK, left) - len(c))
                        if not more:
                            raise OpenError("truncated")
                        c += more
                p = _xor(c, _keystream_chunk(ek, tag, i, len(c)))
                m.update(p)
                ph.update(p)
                o.write(p)
                left -= len(c)
                i += 1
        if not hmac.compare_digest(m.digest()[:taglen], tag):
            raise OpenError("authentication failed")
        digest = ph.hexdigest()
        if want_sha256 is not None and digest != want_sha256:
            raise OpenError("content hash mismatch")
        replace_retry(tmp, dst_path)
        ok = True
        return digest
    finally:
        if not ok and os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ---------------------------------------------------------------------------------------------------------------------
# X25519 (RFC 7748). Not constant-time: it only ever runs on the user's own machine, on the user's own keys.
# ---------------------------------------------------------------------------------------------------------------------

_P = 2 ** 255 - 19
_A24 = 121665
BASE = (9).to_bytes(32, "little")


def _clamp(k):
    k = bytearray(k)
    k[0] &= 248
    k[31] &= 127
    k[31] |= 64
    return int.from_bytes(k, "little")


def x25519(k, u):
    if len(k) != 32 or len(u) != 32:
        raise ValueError("X25519 takes 32-byte inputs")
    k = _clamp(k)
    ub = bytearray(u)
    ub[31] &= 127
    x1 = int.from_bytes(ub, "little") % _P
    x2, z2, x3, z3, swap = 1, 0, x1, 1, 0
    for t in range(254, -1, -1):
        kt = (k >> t) & 1
        swap ^= kt
        if swap:
            x2, x3, z2, z3 = x3, x2, z3, z2
        swap = kt
        a = (x2 + z2) % _P
        aa = a * a % _P
        b = (x2 - z2) % _P
        bb = b * b % _P
        e = (aa - bb) % _P
        c = (x3 + z3) % _P
        d = (x3 - z3) % _P
        da = d * a % _P
        cb = c * b % _P
        x3 = (da + cb) ** 2 % _P
        z3 = x1 * (da - cb) ** 2 % _P
        x2 = aa * bb % _P
        z2 = e * (aa + _A24 * e) % _P
    if swap:
        x2, x3, z2, z3 = x3, x2, z3, z2
    return (x2 * pow(z2, _P - 2, _P) % _P).to_bytes(32, "little")


def x25519_shared(k, u):
    s = x25519(k, u)
    if s == bytes(32):
        raise OpenError("degenerate public key")
    return s


def public_key(priv):
    return x25519(priv, BASE)


# ---------------------------------------------------------------------------------------------------------------------
# Crockford base32
# ---------------------------------------------------------------------------------------------------------------------

_ALPHA = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_REV = {c: i for i, c in enumerate(_ALPHA)}
_REV.update({"O": 0, "I": 1, "L": 1})


def b32encode(data):
    bits = int.from_bytes(data, "big")
    nbits = len(data) * 8
    nchar = (nbits + 4) // 5
    bits <<= nchar * 5 - nbits
    return "".join(_ALPHA[(bits >> (5 * (nchar - 1 - i))) & 31] for i in range(nchar))


class CodeError(ValueError):
    """A code that is not well formed: wrong length, a character that is not in the alphabet, a bad check."""


def b32decode(text, nbytes):
    s = "".join(ch for ch in text.upper() if ch not in "- \t\r\n")
    nchar = (nbytes * 8 + 4) // 5
    if len(s) != nchar:
        raise CodeError("expected %d characters, got %d" % (nchar, len(s)))
    v = 0
    for ch in s:
        if ch not in _REV:
            raise CodeError("'%s' is not a code character" % ch)
        v = (v << 5) | _REV[ch]
    pad = nchar * 5 - nbytes * 8
    if v & ((1 << pad) - 1):
        raise CodeError("not a valid code (padding)")
    return (v >> pad).to_bytes(nbytes, "big")


def group(s, n):
    return "-".join(s[i:i + n] for i in range(0, len(s), n))


# ---------------------------------------------------------------------------------------------------------------------
# Codes
# ---------------------------------------------------------------------------------------------------------------------

CODE_VERSION = b"\x01"
REQUEST_LEN = 35
ACTIVATION_LEN = 31


def request_code(i_pub):
    body = CODE_VERSION + i_pub
    return group(b32encode(body + kdf("req-check", body, n=2)), 4)


def parse_request(text):
    raw = b32decode(text, REQUEST_LEN)
    body, check = raw[:33], raw[33:]
    if body[:1] != CODE_VERSION:
        raise CodeError("request code from an unknown launcher version")
    if not hmac.compare_digest(kdf("req-check", body, n=2), check):
        raise CodeError("request code mistyped (check failed)")
    return body[1:]


def _act_key(shared, k_pub, i_pub):
    return kdf("act-key", shared, k_pub, i_pub)


def slot_seed(master, slot):
    return kdf("slot-seed", master, slot.to_bytes(2, "big"), n=16)


def slot_priv(seed):
    return kdf("slot-priv", seed, n=32)


def auth_priv(master):
    return kdf("auth-priv", master, n=32)


def make_activation(master, slot, i_pub):
    """The keygen's side (the Zig keygen does the same; this one is for tests and the build's self-check)."""
    k_priv = auth_priv(master)
    k_pub = public_key(k_priv)
    key = _act_key(x25519_shared(k_priv, i_pub), k_pub, i_pub)
    head = CODE_VERSION + slot.to_bytes(2, "big")
    sealed = siv_seal(key, head + i_pub, slot_seed(master, slot), taglen=12)
    return group(b32encode(head + sealed), 5)


def open_activation(text, i_priv, k_pub):
    """The launcher's side: (slot, seed). Raises CodeError / OpenError."""
    raw = b32decode(text, ACTIVATION_LEN)
    if raw[:1] != CODE_VERSION:
        raise CodeError("activation code from an unknown keygen version")
    head, sealed = raw[:3], raw[3:]
    slot = int.from_bytes(head[1:3], "big")
    i_pub = public_key(i_priv)
    key = _act_key(x25519_shared(i_priv, k_pub), k_pub, i_pub)
    seed = siv_open(key, head + i_pub, sealed, taglen=12)
    return slot, seed


# ---------------------------------------------------------------------------------------------------------------------
# Keyring and manifest
# ---------------------------------------------------------------------------------------------------------------------

KR_MAGIC = b"BBKR1\x00"
MF_MAGIC = b"BBMF1\x00"
BLOB_AD = b"BBBLOB1"


def make_keyring(build_id, build_key, slot_pubs, e_priv=None):
    """slot_pubs: {slot: S_pub}. Returns the keyring file's bytes."""
    e_priv = e_priv or secrets.token_bytes(32)
    e_pub = public_key(e_priv)
    out = bytearray(KR_MAGIC + build_id + e_pub + len(slot_pubs).to_bytes(2, "big"))
    for slot in sorted(slot_pubs):
        s_pub = slot_pubs[slot]
        wk = kdf("ring-key", x25519_shared(e_priv, s_pub), e_pub, s_pub, build_id)
        out += slot.to_bytes(2, "big") + siv_seal(wk, build_id + slot.to_bytes(2, "big"), build_key, taglen=16)
    return bytes(out)


def open_keyring(data, slot, seed):
    """(build_id, build key) for this slot. Raises OpenError when the slot is not in the keyring (revoked) or the
    seed is not the slot's."""
    if data[:6] != KR_MAGIC or len(data) < 56:
        raise OpenError("not a keyring")
    build_id, e_pub = data[6:22], data[22:54]
    count = int.from_bytes(data[54:56], "big")
    if len(data) != 56 + count * 50:
        raise OpenError("keyring size mismatch")
    priv = slot_priv(seed)
    s_pub = public_key(priv)
    for i in range(count):
        off = 56 + i * 50
        if int.from_bytes(data[off:off + 2], "big") != slot:
            continue
        wk = kdf("ring-key", x25519_shared(priv, e_pub), e_pub, s_pub, build_id)
        return build_id, siv_open(wk, build_id + slot.to_bytes(2, "big"), data[off + 2:off + 50], taglen=16)
    raise OpenError("this tester slot has no key in this build")


def keyring_build_id(data):
    if data[:6] != KR_MAGIC:
        raise OpenError("not a keyring")
    return data[6:22]


def seal_manifest(build_id, build_key, json_bytes):
    key = kdf("manifest-key", build_key, build_id)
    return MF_MAGIC + build_id + siv_seal(key, b"BBMF1" + build_id, json_bytes)


def open_manifest(data, build_id, build_key):
    if data[:6] != MF_MAGIC or data[6:22] != build_id:
        raise OpenError("manifest does not belong to this build")
    return siv_open(kdf("manifest-key", build_key, build_id), b"BBMF1" + build_id, data[22:])
