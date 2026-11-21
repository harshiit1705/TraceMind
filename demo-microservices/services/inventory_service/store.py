"""In-memory inventory catalog and stock allocation store."""

import threading
from typing import Any, Dict, List, Optional, Tuple
from common.models import InventoryItem, OrderItem


INITIAL_CATALOG: Dict[str, Dict] = {
    "SKU-LAPTOP-01": {"name": "Pro Developer Laptop 16\"", "available_stock": 100, "price": 1299.99},
    "SKU-PHONE-02": {"name": "Flagship Smartphone 5G", "available_stock": 150, "price": 799.99},
    "SKU-HEADPHONES-03": {"name": "Noise Cancelling Headphones", "available_stock": 250, "price": 199.99},
    "SKU-KEYBOARD-04": {"name": "Mechanical RGB Keyboard", "available_stock": 300, "price": 119.99},
    "SKU-MOUSE-05": {"name": "Wireless Ergonomic Mouse", "available_stock": 400, "price": 59.99},
}


class InventoryStore:
    """Thread-safe in-memory stock management and reservation tracking for demo simulation.
    
    Note: In-memory store designed for deterministic demo simulation.
    Does not provide durable cross-process distributed transactions.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._stock: Dict[str, Dict] = {}
        self._reservations: Dict[str, Dict[str, Any]] = {}
        self.reset()

    def reset(self) -> None:
        """Reset stock counts back to initial catalog levels and clear all reservations."""
        with self._lock:
            self._stock = {sku: dict(data) for sku, data in INITIAL_CATALOG.items()}
            self._reservations = {}

    def get_item(self, sku: str) -> Optional[InventoryItem]:
        """Look up stock availability for a SKU."""
        with self._lock:
            data = self._stock.get(sku)
            if not data:
                return None
            return InventoryItem(
                sku=sku,
                name=data["name"],
                available_stock=data["available_stock"],
                price=data["price"],
            )

    def get_reservation(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Look up reservation details for an order."""
        with self._lock:
            res = self._reservations.get(order_id)
            if not res:
                return None
            return {
                "status": res["status"],
                "items": [
                    OrderItem(sku=item.sku, quantity=item.quantity, unit_price=item.unit_price)
                    for item in res["items"]
                ],
            }

    def reserve(
        self, items: List[OrderItem], order_id: Optional[str] = None
    ) -> Tuple[bool, List[OrderItem], Optional[str]]:
        """Atomically reserve all requested items or reject if any are insufficient.
        
        If order_id is provided, records reservation for tracking and idempotent retries.
        """
        with self._lock:
            # 0. Idempotency check: if order_id was already reserved, return cached reservation
            if order_id and order_id in self._reservations:
                res = self._reservations[order_id]
                if res["status"] == "RESERVED":
                    return True, res["items"], None
                elif res["status"] == "RELEASED":
                    return False, [], f"Order '{order_id}' was already released"

            # 1. Verification pass
            for item in items:
                record = self._stock.get(item.sku)
                if not record:
                    return False, [], f"SKU '{item.sku}' does not exist in inventory"
                if record["available_stock"] < item.quantity:
                    return (
                        False,
                        [],
                        f"Insufficient stock for SKU '{item.sku}': requested {item.quantity}, available {record['available_stock']}",
                    )

            # 2. Allocation pass
            reserved: List[OrderItem] = []
            for item in items:
                self._stock[item.sku]["available_stock"] -= item.quantity
                reserved.append(OrderItem(sku=item.sku, quantity=item.quantity, unit_price=item.unit_price))

            # 3. Record reservation if order_id is provided
            if order_id:
                self._reservations[order_id] = {
                    "status": "RESERVED",
                    "items": [
                        OrderItem(sku=item.sku, quantity=item.quantity, unit_price=item.unit_price)
                        for item in reserved
                    ],
                }

            return True, reserved, None

    def release(
        self, order_id: str, items: Optional[List[OrderItem]] = None
    ) -> Tuple[bool, List[OrderItem], Optional[str]]:
        """Atomically release a previously reserved order's stock back to inventory.
        
        - Full-reservation-only: partial reservation release is explicitly rejected.
        - Validates that a reservation exists for order_id.
        - Idempotent: repeated release of an already-released reservation returns success without stock inflation.
        - Rejects if reservation does not exist or if partial release is requested.
        """
        with self._lock:
            if not order_id or not str(order_id).strip():
                return False, [], "Order ID is required for inventory release"

            res = self._reservations.get(order_id)
            if not res:
                return False, [], f"No reservation found for order '{order_id}'"

            # Explicit full-reservation-only: reject requests that specify partial or mismatched items
            if items is not None:
                reserved_map = {item.sku: item.quantity for item in res["items"]}
                requested_map = {item.sku: item.quantity for item in items}
                if requested_map != reserved_map:
                    return (
                        False,
                        [],
                        f"Partial or mismatched release is not supported for order '{order_id}'. "
                        "Releases must be for the full reservation.",
                    )

            # Idempotent release: if already released, do not inflate stock again!
            if res["status"] == "RELEASED":
                return True, res["items"], None

            if res["status"] != "RESERVED":
                return False, [], f"Invalid reservation state '{res['status']}' for order '{order_id}'"

            reserved_items = res["items"]

            # Increment stock back for the reserved items
            items_to_restore = reserved_items
            for item in items_to_restore:
                if item.sku in self._stock:
                    self._stock[item.sku]["available_stock"] += item.quantity
                else:
                    self._stock[item.sku] = {
                        "name": item.sku,
                        "available_stock": item.quantity,
                        "price": item.unit_price,
                    }

            res["status"] = "RELEASED"
            return True, items_to_restore, None


inventory_store = InventoryStore()

