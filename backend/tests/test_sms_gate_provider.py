"""SMS Gateway for Android as the customer-summary delivery provider.

Every HTTP call goes to an httpx.MockTransport; nothing is ever sent."""

import base64
import json

import httpx
import pytest

from app.ai.sentiment.provider import SentimentLabel, SentimentResult
from app.composition.services import create_customer_summary_delivery_provider
from app.core.config import Settings
from app.domain.customer_contact import ConsentStatus, CustomerContact, MessagingChannel
from app.domain.customer_summary_delivery import DeliveryStatus
from app.domain.post_call_summary import PostCallSummary
from app.messaging.sms_gate_provider import (
    CLOUD_MESSAGES_URL,
    SmsGateDeliveryProvider,
    SmsGatewayError,
)
from app.services.customer_summary_delivery_service import CustomerSummaryDeliveryService
from app.services.customer_summary_message_service import CustomerSummaryMessageService
from app.services.customer_summary_repository import InMemoryCustomerSummaryDeliveryRepository
from tests.test_call_customer import CRM, build_client

LOCAL_URL = "http://192.168.1.20:8080/message"


class Gateway:
    """A scripted SMS gateway: each request pops the next response."""

    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    @property
    def payloads(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]


def accepted(message_id: str = "gw-123", state: str = "Pending") -> httpx.Response:
    return httpx.Response(202, json={"id": message_id, "state": state})


def provider(gateway: Gateway, url: str = CLOUD_MESSAGES_URL, **kwargs) -> SmsGateDeliveryProvider:
    return SmsGateDeliveryProvider(
        url=url,
        username="gateway-user",
        password="gateway-secret",
        client=httpx.Client(transport=httpx.MockTransport(gateway)),
        sleep=lambda seconds: None,
        **kwargs,
    )


def contact(**overrides) -> CustomerContact:
    values = {
        "customer_id": "C-1",
        "phone_number": "+919845000001",
        "preferred_channel": MessagingChannel.SMS,
        "consent_status": ConsentStatus.GRANTED,
    }
    values.update(overrides)
    return CustomerContact(**values)


def summary() -> PostCallSummary:
    return PostCallSummary(
        call_id="call-1",
        overall_summary="The customer reported a delay.",
        languages=("en",),
        sentiment=SentimentResult(SentimentLabel.NEGATIVE, 0.8, "Upset about the delay."),
        complaints=(),
        unresolved_issues=(),
        actions_promised=("Call back with a delivery date.",),
        follow_up_required=True,
        customer_summary="We will call you back today with your delivery date.",
    )


# ---- Request format ----

def test_sends_one_text_message_with_basic_auth_and_returns_the_gateway_id():
    gateway = Gateway(accepted("gw-123"))

    message_id = provider(gateway, sim_number=2, ttl_seconds=3600).send_summary(
        contact(), "Your summary", MessagingChannel.SMS
    )

    assert message_id == "gw-123"
    (request,) = gateway.requests
    assert request.method == "POST"
    assert str(request.url) == CLOUD_MESSAGES_URL
    expected_auth = base64.b64encode(b"gateway-user:gateway-secret").decode()
    assert request.headers["Authorization"] == f"Basic {expected_auth}"
    body = gateway.payloads[0]
    assert body["textMessage"] == {"text": "Your summary"}
    assert body["phoneNumbers"] == ["+919845000001"]
    assert body["simNumber"] == 2
    assert body["ttl"] == 3600
    assert body["withDeliveryReport"] is True
    assert isinstance(body["id"], str) and body["id"]
    assert "message" not in body  # the deprecated field is never used


def test_local_server_mode_uses_the_same_request():
    gateway = Gateway(accepted())

    provider(gateway, url=LOCAL_URL).send_summary(contact(), "Hi", MessagingChannel.SMS)

    assert str(gateway.requests[0].url) == LOCAL_URL
    assert "simNumber" not in gateway.payloads[0]


def test_falls_back_to_its_own_id_when_the_gateway_returns_none():
    gateway = Gateway(httpx.Response(202, json={}))

    message_id = provider(gateway).send_summary(contact(), "Hi", MessagingChannel.SMS)

    assert message_id == gateway.payloads[0]["id"]


