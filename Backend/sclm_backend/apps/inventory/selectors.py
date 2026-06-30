"""
apps.inventory.selectors
Complex read-only queries for the Inventory module.
"""
import uuid
from django.db.models import Sum


def get_stock_summary(product_id: uuid.UUID) -> dict:
    """Returns current quantity, MAC, and SKU info for a product."""
    from apps.inventory.models import ProductSKU, StockLedger

    product = ProductSKU.objects.get(id=product_id)
    current_qty = StockLedger.objects.filter(
        product_id=product_id
    ).aggregate(total=Sum("delta_quantity"))["total"] or 0

    return {
        "product_id": str(product_id),
        "sku_code": product.sku_code,
        "name": product.name,
        "current_quantity": current_qty,
        "moving_average_cost": float(product.moving_average_cost),
        "total_value": float(product.moving_average_cost * current_qty),
        "is_hazmat": product.is_hazmat,
    }


def get_all_stock_balances() -> list[dict]:
    """
    Returns the running stock balance for all SKUs.
    Uses GROUP BY to compute SUM(delta_quantity) per product.
    """
    from apps.inventory.models import StockLedger, ProductSKU

    ledger_totals = (
        StockLedger.objects
        .values("product_id")
        .annotate(current_qty=Sum("delta_quantity"))
    )
    balance_map = {row["product_id"]: row["current_qty"] for row in ledger_totals}

    result = []
    for product in ProductSKU.objects.all().order_by("sku_code"):
        qty = balance_map.get(product.id, 0)
        result.append({
            "product_id": str(product.id),
            "sku_code": product.sku_code,
            "name": product.name,
            "current_quantity": qty,
            "moving_average_cost": float(product.moving_average_cost),
            "total_value": float(product.moving_average_cost * qty),
            "is_hazmat": product.is_hazmat,
            "reorder_point": product.reorder_point,
            "below_reorder_point": qty <= product.reorder_point,
        })
    return result
