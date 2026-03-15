import sqlite3
import pandas as pd
import streamlit as st
import plotly.express as px
from datetime import datetime

DB_FILE = "finance.db"


# ---------------- DB UTILS ---------------- #

def ensure_schema():

    conn = sqlite3.connect(DB_FILE)

    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN excluded INTEGER DEFAULT 0")
    except:
        pass

    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN notes TEXT")
    except:
        pass

    try:
        conn.execute("ALTER TABLE transactions ADD COLUMN category TEXT")
    except:
        pass

    conn.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE
    )
    """)

    conn.commit()
    conn.close()


# ---------------- LOAD DATA ---------------- #
def load_categories():

    conn = sqlite3.connect(DB_FILE)

    df = pd.read_sql_query(
        "SELECT name FROM categories",
        conn
    )

    conn.close()

    return df["name"].tolist()

def load_data():

    conn = sqlite3.connect(DB_FILE)

    bank = pd.read_sql_query(
        "SELECT * FROM transactions",
        conn
    )

    splitwise = pd.read_sql_query(
        "SELECT * FROM splitwise_transactions",
        conn
    )

    settlements = pd.read_sql_query(
        "SELECT * FROM splitwise_settlements",
        conn
    )

    conn.close()

    if "excluded" not in bank.columns:
        bank["excluded"] = 0

    if "notes" not in bank.columns:
        bank["notes"] = ""

    return bank, splitwise, settlements

def get_salary_transactions():

    conn = sqlite3.connect(DB_FILE)

    df = pd.read_sql_query(
        """
        SELECT id, txn_date, amount
        FROM transactions
        WHERE merchant='Salary'
        ORDER BY txn_date DESC
        """,
        conn
    )

    conn.close()

    return df

# ---------------- SAVE EDITS ---------------- #

def save_edits(df):

    conn = sqlite3.connect(DB_FILE)

    for _, row in df.iterrows():

        conn.execute(
            """
            UPDATE transactions
            SET excluded = ?, notes = ?, category = ?
            WHERE email_id = ?
            """,
            (
                int(row["excluded"]),
                row["notes"],
                row["category"],
                row["email_id"]
            )
        )

    conn.commit()
    conn.close()


# ---------------- METRICS ---------------- #

def compute_metrics(bank, splitwise):

    bank_filtered = bank[bank["excluded"] == 0]

    bank_debits = bank_filtered[
        bank_filtered["txn_type"] == "debit"
    ]["amount"].sum()

    bank_credits = bank_filtered[
        bank_filtered["txn_type"] == "credit"
    ]["amount"].sum()

    owed_to_you = splitwise[
        splitwise["direction"] == "owed"
    ]["your_share"].sum()

    you_owe = splitwise[
        splitwise["direction"] == "owe"
    ]["your_share"].sum()

    # Actual money spent from pocket
    actual_spend = (
        bank_debits
        - owed_to_you
        + you_owe
    )

    return bank_debits, bank_credits, owed_to_you, you_owe, actual_spend


# ---------------- DASHBOARD ---------------- #

ensure_schema()

st.set_page_config(layout="wide", page_title="Finance Dashboard", page_icon="💰")

st.title("💰 Personal Finance Dashboard")

bank, splitwise, settlements = load_data()

bank_debits, bank_credits, owed_to_you, you_owe, actual_spend = compute_metrics(bank, splitwise)

# ---------------- SALARY MANAGER ---------------- #

with st.expander("Edit Salary"):

# ---------------- ADD SALARY ---------------- #

    salary_amount = st.number_input(
        "Salary Amount",
        min_value=0.0,
        step=1000.0
    )

    salary_date = st.date_input(
        "Salary Date"
    )

    if st.button("Add / Update Salary"):
        unix_id = int(datetime.combine(
            salary_date,
            datetime.min.time()
        ).timestamp())

        conn = sqlite3.connect(DB_FILE)

        conn.execute(
            """
            INSERT OR REPLACE INTO transactions
            (email_id, txn_date, amount, txn_type, merchant, category, notes, excluded)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                f"salary_{unix_id}",
                salary_date.isoformat(),
                salary_amount,
                "credit",
                "Salary",
                "Income",
                "Manual salary entry",
                0
            )
        )

        conn.commit()
        conn.close()

        st.success("Salary saved")

        st.rerun()

