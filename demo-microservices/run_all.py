"""Process runner to launch Order, Payment, and Inventory microservices concurrently."""

import asyncio
import logging
import signal
import sys
from pathlib import Path
import uvicorn

# Ensure demo-microservices is on sys.path
root_dir = Path(__file__).resolve().parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from common.config import config
from services.order_service.main import app as order_app
from services.payment_service.main import app as payment_app
from services.inventory_service.main import app as inventory_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s")
logger = logging.getLogger("demo_microservices.runner")


async def main():
    logger.info("Starting demo microservices:")
    logger.info("  Order Service:     http://%s:%d", config.ORDER_SERVICE_HOST, config.ORDER_SERVICE_PORT)
    logger.info("  Payment Service:   http://%s:%d", config.PAYMENT_SERVICE_HOST, config.PAYMENT_SERVICE_PORT)
    logger.info("  Inventory Service: http://%s:%d", config.INVENTORY_SERVICE_HOST, config.INVENTORY_SERVICE_PORT)

    order_config = uvicorn.Config(
        order_app,
        host=config.ORDER_SERVICE_HOST,
        port=config.ORDER_SERVICE_PORT,
        log_level="warning",
    )
    payment_config = uvicorn.Config(
        payment_app,
        host=config.PAYMENT_SERVICE_HOST,
        port=config.PAYMENT_SERVICE_PORT,
        log_level="warning",
    )
    inventory_config = uvicorn.Config(
        inventory_app,
        host=config.INVENTORY_SERVICE_HOST,
        port=config.INVENTORY_SERVICE_PORT,
        log_level="warning",
    )

    servers = [
        uvicorn.Server(order_config),
        uvicorn.Server(payment_config),
        uvicorn.Server(inventory_config),
    ]

    stop_event = asyncio.Event()

    def handle_signal():
        logger.info("Shutdown signal received, stopping all services...")
        stop_event.set()
        for s in servers:
            s.should_exit = True

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, handle_signal)
        except NotImplementedError:
            # Signal handlers not implemented on Windows event loop for add_signal_handler
            pass

    server_tasks = [asyncio.create_task(server.serve()) for server in servers]

    try:
        await asyncio.gather(*server_tasks)
    except (asyncio.CancelledError, KeyboardInterrupt):
        logger.info("Services shutting down...")
    finally:
        for s in servers:
            s.should_exit = True
        logger.info("All demo microservices stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass

