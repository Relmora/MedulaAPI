from types import SimpleNamespace

from pydantic import SecretStr

from backend.config import Settings
from backend.ingestion.rabbitmq import RabbitMQIngestionConsumer


class RecordingHandler:
    def __init__(self) -> None:
        self.deliveries = []

    def handle(self, body, delivery):
        self.deliveries.append((body, delivery))


class FakeChannel:
    def __init__(self) -> None:
        self.is_open = True
        self.exchange_declarations = []
        self.queue_declarations = []
        self.bindings = []
        self.qos = []
        self.consumers = []
        self.acknowledged = []
        self.rejected = []
        self.started = False

    def exchange_declare(self, **values):
        self.exchange_declarations.append(values)

    def queue_declare(self, **values):
        self.queue_declarations.append(values)

    def queue_bind(self, **values):
        self.bindings.append(values)

    def basic_qos(self, **values):
        self.qos.append(values)

    def basic_consume(self, **values):
        self.consumers.append(values)

    def start_consuming(self):
        self.started = True

    def basic_ack(self, **values):
        self.acknowledged.append(values)

    def basic_reject(self, **values):
        self.rejected.append(values)

    def close(self):
        self.is_open = False


class FakeConnection:
    def __init__(self, parameters) -> None:
        self.parameters = parameters
        self.is_open = True
        self.channel_instance = FakeChannel()

    def channel(self):
        return self.channel_instance

    def close(self):
        self.is_open = False


class RecordingConnectionFactory:
    def __init__(self) -> None:
        self.connections = []

    def __call__(self, parameters):
        connection = FakeConnection(parameters)
        self.connections.append(connection)
        return connection


def settings() -> Settings:
    return Settings(
        _env_file=None,
        rabbitmq_password=SecretStr("secret"),
        rabbitmq_exchange="medulla.events",
        rabbitmq_ingestion_queue="document.ingestion",
        rabbitmq_ingestion_routing_key="document.ingestion.requested",
        ingestion_worker_prefetch_count=1,
    )


def test_consumer_uses_durable_topology_manual_ack_and_bounded_prefetch():
    handler = RecordingHandler()
    factory = RecordingConnectionFactory()
    consumer = RabbitMQIngestionConsumer(
        settings(), handler, connection_factory=factory
    )

    consumer.run()

    channel = factory.connections[0].channel_instance
    assert channel.exchange_declarations == [
        {"exchange": "medulla.events", "exchange_type": "direct", "durable": True}
    ]
    assert channel.queue_declarations == [
        {"queue": "document.ingestion", "durable": True}
    ]
    assert channel.bindings == [
        {
            "exchange": "medulla.events",
            "queue": "document.ingestion",
            "routing_key": "document.ingestion.requested",
        }
    ]
    assert channel.qos == [{"prefetch_count": 1}]
    assert channel.consumers[0]["queue"] == "document.ingestion"
    assert channel.consumers[0]["auto_ack"] is False
    assert channel.started is True

    callback = channel.consumers[0]["on_message_callback"]
    callback(
        channel,
        SimpleNamespace(delivery_tag=17),
        SimpleNamespace(),
        b"message",
    )
    body, delivery = handler.deliveries[0]
    assert body == b"message"
    delivery.acknowledge()
    assert channel.acknowledged == [{"delivery_tag": 17}]
