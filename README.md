# SmartStock

SmartStock is a working inventory management and stock prediction application built with Python, Streamlit, SQLite, Pandas and Plotly.

## Features

- Dashboard metrics for product and supplier counts, available units, low stock and reorder alerts.
- Product and supplier create, edit, search, filter and delete workflows.
- Stock transactions for purchases, sales, usage, returns and damaged goods, with atomic stock updates and negative-stock prevention.
- 30-day moving-average demand forecasts and reorder recommendations using:

  `Reorder Point = (Average Daily Demand × Supplier Lead Time) + Safety Stock`

- Inventory, transaction, low-stock and demand reports with CSV downloads.
- A discrete mathematics page demonstrating sets, relations, logic, functions, recurrence relations, counting, graph theory and trees using live database records.
- SQLite persistence and seeded demonstration data on first launch.

## Run locally

From the project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py
```

The database is created as `smartstock.db` beside `app.py`. It is populated with realistic demonstration records the first time the app starts. Existing database content is preserved on subsequent launches.

## Stock calculation notes

Purchases and returns increase on-hand quantity. Sales, usage and damaged items decrease it. A transaction is rejected if its outbound quantity exceeds available stock. The reorder estimate uses total sales in the most recent 30 calendar days divided by 30 as average daily demand. The forecast plots that average as the expected demand for each of the next 14 days.

Product quantity can be set directly during product editing for opening-balance corrections. To preserve an auditable movement history, products that have transactions cannot be deleted, and suppliers linked to products must be unassigned before deletion.
