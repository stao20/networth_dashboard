import streamlit as st
import plotly.graph_objects as go
import pandas as pd

st.set_page_config(page_title="Company Property Investing Tool", layout="wide")
st.title("🏢 Company Property Investment Profitability Evaluator")
st.markdown("""
Easily estimate the fair price for a buy-to-let property based on your expected rent and all key costs. Adjust assumptions, see instant results, and stress test your model.
""")

# --- SIDEBAR: Summary & Reset ---
with st.sidebar:
    st.header("Quick Summary")
    st.markdown("- Enter your expected rent and costs.")
    st.markdown("- Results update instantly.")
    if st.button("Reset to Defaults"):
        st.experimental_rerun()
    st.markdown("---")
    st.caption("Tip: Use the advanced section to stress test or fine-tune assumptions.")

# --- MAIN INPUTS ---
st.header("1. Main Inputs")
main1, main2 = st.columns([2, 1])
with main1:
    st.subheader("Rental Income & Target")
    monthly_rent = st.number_input(
        "Monthly Rent (£)", 
        min_value=0.0, 
        step=50.0, 
        value=1500.0, 
        help="Expected monthly rent for the property."
    )

    target_metric = st.radio(
        "Choose target metric for fair price calculation:",
        ("Net Rental Yield", "Cash-on-Cash Return"),
        index=0,
        help="Select whether to base the fair price calculation on your target net rental yield or target cash-on-cash return."
    )

    if target_metric == "Net Rental Yield":
        target_yield = st.number_input(
            "Target Net Rental Yield (%)", 
            min_value=0.0, 
            max_value=10.0, 
            value=3.0, 
            step=0.1, 
            help="Minimum net yield you want after all costs."
        )
        target_cash_to_cash_return = None
    else:
        target_cash_to_cash_return = st.number_input(
            "Target Cash-on-Cash Return (%)",
            min_value=0.0,
            max_value=20.0,
            value=5.0,
            step=0.1,
            help="Minimum cash-on-cash return you want after all costs and tax."
        )
        target_yield = None
    
    # Maximum net cash flow constraint
    st.markdown("---")
    st.subheader("💰 Maximum Net Cash Flow Constraint")
    enable_cash_flow_constraint = st.checkbox(
        "Enable maximum monthly net cash flow limit",
        value=False,
        help="When enabled, the tool will ensure the calculated fair price generates a monthly cash flow at or below your specified limit."
    )
    
    if enable_cash_flow_constraint:
        max_monthly_cash_flow = st.number_input(
            "Maximum Monthly Net Cash Flow (£)",
            min_value=0.0,
            value=100.0,
            step=50.0,
            help="The maximum amount of cash you want to keep each month. The tool will find a price that generates this amount or slightly lower."
        )
        max_annual_cash_flow = max_monthly_cash_flow * 12
    else:
        max_monthly_cash_flow = None
        max_annual_cash_flow = None
with main2:
    st.subheader("Key Cost Assumptions")
    management_fee_percent = st.number_input("Management Fee (% of rent)", min_value=0.0, max_value=20.0, value=2.0, step=0.5)
    maintenance_method = st.selectbox("Maintenance Provision", ["10% of rental income", "1% of property value"])
    void_days = st.number_input("Void Period (days/year)", min_value=0, max_value=365, value=21, step=1)
    mortgage_interest_rate = st.number_input("Mortgage Interest Rate (%)", min_value=0.0, max_value=15.0, value=4.5, step=0.05)
    mortgage_term_years = st.number_input("Mortgage Term (years)", min_value=1, max_value=40, value=25, step=1)
    property_appreciation_rate = st.number_input("Property Value Appreciation (%/year)", min_value=0.0, max_value=20.0, value=0.0, step=0.1, help="Annual percentage increase in property value")

# --- ACQUISITION & PROPERTY COSTS ---
st.header("2. Acquisition & Property Costs")
acq1, acq2 = st.columns(2)
with acq1:
    legal_fees = st.number_input("Legal Fees (£)", min_value=0.0, value=2000.0, step=100.0)
    mortgage_product_fee = st.number_input("Mortgage Product Fee (£)", min_value=0.0, value=0.0, step=100.0)
    survey_costs = st.number_input("Survey Costs (£)", min_value=0.0, value=300.0, step=50.0)
    broker_fee_percent = st.number_input("Broker Fee (% of loan)", min_value=0.0, max_value=5.0, value=1.0, step=0.05, help="Broker fee as a percentage of the mortgage loan amount. This affects both upfront costs and fair price calculations.")
with acq2:
    service_charge = st.number_input("Service Charge (£/yr)", min_value=0.0, step=50.0)
    ground_rent = st.number_input("Ground Rent (£/yr)", min_value=0.0, step=10.0)
    council_tax = st.number_input("Council Tax (£/yr)", min_value=0.0, step=50.0)
    insurance = st.number_input("Insurance (£/yr)", min_value=0.0, value=200.0, step=10.0)

# --- ADVANCED/EXPANDER ---
with st.expander("Show Advanced, Tax & Stress Test Options"):
    st.subheader("Tax & Certificates")
    allowable_expenses = st.checkbox("Deduct All Allowable Expenses", value=True)
    gas_safety = st.number_input("Gas Safety Certificate (£/yr)", min_value=0.0, value=80.0, step=10.0)
    electrical_inspection = st.number_input("Electrical Inspection (£/5yr)", min_value=0.0, value=225.0, step=25.0)
    epc_certificate = st.number_input("EPC Certificate (£/10yr)", min_value=0.0, value=100.0, step=10.0)

# --- CALCULATION HELPERS ---
def calc_stamp_duty(price):
    duty = 0.0
    if price > 250000:
        duty += (min(price, 925000) - 250000) * 0.10
    if price > 125000:
        duty += (min(price, 250000) - 125000) * 0.07
    if price > 0:
        duty += min(price, 125000) * 0.05
    return duty

def mortgage_annual_payment(principal, annual_rate, years):
    """Calculate the total annual mortgage payment using the annuity formula."""
    if annual_rate == 0 or years == 0:
        return principal / years if years else 0
    r = annual_rate / 100 / 12
    n = years * 12
    payment = principal * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
    return payment * 12  # annual payment

