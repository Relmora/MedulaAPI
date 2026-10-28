import json
from datetime import UTC, datetime
from uuid import uuid4

import pika
import pytest
from pydantic import SecretStr

from backend.config import Settings
from backend.outbox.publisher import OutboxMessage
from backend.outbox.rabbitmq import (
    RabbitMQConfirmingTransport,
    RabbitMQPublishError,
)


class FakeChannel:
    def __init__(self) -> None:
        self.is_open = True
        self.exchange_declarations: list[dict[str, object]] = []
        self.queue_declarations: list[dict[str, object]] = []
        self.bindings: list[dict[str, object]] = []
        self.confirmations_enabled = False
        self.publications: list[dict[str, object]] = []
        self.publish_error: Exception | None = None

    def exchange_declare(self, **values) -> None:
        self.exchange_declarations.append(values)

    def queue_declare(self, **values) -> None:
        self.queue_declarations.append(values)

    def queue_bind(self, **values) -> None:
        self.bindings.append(values)

    def confirm_delivery(self) -> None:
        self.confirmations_enabled = True

    def basic_publish(self, **values) -> None:
        if self.publish_error is not None:
            raise self.publish_error
        self.publications.append(values)

    def close(self) -> None:
        self.is_open = False


class FakeConnection:
    def __init__(self, parameters: pika.ConnectionParameters) -> None:
        self.parameters = parameters
        self.is_open = True
        self.channel_instance = FakeChannel()

    def channel(self) -> FakeChannel:
        return self.channel_instance

    def close(self) -> None:
        self.is_open = False


class RecordingConnectionFactory:
    def __init__(self) -> None:
        self.connections: list[FakeConnection] = []

    def __call__(self, parameters: pika.ConnectionParameters) -> FakeConnection:
        connection = FakeConnection(parameters)
        self.connections.append(connection)
        return connection


def rabbitmq_settings(**overrides) -> Settings:
    values = {
        "rabbitmq_password": SecretStr("rabbit-secret"),
        "rabbitmq_host": "rabbit.internal",
        "rabbitmq_port": 5672,
        "rabbitmq_username": "publisher",
        "rabbitmq_vhost": "medula",
        "rabbitmq_tls": False,
        "rabbitmq_exchange": "medulla.events",
        "rabbitmq_ingestion_queue": "document.ingestion",
        "rabbitmq_ingestion_routing_key": "document.ingestion.requested",
    }
    return Settings(_env_file=None, **(values | overrides))


def message() -> OutboxMessage:
    job_id = uuid4()
    return OutboxMessage(
        event_id=uuid4(),
        event_type="document.ingestion.requested",
        aggregate_type="INGESTION_JOB",
        aggregate_id=job_id,
        schema_version=1,
        occurred_at=datetime(2026, 10, 29, 1, 30, tzinfo=UTC),
        data={
            "job_id": str(job_id),
            "document_id": str(uuid4()),
            "purpose": "INITIAL_INGESTION",
        },
    )


def test_open_connects_and_declares_durable_topology_once():
    factory = RecordingConnectionFactory()
    transport = RabbitMQConfirmingTransport(
        rabbitmq_settings(), connection_factory=factory
    )

    transport.open()
    transport.open()

    assert len(factory.connections) == 1
    connection = factory.connections[0]
    assert connection.parameters.host == "rabbit.internal"
    assert connection.parameters.port == 5672
    assert connection.parameters.virtual_host == "medula"
    assert connection.parameters.credentials.username == "publisher"
    assert connection.channel_instance.exchange_declarations == [
        {
            "exchange": "medulla.events",
            "exchange_type": "direct",
            "durable": True,
        }
    ]
    assert connection.channel_instance.queue_declarations == [
        {"queue": "document.ingestion", "durable": True}
    ]
    assert connection.channel_instance.bindings == [
        {
            "exchange": "medulla.events",
            "queue": "document.ingestion",
            "routing_key": "document.ingestion.requested",
        }
    ]
    assert connection.channel_instance.confirmations_enabled is True


def test_publish_sends_persistent_json_with_identity_and_mandatory_routing():
    factory = RecordingConnectionFactory()
    transport = RabbitMQConfirmingTransport(
        rabbitmq_settings(), connection_factory=factory
    )
    outgoing = message()

    transport.publish(outgoing)

    publication = factory.connections[0].channel_instance.publications[0]
    assert publication["exchange"] == "medulla.events"
    assert publication["routing_key"] == "document.ingestion.requested"
    assert publication["mandatory"] is True
    assert json.loads(publication["body"]) == outgoing.envelope()
    properties = publication["properties"]
    assert properties.content_type == "application/json"
    assert properties.content_encoding == "utf-8"
    assert properties.delivery_mode == pika.DeliveryMode.Persistent.value
    assert properties.message_id == str(outgoing.event_id)
    assert properties.correlation_id == str(outgoing.aggregate_id)
    assert properties.type == outgoing.event_type
    assert properties.timestamp == int(outgoing.occurred_at.timestamp())
    assert properties.headers == {
        "schema_version": 1,
        "aggregate_type": "INGESTION_JOB",
    }


def test_publish_failure_is_redacted_and_connection_is_reset():
    factory = RecordingConnectionFactory()
    transport = RabbitMQConfirmingTransport(
        rabbitmq_settings(), connection_factory=factory
    )
    transport.open()
    first_connection = factory.connections[0]
    first_connection.channel_instance.publish_error = pika.exceptions.NackError([])

    with pytest.raises(RabbitMQPublishError, match="publication failed") as error:
        transport.publish(message())

    assert "rabbit-secret" not in str(error.value)
    assert first_connection.is_open is False
    assert first_connection.channel_instance.is_open is False

    transport.publish(message())
    assert len(factory.connections) == 2


def test_close_releases_channel_and_connection():
    factory = RecordingConnectionFactory()
    transport = RabbitMQConfirmingTransport(
        rabbitmq_settings(), connection_factory=factory
    )
    transport.open()

    transport.close()

    assert factory.connections[0].channel_instance.is_open is False
    assert factory.connections[0].is_open is False


def test_tls_uses_verified_ssl_context():
    factory = RecordingConnectionFactory()
    transport = RabbitMQConfirmingTransport(
        rabbitmq_settings(rabbitmq_tls=True, rabbitmq_port=5671),
        connection_factory=factory,
    )

    transport.open()

    ssl_options = factory.connections[0].parameters.ssl_options
    assert ssl_options is not None
    assert ssl_options.server_hostname == "rabbit.internal"
    assert ssl_options.context.verify_mode == 2
    assert ssl_options.context.check_hostname is True


def test_empty_password_is_rejected_before_connecting():
    with pytest.raises(ValueError, match="RABBITMQ_PASSWORD"):
        RabbitMQConfirmingTransport(rabbitmq_settings(rabbitmq_password=SecretStr("")))
