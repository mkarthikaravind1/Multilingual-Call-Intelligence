"""Customer summary delivery through SMS Gateway for Android (sms-gate.app).

An Android phone running the open-source SMS Gateway app sends the SMS from
its own SIM. The same request works for both of its modes; only the URL
differs:

- Cloud relay:   https://api.sms-gate.app/3rdparty/v1/messages
- Local network: http://<phone-ip>:8080/message

Authentication is HTTP Basic with the username/password the app shows.
The gateway accepts the message (state "Pending") and sends it
asynchronously, so a successful call means "accepted by the gateway", not
"delivered to the handset".
"""

import logging
import time
from collections.abc import Callable
from uuid import uuid4

import httpx

from app.domain.customer_contact import CustomerContact, MessagingChannel
from app.services.customer_summary_delivery_service import CustomerSummaryDeliveryProvider

logger = logging.getLogger(__name__)

CLOUD_MESSAGES_URL = "https://api.sms-gate.app/3rdparty/v1/messages"

_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ERROR_DETAIL = 300


class SmsGatewayError(Exception):
    pass


class SmsGateDeliveryProvider(CustomerSummaryDeliveryProvider):
    supported_channels = frozenset({MessagingChannel.SMS})

    def __init__(
        self,
        url: str,
        username: str,
        password: str,
        timeout_seconds: float = 10.0,
        retry_attempts: int = 0,
        sim_number: int | None = None,
        ttl_seconds: int | None = 86400,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        retry_backoff_seconds: float = 1.0,
    ) -> None:
        if not url.strip():
            raise ValueError("SMS gateway URL must not be empty.")
        if not username.strip() or not password.strip():
            raise ValueError("SMS gateway username and password are required.")
        if retry_attempts < 0:
            raise ValueError("retry_attempts must not be negative.")
        if sim_number is not None and not 1 <= sim_number <= 3:
            raise ValueError("sim_number must be 1, 2 or 3.")
        self._url = url.strip()
        self._auth = (username, password)
        self._retry_attempts = retry_attempts
        self._sim_number = sim_number
        self._ttl_seconds = ttl_seconds
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._sleep = sleep
        self._retry_backoff_seconds = retry_backoff_seconds

    def send_summary(
        self,
        contact: CustomerContact,
        message: str,
        channel: MessagingChannel,
    ) -> str:
        if channel is not MessagingChannel.SMS:
            raise SmsGatewayError(f"SMS gateway cannot send {channel.value} messages.")

        # One id for every attempt: the gateway treats a repeated id as the
        # same message, so a retry after a timeout cannot text the customer twice.
        payload: dict = {
            "id": uuid4().hex,
            "textMessage": {"text": message},
            "phoneNumbers": [contact.normalized_phone_number],
            "withDeliveryReport": True,
        }
        if self._sim_number is not None:
            payload["simNumber"] = self._sim_number
        if self._ttl_seconds is not None:
            payload["ttl"] = self._ttl_seconds

        attempt = 0
        while True:
            try:
                response = self._client.post(self._url, json=payload, auth=self._auth)
            except httpx.HTTPError as exc:
                if attempt < self._retry_attempts:
                    attempt = self._back_off(attempt, f"network error: {type(exc).__name__}")
                    continue
                raise SmsGatewayError(
                    f"SMS gateway unreachable: {type(exc).__name__}"
                ) from exc

            if response.status_code in _RETRYABLE_STATUS and attempt < self._retry_attempts:
                attempt = self._back_off(attempt, f"HTTP {response.status_code}")
                continue
            if response.status_code == 409 and attempt > 0:
                # An earlier attempt already reached the gateway with this id.
                return payload["id"]
            return self._message_id(response, payload["id"])

    def _back_off(self, attempt: int, reason: str) -> int:
        delay = self._retry_backoff_seconds * (2**attempt)
        logger.warning("SMS gateway %s; retrying in %.1fs", reason, delay)
        self._sleep(delay)
        return attempt + 1

    @staticmethod
    def _message_id(response: httpx.Response, requested_id: str) -> str:
        if response.status_code == 401:
            raise SmsGatewayError("SMS gateway rejected the credentials (HTTP 401).")
        if not response.is_success:
            detail = response.text.strip()[:_MAX_ERROR_DETAIL]
            raise SmsGatewayError(f"SMS gateway returned HTTP {response.status_code}: {detail}")
        try:
            body = response.json()
        except ValueError:
            body = None
        message_id = body.get("id") if isinstance(body, dict) else None
        if isinstance(body, dict) and body.get("state") == "Failed":
            raise SmsGatewayError(f"SMS gateway marked message {message_id!r} as Failed.")
        return message_id if isinstance(message_id, str) and message_id else requested_id
