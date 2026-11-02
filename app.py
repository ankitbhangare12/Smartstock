from __future__ import annotations

import sqlite3
from datetime import date

import pandas as pd
import plotly.express as px
import streamlit as st

from analytics import build_reorder_report, daily_sales, moving_average_forecast
from database import (
    TRANSACTION_TYPES,
    delete_product,
    delete_supplier,
    get_products,
    get_suppliers,
    get_transactions,
    initialize_database,
    record_transaction,
    save_product,
    save_supplier,
)


st.set_page_config(
    page_title="SmartStock | Inventory Management",
    page_icon="SS",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stApp { background: #f6f8fb; color: #17243a; }
    [data-testid="stHeader"] { background: #f6f8fb; }
    [data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid #e6eaf0; }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #34445c; }
    .block-container { max-width: 1440px; padding-top: 2rem; padding-bottom: 3rem; }
    h1, h2, h3 { color: #142b4a; letter-spacing: -0.025em; }
    h1 { font-size: 1.85rem !important; font-weight: 650 !important; }
    h2 { font-size: 1.28rem !important; font-weight: 600 !important; }
    h3 { font-size: 1.05rem !important; font-weight: 600 !important; }
    div[data-testid="stMetric"] {
      background: #ffffff; border: 1px solid #e7ebf1; padding: 18px 20px;
      border-radius: 9px; box-shadow: 0 1px 2px rgba(20, 43, 74, .03);
    }
    div[data-testid="stMetricLabel"] { color: #64748b; font-size: .82rem; }
    div[data-testid="stMetricValue"] { color: #142b4a; font-size: 1.7rem; font-weight: 650; }
    .section-note { color: #68778c; font-size: .9rem; margin-top: -.5rem; }
    div.stButton > button[kind="primary"], div.stFormSubmitButton > button {
      background: #1d4778; border-color: #1d4778; border-radius: 6px;
    }
    div[data-testid="stDataFrame"] { border: 1px solid #e7ebf1; border-radius: 8px; overflow: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)

initialize_database()


def section_heading(title: str, description: str = "") -> None:
    st.title(title)
    if description:
        st.markdown(f'<p class="section-note">{description}</p>', unsafe_allow_html=True)


def safe_action(action, success_message: str) -> bool:
    try:
        action()
        st.success(success_message)
        return True
    except (ValueError, sqlite3.IntegrityError) as error:
        st.error(str(error))
    except sqlite3.Error as error:
        st.error(f"Database operation failed: {error}")
    return False


def show_dashboard() -> None:
    section_heading("Dashboard", "A current view of inventory health and recent activity.")
    products = get_products()
    suppliers = get_suppliers()
    transactions = get_transactions(8)
    reorder = build_reorder_report()
    low_stock = products[products["quantity"] <= products["safety_stock"]] if not products.empty else products
    inventory_units = int(products["quantity"].sum()) if not products.empty else 0
    inventory_value = float((products["quantity"] * products["unit_cost"]).sum()) if not products.empty else 0
    reorder_count = int((reorder["stock_status"] == "Reorder now").sum()) if not reorder.empty else 0

    metrics = st.columns(5)
    metrics[0].metric("Products", f"{len(products):,}")
    metrics[1].metric("Suppliers", f"{len(suppliers):,}")
    metrics[2].metric("Available units", f"{inventory_units:,}")
    metrics[3].metric("Low-stock items", f"{len(low_stock):,}")
    metrics[4].metric("Reorder alerts", f"{reorder_count:,}")

    st.write("")
    chart_col, value_col = st.columns([1.7, 1])
    with chart_col:
        st.subheader("Stock by category")
        if products.empty:
            st.info("Add products to see inventory by category.")
        else:
            category_stock = products.groupby("category", as_index=False)["quantity"].sum()
            chart = px.bar(
                category_stock, x="category", y="quantity",
                color_discrete_sequence=["#315f91"],
                labels={"category": "Category", "quantity": "Available units"},
            )
            chart.update_layout(
                margin=dict(l=0, r=0, t=10, b=0), height=300,
                paper_bgcolor="white", plot_bgcolor="white",
                font=dict(family="Inter", color="#43536b"),
                xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#edf0f4"),
            )
            st.plotly_chart(chart, use_container_width=True)
    with value_col:
        st.subheader("Inventory value")
        st.metric("At cost", f"${inventory_value:,.2f}")
        st.caption("Available units multiplied by unit cost.")
        st.subheader("Items to review")
        if reorder_count:
            st.dataframe(
                reorder.loc[reorder["stock_status"] == "Reorder now", ["name", "quantity", "reorder_point"]]
                .rename(columns={"name": "Product", "quantity": "On hand", "reorder_point": "Reorder point"})
                .head(5),
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.success("No products currently meet the reorder threshold.")

    st.subheader("Recent transactions")
    if transactions.empty:
        st.info("Transactions will appear here after the first stock movement.")
    else:
        recent = transactions[["created_at", "product_name", "transaction_type", "quantity", "notes"]].copy()
        recent.columns = ["Date", "Product", "Type", "Quantity", "Notes"]
        st.dataframe(recent, hide_index=True, use_container_width=True)


def show_products() -> None:
    section_heading("Products", "Maintain your catalog, stock levels and supplier assignments.")
    products = get_products()
    suppliers = get_suppliers()
    supplier_options = {row["name"]: int(row["id"]) for _, row in suppliers.iterrows()}

    with st.expander("Add a product", expanded=False):
        with st.form("add_product_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Product name")
            sku = c2.text_input("SKU")
            category = c3.text_input("Category")
            c1, c2, c3 = st.columns(3)
            quantity = c1.number_input("Opening quantity", min_value=0, step=1)
            unit_cost = c2.number_input("Unit cost ($)", min_value=0.0, step=0.25, format="%.2f")
            unit_price = c3.number_input("Unit price ($)", min_value=0.0, step=0.25, format="%.2f")
            c1, c2, c3 = st.columns(3)
            safety_stock = c1.number_input("Safety stock", min_value=0, step=1)
            lead_time = c2.number_input("Supplier lead time (days)", min_value=0, step=1, value=7)
            selected_supplier = c3.selectbox("Supplier", ["Unassigned", *supplier_options.keys()])
            submitted = st.form_submit_button("Add product", type="primary")
            if submitted:
                values = {
                    "name": name, "sku": sku, "category": category, "quantity": quantity,
                    "unit_cost": unit_cost, "unit_price": unit_price, "safety_stock": safety_stock,
                    "lead_time_days": lead_time,
                    "supplier_id": supplier_options.get(selected_supplier),
                }
                if safe_action(lambda: save_product(values), "Product added."):
                    st.rerun()

    if products.empty:
        st.info("No products found.")
        return
    left, right = st.columns([2, 1])
    search = left.text_input("Search products", placeholder="Search by name, SKU or category")
    categories = ["All categories", *sorted(products["category"].dropna().unique().tolist())]
    category_filter = right.selectbox("Category", categories)
    filtered = products.copy()
    if search.strip():
        text = search.strip().lower()
        filtered = filtered[
            filtered[["name", "sku", "category"]].fillna("").astype(str)
            .apply(lambda column: column.str.lower().str.contains(text, regex=False)).any(axis=1)
        ]
    if category_filter != "All categories":
        filtered = filtered[filtered["category"] == category_filter]
    display = filtered[["name", "sku", "category", "quantity", "safety_stock", "unit_cost", "unit_price", "supplier_name"]]
    display = display.rename(columns={
        "name": "Product", "sku": "SKU", "category": "Category", "quantity": "On hand",
        "safety_stock": "Safety stock", "unit_cost": "Unit cost", "unit_price": "Unit price",
        "supplier_name": "Supplier",
    })
    st.dataframe(display, hide_index=True, use_container_width=True)

    st.subheader("Edit or delete a product")
    product_map = {f"{row['name']} · {row['sku']}": row for _, row in products.iterrows()}
    selected_label = st.selectbox("Select product", list(product_map), key="edit_product_select")
    selected = product_map[selected_label]
    with st.form("edit_product_form"):
        c1, c2, c3 = st.columns(3)
        edit_name = c1.text_input("Product name", value=selected["name"], key="edit_name")
        edit_sku = c2.text_input("SKU", value=selected["sku"], key="edit_sku")
        edit_category = c3.text_input("Category", value=selected["category"], key="edit_category")
        c1, c2, c3 = st.columns(3)
        edit_quantity = c1.number_input(
            "On-hand quantity (managed by transactions)",
            min_value=0,
            step=1,
            value=int(selected["quantity"]),
            disabled=True,
        )
        edit_cost = c2.number_input("Unit cost ($)", min_value=0.0, step=0.25, value=float(selected["unit_cost"]), format="%.2f")
        edit_price = c3.number_input("Unit price ($)", min_value=0.0, step=0.25, value=float(selected["unit_price"]), format="%.2f")
        c1, c2, c3 = st.columns(3)
        edit_safety = c1.number_input("Safety stock", min_value=0, step=1, value=int(selected["safety_stock"]))
        edit_lead = c2.number_input("Supplier lead time (days)", min_value=0, step=1, value=int(selected["lead_time_days"]))
        current_supplier = selected["supplier_name"] if pd.notna(selected["supplier_name"]) else "Unassigned"
        supplier_choices = ["Unassigned", *supplier_options.keys()]
        edit_supplier = c3.selectbox(
            "Supplier", supplier_choices,
            index=supplier_choices.index(current_supplier) if current_supplier in supplier_choices else 0,
        )
        save_clicked = st.form_submit_button("Save changes", type="primary")
        if save_clicked:
            values = {
                "name": edit_name, "sku": edit_sku, "category": edit_category,
                "quantity": edit_quantity, "unit_cost": edit_cost, "unit_price": edit_price,
                "safety_stock": edit_safety, "lead_time_days": edit_lead,
                "supplier_id": supplier_options.get(edit_supplier),
            }
            if safe_action(lambda: save_product(values, int(selected["id"])), "Product updated."):
                st.rerun()
    if st.button("Delete selected product", key="delete_product"):
        if safe_action(lambda: delete_product(int(selected["id"])), "Product deleted."):
            st.rerun()
        else:
            st.info("Products with transaction history cannot be deleted.")


def show_suppliers() -> None:
    section_heading("Suppliers", "Keep supplier contacts current and see their linked products.")
    suppliers = get_suppliers()
    if not suppliers.empty:
        st.dataframe(
            suppliers[["name", "contact_person", "email", "phone", "address", "product_count"]]
            .rename(columns={
                "name": "Supplier", "contact_person": "Contact", "email": "Email", "phone": "Phone",
                "address": "Address", "product_count": "Linked products",
            }),
            hide_index=True, use_container_width=True,
        )
    add_col, edit_col = st.columns(2)
    with add_col:
        st.subheader("Add a supplier")
        with st.form("add_supplier_form", clear_on_submit=True):
            name = st.text_input("Supplier name")
            contact = st.text_input("Contact person")
            email = st.text_input("Email")
            phone = st.text_input("Phone")
            address = st.text_input("Address")
            submitted = st.form_submit_button("Add supplier", type="primary")
            if submitted:
                values = {"name": name, "contact_person": contact, "email": email, "phone": phone, "address": address}
                if safe_action(lambda: save_supplier(values), "Supplier added."):
                    st.rerun()
    with edit_col:
        st.subheader("Edit or delete a supplier")
        if suppliers.empty:
            st.info("Add a supplier to manage its details.")
            return
        supplier_map = {row["name"]: row for _, row in suppliers.iterrows()}
        selected_name = st.selectbox("Select supplier", list(supplier_map))
        selected = supplier_map[selected_name]
        with st.form("edit_supplier_form"):
            edit_name = st.text_input("Supplier name", value=selected["name"], key="supplier_edit_name")
            edit_contact = st.text_input("Contact person", value=selected["contact_person"], key="supplier_edit_contact")
            edit_email = st.text_input("Email", value=selected["email"], key="supplier_edit_email")
            edit_phone = st.text_input("Phone", value=selected["phone"], key="supplier_edit_phone")
            edit_address = st.text_input("Address", value=selected["address"], key="supplier_edit_address")
            submitted = st.form_submit_button("Save supplier", type="primary")
            if submitted:
                values = {
                    "name": edit_name, "contact_person": edit_contact, "email": edit_email,
                    "phone": edit_phone, "address": edit_address,
                }
                if safe_action(lambda: save_supplier(values, int(selected["id"])), "Supplier updated."):
                    st.rerun()
        if st.button("Delete selected supplier", key="delete_supplier"):
            if safe_action(lambda: delete_supplier(int(selected["id"])), "Supplier deleted."):
                st.rerun()
            else:
                st.info("A supplier linked to products cannot be deleted. Reassign its products first.")

    st.subheader("Supplier-product links")
    products = get_products()
    if products.empty:
        st.info("No products are linked yet.")
    else:
        links = products[["supplier_name", "name", "sku", "category"]].copy()
        links.columns = ["Supplier", "Product", "SKU", "Category"]
        st.dataframe(links, hide_index=True, use_container_width=True)


def show_transactions() -> None:
    section_heading("Stock transactions", "Record stock movements. Quantity changes are applied immediately.")
    products = get_products()
    if products.empty:
        st.info("Add a product before recording a transaction.")
        return
    product_map = {f"{row['name']} · {row['sku']} (on hand: {row['quantity']})": row for _, row in products.iterrows()}
    with st.form("transaction_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        selected_label = c1.selectbox("Product", list(product_map))
        transaction_type = c2.selectbox("Transaction type", TRANSACTION_TYPES)
        quantity = c3.number_input("Quantity", min_value=1, step=1, value=1)
        c1, c2, c3 = st.columns(3)
        unit_price = c1.number_input("Unit amount ($)", min_value=0.0, step=0.25, format="%.2f")
        transaction_date = c2.date_input("Transaction date", value=date.today(), max_value=date.today())
        notes = c3.text_input("Notes")
        submitted = st.form_submit_button("Record transaction", type="primary")
        if submitted:
            product = product_map[selected_label]
            if safe_action(
                lambda: record_transaction(
                    int(product["id"]), transaction_type, int(quantity), float(unit_price), notes, transaction_date
                ),
                f"{transaction_type} recorded and stock updated.",
            ):
                st.rerun()

    st.subheader("Transaction history")
    transactions = get_transactions()
    if transactions.empty:
        st.info("No transactions recorded.")
    else:
        type_filter = st.multiselect("Filter by type", TRANSACTION_TYPES, default=list(TRANSACTION_TYPES))
        filtered = transactions[transactions["transaction_type"].isin(type_filter)]
        display = filtered[["created_at", "product_name", "sku", "transaction_type", "quantity", "unit_price", "notes"]]
        display.columns = ["Date", "Product", "SKU", "Type", "Quantity", "Unit amount", "Notes"]
        st.dataframe(display, hide_index=True, use_container_width=True)


def show_forecasting() -> None:
    section_heading("Demand & restocking", "A transparent moving-average forecast based on recorded sales.")
    products = get_products()
    if products.empty:
        st.info("Add products and record sales to generate a forecast.")
        return
    reorder = build_reorder_report()
    st.subheader("Smart restocking")
    st.caption("Reorder point = (average daily demand × supplier lead time) + safety stock. Suggested order raises stock to the reorder point.")
    restock_view = reorder[
        ["name", "sku", "quantity", "average_daily_demand", "lead_time_days", "safety_stock", "reorder_point", "suggested_order", "stock_status"]
    ].copy()
    restock_view.columns = [
        "Product", "SKU", "On hand", "Avg daily demand", "Lead time (days)",
        "Safety stock", "Reorder point", "Suggested order", "Status",
    ]
    restock_view["Avg daily demand"] = restock_view["Avg daily demand"].round(2)
    restock_view["Reorder point"] = restock_view["Reorder point"].round(1)
    st.dataframe(restock_view, hide_index=True, use_container_width=True)

    st.subheader("Moving-average demand forecast")
    selected_label = st.selectbox(
        "Product to forecast",
        [f"{row['name']} · {row['sku']}" for _, row in products.iterrows()],
    )
    selected = products[
        products.apply(lambda row: f"{row['name']} · {row['sku']}" == selected_label, axis=1)
    ].iloc[0]
    forecast, average = moving_average_forecast(int(selected["id"]))
    history = daily_sales(int(selected["id"]))
    st.metric("Average daily sales (last 30 days)", f"{average:.2f} units")
    chart_data = pd.concat(
        [
            history.rename(columns={"sales_date": "date", "units_sold": "units"})[["date", "units"]].assign(series="Actual"),
            forecast.rename(columns={"expected_demand": "units"})[["date", "units"]].assign(series="Forecast"),
        ],
        ignore_index=True,
    )
    chart = px.line(
        chart_data, x="date", y="units", color="series", markers=True,
        color_discrete_map={"Actual": "#315f91", "Forecast": "#7f9dbb"},
        labels={"date": "Date", "units": "Units", "series": ""},
    )
    chart.update_layout(
        margin=dict(l=0, r=0, t=15, b=0), height=350, paper_bgcolor="white",
        plot_bgcolor="white", font=dict(family="Inter", color="#43536b"),
        yaxis=dict(rangemode="tozero", gridcolor="#edf0f4"), xaxis=dict(showgrid=False),
        legend=dict(orientation="h", y=1.08, x=0),
    )
    st.plotly_chart(chart, use_container_width=True)


def show_reports() -> None:
    section_heading("Reports", "Filter, review and export inventory and operational data.")
    report_type = st.selectbox(
        "Report",
        ["Inventory", "Transactions", "Low stock", "Demand"],
    )
    if report_type == "Inventory":
        data = get_products()
        columns = ["sku", "name", "category", "quantity", "safety_stock", "unit_cost", "unit_price", "supplier_name"]
        data = data[columns].rename(columns={
            "sku": "SKU", "name": "Product", "category": "Category", "quantity": "On hand",
            "safety_stock": "Safety stock", "unit_cost": "Unit cost", "unit_price": "Unit price",
            "supplier_name": "Supplier",
        })
    elif report_type == "Transactions":
        data = get_transactions()
        data = data[["created_at", "product_name", "sku", "transaction_type", "quantity", "unit_price", "notes"]]
        data.columns = ["Date", "Product", "SKU", "Type", "Quantity", "Unit amount", "Notes"]
    elif report_type == "Low stock":
        report = build_reorder_report()
        data = report[report["quantity"] <= report["safety_stock"]][
            ["sku", "name", "quantity", "safety_stock", "stock_status", "supplier_name"]
        ].rename(columns={
            "sku": "SKU", "name": "Product", "quantity": "On hand", "safety_stock": "Safety stock",
            "stock_status": "Status", "supplier_name": "Supplier",
        })
    else:
        data = build_reorder_report()[
            ["sku", "name", "quantity", "average_daily_demand", "lead_time_days", "reorder_point", "suggested_order"]
        ].rename(columns={
            "sku": "SKU", "name": "Product", "quantity": "On hand",
            "average_daily_demand": "Avg daily demand", "lead_time_days": "Lead time (days)",
            "reorder_point": "Reorder point", "suggested_order": "Suggested order",
        })
        if "Avg daily demand" in data:
            data["Avg daily demand"] = data["Avg daily demand"].round(2)
            data["Reorder point"] = data["Reorder point"].round(1)
    st.dataframe(data, hide_index=True, use_container_width=True)
    filename = f"smartstock_{report_type.lower().replace(' ', '_')}_{date.today().isoformat()}.csv"
    st.download_button(
        "Download CSV",
        data=data.to_csv(index=False).encode("utf-8-sig"),
        file_name=filename,
        mime="text/csv",
        type="primary",
    )


def show_discrete_math() -> None:
    section_heading(
        "Discrete mathematics",
        "Eight foundational concepts demonstrated with the live products, suppliers and stock movements.",
    )
    products = get_products()
    suppliers = get_suppliers()
    transactions = get_transactions()
    category_set = set(products["category"].dropna()) if not products.empty else set()
    low_set = set(
        products.loc[products["quantity"] <= products["safety_stock"], "name"]
    ) if not products.empty else set()
    out_of_stock = set(products.loc[products["quantity"] == 0, "name"]) if not products.empty else set()
    supplier_by_product = dict(zip(products["name"], products["supplier_name"])) if not products.empty else {}
    categories_by_product = dict(zip(products["name"], products["category"])) if not products.empty else {}

    with st.expander("1. Sets and set operations", expanded=True):
        st.write("**Product categories**", sorted(category_set))
        st.write("**Low-stock products**", sorted(low_set))
        st.write("**Out-of-stock products**", sorted(out_of_stock))
        st.write("**Low stock ∪ out of stock**", sorted(low_set | out_of_stock))
        st.write("**Products not low-stock**", sorted(set(products["name"]) - low_set) if not products.empty else [])

    with st.expander("2. Relations"):
        st.write("Supplier-to-product relation (each pair is a current database link):")
        relation = products[["supplier_name", "name", "sku"]].rename(
            columns={"supplier_name": "Supplier", "name": "Product", "sku": "SKU"}
        ) if not products.empty else pd.DataFrame(columns=["Supplier", "Product", "SKU"])
        st.dataframe(relation, hide_index=True, use_container_width=True)
        st.caption(f"Relation size: {len(relation)} supplier-product pairs.")

    with st.expander("3. Logic and Boolean conditions"):
        if products.empty:
            st.info("Add products to evaluate inventory conditions.")
        else:
            logic = products[["id", "name", "quantity", "safety_stock", "lead_time_days"]].copy()
            logic["low_stock (quantity ≤ safety stock)"] = logic["quantity"] <= logic["safety_stock"]
            reorder = build_reorder_report().set_index("id")
            logic["needs_reorder (quantity ≤ safety stock + lead time demand)"] = logic.apply(
                lambda row: row["quantity"] <= (
                    row["safety_stock"] + row["lead_time_days"]
                    * reorder.loc[row["id"], "average_daily_demand"]
                ),
                axis=1,
            )
            logic = logic.drop(columns="id")
            logic = logic.rename(columns={"name": "Product", "quantity": "On hand", "safety_stock": "Safety stock", "lead_time_days": "Lead time"})
            st.dataframe(logic, hide_index=True, use_container_width=True)
            st.caption("Conditions use the same non-negative stock and lead-time values as the operational inventory.")

    with st.expander("4. Functions"):
        st.write("**Product → category** (each product maps to one category):")
        st.json(categories_by_product)
        st.write("**Product → supplier** (supplier assignment may be unassigned):")
        st.json(supplier_by_product)
        if not products.empty:
            value_function = {
                row["sku"]: round(float(row["quantity"] * row["unit_cost"]), 2)
                for _, row in products.iterrows()
            }
            st.write("**SKU → current inventory value at cost**")
            st.json(value_function)

    with st.expander("5. Recurrence relations for stock updates"):
        if products.empty:
            st.info("Add products and record stock movements to see the recurrence.")
        else:
            selected = st.selectbox(
                "Product for stock recurrence",
                [f"{row['name']} · {row['sku']}" for _, row in products.iterrows()],
                key="recurrence_product",
            )
            product = products[
                products.apply(lambda row: f"{row['name']} · {row['sku']}" == selected, axis=1)
            ].iloc[0]
            product_transactions = transactions[transactions["product_id"] == product["id"]].sort_values(
                ["created_at", "id"]
            )
            signed_types = {"Purchase": 1, "Return": 1, "Sale": -1, "Usage": -1, "Damaged": -1}
            movements = [
                (signed_types[row["transaction_type"]] * int(row["quantity"]), row)
                for _, row in product_transactions.iterrows()
            ]
            opening = int(product["quantity"]) - sum(amount for amount, _ in movements)
            balance = opening
            rows = [{"Step": 0, "Transaction": "Opening balance", "Change": 0, "Stock after": balance}]
            for step, (amount, row) in enumerate(movements, 1):
                balance += amount
                rows.append({
                    "Step": step, "Transaction": row["transaction_type"],
                    "Change": amount, "Stock after": balance,
                })
            st.code("Sₙ = Sₙ₋₁ + qₙ for purchases/returns; Sₙ = Sₙ₋₁ − qₙ for sales/usage/damage")
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            st.caption("The opening balance is derived so the recorded transaction sequence reconciles to current stock.")

    with st.expander("6. Counting"):
        product_count = len(products)
        supplier_count = len(suppliers)
        transaction_count = len(transactions)
        st.write({
            "Products (|P|)": product_count,
            "Suppliers (|S|)": supplier_count,
            "Transactions (|T|)": transaction_count,
            "Possible product-supplier pairs (|P| × |S|)": product_count * supplier_count,
            "Recorded supplier-product links": int(products["supplier_id"].notna().sum()) if not products.empty else 0,
        })

    with st.expander("7. Graph theory: supplier-product connections"):
        edges = products[products["supplier_name"].notna()][["supplier_name", "name"]].copy()
        edges.columns = ["Supplier node", "Product node"]
        st.write("The supplier-product network is a bipartite graph: supplier and product nodes are connected by current assignments.")
        st.dataframe(edges, hide_index=True, use_container_width=True)
        if not edges.empty:
            degree = edges.groupby("Supplier node", as_index=False).size().rename(columns={"size": "Product connections"})
            graph = px.bar(degree, x="Supplier node", y="Product connections", color_discrete_sequence=["#315f91"])
            graph.update_layout(
                margin=dict(l=0, r=0, t=10, b=0), height=280, paper_bgcolor="white",
                plot_bgcolor="white", font=dict(family="Inter", color="#43536b"),
                xaxis=dict(showgrid=False), yaxis=dict(gridcolor="#edf0f4"),
            )
            st.plotly_chart(graph, use_container_width=True)
        else:
            st.info("Assign suppliers to products to create graph edges.")

    with st.expander("8. Trees: product-category hierarchy"):
        if not products.empty:
            tree = products.groupby("category")["name"].apply(list).to_dict()
            st.write("Root → category → product")
            for category, names in sorted(tree.items()):
                st.markdown(f"**{category}**")
                for name in sorted(names):
                    st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;↳ {name}", unsafe_allow_html=True)
        else:
            st.info("Add categorized products to build the hierarchy.")


PAGES = {
    "Dashboard": show_dashboard,
    "Products": show_products,
    "Suppliers": show_suppliers,
    "Stock transactions": show_transactions,
    "Demand & restocking": show_forecasting,
    "Reports": show_reports,
    "Discrete mathematics": show_discrete_math,
}

with st.sidebar:
    st.markdown("## SmartStock")
    st.caption("Inventory management")
    page = st.radio("Navigation", list(PAGES), label_visibility="collapsed")
    st.divider()
    st.caption("Stock levels update as transactions are recorded.")

PAGES[page]()