def calculate_annual_interest_principal(loan_amount, annual_rate, years, year_number):
    """
    Calculate actual interest and principal for a specific year using proper amortization.
    
    Args:
        loan_amount: Original loan amount
        annual_rate: Annual interest rate as percentage
        years: Total mortgage term in years
        year_number: Which year to calculate (1-based, where 1 = first year)
    
    Returns:
        (annual_interest, annual_principal): Tuple of interest and principal paid in that year
    """
    if annual_rate == 0 or years == 0 or year_number < 1 or year_number > years:
        # For zero interest or invalid year, simple linear split
        annual_payment = mortgage_annual_payment(loan_amount, annual_rate, years)
        if years == 0:
            return 0, 0
        return annual_payment / years, annual_payment / years
    
    # Calculate monthly payment
    r = annual_rate / 100 / 12
    n = years * 12
    monthly_payment = loan_amount * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
    
    # Calculate starting balance for this year
    # Months elapsed before this year starts
    months_elapsed = (year_number - 1) * 12
    if months_elapsed == 0:
        current_balance = loan_amount
    else:
        # Calculate remaining balance using present value formula
        months_remaining_before_year = n - months_elapsed
        current_balance = monthly_payment * ((1 - (1 + r) ** (-months_remaining_before_year)) / r)
    
    # Calculate interest and principal for each month in this year
    annual_interest = 0.0
    annual_principal = 0.0
    balance = current_balance
    
    for month in range(12):
        monthly_interest = balance * r
        monthly_principal = monthly_payment - monthly_interest
        annual_interest += monthly_interest
        annual_principal += monthly_principal
        balance = balance - monthly_principal
    
    return annual_interest, annual_principal

def calculate_first_year_interest_principal(loan_amount, annual_rate, years):
    """
    Calculate interest and principal for the first year of the mortgage.
    Wrapper function for convenience in fair price calculations.
    
    Returns:
        (annual_interest, annual_principal): Tuple of interest and principal paid in year 1
    """
    return calculate_annual_interest_principal(loan_amount, annual_rate, years, 1)

def calculate_corporation_tax(profit):
    """
    UK Corporation Tax (2023+):
    - 19% for profits up to £50,000
    - 25% for profits over £250,000
    - Marginal relief for profits between £50,000 and £250,000
    """
    if profit <= 0:
        return 0, 0.0
    if profit <= 50000:
        return profit * 0.19, 19.0
    elif profit >= 250000:
        return profit * 0.25, 25.0
    else:
        # Correct marginal relief formula for profits between £50k-£250k
        # The effective rate increases linearly from 19% to 25%
        # Formula: 19% + (profit - £50k) × 6% ÷ £200k
        effective_rate = 19.0 + (profit - 50000) * 6.0 / 200000
        tax = profit * (effective_rate / 100)
        return tax, effective_rate

def compute_net_yield(price):
    deposit_percent_fp = 25.0
    loan_amount_fp = price * (1 - deposit_percent_fp / 100)
    deposit_amount_fp = price * (deposit_percent_fp / 100)
    broker_fee_fp = loan_amount_fp * (broker_fee_percent / 100)
    duty_fp = calc_stamp_duty(price)
    total_acquisition_fp = deposit_amount_fp + duty_fp + legal_fees + mortgage_product_fee + survey_costs + broker_fee_fp
    # Use annuity formula for annual mortgage payment
    annual_mortgage_payment_fp = mortgage_annual_payment(loan_amount_fp, mortgage_interest_rate, mortgage_term_years)
    # Calculate actual first-year interest and principal using proper amortization
    annual_interest_fp, annual_equity_fp = calculate_first_year_interest_principal(loan_amount_fp, mortgage_interest_rate, mortgage_term_years)
    if maintenance_method == "1% of property value":
        maintenance_fp = price * 0.01
    else:
        maintenance_fp = monthly_rent * 12 * 0.10
    management_fees_fp = monthly_rent * 12 * (management_fee_percent / 100)
    annual_gas_fp = gas_safety
    annual_electrical_fp = electrical_inspection / 5
    annual_epc_fp = epc_certificate / 10
    vacancy_cost_fp = (void_days / 365) * (monthly_rent * 12)
    annual_operating_costs_fp = (
        service_charge + ground_rent + council_tax + insurance +
        management_fees_fp + maintenance_fp + annual_gas_fp + annual_electrical_fp + annual_epc_fp + vacancy_cost_fp
    )
    annual_rent_fp = monthly_rent * 12
    net_income_before_tax_fp = annual_rent_fp - (annual_operating_costs_fp + annual_interest_fp)
    # Add equity increase to yield
    return ((net_income_before_tax_fp + annual_equity_fp) / price) * 100 if price else 0

def compute_cash_on_cash_return(price):
    """Compute cash-on-cash return for a given property price."""
    deposit_percent_fp = 25.0
    loan_amount_fp = price * (1 - deposit_percent_fp / 100)
    deposit_amount_fp = price * (deposit_percent_fp / 100)
    broker_fee_fp = loan_amount_fp * (broker_fee_percent / 100)
    duty_fp = calc_stamp_duty(price)
    total_acquisition_fp = deposit_amount_fp + duty_fp + legal_fees + mortgage_product_fee + survey_costs + broker_fee_fp
    
    # Use annuity formula for annual mortgage payment
    annual_mortgage_payment_fp = mortgage_annual_payment(loan_amount_fp, mortgage_interest_rate, mortgage_term_years)
    # Calculate actual first-year interest and principal using proper amortization
    annual_interest_fp, annual_equity_fp = calculate_first_year_interest_principal(loan_amount_fp, mortgage_interest_rate, mortgage_term_years)
    
    if maintenance_method == "1% of property value":
        maintenance_fp = price * 0.01
    else:
        maintenance_fp = monthly_rent * 12 * 0.10
    
    management_fees_fp = monthly_rent * 12 * (management_fee_percent / 100)
    annual_gas_fp = gas_safety
    annual_electrical_fp = electrical_inspection / 5
    annual_epc_fp = epc_certificate / 10
    vacancy_cost_fp = (void_days / 365) * (monthly_rent * 12)
    
    annual_operating_costs_fp = (
        service_charge + ground_rent + council_tax + insurance +
        management_fees_fp + maintenance_fp + annual_gas_fp + annual_electrical_fp + annual_epc_fp + vacancy_cost_fp
    )
    
    annual_rent_fp = monthly_rent * 12
    net_income_before_tax_fp = annual_rent_fp - (annual_operating_costs_fp + annual_interest_fp)
    
    # Calculate corporation tax - always deduct operating costs and interest for tax purposes
    # The allowable_expenses flag only affects yield calculations, not tax calculations
    taxable_profit_fp = net_income_before_tax_fp  # Rent - Operating Costs - Interest
    
    corp_tax_fp, _ = calculate_corporation_tax(max(0, taxable_profit_fp))
    net_income_after_tax_fp = net_income_before_tax_fp - corp_tax_fp
    
    # Add equity increase AFTER tax calculation (equity is not taxable income)
    net_income_after_tax_with_equity_fp = net_income_after_tax_fp + annual_equity_fp
    
    return (net_income_after_tax_with_equity_fp / total_acquisition_fp) * 100 if total_acquisition_fp else 0

