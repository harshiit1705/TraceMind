"""In-memory inventory catalog and stock allocation store."""

from typing import Dict, List, Optional, Tuple
from common.models import InventoryItem, OrderItem


INITIAL_CATALOG: Dict[str, Dict] = {
    "SKU-LAPTOP-01": {"name": "Pro Developer Laptop 16\"", "available_stock": 100, "price": 1299.99},
    "SKU-PHONE-02": {"name": "Flagship Smartphone 5G", "available_stock": 150, "price": 799.99},
    "SKU-HEADPHONES-03": {"name": "Noise Cancelling Headphones", "available_stock": 250, "price": 199.99},
    "SKU-KEYBOARD-04": {"name": "Mechanical RGB Keyboard", "available_stock": 300, "price": 119.99},
    "SKU-MOUSE-05": {"name": "Wireless Ergonomic Mouse", "available_stock": 400, "price": 59.99},
}


class InventoryStore:
    """Thread-safe in-memory stock management for demo simulation."""

    def __init__(self):
        self._stock: Dict[str, Dict] = {}
        self.reset()

    def reset(self) -> None:
        """Reset stock counts back to initial catalog levels."""
        self._stock = {sku: dict(data) for sku, data in INITIAL_CATALOG.items()}

    def get_item(self, sku: str) -> Optional[InventoryItem]:
        """Look up stock availability for a SKU."""
        data = self._stock.get(sku)
        if not data:
            return None
        return InventoryItem(
            sku=sku,
            name=data["name"],
            available_stock=data["available_stock"],
            price=data["price"],
        )

    def reserve(self, items: List[OrderItem]) -> Tuple[bool, List[OrderItem], Optional[str]]:
        """Atomically reserve all requested items or reject if any are insufficient."""
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
            reserved.append(item)

        return True, reserved, None


inventory_store = InventoryStore()

