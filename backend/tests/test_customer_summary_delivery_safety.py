"""Customer summary texts when things go wrong: a gateway that fails, a
customer who cannot be looked up, two runs for the same call, a summary
that is too long, and delivery that was never set up. Nothing is ever sent:
the gateway is an httpx.MockTransport."""

import dataclasses

import httpx

from app.ai.summary.llm_provider import SAFE_CUSTOMER_MESSAGE
from app.composition.services import create_customer_summary_delivery_provider
from app.core.config import Settings
from app.core.production_checks import configuration_problems
from app.crm.provider import CrmUnavailableError
from app.domain.customer_contact import MessagingChannel
from app.domain.customer_summary_delivery import DeliveryStatus
from app.messaging.sms_length import sms_parts
from app.services.customer_summary_delivery_service import (
    CUSTOMER_LOOKUP_FAILED,
    QUEUED_STALE_SECONDS,
    CustomerSummaryDeliveryService,
)
from app.services.customer_summary_message_service import CustomerSummaryMessageService
from app.services.customer_summary_repository import InMemoryCustomerSummaryDeliveryRepository
from tests.test_sms_gate_provider import Gateway, accepted, contact, provider, summary

DOWN = httpx.Response(503)


def _service(gateway: Gateway, repository=None, **kwargs):
    repository = repository or InMemoryCustomerSummaryDeliveryRepository()
    service = CustomerSummaryDeliveryService(
        provider=provider(gateway),
        message_service=CustomerSummaryMessageService(),
        repository=repository,
        **kwargs,
    )
    return service, repository


def _summaries(call_id: str):
    return summary() if call_id == "call-1" else None


# ---- A delivery that failed is tried again ----

def test_a_failed_delivery_is_sent_by_a_later_retry():
    gateway = Gateway(DOWN, accepted("gw-2"))
    service, repository = _service(gateway)

    first = service.deliver_for_call(summary(), lambda call_id: contact())
    assert first.status is DeliveryStatus.FAILED

    assert service.retry_unfinished(_summaries, lambda call_id: contact()) == 1

    (delivery,) = repository.get_by_call_id("call-1")
    assert delivery.status is DeliveryStatus.SENT
    assert delivery.attempts == 2
    assert delivery.delivery_id == first.delivery_id
    # The same message to the gateway both times, so it cannot arrive twice.
    assert gateway.payloads[0]["id"] == gateway.payloads[1]["id"]


def test_retries_stop_after_the_attempt_limit():
    gateway = Gateway(DOWN, DOWN, DOWN)
    service, repository = _service(gateway, max_attempts=3)

    service.deliver_for_call(summary(), lambda call_id: contact())
    for _ in range(5):
        service.retry_unfinished(_summaries, lambda call_id: contact())

    (delivery,) = repository.get_by_call_id("call-1")
    assert delivery.status is DeliveryStatus.FAILED
    assert delivery.attempts == 3
    assert len(gateway.requests) == 3


def test_a_sent_or_refused_delivery_is_never_retried():
    gateway = Gateway(accepted())
    service, _ = _service(gateway)
    service.deliver_for_call(summary(), lambda call_id: contact())

    assert service.retry_unfinished(_summaries, lambda call_id: contact()) == 0
    assert len(gateway.requests) == 1


def test_the_gateway_already_having_the_message_counts_as_sent():
    # e.g. the process stopped after the gateway accepted it but before the
    # outcome was recorded.
    gateway = Gateway(httpx.Response(409))
    service, _ = _service(gateway)

    delivery = service.deliver_for_call(summary(), lambda call_id: contact())

    assert delivery.status is DeliveryStatus.SENT


# ---- The customer could not be looked up ----

def test_a_crm_outage_is_recorded_and_the_text_goes_out_once_the_crm_is_back():
    gateway = Gateway(accepted("gw-9"))
    service, repository = _service(gateway)

    def crm_down(call_id):
        raise CrmUnavailableError("timeout")

    missed = service.deliver_for_call(summary(), crm_down)
    assert missed.status is DeliveryStatus.FAILED
    assert missed.failure_reason == CUSTOMER_LOOKUP_FAILED
    assert gateway.requests == []

    assert service.retry_unfinished(_summaries, lambda call_id: contact()) == 1

    (delivery,) = repository.get_by_call_id("call-1")
    assert delivery.status is DeliveryStatus.SENT
    assert delivery.customer_id == "C-1"
    assert delivery.failure_reason is None
    assert len(gateway.requests) == 1


def test_a_call_with_no_customer_after_all_stops_being_retried():
    gateway = Gateway()
    service, repository = _service(gateway)

    def crm_down(call_id):
        raise CrmUnavailableError("timeout")

    service.deliver_for_call(summary(), crm_down)
    service.retry_unfinished(_summaries, lambda call_id: None)

    (delivery,) = repository.get_by_call_id("call-1")
    assert delivery.status is DeliveryStatus.REJECTED
    assert delivery.failure_reason == "customer_not_identified"
    assert repository.list_unfinished(10) == ()


def test_a_call_with_no_customer_records_nothing():
    service, repository = _service(Gateway())

    assert service.deliver_for_call(summary(), lambda call_id: None) is None
    assert repository.get_by_call_id("call-1") == ()


# ---- Two runs for the same call ----

class _RacingRepository(InMemoryCustomerSummaryDeliveryRepository):
    """Another run stores its delivery between this run's check and its claim."""

    def __init__(self, other_run) -> None:
        super().__init__()
        self._other_run = other_run

    def add_if_absent(self, delivery):
        if self._other_run is not None:
            other_run, self._other_run = self._other_run, None
            other_run()
        return super().add_if_absent(delivery)


