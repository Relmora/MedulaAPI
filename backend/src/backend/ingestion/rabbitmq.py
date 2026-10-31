"""Blocking RabbitMQ consumer adapter for ingestion deliveries."""

import ssl
from collections.abc import Callable
from dataclasses import dataclass
from threading import Lock
from typing import Protocol

import pika
from pika.adapters.blocking_connection import BlockingChannel, BlockingConnection
from pika.spec import Basic, BasicProperties

from backend.config import Settings
from backend.ingestion.worker import Delivery

ConnectionFactory = Callable[[pika.ConnectionParameters], BlockingConnection]


class DeliveryHandler(Protocol):
    def handle(self, body: bytes, delivery: Delivery): ...


@dataclass
class RabbitMQDelivery:
    channel: BlockingChannel
    delivery_tag: int

    def acknowledge(self) -> None:
        self.channel.basic_ack(delivery_tag=self.delivery_tag)

    def reject(self, *, requeue: bool) -> None:
        self.channel.basic_reject(
            delivery_tag=self.delivery_tag,
            requeue=requeue,
        )


def build_delivery_callback(handler: DeliveryHandler):
    """Adapt pika callback arguments to the broker-neutral worker boundary."""

    def on_message(
        channel: BlockingChannel,
        method: Basic.Deliver,
        _properties: BasicProperties,
        body: bytes,
    ) -> None:
        handler.handle(
            body,
            RabbitMQDelivery(channel=channel, delivery_tag=method.delivery_tag),
        )

    return on_message


class RabbitMQIngestionConsumer:
    """Consume durable ingestion messages with manual acknowledgements."""

    def __init__(
        self,
        settings: Settings,
        handler: DeliveryHandler,
        *,
        connection_factory: ConnectionFactory = pika.BlockingConnection,
    ) -> None:
        password = settings.rabbitmq_password.get_secret_value()
        if not password:
            raise ValueError("RABBITMQ_PASSWORD must be set before connecting.")

        self._exchange = settings.rabbitmq_exchange
        self._queue = settings.rabbitmq_ingestion_queue
        self._routing_key = settings.rabbitmq_ingestion_routing_key
        self._prefetch_count = settings.ingestion_worker_prefetch_count
        self._callback = build_delivery_callback(handler)
        self._connection_factory = connection_factory
        self._parameters = self._build_connection_parameters(settings, password)
        self._connection: BlockingConnection | None = None
        self._channel: BlockingChannel | None = None
        self._lock = Lock()

    def run(self) -> None:
        """Connect, declare topology, and consume until RabbitMQ stops the loop."""
        with self._lock:
            channel = self._ensure_channel()
            channel.basic_qos(prefetch_count=self._prefetch_count)
            channel.basic_consume(
                queue=self._queue,
                on_message_callback=self._callback,
                auto_ack=False,
            )
        channel.start_consuming()

    def close(self) -> None:
        with self._lock:
            channel = self._channel
            connection = self._connection
            self._channel = None
            self._connection = None
            try:
                if channel is not None and channel.is_open:
                    channel.close()
            finally:
                if connection is not None and connection.is_open:
                    connection.close()

    def _ensure_channel(self) -> BlockingChannel:
        if (
            self._connection is not None
            and self._connection.is_open
            and self._channel is not None
            and self._channel.is_open
        ):
            return self._channel

        connection = self._connection_factory(self._parameters)
        try:
            channel = connection.channel()
            channel.exchange_declare(
                exchange=self._exchange,
                exchange_type="direct",
                durable=True,
            )
            channel.queue_declare(queue=self._queue, durable=True)
            channel.queue_bind(
                exchange=self._exchange,
                queue=self._queue,
                routing_key=self._routing_key,
            )
        except Exception:
            if connection.is_open:
                connection.close()
            raise

        self._connection = connection
        self._channel = channel
        return channel

    @staticmethod
    def _build_connection_parameters(
        settings: Settings,
        password: str,
    ) -> pika.ConnectionParameters:
        ssl_options = None
        if settings.rabbitmq_tls:
            ssl_context = ssl.create_default_context()
            ssl_options = pika.SSLOptions(ssl_context, settings.rabbitmq_host)

        return pika.ConnectionParameters(
            host=settings.rabbitmq_host,
            port=settings.rabbitmq_port,
            virtual_host=settings.rabbitmq_vhost,
            credentials=pika.PlainCredentials(
                settings.rabbitmq_username,
                password,
            ),
            heartbeat=60,
            connection_attempts=3,
            retry_delay=2,
            socket_timeout=10,
            stack_timeout=15,
            blocked_connection_timeout=30,
            ssl_options=ssl_options,
            client_properties={"connection_name": "medula-ingestion-worker"},
        )
