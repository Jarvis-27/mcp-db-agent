"""Small Stripe API client for subscription checkout and portal sessions."""

from dataclasses import dataclass
from typing import Any

import httpx


class StripeAPIError(RuntimeError):
    """Raised when Stripe returns a non-2xx response."""


@dataclass(frozen=True)
class StripeCheckoutSession:
    id: str
    url: str


@dataclass(frozen=True)
class StripePortalSession:
    id: str
    url: str


class StripeClient:
    """HTTP wrapper around the minimal Stripe APIs this app needs for v1 billing."""

    def __init__(
        self,
        *,
        secret_key: str,
        api_base: str = "https://api.stripe.com",
        timeout_seconds: float = 10.0,
    ) -> None:
        self._secret_key = secret_key
        self._api_base = api_base.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def create_customer(self, *, email: str, user_id: str) -> str:
        data = await self._post(
            "/v1/customers",
            {
                "email": email,
                "metadata[user_id]": user_id,
            },
        )
        return str(data["id"])

    async def create_checkout_session(
        self,
        *,
        customer_id: str,
        user_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
    ) -> StripeCheckoutSession:
        data = await self._post(
            "/v1/checkout/sessions",
            {
                "mode": "subscription",
                "customer": customer_id,
                "line_items[0][price]": price_id,
                "line_items[0][quantity]": "1",
                "success_url": success_url,
                "cancel_url": cancel_url,
                "client_reference_id": user_id,
                "metadata[user_id]": user_id,
                "subscription_data[metadata][user_id]": user_id,
                "billing_address_collection": "required",
            },
        )
        return StripeCheckoutSession(id=str(data["id"]), url=str(data["url"]))

    async def create_portal_session(
        self,
        *,
        customer_id: str,
        return_url: str,
    ) -> StripePortalSession:
        data = await self._post(
            "/v1/billing_portal/sessions",
            {
                "customer": customer_id,
                "return_url": return_url,
            },
        )
        return StripePortalSession(id=str(data["id"]), url=str(data["url"]))

    async def _post(self, path: str, data: dict[str, str]) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._secret_key}"}
        async with httpx.AsyncClient(
            base_url=self._api_base,
            timeout=self._timeout_seconds,
            headers=headers,
        ) as client:
            response = await client.post(path, data=data)

        if response.status_code >= 400:
            detail = response.text
            try:
                payload = response.json()
                detail = str(payload.get("error", {}).get("message") or payload)
            except Exception:
                pass
            raise StripeAPIError(f"Stripe API error ({response.status_code}): {detail}")

        return response.json()
