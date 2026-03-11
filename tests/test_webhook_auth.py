import base64
import hashlib
import hmac


def build_signature(raw_body: bytes, consumer_secret: str) -> str:
    digest = hmac.new(
        consumer_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).digest()
    encoded_digest = base64.b64encode(digest).decode("ascii")
    return f"sha256={encoded_digest}"


def test_verify_x_signature_returns_true_for_valid_signature() -> None:
    from dmguard.webhook_auth import verify_x_signature

    raw_body = b'{"event_id":"123"}'
    consumer_secret = "consumer-secret"
    signature_header = build_signature(raw_body, consumer_secret)

    assert verify_x_signature(raw_body, signature_header, consumer_secret) is True


def test_verify_x_signature_returns_false_for_tampered_body() -> None:
    from dmguard.webhook_auth import verify_x_signature

    consumer_secret = "consumer-secret"
    signature_header = build_signature(b'{"event_id":"123"}', consumer_secret)

    assert (
        verify_x_signature(b'{"event_id":"999"}', signature_header, consumer_secret)
        is False
    )


def test_verify_x_signature_returns_false_for_wrong_secret() -> None:
    from dmguard.webhook_auth import verify_x_signature

    raw_body = b'{"event_id":"123"}'
    signature_header = build_signature(raw_body, "correct-secret")

    assert verify_x_signature(raw_body, signature_header, "wrong-secret") is False


def test_verify_x_signature_returns_false_for_missing_header() -> None:
    from dmguard.webhook_auth import verify_x_signature

    assert verify_x_signature(b"payload", "", "consumer-secret") is False


def test_verify_x_signature_returns_false_for_malformed_header() -> None:
    from dmguard.webhook_auth import verify_x_signature

    malformed_header = "sha1=not-the-right-signature"

    assert verify_x_signature(b"payload", malformed_header, "consumer-secret") is False


def test_verify_x_signature_uses_compare_digest(
    monkeypatch,
) -> None:
    from dmguard import webhook_auth

    raw_body = b'{"event_id":"123"}'
    consumer_secret = "consumer-secret"
    expected_signature = build_signature(raw_body, consumer_secret)
    compare_digest_calls: list[tuple[str, str]] = []

    def fake_compare_digest(left: str, right: str) -> bool:
        compare_digest_calls.append((left, right))
        return True

    monkeypatch.setattr(webhook_auth.hmac, "compare_digest", fake_compare_digest)

    assert (
        webhook_auth.verify_x_signature(
            raw_body,
            expected_signature,
            consumer_secret,
        )
        is True
    )
    assert compare_digest_calls == [(expected_signature, expected_signature)]