def test_two_overlapping_runs_send_one_text():
    gateway = Gateway(accepted("gw-1"))
    repository = _RacingRepository(
        lambda: service.send_summary_to_customer(summary(), contact())
    )
    service, _ = _service(gateway, repository)

    delivery = service.send_summary_to_customer(summary(), contact())

    assert delivery.status is DeliveryStatus.SENT
    assert len(gateway.requests) == 1
    assert len(repository.get_by_call_id("call-1")) == 1


def test_a_delivery_in_progress_is_left_alone_until_it_is_stale():
    gateway = Gateway(accepted("gw-1"))
    service, repository = _service(gateway)
    sent = service.send_summary_to_customer(summary(), contact())
    in_progress = dataclasses.replace(
        sent, status=DeliveryStatus.QUEUED, provider_message_id=None
    )
    repository.save(in_progress)

    assert service.send_summary_to_customer(summary(), contact()) == in_progress
    assert len(gateway.requests) == 1

    # Interrupted long ago: tried again, and the gateway (which got it the
    # first time) answers that it already has that message.
    repository.save(
        dataclasses.replace(in_progress, updated_at=sent.updated_at - QUEUED_STALE_SECONDS - 1)
    )
    gateway.responses.append(httpx.Response(409))

    retried = service.send_summary_to_customer(summary(), contact())

    assert retried.status is DeliveryStatus.SENT
    assert gateway.payloads[0]["id"] == gateway.payloads[1]["id"]


def test_claiming_a_retry_works_once():
    repository = InMemoryCustomerSummaryDeliveryRepository()
    gateway = Gateway(DOWN)
    service, _ = _service(gateway, repository)
    failed = service.send_summary_to_customer(summary(), contact())

    assert repository.claim_retry(failed.delivery_id, failed.attempts, 5.0) is True
    assert repository.claim_retry(failed.delivery_id, failed.attempts, 6.0) is False


# ---- Delivery that was never set up ----

def test_a_disabled_provider_records_not_sent_rather_than_sent():
    disabled = create_customer_summary_delivery_provider(
        Settings(_env_file=None, customer_summary_delivery_provider="disabled")  # type: ignore[call-arg]
    )
    service = CustomerSummaryDeliveryService(
        provider=disabled, repository=InMemoryCustomerSummaryDeliveryRepository()
    )

    delivery = service.send_summary_to_customer(summary(), contact())

    assert delivery.status is DeliveryStatus.REJECTED
    assert delivery.failure_reason == "delivery_not_configured"
    assert delivery.provider_message_id is None


def test_the_noop_provider_still_records_sent():
    noop = create_customer_summary_delivery_provider(
        Settings(_env_file=None, customer_summary_delivery_provider="noop")  # type: ignore[call-arg]
    )
    service = CustomerSummaryDeliveryService(
        provider=noop, repository=InMemoryCustomerSummaryDeliveryRepository()
    )

    assert service.send_summary_to_customer(summary(), contact()).status is DeliveryStatus.SENT


def _problems(**values) -> str:
    return "\n".join(configuration_problems(Settings(_env_file=None, **values)))  # type: ignore[call-arg]


def test_production_check_refuses_summaries_enabled_with_no_provider():
    assert "CUSTOMER_SUMMARY_DELIVERY_PROVIDER" in _problems(customer_summary_enabled=True)
    assert "CUSTOMER_SUMMARY_DELIVERY_PROVIDER" in _problems(
        customer_summary_enabled=True, customer_summary_delivery_provider="noop"
    )
    assert "CUSTOMER_SUMMARY" not in _problems(customer_summary_enabled=False)


def test_production_check_refuses_the_sms_gateway_without_credentials():
    assert "SMS_GATE_USERNAME" in _problems(
        customer_summary_enabled=True, customer_summary_delivery_provider="sms_gate"
    )
    assert "SMS_GATE" not in _problems(
        customer_summary_enabled=True,
        customer_summary_delivery_provider="sms_gate",
        sms_gate_username="gateway-user",
        sms_gate_password="gateway-secret",
    )


# ---- Length ----

def test_sms_parts_for_latin_and_tamil_text():
    assert sms_parts("a" * 160) == 1
    assert sms_parts("a" * 161) == 2
    assert sms_parts("a" * 459) == 3
    assert sms_parts("a" * 460) == 4
    assert sms_parts("{" * 80) == 1  # two characters each
    assert sms_parts("{" * 81) == 2
    assert sms_parts("க" * 70) == 1
    assert sms_parts("க" * 71) == 2
    assert sms_parts("க" * 201) == 3
    assert sms_parts("க" * 202) == 4


def _message(text: str, **kwargs) -> str:
    long_summary = dataclasses.replace(summary(), customer_summary=text)
    return (
        CustomerSummaryMessageService(**kwargs)
        .build_message(long_summary, contact(), MessagingChannel.SMS)
        .content
    )


def test_a_normal_summary_keeps_its_greeting():
    assert _message("We will call you back today.") == (
        "Hi there, here is your call summary.\n\nWe will call you back today."
    )


def test_a_summary_that_only_fits_without_the_greeting_is_sent_without_it():
    tamil = "க" * 190

    assert _message(tamil) == tamil


def test_a_summary_over_three_parts_is_replaced_by_the_standard_message():
    assert _message("க" * 202) == SAFE_CUSTOMER_MESSAGE
    assert _message("a" * 460) == SAFE_CUSTOMER_MESSAGE
    # No limit when it is switched off.
    assert _message("a" * 460, sms_max_parts=0).endswith("a" * 460)


def test_whatsapp_messages_are_not_limited():
    long_summary = dataclasses.replace(summary(), customer_summary="a" * 2000)

    message = CustomerSummaryMessageService().build_message(
        long_summary, contact(), MessagingChannel.WHATSAPP
    )

    assert message.content.endswith("a" * 2000)
