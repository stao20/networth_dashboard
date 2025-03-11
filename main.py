import streamlit as st
import pandas as pd
import plotly.express as px
import sqlite3
from enum import Enum

# Set the database file path
DB_PATH = 'net_worth.db'

st.title('Net Worth Tracking Dashboard')

# Account types enumeration
class Account(Enum):
    A = 'A'
    B = 'B'
    C = 'C'
    D = 'D'

# Create database connection and tables
def create_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS account_values (date TEXT, account TEXT, value REAL, PRIMARY KEY (date, account))''')
    return conn

# Load account values data
def load_account_data():
    conn = create_connection()
    data = pd.read_sql_query('SELECT * FROM account_values ORDER BY date, account', conn)
    conn.close()
    return data

# Save an account value to SQLite
def save_account_value(date, account, value):
    conn = create_connection()
    conn.execute('INSERT OR REPLACE INTO account_values (date, account, value) VALUES (?, ?, ?)', (date, account, value))
    conn.commit()
    conn.close()

# Update an existing account value
def update_account_value(date, account, value):
    conn = create_connection()
    conn.execute('UPDATE account_values SET value = ? WHERE date = ? AND account = ?', (value, date, account))
    conn.commit()
    conn.close()

# Delete all entries for a specific date
def delete_entries_by_date(date):
    conn = create_connection()
    conn.execute('DELETE FROM account_values WHERE date = ?', (date,))
    conn.commit()
    conn.close()

# Load existing account data
account_data = load_account_data()

# Account Value Entry Form
st.header('Account Values')
date = st.date_input('Date')
account = st.selectbox('Select Account', [e.value for e in Account])
account_value = st.number_input('Account Value', step=100.0)

if st.button('Add/Update Account Value'):
    save_account_value(date.strftime('%Y-%m-%d'), account, account_value)
    st.success(f'Account {account} value for {date} saved successfully!')
    account_data = load_account_data()

# Remove Entries by Date
st.header('Remove Entries')
delete_date = st.date_input('Date to Remove')
if st.button('Remove All Entries for Date'):
    delete_entries_by_date(delete_date.strftime('%Y-%m-%d'))
    st.success(f'All entries for {delete_date} have been removed.')
    account_data = load_account_data()

# Display Account Data
st.header('Account Value Records')
if not account_data.empty:
    net_worth_df = account_data.groupby('date')['value'].sum().reset_index()
    net_worth_df.columns = ['date', 'net_worth']
    st.dataframe(account_data)
    st.header('Net Worth Summary')
    st.dataframe(net_worth_df)
else:
    st.info('No account data to display. Add some records!')

# Plotting Line Chart
st.header('Net Worth Over Time')
if not account_data.empty:
    net_worth_df['date'] = pd.to_datetime(net_worth_df['date'])
    fig = px.line(net_worth_df, x='date', y='net_worth', title='Net Worth Over Time', markers=True)
    st.plotly_chart(fig)
else:
    st.info('No data to display. Add some records!')