def find_max_viable_price(rent, mortgage_rate, mortgage_term):
    """Find the maximum property price where rent > mortgage payment."""
    low, high = 50000, 2000000
    
    for _ in range(50):  # Max 50 iterations
        mid = (low + high) / 2
        loan_amount = mid * 0.75  # 75% LTV
        annual_mortgage_payment = mortgage_annual_payment(loan_amount, mortgage_rate, mortgage_term)
        
        if annual_rent <= annual_mortgage_payment:
            high = mid  # Price too high
        else:
            low = mid   # Price viable, try higher
            
        if high - low < 1000:  # Within £1k tolerance
            break
    
    return low  # Return the highest viable price

def find_max_cash_flow_price(rent, max_annual_cash_flow, mortgage_rate, mortgage_term):
    """Find the lowest property price that satisfies the maximum cash flow requirement."""
    target_monthly_cash_flow = max_annual_cash_flow / 12
    
    # Start with a reasonable price range
    low, high = 50000, 2000000
    
    for _ in range(100):  # More iterations for precision
        mid = (low + high) / 2
        
        # Calculate cash flow for this price
        loan_amount = mid * 0.75  # 75% LTV
        annual_mortgage_payment = mortgage_annual_payment(loan_amount, mortgage_rate, mortgage_term)
        # Calculate actual first-year interest and principal using proper amortization
        annual_interest, annual_equity = calculate_first_year_interest_principal(loan_amount, mortgage_rate, mortgage_term)
        
        # Calculate operating costs (simplified for this function)
        if maintenance_method == "1% of property value":
            maintenance = mid * 0.01
        else:
            maintenance = rent * 12 * 0.10
        
        management_fees = rent * 12 * (management_fee_percent / 100)
        annual_operating_costs = (
            service_charge + ground_rent + council_tax + insurance +
            management_fees + maintenance + gas_safety + electrical_inspection / 5 + 
            epc_certificate / 10 + (void_days / 365) * (rent * 12)
        )
        
        net_income_before_tax = rent * 12 - (annual_operating_costs + annual_interest)
        
        # Corporation tax calculation - always deduct operating costs and interest for tax purposes
        taxable_profit = net_income_before_tax  # Rent - Operating Costs - Interest
        
        corp_tax, _ = calculate_corporation_tax(max(0, taxable_profit))
        net_income_after_tax = net_income_before_tax - corp_tax
        
        # Annual equity (principal) already calculated above using proper amortization
        
        # Calculate monthly cash flow (excluding equity) - same as main calculation
        monthly_cash_flow = (net_income_after_tax - annual_equity) / 12
        
        # We want to find the lowest price where cash flow <= target
        if monthly_cash_flow <= target_monthly_cash_flow:
            # This price is viable, try to go lower to get closer to target
            high = mid
        else:
            # This price gives too high cash flow, need to go higher
            low = mid
            
        if high - low < 500:  # Tighter tolerance
            break
    
    return high  # Return the lowest viable price

def find_fair_price(target_metric, target_value, rent, tol=0.01, max_iter=50, max_cash_flow=None):
    """Find fair price based on either target yield or target cash-on-cash return, ensuring rent > mortgage payment and maximum cash flow."""
    # First, find the maximum viable price that satisfies the constraint
    max_viable_price = find_max_viable_price(rent, mortgage_interest_rate, mortgage_term_years)
    
    # If no viable price exists, return the maximum viable price with a warning
    if max_viable_price < 50000:
        return max_viable_price, 0.0
    
    # If cash flow constraint is enabled, find the minimum price that satisfies it
    if max_cash_flow is not None:
        min_cash_flow_price = find_max_cash_flow_price(rent, max_cash_flow, mortgage_interest_rate, mortgage_term_years)
        # We want the lower of the two prices to satisfy both constraints
        # This ensures we meet both the rent > mortgage constraint AND the cash flow constraint
        max_viable_price = min(max_viable_price, min_cash_flow_price)
        
        if max_viable_price < 50000:
            return max_viable_price, 0.0
    
    # Now search within the viable price range
    low, high = 50000, max_viable_price
    
    for _ in range(max_iter):
        mid = (low + high) / 2
        
        if target_metric == "Net Rental Yield":
            computed_value = compute_net_yield(mid)
        else:  # Cash-on-Cash Return
            computed_value = compute_cash_on_cash_return(mid)
        
        if abs(computed_value - target_value) < tol:
            return mid, computed_value
        
        if computed_value > target_value:
            low = mid
        else:
            high = mid
    
    return mid, computed_value

def calculate_remaining_mortgage_balance(original_loan, annual_rate, years_remaining, total_years):
    """Calculate remaining mortgage balance after a certain number of years."""
    if annual_rate == 0 or total_years == 0:
        return original_loan * (years_remaining / total_years) if total_years else 0
    
    # Calculate monthly payment
    r = annual_rate / 100 / 12
    n = total_years * 12
    monthly_payment = original_loan * (r * (1 + r) ** n) / ((1 + r) ** n - 1)
    
    # Calculate remaining balance after years_remaining
    months_remaining = years_remaining * 12
    if months_remaining <= 0:
        return 0
    
    remaining_balance = monthly_payment * ((1 - (1 + r) ** (-months_remaining)) / r)
    return remaining_balance