def test_whatsapp_is_not_supported():
    gateway = Gateway()

    with pytest.raises(SmsGatewayError, match="whatsapp"):
        provider(gateway).send_summary(contact(), "Hi", MessagingChannel.WHATSAPP)
    assert gateway.requests == []


# ---- Errors and retries ----

def test_rejected_credentials_fail_without_retrying_or_leaking_them():
    gateway = Gateway(httpx.Response(401, text="Unauthorized"))

    with pytest.raises(SmsGatewayError, match="credentials") as error:
        provider(gateway, retry_attempts=3).send_summary(contact(), "Hi", MessagingChannel.SMS)

    assert len(gateway.requests) == 1
    assert "gateway-secret" not in str(error.value)


def test_client_errors_are_reported_with_the_gateway_detail():
    gateway = Gateway(httpx.Response(400, json={"message": "invalid phone number"}))

    with pytest.raises(SmsGatewayError, match="HTTP 400.*invalid phone number"):
        provider(gateway, retry_attempts=2).send_summary(contact(), "Hi", MessagingChannel.SMS)
    assert len(gateway.requests) == 1


def test_server_errors_and_network_errors_are_retried_with_the_same_message_id():
    sleeps: list[float] = []
    gateway = Gateway(
        httpx.Response(503, json={"error": "QueueLimitExceeded"}),
        httpx.ConnectTimeout("timed out"),
        accepted("gw-9"),
    )
    sms = SmsGateDeliveryProvider(
        url=CLOUD_MESSAGES_URL,
        username="gateway-user",
        password="gateway-secret",
        retry_attempts=2,
        client=httpx.Client(transport=httpx.MockTransport(gateway)),
        sleep=sleeps.append,
        retry_backoff_seconds=0.5,
    )

    assert sms.send_summary(contact(), "Hi", MessagingChannel.SMS) == "gw-9"
    assert len({payload["id"] for payload in gateway.payloads}) == 1
    assert sleeps == [0.5, 1.0]


def test_retries_stop_after_the_configured_attempts():
    gateway = Gateway(httpx.ConnectError("down"), httpx.ConnectError("down"))

    with pytest.raises(SmsGatewayError, match="unreachable"):
        provider(gateway, retry_attempts=1).send_summary(contact(), "Hi", MessagingChannel.SMS)
    assert len(gateway.requests) == 2


def test_duplicate_id_after_a_retry_means_the_first_attempt_got_through():
    gateway = Gateway(httpx.ReadTimeout("slow"), httpx.Response(409, json={"message": "exists"}))

    message_id = provider(gateway, retry_attempts=1).send_summary(
        contact(), "Hi", MessagingChannel.SMS
    )

    assert message_id == gateway.payloads[0]["id"]


def test_message_the_gateway_marks_failed_is_an_error():
    gateway = Gateway(accepted("gw-1", state="Failed"))

    with pytest.raises(SmsGatewayError, match="Failed"):
        provider(gateway).send_summary(contact(), "Hi", MessagingChannel.SMS)


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"url": ""}, "URL"),
        ({"username": ""}, "username and password"),
        ({"password": " "}, "username and password"),
        ({"retry_attempts": -1}, "retry_attempts"),
        ({"sim_number": 4}, "sim_number"),
    ],
)
def test_invalid_configuration_is_rejected(kwargs, message):
    values = {"url": CLOUD_MESSAGES_URL, "username": "u", "password": "p"}
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        SmsGateDeliveryProvider(**values)


# ---- Configuration ----

def test_factory_builds_the_sms_gateway_from_settings():
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        customer_summary_delivery_provider="sms_gate",
        sms_gate_url=LOCAL_URL,
        sms_gate_username="gateway-user",
        sms_gate_password="gateway-secret",
        customer_summary_sms_retry_attempts=2,
    )

    built = create_customer_summary_delivery_provider(settings)

    assert isinstance(built, SmsGateDeliveryProvider)
    assert built.supported_channels == frozenset({MessagingChannel.SMS})


def test_factory_refuses_the_sms_gateway_without_credentials():
    settings = Settings(_env_file=None, customer_summary_delivery_provider="sms_gate")  # type: ignore[call-arg]

    with pytest.raises(ValueError, match="username and password"):
        create_customer_summary_delivery_provider(settings)