# ---------------- TOP METRICS ---------------- #

col1, col2, col3, col4, col5 = st.columns(5)

col1.metric("💸 Bank Spend", f"₹{bank_debits:,.2f}")
col2.metric("💰 Income", f"₹{bank_credits:,.2f}")
col3.metric("🤝 Friends Owe You", f"₹{owed_to_you:,.2f}")
col4.metric("💳 You Owe Friends", f"₹{you_owe:,.2f}")
col5.metric("📉 Actual Spend", f"₹{actual_spend:,.2f}")

st.divider()

# ---------------- CASHFLOW ---------------- #
st.subheader("Cashflow Over Time")

bank_filtered_cf = bank[bank["excluded"] == 0].copy()
bank_filtered_cf["txn_date"] = pd.to_datetime(bank_filtered_cf["txn_date"], errors="coerce")

timeline = (
    bank_filtered_cf.groupby(["txn_date","txn_type"])["amount"]
    .sum()
    .unstack(fill_value=0)
)

if not timeline.empty:
    fig = px.area(timeline, title="Income vs Spending")
    st.plotly_chart(fig, use_container_width=True)

st.divider()



# ---------------- SPENDING BY MERCHANT ---------------- #

st.subheader("Spending by Merchant")

bank_filtered = bank[bank["excluded"] == 0]

merchant_spend = (
    bank_filtered[bank_filtered["txn_type"] == "debit"]
    .groupby("merchant")["amount"]
    .sum()
    .sort_values(ascending=False)
)

fig = px.bar(
    merchant_spend,
    title="Top Spending Merchants"
)

st.plotly_chart(fig, use_container_width=True)


# ---------------- SPENDING OVER TIME ---------------- #

st.subheader("Spending Over Time")

bank_filtered["txn_date"] = pd.to_datetime(bank_filtered["txn_date"], errors="coerce")

daily_spend = (
    bank_filtered[bank_filtered["txn_type"] == "debit"]
    .groupby("txn_date")["amount"]
    .sum()
)

fig = px.line(
    daily_spend,
    title="Daily Spending"
)

st.plotly_chart(fig, use_container_width=True)

st.subheader("Spending by Category")

bank_filtered = bank[(bank["excluded"] == 0) & (bank["txn_type"] == "debit")]

cat_spend = (
    bank_filtered.groupby("category")["amount"]
    .sum()
    .sort_values(ascending=False)
)

fig = px.pie(
    cat_spend,
    values=cat_spend.values,
    names=cat_spend.index,
    title="Category Spend"
)

st.plotly_chart(fig, use_container_width=True)


# ---------------- SPLITWISE BALANCE ---------------- #

st.subheader("Splitwise Balances")

balance = (
    splitwise
    .groupby(["person_name", "direction"])["your_share"]
    .sum()
    .unstack(fill_value=0)
)

balance["net"] = balance.get("owed", 0) - balance.get("owe", 0)

st.dataframe(balance)


# ---------------- SPLITWISE PIE ---------------- #

st.subheader("Splitwise Distribution")

owed_chart = splitwise[splitwise["direction"] == "owed"]

if not owed_chart.empty:

    fig = px.pie(
        owed_chart,
        values="your_share",
        names="person_name",
        title="Who Owes You Money"
    )

    st.plotly_chart(fig, use_container_width=True)


# ---------------- EDITABLE TRANSACTIONS ---------------- #

st.subheader("Manage Categories")

categories = load_categories()

new_cat = st.text_input("Add New Category")