def calculate_equity_and_return_analysis(property_price, loan_amount, mortgage_rate, mortgage_term, appreciation_rate, total_acquisition_cost):
    """Calculate equity and return analysis over the mortgage term."""
    years = []
    property_values = []
    remaining_mortgages = []
    equities = []
    returns = []
    cumulative_rental_income = []
    cumulative_costs = []
    net_returns = []
    
    # Calculate annual rental income and costs (simplified for this analysis)
    annual_rent_income = monthly_rent * 12
    
    # Calculate annual operating costs (simplified)
    if maintenance_method == "1% of property value":
        maintenance = property_price * 0.01
    else:
        maintenance = monthly_rent * 12 * 0.10
    
    management_fees = monthly_rent * 12 * (management_fee_percent / 100)
    annual_operating_costs = (
        service_charge + ground_rent + council_tax + insurance +
        management_fees + maintenance + gas_safety + electrical_inspection / 5 + 
        epc_certificate / 10 + (void_days / 365) * (monthly_rent * 12)
    )
    
    # Calculate annual mortgage payment
    annual_mortgage_payment = mortgage_annual_payment(loan_amount, mortgage_rate, mortgage_term)
    
    cumulative_rental = 0
    cumulative_cost = 0
    
    for year in range(mortgage_term + 1):
        # Calculate property value with appreciation
        current_property_value = property_price * ((1 + appreciation_rate / 100) ** year)
        
        # Calculate remaining mortgage balance
        years_remaining = max(0, mortgage_term - year)
        remaining_mortgage = calculate_remaining_mortgage_balance(loan_amount, mortgage_rate, years_remaining, mortgage_term)
        
        # Calculate equity
        equity = current_property_value - remaining_mortgage
        
        # Calculate return based on equity vs initial investment
        return_percentage = ((equity - total_acquisition_cost) / total_acquisition_cost) * 100 if total_acquisition_cost > 0 else 0
        
        # Track cumulative rental income and costs
        if year > 0:  # Start accumulating from year 1
            cumulative_rental += annual_rent_income
            # Calculate actual interest for this year using proper amortization
            # Only subtract interest portion of mortgage payment, not principal (principal increases equity)
            annual_interest, _ = calculate_annual_interest_principal(loan_amount, mortgage_rate, mortgage_term, year)
            cumulative_cost += annual_operating_costs + annual_interest
        
        # Calculate net return (equity + cumulative rental income - cumulative costs - initial investment)
        net_return = equity + cumulative_rental - cumulative_cost - total_acquisition_cost
        net_return_percentage = (net_return / total_acquisition_cost) * 100 if total_acquisition_cost > 0 else 0
        
        years.append(year)
        property_values.append(current_property_value)
        remaining_mortgages.append(remaining_mortgage)
        equities.append(equity)
        returns.append(return_percentage)
        cumulative_rental_income.append(cumulative_rental)
        cumulative_costs.append(cumulative_cost)
        net_returns.append(net_return_percentage)
    
    return {
        'years': years,
        'property_values': property_values,
        'remaining_mortgages': remaining_mortgages,
        'equities': equities,
        'returns': returns,
        'cumulative_rental_income': cumulative_rental_income,
        'cumulative_costs': cumulative_costs,
        'net_returns': net_returns
    }

# Check rent vs mortgage constraint after functions are defined
annual_rent = monthly_rent * 12
# Calculate mortgage payment for constraint check (using a reasonable property price estimate)
estimated_property_price = monthly_rent * 200  # Rough estimate: 200x monthly rent
estimated_loan_amount = estimated_property_price * 0.75  # 75% LTV
estimated_annual_mortgage_payment = mortgage_annual_payment(estimated_loan_amount, mortgage_interest_rate, mortgage_term_years)

if annual_rent <= estimated_annual_mortgage_payment:
    st.warning(f"⚠️ **Constraint Warning**: Annual rent (£{annual_rent:,.2f}) is close to estimated annual mortgage payment (£{estimated_annual_mortgage_payment:,.2f}). The tool will automatically adjust the fair price to ensure rent > mortgage payment.")

# --- FAIR PRICE & METRICS ---
if monthly_rent > 0:
    if target_metric == "Net Rental Yield":
        fair_price, fair_yield = find_fair_price("Net Rental Yield", target_yield, monthly_rent, max_cash_flow=max_annual_cash_flow)
        fair_coc_return = compute_cash_on_cash_return(fair_price)
    else:  # Cash-on-Cash Return
        fair_price, fair_coc_return = find_fair_price("Cash-on-Cash Return", target_cash_to_cash_return, monthly_rent, max_cash_flow=max_annual_cash_flow)
        fair_yield = compute_net_yield(fair_price)
    
    # Check if a viable price was found
    if fair_price < 50000:
        if enable_cash_flow_constraint and max_annual_cash_flow:
            st.error("❌ **No Viable Investment Found**: Even at the minimum property price, your investment cannot meet both the rent > mortgage constraint and the maximum cash flow requirement.")
            st.info("**Recommendations**: Increase monthly rent, reduce mortgage interest rate, extend mortgage term, or increase your maximum cash flow limit.")
        else:
            st.error("❌ **No Viable Investment Found**: Even at the minimum property price, your rent cannot cover the mortgage payment with current assumptions.")
            st.info("**Recommendations**: Increase monthly rent, reduce mortgage interest rate, or extend mortgage term.")
        st.stop()
    
    fair_stamp_duty = calc_stamp_duty(fair_price)
else:
    fair_price, fair_yield, fair_coc_return, fair_stamp_duty = 0.0, 0.0, 0.0, 0.0

property_price = fair_price
stamp_duty = fair_stamp_duty

deposit_percent = 25.0
loan_amount = property_price * (1 - deposit_percent / 100)
deposit_amount = property_price * (deposit_percent / 100)
broker_fee = loan_amount * (broker_fee_percent / 100)
total_acquisition = (
    deposit_amount + stamp_duty + legal_fees + mortgage_product_fee + survey_costs + broker_fee
)

