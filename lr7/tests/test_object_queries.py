import copy
import unittest
from dataclasses import dataclass
from decimal import Decimal

try:
    from lr7.src import object_queries as queries
except ModuleNotFoundError as error:
    if error.name != "lr7":
        raise
    from src import object_queries as queries


@dataclass
class Supplier:
    supplier_id: int
    tax_id: str
    name: str
    rating: Decimal
    is_active: bool = True


@dataclass
class Product:
    sku: str
    unit_price: Decimal


@dataclass
class Warehouse:
    warehouse_id: int
    code: str
    city: str


@dataclass
class Delivery:
    delivery_id: int
    supplier_id: int
    warehouse_id: int
    quantity: int
    unit_cost: Decimal
    quality_status: str


class ObjectQueriesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.suppliers = [
            Supplier(1, "111", "Первый", Decimal("4.00")),
            Supplier(2, "222", "Второй", Decimal("5.00"), False),
            Supplier(3, "333", "Третий", Decimal("3.99")),
            Supplier(4, "444", "Без поставок", Decimal("4.50")),
        ]
        self.products = [
            Product("C", Decimal(5)),
            Product("B", Decimal(10)),
            Product("A", Decimal(10)),
            Product("A", Decimal(10)),
        ]
        self.warehouses = [
            Warehouse(1, "WH-1", "Москва"),
            Warehouse(2, "WH-2", "Казань"),
        ]
        self.deliveries = [
            Delivery(1, 1, 1, 2, Decimal("1.25"), "accepted"),
            Delivery(2, 1, 2, 3, Decimal("2.10"), "rejected"),
            Delivery(3, 2, 1, 1, Decimal("1.25"), "accepted"),
            Delivery(4, 3, 9, 0, Decimal(9), "inspection"),
        ]

    def test_filter_and_projection(self) -> None:
        self.assertEqual(
            queries.select_active_suppliers(self.suppliers, Decimal(4)),
            [
                ("111", "Первый"),
                ("444", "Без поставок"),
            ],
        )

    def test_order_limit_and_stability(self) -> None:
        result = queries.top_products(self.products, 3)
        self.assertEqual([product.sku for product in result], ["A", "A", "B"])
        self.assertIs(result[0], self.products[2])
        self.assertIs(result[1], self.products[3])
        self.assertEqual(queries.top_products(self.products, 0), [])
        with self.assertRaises(ValueError):
            queries.top_products(self.products, -1)

    def test_group_and_aggregates(self) -> None:
        result = queries.summarize_deliveries(self.deliveries)
        self.assertEqual(
            result["accepted"],
            {"count": 2, "quantity": 3, "total_cost": Decimal("3.75")},
        )
        self.assertEqual(result["rejected"]["total_cost"], Decimal("6.30"))
        self.assertEqual(list(result), ["accepted", "inspection", "rejected"])

    def test_inner_join(self) -> None:
        self.assertEqual(
            queries.join_deliveries_warehouses(self.deliveries, self.warehouses),
            [
                (1, "WH-1", "Москва"),
                (2, "WH-2", "Казань"),
                (3, "WH-1", "Москва"),
            ],
        )

    def test_any_all_and_no_vacuous_match(self) -> None:
        result = queries.suppliers_with_valid_deliveries(
            self.suppliers, self.deliveries
        )
        self.assertEqual(
            [(row["supplier"].supplier_id, row["has_rejected"]) for row in result],
            [
                (1, True),
                (2, False),
            ],
        )

    def test_empty_inputs(self) -> None:
        self.assertEqual(queries.select_active_suppliers([], Decimal(4)), [])
        self.assertEqual(queries.top_products([], 10), [])
        self.assertEqual(queries.summarize_deliveries([]), {})
        self.assertEqual(queries.join_deliveries_warehouses([], self.warehouses), [])
        self.assertEqual(queries.join_deliveries_warehouses(self.deliveries, []), [])
        self.assertEqual(
            queries.suppliers_with_valid_deliveries(self.suppliers, []), []
        )
        self.assertEqual(
            queries.suppliers_with_valid_deliveries([], self.deliveries), []
        )

    def test_inputs_unchanged(self) -> None:
        original = copy.deepcopy(
            (self.suppliers, self.products, self.warehouses, self.deliveries)
        )
        queries.select_active_suppliers(self.suppliers, Decimal(4))
        queries.top_products(self.products, 2)
        queries.summarize_deliveries(self.deliveries)
        queries.join_deliveries_warehouses(self.deliveries, self.warehouses)
        queries.suppliers_with_valid_deliveries(self.suppliers, self.deliveries)
        self.assertEqual(
            (self.suppliers, self.products, self.warehouses, self.deliveries), original
        )
