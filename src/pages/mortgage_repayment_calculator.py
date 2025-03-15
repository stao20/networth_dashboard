import streamlit as st

def calculate_monthly_mortgage(property_value, deposit_percentage, interest_rate, years):
    loan_amount = property_value * (1 - deposit_percentage / 100)
    monthly_interest_rate = interest_rate / 100 / 12
    num_payments = years * 12
    if monthly_interest_rate == 0:
        return loan_amount / num_payments
    return loan_amount * (monthly_interest_rate * (1 + monthly_interest_rate) ** num_payments) / ((1 + monthly_interest_rate) ** num_payments - 1)

st.title("Mortgage Repayment Calculator")

st.markdown("[Compare the best mortgage deals](https://www.moneysavingexpert.com/mortgages/best-buys/) on MoneySavingExpert.com")

property_value = st.number_input("Property Value (£)", min_value=0.0, step=1000.0)
deposit_percentage = st.number_input("Deposit Percentage (%)", min_value=0.0, max_value=100.0, step=0.1)
interest_rate = st.number_input("Interest Rate (%)", min_value=0.0, step=0.1)
service_charge = st.number_input("Service Charge p.a. (£)", min_value=0.0, step=10.0)
ground_rent = st.number_input("Ground Rent p.a. (£)", min_value=0.0, step=10.0)
council_tax = st.number_input("Council Tax p.a. (£)", min_value=0.0, step=10.0)
years = st.slider("Mortgage Term (Years)", min_value=1, max_value=40, value=25)

if st.button("Calculate"):
    monthly_mortgage_payment = calculate_monthly_mortgage(property_value, deposit_percentage, interest_rate, years)
    monthly_additional = (service_charge + ground_rent + council_tax) / 12
    total_monthly_payment = monthly_mortgage_payment + monthly_additional

    st.write(f"Monthly Mortgage Payment: £{monthly_mortgage_payment:.2f}")
    st.write(f"Monthly Total Payment: £{total_monthly_payment:.2f}")
