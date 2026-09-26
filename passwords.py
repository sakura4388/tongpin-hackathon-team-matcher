"""Password hashing shared by the local Flask app and Cloudflare Worker."""

import secrets

from werkzeug.security import check_password_hash, generate_password_hash


WORKER_PBKDF2_ITERATIONS = 100_000


def hash_password(password, *, cloudflare=False):
    if not cloudflare:
        return generate_password_hash(password, method="pbkdf2:sha256:600000")

    salt = _random_salt()
    digest = _webcrypto_pbkdf2(password, salt, WORKER_PBKDF2_ITERATIONS)
    return f"pbkdf2:sha256:{WORKER_PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(stored_hash, password, *, cloudflare=False):
    if not cloudflare:
        return check_password_hash(stored_hash, password)

    try:
        method, salt_hex, digest_hex = stored_hash.split("$", 2)
        algorithm, digest, iteration_count = method.split(":")
        if algorithm != "pbkdf2" or digest != "sha256":
            return False
        iterations = int(iteration_count)
        if not 100_000 <= iterations <= WORKER_PBKDF2_ITERATIONS:
            return False
        actual = _webcrypto_pbkdf2(password, bytes.fromhex(salt_hex), iterations)
        return secrets.compare_digest(actual.hex(), digest_hex)
    except (TypeError, ValueError):
        return False


def _random_salt():
    from js import Uint8Array, crypto

    salt = crypto.getRandomValues(Uint8Array.new(16))
    return bytes(list(salt))


def _webcrypto_pbkdf2(password, salt, iterations):
    from js import Object, TextEncoder, Uint8Array, crypto
    from pyodide.ffi import run_sync, to_js

    key = run_sync(crypto.subtle.importKey(
        "raw",
        TextEncoder.new().encode(password),
        to_js({"name": "PBKDF2"}, dict_converter=Object.fromEntries),
        False,
        to_js(["deriveBits"]),
    ))
    salt_array = Uint8Array.new(len(salt))
    for index, value in enumerate(salt):
        salt_array[index] = value
    parameters = to_js({
        "name": "PBKDF2",
        "salt": salt_array,
        "iterations": iterations,
        "hash": "SHA-256",
    }, dict_converter=Object.fromEntries)
    derived = run_sync(crypto.subtle.deriveBits(parameters, key, 256))
    return bytes(list(Uint8Array.new(derived)))
