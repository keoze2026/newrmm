import secrets

# Unambiguous alphabet: no 0/O, 1/I/L - the code is read aloud over the phone.
ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"


def generate_session_code(length: int) -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def generate_device_secret() -> str:
    return secrets.token_urlsafe(32)
