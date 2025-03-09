import streamlit as st
import pandas as pd
import plotly.express as px
import sqlite3

# Set the database file path
DB_PATH = 'net_worth.db'

st.title('Net Worth Tracking Dashboard')

# Create database connection and table
def create_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''CREATE TABLE IF NOT EXISTS net_worth (date TEXT PRIMARY KEY, value REAL)''')
    return conn

# Load data from SQLite
def load_data():
    conn = create_connection()
    data = pd.read_sql_query('SELECT * FROM net_worth ORDER BY date', conn)
    conn.close()
    return data

# Save a new record to SQLite
def save_record(date, value):
    conn = create_connection()
    conn.execute('INSERT OR REPLACE INTO net_worth (date, value) VALUES (?, ?)', (date, value))
    conn.commit()
    conn.close()

# Delete all records from SQLite
def delete_all_data():
    conn = create_connection()
    conn.execute('DELETE FROM net_worth')
    conn.commit()
    conn.close()

# Delete a single record by date from SQLite
def delete_record(date):
    conn = create_connection()
    conn.execute('DELETE FROM net_worth WHERE date = ?', (date,))
    conn.commit()
    conn.close()

# Load existing data
data = load_data()

# Data Entry Form
st.header('Add New Record')
date = st.date_input('Date')
net_worth = st.number_input('Net Worth', step=100.0)

if st.button('Add Record'):
    if date.strftime('%Y-%m-%d') in data['date'].values:
        st.warning('A record with this date already exists.')
    else:
        save_record(date.strftime('%Y-%m-%d'), net_worth)
        st.success('Record added successfully!')
        data = load_data()

# Delete Data Button
st.header('Delete Records')
if st.button('Delete All Data'):
    delete_all_data()
    data = load_data()
    st.success('All data deleted successfully!')

# Delete Single Record by Date
delete_date = st.date_input('Select Date to Delete')
if st.button('Delete Record'):
    if delete_date.strftime('%Y-%m-%d') in data['date'].values:
        delete_record(delete_date.strftime('%Y-%m-%d'))
        st.success(f'Record for {delete_date} deleted successfully!')
        data = load_data()
    else:
        st.warning('No record found for the selected date.')

# Display Data
st.header('Net Worth Records')
st.dataframe(data)

# Plotting Line Chart
st.header('Net Worth Over Time')
if not data.empty:
    data['date'] = pd.to_datetime(data['date'])
    fig = px.line(data, x='date', y='value', title='Net Worth Over Time', markers=True)
    st.plotly_chart(fig)
else:
    st.info('No data to display. Add some records!')
