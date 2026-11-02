import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import database
from analytics import build_reorder_report, moving_average_forecast


class InventoryWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path_patch = patch.object(
            database, "DATABASE_PATH", Path(self.temporary_directory.name) / "test_smartstock.db"
        )
        self.database_path_patch.start()
        database.initialize_database()

    def tearDown(self):
        self.database_path_patch.stop()
        self.temporary_directory.cleanup()

    def test_seed_data_and_reorder_calculation(self):
        products = database.get_products()
        self.assertEqual(len(products), 6)

        report = build_reorder_report().set_index("sku")
        hub = report.loc["ELC-3180"]
        self.assertAlmostEqual(hub["average_daily_demand"], 9 / 30)
        self.assertAlmostEqual(hub["reorder_point"], 15.6)
        self.assertEqual(hub["suggested_order"], 8)

    def test_stock_transaction_updates_quantity_and_history(self):
        product = database.get_products().iloc[0]
        initial_quantity = int(product["quantity"])
        initial_transactions = len(database.get_transactions())

        database.record_transaction(int(product["id"]), "Purchase", 4, 4.20, "Restock")
        database.record_transaction(int(product["id"]), "Sale", 2, 7.50, "Order")

        updated = database.get_products().set_index("id").loc[product["id"]]
        self.assertEqual(int(updated["quantity"]), initial_quantity + 2)
        self.assertEqual(len(database.get_transactions()), initial_transactions + 2)

    def test_all_transaction_types_apply_the_correct_stock_direction(self):
        product = database.get_products().iloc[0]
        initial_quantity = int(product["quantity"])
        movements = (
            ("Purchase", 2, 2),
            ("Sale", 1, -1),
            ("Usage", 1, -1),
            ("Return", 2, 2),
            ("Damaged", 1, -1),
        )

        for transaction_type, quantity, _ in movements:
            database.record_transaction(int(product["id"]), transaction_type, quantity, 1.0)

        expected_quantity = initial_quantity + sum(change for _, _, change in movements)
        actual_quantity = int(database.get_products().set_index("id").loc[product["id"], "quantity"])
        self.assertEqual(actual_quantity, expected_quantity)

    def test_product_and_supplier_create_update_delete(self):
        database.save_supplier({
            "name": "Workflow Supplier",
            "contact_person": "Morgan Lee",
            "email": "morgan@example.com",
            "phone": "555-0100",
            "address": "10 Test Street",
        })
        supplier = database.get_suppliers().set_index("name").loc["Workflow Supplier"]
        database.save_product({
            "name": "Workflow Product",
            "sku": "TEST-100",
            "category": "Testing",
            "quantity": 5,
            "unit_cost": 2.5,
            "unit_price": 4.0,
            "safety_stock": 2,
            "lead_time_days": 4,
            "supplier_id": int(supplier["id"]),
        })
        product = database.get_products().set_index("sku").loc["TEST-100"]
        self.assertEqual(product["supplier_name"], "Workflow Supplier")

        database.save_product({
            "name": "Updated Workflow Product",
            "sku": "TEST-100",
            "category": "Testing",
            "quantity": 5,
            "unit_cost": 2.75,
            "unit_price": 4.5,
            "safety_stock": 3,
            "lead_time_days": 6,
            "supplier_id": int(supplier["id"]),
        }, int(product["id"]))
        self.assertEqual(database.get_products().set_index("sku").loc["TEST-100", "name"], "Updated Workflow Product")

        database.delete_product(int(product["id"]))
        database.delete_supplier(int(supplier["id"]))
        self.assertNotIn("TEST-100", database.get_products()["sku"].tolist())
        self.assertNotIn("Workflow Supplier", database.get_suppliers()["name"].tolist())

    def test_overselling_is_rejected_without_partial_changes(self):
        product = database.get_products().iloc[0]
        quantity_before = int(product["quantity"])
        transactions_before = len(database.get_transactions())

        with self.assertRaisesRegex(ValueError, "below zero"):
            database.record_transaction(
                int(product["id"]), "Sale", quantity_before + 1, 1.0, "Excess sale"
            )

        quantity_after = int(database.get_products().set_index("id").loc[product["id"], "quantity"])
        self.assertEqual(quantity_after, quantity_before)
        self.assertEqual(len(database.get_transactions()), transactions_before)

    def test_moving_average_forecast_uses_calendar_days(self):
        product = database.get_products().iloc[0]
        forecast, average = moving_average_forecast(int(product["id"]))
        self.assertEqual(len(forecast), 14)
        self.assertAlmostEqual(average, 18 / 30)
        self.assertTrue((forecast["expected_demand"] == average).all())

    def test_transaction_quantity_must_be_a_positive_integer(self):
        product = database.get_products().iloc[0]
        with self.assertRaisesRegex(ValueError, "positive whole number"):
            database.record_transaction(int(product["id"]), "Sale", 1.5, 1.0)


if __name__ == "__main__":
    unittest.main()
