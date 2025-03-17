import streamlit as st

def calculate_monthly_mortgage(property_value, deposit_percentage, interest_rate, years):
    loan_amount = property_value * (1 - deposit_percentage / 100)
    monthly_interest_rate = interest_rate / 100 / 12
    num_payments = years * 12
    if monthly_interest_rate == 0:
        return loan_amount / num_payments
    return loan_amount * (monthly_interest_rate * (1 + monthly_interest_rate) ** num_payments) / ((1 + monthly_interest_rate) ** num_payments - 1)

st.title("Mortgage Repayment Calculator")

st.link_button("Compare the best mortgage deals", "https://www.moneysavingexpert.com/mortgages/best-buys/")

property_value = st.number_input("Property Value (£)", min_value=0.0, step=1000.0)

option = st.selectbox("Select Deposit Input Type", ("Deposit Value", "Deposit Percentage"))

if option == "Deposit Value":
    deposit_value = st.number_input("Deposit Value (£)", min_value=0.0, step=1000.0, value=property_value * 0.25)
    deposit_percentage = (deposit_value / property_value) * 100 if property_value > 0 else 0
else:
    deposit_percentage = st.number_input("Deposit Percentage (%)", min_value=0.0, max_value=100.0, step=0.1, value=25.0)
    deposit_value = (deposit_percentage / 100) * property_value

st.write(f"Calculated Deposit Percentage: {deposit_percentage:.2f}%")
st.write(f"Calculated Deposit Value: £{deposit_value:.2f}")

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