# ---- Through the delivery service ----

def delivery_service(gateway: Gateway):
    repository = InMemoryCustomerSummaryDeliveryRepository()
    service = CustomerSummaryDeliveryService(
        provider=provider(gateway),
        message_service=CustomerSummaryMessageService(),
        repository=repository,
    )
    return service, repository


def test_summary_is_sent_by_sms_and_recorded():
    gateway = Gateway(accepted("gw-55"))
    service, _ = delivery_service(gateway)

    delivery = service.send_summary_to_customer(summary(), contact())

    assert delivery.status is DeliveryStatus.SENT
    assert delivery.provider_message_id == "gw-55"
    assert delivery.provider == "SmsGateDeliveryProvider"
    assert "delivery date" in gateway.payloads[0]["textMessage"]["text"]


def test_whatsapp_preference_falls_back_to_sms():
    gateway = Gateway(accepted())
    service, _ = delivery_service(gateway)

    delivery = service.send_summary_to_customer(
        summary(), contact(preferred_channel=MessagingChannel.WHATSAPP)
    )

    assert delivery.status is DeliveryStatus.SENT
    assert delivery.channel is MessagingChannel.SMS
    assert len(gateway.requests) == 1


def test_gateway_failure_is_recorded_as_a_failed_delivery():
    gateway = Gateway(httpx.Response(401))
    service, _ = delivery_service(gateway)

    delivery = service.send_summary_to_customer(summary(), contact())

    assert delivery.status is DeliveryStatus.FAILED
    assert delivery.failure_reason == "provider_delivery_failed"
    assert "credentials" in delivery.last_error


def test_no_consent_means_the_gateway_is_never_called():
    gateway = Gateway()
    service, _ = delivery_service(gateway)

    delivery = service.send_summary_to_customer(
        summary(), contact(consent_status=ConsentStatus.UNKNOWN)
    )

    assert delivery.status is DeliveryStatus.REJECTED
    assert gateway.requests == []


def test_a_summary_is_sent_once_per_call():
    gateway = Gateway(accepted("gw-1"))
    service, repository = delivery_service(gateway)

    first = service.send_summary_to_customer(summary(), contact())
    second = service.send_summary_to_customer(summary(), contact())

    assert second == first
    assert len(gateway.requests) == 1
    assert len(repository.get_by_call_id("call-1")) == 1


# ---- Delivery status API ----

@pytest.fixture
def crm_file(tmp_path):
    path = tmp_path / "crm.json"
    path.write_text(json.dumps(CRM), encoding="utf-8")
    return path


def _complete_call(client, call_id: str, caller_number: str) -> None:
    client.post("/api/v1/calls", json={"call_id": call_id, "caller_number": caller_number})
    client.post(
        f"/api/v1/calls/{call_id}/utterances",
        json={
            "utterance_id": "u1",
            "transcript": "My car was supposed to be ready yesterday.",
            "speaker_role": "CUSTOMER",
            "languages": ["en"],
            "start_time": 0.0,
            "end_time": 3.0,
        },
    )
    assert client.post(f"/api/v1/calls/{call_id}/complete", json={"end_time": 30.0}).status_code == 200


def test_delivery_status_endpoint_lists_the_call_deliveries(crm_file):
    client, _, _ = build_client(
        crm_file, customer_summary_enabled=True, customer_summary_delivery_provider="noop"
    )
    _complete_call(client, "d-1", "9845000001")

    body = client.get("/api/v1/calls/d-1/summary-delivery").json()

    assert body["enabled"] is True
    (delivery,) = body["deliveries"]
    assert delivery["status"] == "sent"
    assert delivery["customer_id"] == "C-1"
    assert delivery["message"]


def test_delivery_status_endpoint_reports_when_delivery_is_off(crm_file):
    client, _, _ = build_client(crm_file)
    _complete_call(client, "d-2", "9845000001")

    body = client.get("/api/v1/calls/d-2/summary-delivery").json()

    assert body == {"call_id": "d-2", "enabled": False, "deliveries": []}


def test_delivery_status_for_unknown_call_returns_404(crm_file):
    client, _, _ = build_client(crm_file)

    assert client.get("/api/v1/calls/missing/summary-delivery").status_code == 404
