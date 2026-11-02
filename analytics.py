from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from database import get_products, read_frame


def daily_sales(product_id: int, days: int = 30) -> pd.DataFrame:
    end_date = date.today()
    start_date = end_date - timedelta(days=days - 1)
    transactions = read_frame(
        """
        SELECT date(created_at) AS sales_date, SUM(quantity) AS units_sold
        FROM transactions
        WHERE product_id = ? AND transaction_type = 'Sale'
          AND date(created_at) BETWEEN ? AND ?
        GROUP BY date(created_at)
        """,
        (product_id, start_date.isoformat(), end_date.isoformat()),
    )
    transactions["sales_date"] = pd.to_datetime(transactions["sales_date"])
    calendar = pd.DataFrame({"sales_date": pd.date_range(start_date, end_date)})
    result = calendar.merge(transactions, on="sales_date", how="left")
    result["units_sold"] = result["units_sold"].fillna(0).astype(int)
    return result


def moving_average_forecast(product_id: int, history_days: int = 30, forecast_days: int = 14) -> tuple[pd.DataFrame, float]:
    history = daily_sales(product_id, history_days)
    daily_average = float(history["units_sold"].mean()) if not history.empty else 0.0
    forecast_dates = pd.date_range(date.today() + timedelta(days=1), periods=forecast_days)
    forecast = pd.DataFrame(
        {
            "date": forecast_dates,
            "expected_demand": [daily_average] * forecast_days,
        }
    )
    return forecast, daily_average


def build_reorder_report() -> pd.DataFrame:
    products = get_products()
    if products.empty:
        products["average_daily_demand"] = pd.Series(dtype=float)
        products["reorder_point"] = pd.Series(dtype=float)
        products["suggested_order"] = pd.Series(dtype=int)
        products["stock_status"] = pd.Series(dtype=str)
        return products
    totals = read_frame(
        """
        SELECT product_id, SUM(quantity) AS units_sold
        FROM transactions
        WHERE transaction_type = 'Sale'
          AND date(created_at) >= date('now', '-29 days')
          AND date(created_at) <= date('now')
        GROUP BY product_id
        """
    )
    products = products.merge(totals, how="left", left_on="id", right_on="product_id")
    products["average_daily_demand"] = products["units_sold"].fillna(0) / 30
    products["reorder_point"] = (
        products["average_daily_demand"] * products["lead_time_days"] + products["safety_stock"]
    )
    products["suggested_order"] = (
        products["reorder_point"].apply(lambda value: max(0, int(value + 0.999999)))
        - products["quantity"]
    ).clip(lower=0).astype(int)
    products["stock_status"] = products.apply(
        lambda row: "Reorder now"
        if row["quantity"] <= row["reorder_point"]
        else ("Low stock" if row["quantity"] <= row["safety_stock"] else "Healthy"),
        axis=1,
    )
    return products