# Use annuity formula for annual mortgage payment
annual_mortgage_payment = mortgage_annual_payment(loan_amount, mortgage_interest_rate, mortgage_term_years)
# Calculate actual first-year interest and principal using proper amortization
annual_interest, annual_equity = calculate_first_year_interest_principal(loan_amount, mortgage_interest_rate, mortgage_term_years)

if maintenance_method == "1% of property value":
    maintenance = property_price * 0.01
else:
    maintenance = monthly_rent * 12 * 0.10
management_fees = monthly_rent * 12 * (management_fee_percent / 100)
annual_gas = gas_safety
annual_electrical = electrical_inspection / 5
annual_epc = epc_certificate / 10
vacancy_cost = (void_days / 365) * (monthly_rent * 12)
annual_operating_costs = (
    service_charge + ground_rent + council_tax + insurance +
    management_fees + maintenance + annual_gas + annual_electrical + annual_epc + vacancy_cost
)
net_income_before_tax = annual_rent - (annual_operating_costs + annual_interest)
# Add equity increase to net income for yield and return
net_income_before_tax_with_equity = net_income_before_tax + annual_equity

# Corporation tax calculation - always deduct operating costs and interest for tax purposes
# The allowable_expenses flag only affects yield calculations, not tax calculations
taxable_profit = net_income_before_tax  # Rent - Operating Costs - Interest
corp_tax, effective_corp_tax_rate = calculate_corporation_tax(max(0, taxable_profit))
net_income_after_tax = net_income_before_tax - corp_tax
net_income_after_tax_with_equity = net_income_after_tax + annual_equity

# Calculate cash flow excluding equity (actual monthly cash flow)
net_income_after_tax_excluding_equity = net_income_after_tax - annual_equity

net_rental_yield = (net_income_before_tax_with_equity / property_price) * 100 if property_price else 0
cash_on_cash_return = (net_income_after_tax_with_equity / total_acquisition) * 100 if total_acquisition else 0
monthly_net_cash_flow = net_income_after_tax_excluding_equity / 12 if property_price else 0
break_even_occupancy = ((annual_operating_costs + annual_interest) / annual_rent) * 100 if annual_rent else 0

# --- RESULTS SECTION ---
st.header("3. Results & Key Metrics")

# Explain the constraint adjustment
if fair_price > 0:
    actual_loan_amount = fair_price * 0.75
    actual_annual_mortgage_payment = mortgage_annual_payment(actual_loan_amount, mortgage_interest_rate, mortgage_term_years)
    
    constraint_messages = []
    if annual_rent <= estimated_annual_mortgage_payment:
        constraint_messages.append("rent covers the mortgage payment")
    
    if enable_cash_flow_constraint and max_annual_cash_flow:
        constraint_messages.append(f"monthly cash flow ≤ £{max_monthly_cash_flow:,.0f}")
    
    if constraint_messages:
        st.info(f"💡 **Smart Price Adjustment**: The tool automatically adjusted the fair price to ensure {' and '.join(constraint_messages)}. The calculated price now guarantees all constraints are met.")

res1, res2, res3 = st.columns([2, 2, 2])
with res1:
    st.markdown("### 🏷️ Fair Price")
    st.metric(
        "Fair Price (max to pay)",
        f"£{fair_price:,.0f}",
        help=f"The maximum property price you should pay to achieve your target {target_metric.lower()} ({target_yield if target_metric == 'Net Rental Yield' else target_cash_to_cash_return:.2f}%), given your rent and all cost assumptions."
    )
    
    # Show broker fee impact if it's non-zero
    if broker_fee_percent > 0:
        broker_fee_amount = loan_amount * (broker_fee_percent / 100)
        st.info(f"💰 **Broker Fee Impact**: £{broker_fee_amount:,.0f} (£{broker_fee_percent:.2f}% of £{loan_amount:,.0f} loan) included in upfront costs")
    
    # Show constraint satisfaction status
    if fair_price > 0:
        actual_loan_amount = fair_price * 0.75
        actual_annual_mortgage_payment = mortgage_annual_payment(actual_loan_amount, mortgage_interest_rate, mortgage_term_years)
        
        # Check rent vs mortgage constraint
        rent_constraint_met = annual_rent > actual_annual_mortgage_payment
        if rent_constraint_met:
            st.success("✅ **Rent > Mortgage Payment**: Constraint satisfied")
        else:
            st.error("❌ **Rent ≤ Mortgage Payment**: Constraint violated")
        
        # Check cash flow constraint if enabled
        if enable_cash_flow_constraint and max_annual_cash_flow:
            actual_monthly_cash_flow = monthly_net_cash_flow  # Use the same calculation as main display
            cash_flow_constraint_met = actual_monthly_cash_flow <= max_monthly_cash_flow
            
            if cash_flow_constraint_met:
                st.success(f"✅ **Monthly Cash Flow ≤ £{max_monthly_cash_flow:,.0f}**: Constraint satisfied")
                st.info(f"📊 **Cash Flow Details**: Target: £{max_monthly_cash_flow:,.0f}/month, Actual: £{actual_monthly_cash_flow:,.2f}/month, Difference: £{max_monthly_cash_flow - actual_monthly_cash_flow:,.2f}/month")
            else:
                st.error(f"❌ **Monthly Cash Flow > £{max_monthly_cash_flow:,.0f}**: Constraint violated")
                st.error(f"📊 **Cash Flow Details**: Target: £{max_monthly_cash_flow:,.0f}/month, Actual: £{actual_monthly_cash_flow:,.0f}/month, Exceeded by: £{actual_monthly_cash_flow - max_monthly_cash_flow:,.2f}/month")
with res2:
    st.markdown("### 🧾 Stamp Duty")
    st.metric(
        "Stamp Duty",
        f"£{fair_stamp_duty:,.2f}",
        help="One-time tax paid on property purchase, calculated using UK tiered rates: 5% up to £125k, 7% to £250k, 10% to £925k."
    )
with res3:
    st.markdown("### 📊 Target vs Achieved")
    if target_metric == "Net Rental Yield":
        st.metric(
            "Net Rental Yield (%)",
            f"{fair_yield:.2f}",
            help="Target achieved! This is the net rental yield at the computed fair price."
        )
        st.metric(
            "Cash-on-Cash Return (%)",
            f"{fair_coc_return:.2f}",
            help="This is the cash-on-cash return at the computed fair price."
        )
    else:  # Cash-on-Cash Return
        st.metric(
            "Cash-on-Cash Return (%)",
            f"{fair_coc_return:.2f}",
            help="Target achieved! This is the cash-on-cash return at the computed fair price."
        )
        st.metric(
            "Net Rental Yield (%)",
            f"{fair_yield:.2f}",
            help="This is the net rental yield at the computed fair price."
        )