if st.button("Create Category"):

    if new_cat:

        conn = sqlite3.connect(DB_FILE)

        conn.execute(
            "INSERT OR IGNORE INTO categories(name) VALUES (?)",
            (new_cat,)
        )

        conn.commit()
        conn.close()

        st.success(f"Category '{new_cat}' added")
        st.rerun()

st.subheader("Edit Transactions")

edited_df = st.data_editor(
    bank,
    use_container_width=True,
    column_config={
        "excluded": st.column_config.CheckboxColumn(
            "Exclude",
            help="Exclude from calculations"
        ),

        "notes": st.column_config.TextColumn(
            "Notes"
        ),

        "category": st.column_config.SelectboxColumn(
            "Category",
            options=categories
        )
    }
)

if st.button("Save Changes"):
    save_edits(edited_df)
    st.success("Changes saved successfully!")


# ---------------- RAW DATA ---------------- #


# ---------------- SIDEBAR FILTERS ---------------- #
st.sidebar.header("Filters")

bank["txn_date"] = pd.to_datetime(bank["txn_date"], errors="coerce")

min_date = bank["txn_date"].min()
max_date = bank["txn_date"].max()

date_range = st.sidebar.date_input(
    "Date Range",
    value=(min_date, max_date)
)

categories = load_categories()
selected_category = st.sidebar.multiselect("Category", categories)

selected_merchant = st.sidebar.multiselect(
    "Merchant",
    bank["merchant"].dropna().unique()
)

search_term = st.sidebar.text_input("Search transaction")

filtered_bank = bank.copy()

if len(date_range) == 2:
    filtered_bank = filtered_bank[
        (filtered_bank["txn_date"] >= pd.to_datetime(date_range[0])) &
        (filtered_bank["txn_date"] <= pd.to_datetime(date_range[1]))
    ]

if selected_category:
    filtered_bank = filtered_bank[filtered_bank["category"].isin(selected_category)]

if selected_merchant:
    filtered_bank = filtered_bank[filtered_bank["merchant"].isin(selected_merchant)]

if search_term:
    filtered_bank = filtered_bank[
        filtered_bank["merchant"].str.contains(search_term, case=False, na=False)
    ]

# ---------------- MONTHLY SPENDING ---------------- #
st.subheader("Monthly Spending")

monthly = (
    filtered_bank[filtered_bank["txn_type"] == "debit"]
    .groupby(filtered_bank["txn_date"].dt.to_period("M"))["amount"]
    .sum()
)

monthly.index = monthly.index.astype(str)

fig = px.bar(monthly, title="Monthly Spend")
st.plotly_chart(fig, use_container_width=True)

# ---------------- BUDGET TRACKING ---------------- #
st.subheader("Category Budgets")

conn = sqlite3.connect(DB_FILE)

conn.execute("""
CREATE TABLE IF NOT EXISTS budgets (
    category TEXT PRIMARY KEY,
    amount REAL
)
""")

budget_df = pd.read_sql_query("SELECT * FROM budgets", conn)

budget_editor = st.data_editor(
    budget_df,
    num_rows="dynamic",
    use_container_width=True
)

if st.button("Save Budgets"):
    conn.execute("DELETE FROM budgets")
    for _, r in budget_editor.iterrows():
        conn.execute(
            "INSERT INTO budgets(category,amount) VALUES (?,?)",
            (r["category"], r["amount"])
        )
    conn.commit()
    st.success("Budgets updated")

# Show progress vs budget
if not budget_editor.empty:

    spend_by_cat = (
        filtered_bank[filtered_bank["txn_type"] == "debit"]
        .groupby("category")["amount"]
        .sum()
    )

    for _, r in budget_editor.iterrows():
        cat = r["category"]
        budget = r["amount"]
        spent = spend_by_cat.get(cat, 0)

        st.write(cat)
        st.progress(min(spent / budget, 1.0))
        st.write(f"₹{spent:.0f} / ₹{budget:.0f}")


st.subheader("Recent Transactions")

st.dataframe(
    bank.sort_values("id", ascending=False).head(20),
    use_container_width=True
)