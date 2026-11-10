"""Configuration settings for demo-microservices."""

import os
from typing import Optional


class DemoConfig:
    """Configuration loaded from environment variables with sensible defaults."""

    # TraceMind Backend Integration
    TRACEMIND_API_URL: str = os.getenv("TRACEMIND_API_URL", "http://localhost:8000/api/v1").rstrip("/")
    PROJECT_SLUG: str = os.getenv("PROJECT_SLUG", "core-ecommerce")
    PROJECT_ID: Optional[str] = os.getenv("PROJECT_ID", None)

    # Microservice Network Ports
    ORDER_SERVICE_HOST: str = os.getenv("ORDER_SERVICE_HOST", "127.0.0.1")
    ORDER_SERVICE_PORT: int = int(os.getenv("ORDER_SERVICE_PORT", "8001"))

    PAYMENT_SERVICE_HOST: str = os.getenv("PAYMENT_SERVICE_HOST", "127.0.0.1")
    PAYMENT_SERVICE_PORT: int = int(os.getenv("PAYMENT_SERVICE_PORT", "8002"))

    INVENTORY_SERVICE_HOST: str = os.getenv("INVENTORY_SERVICE_HOST", "127.0.0.1")
    INVENTORY_SERVICE_PORT: int = int(os.getenv("INVENTORY_SERVICE_PORT", "8003"))

    # Service-to-Service Base URLs
    @classmethod
    def get_inventory_url(cls) -> str:
        return f"http://{cls.INVENTORY_SERVICE_HOST}:{cls.INVENTORY_SERVICE_PORT}"

    @classmethod
    def get_payment_url(cls) -> str:
        return f"http://{cls.PAYMENT_SERVICE_HOST}:{cls.PAYMENT_SERVICE_PORT}"

    @classmethod
    def get_order_url(cls) -> str:
        return f"http://{cls.ORDER_SERVICE_HOST}:{cls.ORDER_SERVICE_PORT}"

    # Telemetry Configuration
    TELEMETRY_ENABLED: bool = os.getenv("TELEMETRY_ENABLED", "true").lower() in ("true", "1", "yes")
    TELEMETRY_TIMEOUT_SECONDS: float = float(os.getenv("TELEMETRY_TIMEOUT_SECONDS", "2.0"))
    TELEMETRY_MAX_RETRIES: int = int(os.getenv("TELEMETRY_MAX_RETRIES", "1"))
    TELEMETRY_QUEUE_MAX_SIZE: int = int(os.getenv("TELEMETRY_QUEUE_MAX_SIZE", "1000"))
    TELEMETRY_AGGREGATION_INTERVAL_SECONDS: float = float(
        os.getenv("TELEMETRY_AGGREGATION_INTERVAL_SECONDS", "1.0")
    )
    TELEMETRY_SHUTDOWN_TIMEOUT_SECONDS: float = float(
        os.getenv("TELEMETRY_SHUTDOWN_TIMEOUT_SECONDS", "5.0")
    )


config = DemoConfig()