met2, met3, met4 = st.columns(3)
met2.metric(
    "Monthly Net Cash Flow (£)",
    f"{monthly_net_cash_flow:,.2f}",
    help="Net Income After Tax minus full mortgage payment (principal + interest), divided by 12. The actual cash you keep each month after all costs, tax, and mortgage payments."
)
met3.metric(
    "Break-even Occupancy (%)",
    f"{break_even_occupancy:.1f}",
    help="(Annual Costs + Mortgage Interest) / Annual Rent × 100. Minimum % of the year the property must be rented to cover all costs."
)
met4.metric(
    "Total Acquisition (£)",
    f"{total_acquisition:,.0f}",
    help="Total cash needed up front: deposit, stamp duty, legal, broker, survey, and mortgage fees."
)

# Add basic cash flow overview
st.subheader("💰 Basic Cash Flow Overview")
basic_col1, basic_col2, basic_col3 = st.columns(3)
with basic_col1:
    st.metric(
        "Annual Rent",
        f"£{annual_rent:,.2f}",
        help="Total annual rental income"
    )
with basic_col2:
    st.metric(
        "Annual Mortgage Payment",
        f"£{annual_mortgage_payment:,.2f}",
        help="Total annual mortgage payment (principal + interest)"
    )
with basic_col3:
    basic_surplus = annual_rent - annual_mortgage_payment
    st.metric(
        "Rent vs Mortgage",
        f"£{basic_surplus/12:,.2f}/month",
        delta=f"£{basic_surplus:,.2f} annually",
        delta_color="normal" if basic_surplus > 0 else "inverse",
        help="Monthly difference between rent and mortgage payment (before other costs)"
    )

# --- COST BREAKDOWN CHART ---
cost_labels = [
    "Stamp Duty", "Legal Fees", "Mortgage Product Fee", "Survey Costs", "Broker Fee", "Deposit"
]
cost_values = [
    stamp_duty, legal_fees, mortgage_product_fee, survey_costs, broker_fee, deposit_amount
]
if property_price > 0:
    fig = go.Figure(data=[go.Pie(labels=cost_labels, values=cost_values, hole=0.4)])
    fig.update_layout(title_text="Acquisition Cost Breakdown", showlegend=True)
    st.plotly_chart(fig, use_container_width=True)

# --- DETAILS ---
with st.expander("Show Calculation Details"):
    # Property & Financing
    st.subheader("🏠 Property & Financing")
    st.write(f"**Property Price:** £{property_price:,.2f}")
    st.write(f"**Loan Amount (75% LTV):** £{loan_amount:,.2f}")
    st.write(f"**Deposit Amount (25%):** £{deposit_amount:,.2f}")
    st.write(f"**Annual Mortgage Payment:** £{annual_mortgage_payment:,.2f}")
    st.write(f"**Annual Mortgage Interest:** £{annual_interest:,.2f}")
    st.write(f"**Annual Equity Payment:** £{annual_equity:,.2f}")
    
    # Income & Revenue
    st.subheader("💰 Income & Revenue")
    st.write(f"**Annual Rent:** £{annual_rent:,.2f}")
    st.write(f"**Monthly Rent:** £{monthly_rent:,.2f}")
    
    # Operating Costs
    st.subheader("📊 Operating Costs")
    st.write(f"**Service Charge:** £{service_charge:,.2f}")
    st.write(f"**Ground Rent:** £{ground_rent:,.2f}")
    st.write(f"**Council Tax:** £{council_tax:,.2f}")
    st.write(f"**Insurance:** £{insurance:,.2f}")
    st.write(f"**Management Fees:** £{management_fees:,.2f}")
    st.write(f"**Maintenance Provision:** £{maintenance:,.2f}")
    st.write(f"**Gas Safety Certificate:** £{gas_safety:,.2f}")
    st.write(f"**Electrical Inspection:** £{electrical_inspection/5:,.2f}/year")
    st.write(f"**EPC Certificate:** £{epc_certificate/10:,.2f}/year")
    st.write(f"**Vacancy Cost:** £{vacancy_cost:,.2f}")
    st.write(f"**Total Annual Operating Costs:** £{annual_operating_costs:,.2f}")
    
    # Financial Performance
    st.subheader("📈 Financial Performance")
    st.write(f"**Net Income Before Tax (excl. equity):** £{net_income_before_tax:,.2f}")
    st.write(f"**Net Income Before Tax (incl. equity):** £{net_income_before_tax_with_equity:,.2f}")
    st.write(f"**Corporation Tax:** £{corp_tax:,.2f} (Effective Rate: {effective_corp_tax_rate:.2f}%)")
    st.write(f"**Net Income After Tax (excl. equity):** £{net_income_after_tax:,.2f}")
    st.write(f"**Net Income After Tax (incl. equity):** £{net_income_after_tax_with_equity:,.2f}")
    
    # Cash Flow Analysis
    st.subheader("💸 Cash Flow Analysis")
    st.write(f"**Monthly Net Cash Flow:** £{monthly_net_cash_flow:,.2f}")
    st.write(f"**Annual Net Cash Flow:** £{monthly_net_cash_flow * 12:,.2f}")
    if enable_cash_flow_constraint and max_annual_cash_flow:
        st.write(f"**Cash Flow Constraint:** Maximum £{max_monthly_cash_flow:,.2f}/month")
        st.write(f"**Constraint Status:** {'✅ Satisfied' if monthly_net_cash_flow <= max_monthly_cash_flow else '❌ Exceeded'}")
    
    # Key Metrics
    st.subheader("🎯 Key Metrics")
    st.write(f"**Break-even Occupancy:** {break_even_occupancy:.1f}%")
    st.write(f"**Net Rental Yield:** {net_rental_yield:.2f}%")
    st.write(f"**Cash-on-Cash Return:** {cash_on_cash_return:.2f}%")
    
    # Broker fee impact explanation
    if broker_fee_percent > 0:
        st.subheader("💰 Broker Fee Impact on Returns")
        broker_fee_amount = loan_amount * (broker_fee_percent / 100)
        st.write(f"**Broker Fee Amount:** £{broker_fee_amount:,.2f} (£{broker_fee_percent:.2f}% of £{loan_amount:,.0f} loan)")
        st.write(f"**Total Upfront Investment:** £{total_acquisition:,.2f} (includes broker fee)")
        st.write(f"**Cash-on-Cash Return Impact:** Higher broker fees reduce cash-on-cash return by increasing the denominator (total upfront investment)")

