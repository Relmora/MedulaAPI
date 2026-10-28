"""Synchronous RabbitMQ transport with durable topology and confirmations."""

import json
import ssl
from collections.abc import Callable
from threading import Lock

import pika
from pika.adapters.blocking_connection import BlockingChannel, BlockingConnection

from backend.config import Settings
from backend.outbox.publisher import OutboxMessage

ConnectionFactory = Callable[[pika.ConnectionParameters], BlockingConnection]


class RabbitMQPublishError(RuntimeError):
    """Safe publication failure that does not expose connection credentials."""


class RabbitMQConfirmingTransport:
    """Publish persistent JSON messages after RabbitMQ confirms acceptance."""

    def __init__(
        self,
        settings: Settings,
        *,
        connection_factory: ConnectionFactory = pika.BlockingConnection,
    ) -> None:
        password = settings.rabbitmq_password.get_secret_value()
        if not password:
            raise ValueError("RABBITMQ_PASSWORD must be set before connecting.")

        self._exchange = settings.rabbitmq_exchange
        self._queue = settings.rabbitmq_ingestion_queue
        self._ingestion_routing_key = settings.rabbitmq_ingestion_routing_key
        self._connection_factory = connection_factory
        self._parameters = self._build_connection_parameters(settings, password)
        self._connection: BlockingConnection | None = None
        self._channel: BlockingChannel | None = None
        self._lock = Lock()

    def open(self) -> None:
        """Connect and idempotently declare the ingestion topology."""
        with self._lock:
            try:
                self._ensure_channel()
            except Exception as error:
                self._close_without_lock()
                raise RabbitMQPublishError("RabbitMQ connection failed.") from error

    def publish(self, message: OutboxMessage) -> None:
        """Publish one message and return only after a broker confirmation."""
        body = json.dumps(
            message.envelope(),
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        properties = pika.BasicProperties(
            content_type="application/json",
            content_encoding="utf-8",
            delivery_mode=pika.DeliveryMode.Persistent,
            message_id=str(message.event_id),
            correlation_id=str(message.aggregate_id),
            timestamp=int(message.occurred_at.timestamp()),
            type=message.event_type,
            app_id="medula-api-outbox",
            headers={
                "schema_version": message.schema_version,
                "aggregate_type": message.aggregate_type,
            },
        )

        with self._lock:
            try:
                channel = self._ensure_channel()
                channel.basic_publish(
                    exchange=self._exchange,
                    routing_key=message.event_type,
                    body=body,
                    properties=properties,
                    mandatory=True,
                )
            except Exception as error:
                self._close_without_lock()
                raise RabbitMQPublishError("RabbitMQ publication failed.") from error

    def close(self) -> None:
        """Close the channel and connection if they are open."""
        with self._lock:
            self._close_without_lock()

    def __enter__(self) -> "RabbitMQConfirmingTransport":
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    def _ensure_channel(self) -> BlockingChannel:
        if (
            self._connection is not None
            and self._connection.is_open
            and self._channel is not None
            and self._channel.is_open
        ):
            return self._channel

        self._close_without_lock()
        connection = self._connection_factory(self._parameters)
        try:
            channel = connection.channel()
            channel.exchange_declare(
                exchange=self._exchange,
                exchange_type="direct",
                durable=True,
            )
            channel.queue_declare(
                queue=self._queue,
                durable=True,
            )
            channel.queue_bind(
                exchange=self._exchange,
                queue=self._queue,
                routing_key=self._ingestion_routing_key,
            )
            channel.confirm_delivery()
        except Exception:
            if connection.is_open:
                connection.close()
            raise

        self._connection = connection
        self._channel = channel
        return channel

    def _close_without_lock(self) -> None:
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
            client_properties={
                "connection_name": "medula-api-outbox-publisher",
            },
        )
