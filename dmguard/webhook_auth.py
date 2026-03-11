import base64
import hashlib
import hmac


SIGNATURE_PREFIX = "sha256="


def verify_x_signature(
    raw_body: bytes,
    signature_header: str,
    consumer_secret: str,
) -> bool:
    if not signature_header.startswith(SIGNATURE_PREFIX):
        return False

    digest = hmac.new(
        consumer_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).digest()
    expected_signature = SIGNATURE_PREFIX + base64.b64encode(digest).decode("ascii")

    return hmac.compare_digest(signature_header, expected_signature)


__all__ = ["verify_x_signature"]