# --- PROPERTY APPRECIATION & RETURN ANALYSIS ---
if property_price > 0 and property_appreciation_rate >= 0:
    st.header("4. Property Appreciation & Return Analysis")
    
    # Calculate the analysis
    analysis_data = calculate_equity_and_return_analysis(
        property_price, loan_amount, mortgage_interest_rate, mortgage_term_years, 
        property_appreciation_rate, total_acquisition
    )
    
    # Display key metrics
    final_year = mortgage_term_years
    final_equity = analysis_data['equities'][-1]
    final_property_value = analysis_data['property_values'][-1]
    final_return = analysis_data['net_returns'][-1]
    
    st.subheader("📈 Key Return Metrics")
    return_col1, return_col2, return_col3, return_col4 = st.columns(4)
    
    with return_col1:
        st.metric(
            f"Property Value After {final_year} Years",
            f"£{final_property_value:,.0f}",
            delta=f"£{final_property_value - property_price:,.0f}",
            delta_color="normal",
            help=f"Property value after {final_year} years with {property_appreciation_rate}% annual appreciation"
        )
    
    with return_col2:
        st.metric(
            f"Equity After {final_year} Years",
            f"£{final_equity:,.0f}",
            delta=f"£{final_equity - total_acquisition:,.0f}",
            delta_color="normal",
            help="Total equity (property value - remaining mortgage) after mortgage is paid off"
        )
    
    with return_col3:
        st.metric(
            f"Total Return After {final_year} Years",
            f"{final_return:.1f}%",
            help="Total return including equity appreciation and rental income minus all costs"
        )
    
    with return_col4:
        annualized_return = ((final_equity / total_acquisition) ** (1/final_year) - 1) * 100 if total_acquisition > 0 else 0
        st.metric(
            "Annualized Return",
            f"{annualized_return:.1f}%",
            help="Compound annual growth rate of equity over the mortgage term"
        )
    
    # Create the return analysis plot
    st.subheader("📊 Return Analysis Over Time")
    
    # Create figure with secondary y-axis
    fig = go.Figure()
    
    # Add equity line
    fig.add_trace(go.Scatter(
        x=analysis_data['years'],
        y=analysis_data['equities'],
        mode='lines+markers',
        name='Equity',
        line=dict(color='#1f77b4', width=3),
        marker=dict(size=6)
    ))
    
    # Add property value line
    fig.add_trace(go.Scatter(
        x=analysis_data['years'],
        y=analysis_data['property_values'],
        mode='lines+markers',
        name='Property Value',
        line=dict(color='#ff7f0e', width=2),
        marker=dict(size=4)
    ))
    
    # Add remaining mortgage line
    fig.add_trace(go.Scatter(
        x=analysis_data['years'],
        y=analysis_data['remaining_mortgages'],
        mode='lines+markers',
        name='Remaining Mortgage',
        line=dict(color='#d62728', width=2),
        marker=dict(size=4)
    ))
    
    # Add return percentage line (secondary y-axis)
    fig.add_trace(go.Scatter(
        x=analysis_data['years'],
        y=analysis_data['net_returns'],
        mode='lines+markers',
        name='Total Return %',
        line=dict(color='#2ca02c', width=3),
        marker=dict(size=6),
        yaxis='y2'
    ))
    
    # Update layout
    fig.update_layout(
        title=f'Property Investment Analysis Over {mortgage_term_years} Years<br><sub>Property Appreciation: {property_appreciation_rate}% per year</sub>',
        xaxis_title='Year',
        yaxis_title='Value (£)',
        yaxis2=dict(
            title='Return (%)',
            overlaying='y',
            side='right'
        ),
        hovermode='x unified',
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01
        ),
        height=600
    )
    
    # Format y-axis as currency
    fig.update_yaxes(tickformat='£,.0f')
    fig.update_layout(yaxis2=dict(tickformat='.1f%'))
    
    st.plotly_chart(fig, use_container_width=True)
    
    # Additional Return Analysis Plots
    st.subheader("📈 Return Rate & Amount Analysis")
    
    # Create two columns for the new plots
    plot_col1, plot_col2 = st.columns(2)
    
    with plot_col1:
        # Return Rate per Year Plot
        fig_rate = go.Figure()
        
        # Calculate annual return rates
        annual_return_rates = []
        for i in range(1, len(analysis_data['years'])):
            if i == 1:
                # First year return rate: (equity + rental income - costs - initial investment) / initial investment
                first_year_equity = analysis_data['equities'][i]
                first_year_rental = analysis_data['cumulative_rental_income'][i]
                first_year_costs = analysis_data['cumulative_costs'][i]
                first_year_return = first_year_equity + first_year_rental - first_year_costs - total_acquisition
                rate = (first_year_return / total_acquisition) * 100 if total_acquisition > 0 else 0
            else:
                # Year-over-year return rate: (current_equity - previous_equity + annual_rental - annual_costs) / previous_equity
                prev_equity = analysis_data['equities'][i-1]
                curr_equity = analysis_data['equities'][i]
                annual_rental = monthly_rent * 12
                # Calculate annual costs (operating + interest only)
                if maintenance_method == "1% of property value":
                    maintenance = property_price * 0.01
                else:
                    maintenance = monthly_rent * 12 * 0.10
                management_fees = monthly_rent * 12 * (management_fee_percent / 100)
                annual_operating_costs = (
                    service_charge + ground_rent + council_tax + insurance +
                    management_fees + maintenance + gas_safety + electrical_inspection / 5 + 
                    epc_certificate / 10 + (void_days / 365) * (monthly_rent * 12)
                )
                annual_mortgage_payment = mortgage_annual_payment(loan_amount, mortgage_interest_rate, mortgage_term_years)
                # Calculate actual interest for this specific year using proper amortization
                annual_interest, _ = calculate_annual_interest_principal(loan_amount, mortgage_interest_rate, mortgage_term_years, i)
                annual_costs = annual_operating_costs + annual_interest
                
                annual_return = (curr_equity - prev_equity) + annual_rental - annual_costs
                rate = (annual_return / prev_equity) * 100 if prev_equity > 0 else 0
            annual_return_rates.append(rate)
        
        fig_rate.add_trace(go.Scatter(
            x=analysis_data['years'][1:],  # Skip year 0
            y=annual_return_rates,
            mode='lines+markers',
            name='Annual Return Rate',
            line=dict(color='#2ca02c', width=3),
            marker=dict(size=8)
        ))
        
        fig_rate.update_layout(
            title='Return Rate per Year',
            xaxis_title='Year',
            yaxis_title='Return Rate (%)',
            height=400,
            showlegend=False
        )
        
        fig_rate.update_yaxes(tickformat='.1f%')
        st.plotly_chart(fig_rate, use_container_width=True)
    
    with plot_col2:
        # Return Amount per Year Plot
        fig_amount = go.Figure()
        
        # Calculate annual return amounts
        annual_return_amounts = []
        for i in range(1, len(analysis_data['years'])):
            if i == 1:
                # First year return amount: equity + rental income - costs - initial investment
                first_year_equity = analysis_data['equities'][i]
                first_year_rental = analysis_data['cumulative_rental_income'][i]
                first_year_costs = analysis_data['cumulative_costs'][i]
                amount = first_year_equity + first_year_rental - first_year_costs - total_acquisition
            else:
                # Year-over-year return amount: equity increase + rental income - costs
                prev_equity = analysis_data['equities'][i-1]
                curr_equity = analysis_data['equities'][i]
                annual_rental = monthly_rent * 12
                # Calculate annual costs (operating + interest only)
                if maintenance_method == "1% of property value":
                    maintenance = property_price * 0.01
                else:
                    maintenance = monthly_rent * 12 * 0.10
                management_fees = monthly_rent * 12 * (management_fee_percent / 100)
                annual_operating_costs = (
                    service_charge + ground_rent + council_tax + insurance +
                    management_fees + maintenance + gas_safety + electrical_inspection / 5 + 
                    epc_certificate / 10 + (void_days / 365) * (monthly_rent * 12)
                )
                annual_mortgage_payment = mortgage_annual_payment(loan_amount, mortgage_interest_rate, mortgage_term_years)
                # Calculate actual interest for this specific year using proper amortization
                annual_interest, _ = calculate_annual_interest_principal(loan_amount, mortgage_interest_rate, mortgage_term_years, i)
                annual_costs = annual_operating_costs + annual_interest
                
                amount = (curr_equity - prev_equity) + annual_rental - annual_costs
            annual_return_amounts.append(amount)
        
        fig_amount.add_trace(go.Scatter(
            x=analysis_data['years'][1:],  # Skip year 0
            y=annual_return_amounts,
            mode='lines+markers',
            name='Annual Return Amount',
            line=dict(color='#1f77b4', width=3),
            marker=dict(size=8),
            fill='tonexty' if len(annual_return_amounts) > 1 else 'tozeroy'
        ))
        
        fig_amount.update_layout(
            title='Return Amount per Year',
            xaxis_title='Year',
            yaxis_title='Return Amount (£)',
            height=400,
            showlegend=False
        )
        
        fig_amount.update_yaxes(tickformat='£,.0f')
        st.plotly_chart(fig_amount, use_container_width=True)
    
    # Summary of return metrics
    st.subheader("📊 Return Summary")
    summary_col1, summary_col2, summary_col3 = st.columns(3)
    
    with summary_col1:
        avg_annual_return_rate = sum(annual_return_rates) / len(annual_return_rates) if annual_return_rates else 0
        st.metric(
            "Average Annual Return Rate",
            f"{avg_annual_return_rate:.1f}%",
            help="Average return rate per year over the mortgage term"
        )
    
    with summary_col2:
        total_return_amount = analysis_data['equities'][-1] - total_acquisition
        st.metric(
            "Total Return Amount",
            f"£{total_return_amount:,.0f}",
            help="Total return amount over the entire mortgage term"
        )
    
    with summary_col3:
        best_year_return = max(annual_return_rates) if annual_return_rates else 0
        best_year = analysis_data['years'][annual_return_rates.index(best_year_return) + 1] if annual_return_rates else 0
        st.metric(
            "Best Year Return Rate",
            f"{best_year_return:.1f}%",
            delta=f"Year {best_year}",
            help="Highest annual return rate achieved"
        )
    
    # Detailed yearly breakdown
    with st.expander("Show Detailed Yearly Breakdown"):
        st.subheader("📋 Year-by-Year Analysis")
        
        # Create a DataFrame for better display
        
        df_data = {
            'Year': analysis_data['years'],
            'Property Value (£)': [f"£{val:,.0f}" for val in analysis_data['property_values']],
            'Remaining Mortgage (£)': [f"£{val:,.0f}" for val in analysis_data['remaining_mortgages']],
            'Equity (£)': [f"£{val:,.0f}" for val in analysis_data['equities']],
            'Total Return (%)': [f"{val:.1f}%" for val in analysis_data['net_returns']]
        }
        
        df = pd.DataFrame(df_data)
        st.dataframe(df, use_container_width=True)
        
        # Summary statistics
        st.subheader("📊 Summary Statistics")
        summary_col1, summary_col2 = st.columns(2)
        
        with summary_col1:
            st.metric("Initial Investment", f"£{total_acquisition:,.0f}")
            st.metric("Final Property Value", f"£{final_property_value:,.0f}")
            st.metric("Total Appreciation", f"£{final_property_value - property_price:,.0f}")
        
        with summary_col2:
            st.metric("Final Equity", f"£{final_equity:,.0f}")
            st.metric("Total Return", f"{final_return:.1f}%")
            st.metric("Annualized Return", f"{annualized_return:.1f}%")

st.caption("All calculations are estimates. For detailed advice, consult a qualified property accountant or advisor.")
