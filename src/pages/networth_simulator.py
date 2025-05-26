import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objs as go
from supabase import create_client, Client
import os
from dotenv import load_dotenv
import logging
from datetime import datetime

# Supabase connection handled via SupabaseHandler class
class SupabaseHandler:
    def __init__(self):
        SUPABASE_URL = os.getenv("SUPABASE_URL")
        SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        if not SUPABASE_URL or not SUPABASE_KEY:
            load_dotenv()
            logging.info("Loading environment variables")
            SUPABASE_URL = os.getenv("SUPABASE_URL")
            SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        self.supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    def load_pots(self):
        response = self.supabase.table("networth_pots").select("*").execute()
        return response.data if response.data else []

    def save_pots(self, pots):
        self.supabase.table("networth_pots").upsert(pots).execute()

    def delete_pot(self, pot_id):
        self.supabase.table("networth_pots").delete().match({"id": pot_id}).execute()

    def save_simulation(self, name, timeline, networth):
        data = {
            "name": name,
            "timeline": timeline.tolist(),
            "networth": networth.tolist(),
            "after_30y": networth[-1],
            "date_to_million": self.calculate_million_date(timeline, networth)
        }
        response = self.supabase.table("saved_simulations").upsert(data).execute()
        return response

    def load_simulations(self):
        response = self.supabase.table("saved_simulations").select("*").execute()
        return response.data if response.data else []

    def calculate_million_date(self, timeline, networth):
        for t, nw in zip(timeline, networth):
            if nw >= 1_000_000:
                return (datetime.now() + pd.DateOffset(months=t)).strftime('%Y-%m-%d')
        return "Never"

supabase_handler = SupabaseHandler()

st.title('Net Worth Simulator')

# Function to load pots from Supabase
def load_pots():
    st.session_state.pots = supabase_handler.load_pots()

# Function to save pots to Supabase
def save_pots():
    supabase_handler.save_pots(st.session_state.pots)

# Initialize state and load data
if 'pots' not in st.session_state:
    load_pots()

if 'simulations' not in st.session_state:
    st.session_state.simulations = supabase_handler.load_simulations()

# Function to add a new pot
def add_pot():
    new_pot = {'initial': 0.0, 'monthly': 0.0, 'rate': 0.0}
    st.session_state.pots.append(new_pot)
    save_pots()

st.button('Add Pot', on_click=add_pot)

# Function to remove a pot
def remove_pot(index):
    pot_id = st.session_state.pots[index].get("id")
    if pot_id:
        supabase_handler.delete_pot(pot_id)
    del st.session_state.pots[index]
    save_pots()
    st.rerun()

# Display pot inputs
for i, pot in enumerate(st.session_state.pots):
    st.write(f'### Pot {i + 1}')
    pot['initial'] = st.number_input(f'Initial Amount (Pot {i + 1})', min_value=0.0, value=pot['initial'])
    pot['monthly'] = st.number_input(f'Monthly Contribution (Pot {i + 1})', min_value=0.0, value=pot['monthly'])
    pot['rate'] = st.number_input(f'Annual Return Rate (%) (Pot {i + 1})', min_value=0.0, max_value=100.0, value=pot['rate'])
    if st.button(f'Remove Pot {i + 1}'):
        remove_pot(i)

# Simulation function
def simulate_net_worth(years=30):
    months = years * 12
    timeline = np.arange(months)
    total_networth = np.zeros(months)
    for pot in st.session_state.pots:
        initial = pot['initial']
        monthly = pot['monthly']
        rate = pot['rate'] / 100
        growth = initial * ((1 + rate / 12) ** timeline)
        if rate == 0:
            contributions = monthly * timeline
        else:
            contributions = monthly * (((1 + rate / 12) ** timeline - 1) / (rate / 12))
        networth = growth + contributions
        total_networth += networth
    return timeline, total_networth

# Run simulation and plot
if st.button('Simulate Net Worth'):
    timeline, networth = simulate_net_worth()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=timeline / 12, y=networth, mode='lines', name='Total Net Worth'))
    fig.update_layout(title='Net Worth Growth Over Time', xaxis_title='Years', yaxis_title='Net Worth')
    st.plotly_chart(fig)
    
    name = st.text_input("Enter a name for this simulation:")
    if st.button("Save Simulation") and name:
        response = supabase_handler.save_simulation(name, timeline, networth)
        if response and response.data:
            st.success("Simulation saved successfully!")
        else:
            st.error("Failed to save simulation. Try again.")
        st.session_state.simulations = supabase_handler.load_simulations()
        st.rerun()

# Display saved simulations
st.write("## Saved Simulations")
sim_df = pd.DataFrame(st.session_state.simulations)

if not sim_df.empty:
    st.dataframe(sim_df[['name', 'after_30y', 'date_to_million']])
    selected_sim = st.selectbox("Select a simulation to view:", sim_df['name'])
    if selected_sim:
        sim_data = sim_df[sim_df['name'] == selected_sim].iloc[0]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=np.array(sim_data['timeline']) / 12, y=sim_data['networth'], mode='lines', name=selected_sim))
        fig.update_layout(title=f'{selected_sim} - Net Worth Growth', xaxis_title='Years', yaxis_title='Net Worth')
        st.plotly_chart(fig)
