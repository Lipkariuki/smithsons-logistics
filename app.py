import streamlit as st
import pandas as pd
import requests
from datetime import datetime

BASE_URL = "http://127.0.0.1:8000"

st.title("🚛 Create New Order")

with st.form("order_form"):
    # ✅ Product section (top)
    product_type = st.text_input("Product Type")  # e.g., KEG
    # e.g., 50L Barrels, Premium Spirits
    product_description = st.text_area("Product Description")

    invoice_number = st.text_input("Invoice Number")
    purchase_order_number = st.text_input("Purchase Order Number")
    dispatch_note_number = st.text_input("Dispatch Note Number")
    truck_plate = st.text_input("Truck Plate")
    destination = st.text_input("Destination")
    date = st.date_input("Delivery Date", value=datetime.today())
    time = st.time_input("Time", value=datetime.now().time())
    cases = st.number_input("Number of Cases", min_value=1)
    price_per_case = st.number_input("Price per Case", min_value=0.0)
    millage_fee = st.number_input("Millage Fee", min_value=0.0, value=0.0)
    dispatch_note = st.text_area("Dispatch Note")

    total_amount = cases * price_per_case

    submit = st.form_submit_button("Create Order")

if submit:
    full_datetime = datetime.combine(date, time)

    payload = {
        "invoice_number": invoice_number,
        "purchase_order_number": purchase_order_number,
        "dispatch_note_number": dispatch_note_number,
        "date": full_datetime.isoformat(),
        "product_type": product_type,
        "product_description": product_description,
        "truck_plate": truck_plate,
        "destination": destination,
        "cases": cases,
        "price_per_case": price_per_case,
        "total_amount": total_amount,
        "millage_fee": millage_fee,
        "dispatch_note": dispatch_note
    }

    try:
        res = requests.post(f"{BASE_URL}/orders/", json=payload)
        if res.status_code == 200:
            st.success("✅ Order created successfully!")
        else:
            st.error(f"❌ Error: {res.status_code} - {res.text}")
    except Exception as e:
        st.error(f"⚠️ Exception: {str(e)}")


# =============================
# Display orders below
# =============================

# =============================
# Display orders below
# =============================

st.title("📦 Existing Orders Dashboard")

try:
    res_orders = requests.get(f"{BASE_URL}/orders/")
    orders = res_orders.json()
except Exception as e:
    st.error(f"❌ Failed to fetch orders: {e}")
    orders = []

if orders:
    df = pd.DataFrame(orders)

    # ✅ Format for display
    formatted_df = df.copy()
    formatted_df["price_per_case"] = formatted_df["price_per_case"].apply(
        lambda x: f"KES {x:,.2f}")
    formatted_df["total_amount"] = formatted_df["total_amount"].apply(
        lambda x: f"KES {x:,.2f}")
    formatted_df["cases"] = formatted_df["cases"].astype(int)
    formatted_df["date"] = pd.to_datetime(
        formatted_df["date"], format='mixed').dt.strftime("%Y-%m-%d %H:%M")

    # ✅ Only show columns that exist
    expected_columns = [
        "product_type", "product_description",
        "invoice_number", "purchase_order_number", "dispatch_note_number",
        "date", "truck_plate", "destination",
        "cases", "price_per_case", "total_amount"
    ]
    existing_columns = [
        col for col in expected_columns if col in formatted_df.columns]

    st.subheader("🧾 Orders Summary")
    st.dataframe(formatted_df[existing_columns], use_container_width=True)

    st.subheader("🔍 Order Details")
    for order in orders:
        with st.expander(f"🔎 Order: {order['invoice_number']} | {order['destination']}"):
            st.markdown(f"""
            - **Product:** {order.get('product_type', 'N/A')}
            - **Description:** {order.get('product_description', 'N/A')}
            - **Truck Plate:** {order.get('truck_plate', 'N/A')}
            - **Cases:** {order.get('cases', 'N/A')}
            - **Price per Case:** KES {order.get('price_per_case', 0):,.2f}
            - **Total Amount:** KES {order.get('total_amount', 0):,.2f}
            - **Millage Fee:** KES {order.get('millage_fee', 0) or 0}
            - **Dispatch Note:** {order.get('dispatch_note', 'N/A')}
            - **PO Number:** {order.get('purchase_order_number', 'N/A')}
            - **Dispatch Note Number:** {order.get('dispatch_note_number', 'N/A')}
            - **Date:** {order.get('date', 'N/A')}
            """)
else:
    st.info("No orders found.")


st.title("🚚 Trip Profitability Dashboard")

try:
    res = requests.get(f"{BASE_URL}/trips/")
    trips = res.json()
except Exception as e:
    st.error(f"❌ Failed to fetch trips: {e}")
    trips = []

profit_data = []

for trip in trips:
    try:
        profit_res = requests.get(f"{BASE_URL}/trips/{trip['id']}/profit")
        profit = profit_res.json()
        profit_data.append({
            "Trip ID": trip["id"],
            "Destination": trip.get("order", {}).get("destination", "N/A"),
            "Revenue (KES)": profit["revenue"],
            "Expenses (KES)": profit["total_expenses"],
            "Commission (KES)": profit["commission_paid"],
            "Net Profit (KES)": profit["net_profit"]
        })
    except:
        continue


if profit_data:
    df_profit = pd.DataFrame(profit_data)
    df_profit["Revenue (KES)"] = df_profit["Revenue (KES)"].apply(
        lambda x: f"KES {x:,.0f}")
    df_profit["Expenses (KES)"] = df_profit["Expenses (KES)"].apply(
        lambda x: f"KES {x:,.0f}")
    df_profit["Commission (KES)"] = df_profit["Commission (KES)"].apply(
        lambda x: f"KES {x:,.0f}")
    df_profit["Net Profit (KES)"] = df_profit["Net Profit (KES)"].apply(
        lambda x: f"KES {x:,.0f}")

    st.subheader("📈 Trip Profit Summary")
    st.dataframe(df_profit, use_container_width=True)
else:
    st.info("No trip profitability data available.")
