from typing import Any

from dmguard.x_client import XClient


WEBHOOK_PATH = "/webhooks/x"


def build_public_webhook_url(public_hostname: str) -> str:
    return f"https://{public_hostname}{WEBHOOK_PATH}"


async def ensure_webhook_registered(
    client: XClient,
    webhook_url: str,
) -> dict[str, object]:
    webhook = await _find_matching_webhook(client, webhook_url)
    if webhook is not None and webhook["valid"] is True:
        return webhook

    if webhook is not None:
        await client.put(f"/2/webhooks/{webhook['id']}")
        webhook = await _find_matching_webhook(client, webhook_url)
        if webhook is not None and webhook["valid"] is True:
            return webhook
        raise ValueError(f"X webhook is not valid after validation: {webhook_url}")

    response = await client.post("/2/webhooks", json={"url": webhook_url})
    created = _normalize_webhook(_extract_webhook_object(response.json()))
    if created["url"] != webhook_url:
        raise ValueError(f"X webhook response URL mismatch: {created['url']}")
    if created["valid"] is not True:
        raise ValueError(f"X webhook is not valid after creation: {webhook_url}")
    return created


async def _find_matching_webhook(
    client: XClient,
    webhook_url: str,
) -> dict[str, object] | None:
    response = await client.get("/2/webhooks")
    payload = response.json()
    data = payload.get("data", [])
    if not isinstance(data, list):
        raise ValueError("X webhook list response must contain a data list")

    for item in data:
        if not isinstance(item, dict):
            continue
        webhook = _normalize_webhook(item)
        if webhook["url"] == webhook_url:
            return webhook

    return None


def _extract_webhook_object(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, dict):
        return data
    if "id" in payload and "url" in payload:
        return payload
    raise ValueError("X webhook response did not contain a webhook object")


def _normalize_webhook(payload: dict[str, Any]) -> dict[str, object]:
    webhook_id = payload.get("id")
    url = payload.get("url")
    valid = payload.get("valid")
    created_at = payload.get("created_at")

    if not isinstance(webhook_id, str) or not webhook_id:
        raise ValueError("X webhook payload missing string id")
    if not isinstance(url, str) or not url:
        raise ValueError("X webhook payload missing string url")
    if not isinstance(valid, bool):
        raise ValueError("X webhook payload missing boolean valid flag")

    webhook: dict[str, object] = {
        "id": webhook_id,
        "url": url,
        "valid": valid,
    }
    if isinstance(created_at, str) and created_at:
        webhook["created_at"] = created_at
    return webhook


__all__ = [
    "WEBHOOK_PATH",
    "build_public_webhook_url",
    "ensure_webhook_registered",
]
