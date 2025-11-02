# Property Investment Calculator - Formulas & Logic Explained

This document explains all the formulas and calculation logic used in the Company Property Investment Profitability Evaluator.

---

## Table of Contents

1. [Overview](#overview)
2. [Core Financial Metrics](#core-financial-metrics)
3. [Return Computation Formulas](#return-computation-formulas)
4. [Cost Calculations](#cost-calculations)
5. [Mortgage Calculations](#mortgage-calculations)
6. [Fair Price Calculation](#fair-price-calculation)
7. [Key Assumptions & Simplifications](#key-assumptions--simplifications)

---

## Overview

The calculator evaluates buy-to-let property investments by:
1. Calculating the **fair price** based on target yield or cash-on-cash return
2. Computing various return metrics over the mortgage term
3. Analyzing cash flow and break-even occupancy
4. Projecting equity growth with property appreciation

**Important:** All mortgage interest and principal calculations use **accurate amortization formulas** based on outstanding loan balance, not simplified approximations. Early years correctly show higher interest costs (~70-80%) and lower principal (~20-30%), while later years show lower interest (~20-30%) and higher principal (~70-80%).

---

## Core Financial Metrics

### 1. Net Rental Yield

**Formula:**
```
Net Rental Yield = ((Net Income Before Tax + Annual Equity) / Property Price) × 100%
```

**Breakdown:**
- **Net Income Before Tax** = Annual Rent - Operating Costs - Mortgage Interest
- **Annual Equity** = Principal portion of mortgage payment (calculated using accurate amortization)
- **Property Price** = Purchase price of the property

**Why include equity?** Equity paydown is considered part of the return because it increases your ownership stake in the property.

**Calculation (lines 215-241):**
```python
# Calculate actual first-year interest and principal using proper amortization
annual_interest_fp, annual_equity_fp = calculate_first_year_interest_principal(loan_amount_fp, mortgage_interest_rate, mortgage_term_years)
net_income_before_tax = annual_rent - (annual_operating_costs + annual_interest)
net_income_before_tax_with_equity = net_income_before_tax + annual_equity
net_rental_yield = (net_income_before_tax_with_equity / property_price) × 100
```

---

### 2. Cash-on-Cash Return

**Formula:**
```
Cash-on-Cash Return = ((Net Income After Tax + Annual Equity) / Total Upfront Investment) × 100%
```

**Breakdown:**
- **Net Income After Tax** = Net Income Before Tax - Corporation Tax
- **Annual Equity** = Principal portion of mortgage payment
- **Total Upfront Investment** = Deposit + Stamp Duty + Legal Fees + Survey Costs + Broker Fee + Mortgage Fees

**Key Difference from Yield:** Uses actual cash invested (not property value) as denominator, making it more relevant for investors using leverage.

**Calculation (lines 243-285):**
```python
# Calculate actual first-year interest and principal using proper amortization
annual_interest_fp, annual_equity_fp = calculate_first_year_interest_principal(loan_amount_fp, mortgage_interest_rate, mortgage_term_years)
taxable_profit = net_income_before_tax  # Rent - Operating Costs - Interest
corp_tax = calculate_corporation_tax(max(0, taxable_profit))
net_income_after_tax = net_income_before_tax - corp_tax
net_income_after_tax_with_equity = net_income_after_tax + annual_equity
cash_on_cash_return = (net_income_after_tax_with_equity / total_acquisition) × 100
```

---

### 3. Monthly Net Cash Flow

**Formula:**
```
Monthly Net Cash Flow = (Net Income After Tax - Annual Equity) / 12
```

**Why subtract equity?** Principal payments reduce available cash, even though they increase equity. This metric shows actual cash retained each month.

**Calculation (line 577):**
```python
net_income_after_tax_excluding_equity = net_income_after_tax - annual_equity
monthly_net_cash_flow = net_income_after_tax_excluding_equity / 12
```

---

### 4. Break-Even Occupancy

**Formula:**
```
Break-even Occupancy = ((Annual Operating Costs + Annual Interest) / Annual Rent) × 100%
```

Minimum occupancy percentage needed to cover all costs (excluding principal repayment).

**Calculation (line 578):**
```python
break_even_occupancy = ((annual_operating_costs + annual_interest) / annual_rent) × 100
```

---

## Return Computation Formulas

The calculator tracks several return metrics over the mortgage term to analyze investment performance.

### 1. Equity Calculation

**Formula:**
```
Equity = Current Property Value - Remaining Mortgage Balance
```

**Property Value with Appreciation (line 455):**
```
Current Property Value = Initial Price × (1 + appreciation_rate/100)^years
```

**Remaining Mortgage Balance (lines 402-418):**
```
Remaining Balance = Monthly Payment × ((1 - (1 + r)^(-months_remaining)) / r)
```

Where:
- `r` = monthly interest rate (annual_rate / 100 / 12)
- `months_remaining` = years remaining × 12

Uses the present value of annuity formula (backward calculation from remaining payments).

---

### 2. Simple Return Percentage

**Formula (line 465):**
```
Return % = ((Current Equity - Initial Investment) / Initial Investment) × 100%
```

**What it measures:** Pure equity growth return, ignoring rental income and costs. Less comprehensive than net return.

---

### 3. Net Return Percentage (Primary Metric)

**Formula (line 477):**
```
Net Return % = ((Equity + Cumulative Rental Income - Cumulative Costs - Initial Investment) / Initial Investment) × 100%
```

**Components:**
- **Equity** = Current Property Value - Remaining Mortgage
- **Cumulative Rental Income** = Sum of all rental income from year 1 to current year
- **Cumulative Costs** = Sum of (Operating Costs + Interest Only) over years
  - ⚠️ **Note:** Principal payments are NOT included as costs (they build equity)
- **Initial Investment** = Total upfront cash invested

**Why this is important:** Provides total investment return including rental income, costs, and equity growth. This is the primary return metric displayed in the analysis charts.

**Calculation (lines 470-477):**
```python
if year > 0:
    cumulative_rental += annual_rent_income
    # Calculate actual interest for this year using proper amortization
    annual_interest, _ = calculate_annual_interest_principal(loan_amount, mortgage_rate, mortgage_term, year)
    cumulative_cost += annual_operating_costs + annual_interest

net_return = equity + cumulative_rental - cumulative_cost - total_acquisition_cost
net_return_percentage = (net_return / total_acquisition_cost) × 100
```

---

### 4. First Year Return Rate

**Formula (lines 920-925):**
```
First Year Return = (First Year Equity + First Year Rental - First Year Costs - Initial Investment) / Initial Investment × 100%
```

**Components for Year 1:**
- First Year Equity = Property Value (with 1 year appreciation) - Remaining Mortgage after 1 year
- First Year Rental = Annual rent income
- First Year Costs = Operating Costs + Interest (cumulative)

---

### 5. Year-over-Year Return Rate

**Formula (lines 927-948):**
```
Annual Return Rate = ((Current Equity - Previous Equity) + Annual Rental - Annual Costs) / Previous Equity × 100%
```

**Breakdown:**
- **Equity Change** = Current Year Equity - Previous Year Equity
- **Annual Rental** = Monthly Rent × 12
- **Annual Costs** = Operating Costs + Interest (principal excluded)
- **Previous Equity** = Equity at start of the year (used as denominator for percentage)

**What it measures:** Yearly return rate relative to the equity base at the start of that year.

---

### 6. Annualized Return (CAGR)

**Formula (line 826):**
```
Annualized Return = ((Final Equity / Initial Investment)^(1/Years) - 1) × 100%
```

**Where:**
- **Final Equity** = Property Value at end of mortgage term - Remaining Mortgage (0, since fully paid)
- **Initial Investment** = Total upfront cash (already in denominator)
- **Years** = Mortgage term in years

**Why this formula is correct:**
This is the standard **Compound Annual Growth Rate (CAGR)** formula. The initial investment is already accounted for in the denominator. The `- 1` at the end converts the growth ratio to a percentage return.

**Example:**
- Initial Investment: £100,000
- Final Equity: £200,000
- Years: 10
- CAGR = ((£200,000 / £100,000)^(1/10) - 1) × 100% = (2^0.1 - 1) × 100% = 7.18% per year

**Note:** If you wanted to calculate the return on profit instead:
```
Alternative: ((Final Equity - Initial Investment) / Initial Investment)^(1/Years) - 1
```
This would give: ((£200k - £100k) / £100k)^(1/10) - 1 = (1)^(1/10) - 1 = 0% ❌ (incorrect)

The correct approach uses the **total ending value** (Final Equity), not just the profit. The ratio `Final Equity / Initial Investment` represents the total growth multiplier.

**What it measures:** Compound Annual Growth Rate (CAGR) of equity over the entire mortgage term. Shows the average annual return if returns were evenly distributed.

**Important:** This formula calculates equity growth CAGR only. It does NOT include rental income in the calculation. For total return including rental income, see the "Net Return Percentage" formula above.

---

## Cost Calculations

### Operating Costs

**Formula (lines 234-237, 268-271):**
```
Annual Operating Costs = 
    Service Charge 
    + Ground Rent 
    + Council Tax 
    + Insurance 
    + Management Fees (% of rent)
    + Maintenance (1% of property value OR 10% of rent)
    + Gas Safety Certificate
    + Electrical Inspection / 5 (annualized)
    + EPC Certificate / 10 (annualized)
    + Vacancy Cost ((void_days/365) × annual_rent)
```

**Maintenance Options:**
- **Option 1:** 1% of property value per year
- **Option 2:** 10% of annual rental income

**Vacancy Cost:**
Accounts for periods when the property is unoccupied and not generating rent.

---

### Total Acquisition Cost

**Formula (lines 539-541):**
```
Total Acquisition = 
    Deposit (25% of property price)
    + Stamp Duty (tiered UK rates)
    + Legal Fees
    + Mortgage Product Fee
    + Survey Costs
    + Broker Fee (% of loan amount)
```

---

### Corporation Tax

**UK Corporation Tax Structure (lines 134-153):**

```
If profit ≤ £50,000:
    Tax = profit × 19%

If profit ≥ £250,000:
    Tax = profit × 25%

If £50,000 < profit < £250,000:
    Effective Rate = 19% + (profit - £50,000) × 6% / £200,000
    Tax = profit × (Effective Rate / 100)
```

**Taxable Profit Calculation:**
```
Taxable Profit = Annual Rent - Operating Costs - Mortgage Interest
```

⚠️ **Note:** Principal payments are NOT tax-deductible (they build equity, not reduce profit).

---

### Stamp Duty

**UK Tiered Stamp Duty (lines 115-123):**
```
If price > £250,000:
    duty += (min(price, £925,000) - £250,000) × 10%

If price > £125,000:
    duty += (min(price, £250,000) - £125,000) × 7%

If price > £0:
    duty += min(price, £125,000) × 5%
```

Tiered rates with bands at £125k, £250k, and £925k.

---

## Mortgage Calculations

### Annual Mortgage Payment (Annuity Formula)

**Formula (lines 125-132):**
```
Monthly Payment = Principal × (r × (1 + r)ⁿ) / ((1 + r)ⁿ - 1)
Annual Payment = Monthly Payment × 12
```

**Where:**
- `r` = monthly interest rate = (annual_rate / 100) / 12
- `n` = total number of payments = years × 12
- `Principal` = Loan amount (typically 75% LTV)

**Standard loan amortization formula** that calculates the fixed payment needed to pay off the loan over the term.

---

### Interest vs Principal Split

**Accurate Amortization Calculation (lines 134-191):**

The code now uses proper amortization formulas to calculate actual interest and principal for each year:

**For each month in a year:**
```
Monthly Interest = Outstanding Balance × Monthly Interest Rate
Monthly Principal = Monthly Payment - Monthly Interest
New Outstanding Balance = Outstanding Balance - Monthly Principal
```

**Annual totals:**
```
Annual Interest = Sum of 12 monthly interest payments
Annual Principal = Sum of 12 monthly principal payments
```

**Helper Functions:**
- `calculate_annual_interest_principal(loan_amount, annual_rate, years, year_number)` - Calculates interest and principal for a specific year
- `calculate_first_year_interest_principal(loan_amount, annual_rate, years)` - Convenience wrapper for year 1

**Actual Amortization Behavior:**
- **Early years:** ~70-80% interest, ~20-30% principal (due to larger outstanding balance)
- **Later years:** ~20-30% interest, ~70-80% principal (due to smaller outstanding balance)

This provides accurate calculations throughout the investment analysis, showing how interest costs decrease over time while principal payments (equity building) increase.

---

### Remaining Mortgage Balance

**Formula (lines 344-360):**
```
Remaining Balance = Monthly Payment × ((1 - (1 + r)^(-months_remaining)) / r)
```

**Where:**
- `months_remaining` = years_remaining × 12
- Uses present value of annuity formula (backward calculation)

This calculates how much principal is still owed after a certain number of years.

---

## Fair Price Calculation

The calculator finds the maximum price you should pay to achieve your target yield or cash-on-cash return.

### Algorithm (lines 362-400)

**Binary Search Approach:**

1. **Find Maximum Viable Price** (lines 287-305):
   - Ensures Annual Rent > Annual Mortgage Payment
   - Uses binary search between £50k and £2M
   - Finds highest price where rent covers mortgage

2. **Apply Cash Flow Constraint** (if enabled, lines 307-360):
   - Finds lowest price that satisfies maximum monthly cash flow
   - Ensures monthly net cash flow ≤ maximum allowed
   - Uses accurate first-year amortization for interest/principal calculation

3. **Find Target Price** (lines 381-400):
   - Binary search between £50k and maximum viable price
   - Calculates yield/return for each test price
   - Adjusts price until computed value matches target (within tolerance)

**Constraints Applied:**
- ✅ Rent must exceed mortgage payment
- ✅ Monthly cash flow ≤ maximum (if constraint enabled)
- ✅ Target yield/return must be achieved

---

## Key Assumptions & Simplifications

### 1. Interest/Principal Split

**Assumption:** 50% interest, 50% principal throughout loan term.

**Reality:** The split changes over time. Early payments are mostly interest, later payments are mostly principal.

**Impact:** 
- Slightly overestimates interest costs in early years
- Slightly underestimates interest costs in later years
- Net effect tends to average out over long term

---

### 2. Fixed Costs Over Time

**Assumption:** Operating costs remain constant over mortgage term.

**Reality:** Costs typically increase with inflation (typically 2-3% per year).

**Impact:** Underestimates future costs, slightly overestimates returns.

---

### 3. Fixed Rental Income

**Assumption:** Monthly rent stays constant.

**Reality:** Rents typically increase with inflation or market conditions.

**Impact:** Underestimates rental income growth, potentially underestimates returns.

---

### 4. Property Appreciation

**Assumption:** Constant annual appreciation rate (user-specified, default 0%).

**Reality:** Property values fluctuate and don't grow linearly.

**Impact:** Using 0% is conservative. Higher rates are speculative.

---

### 5. No Refinancing

**Assumption:** Mortgage terms remain constant, no refinancing or early payoff.

**Reality:** Investors may refinance to get better rates or change loan terms.

---

### 6. Tax Simplifications

**Assumption:** 
- Corporation tax applies to all rental profit
- No other tax considerations (income tax on dividends, capital gains, etc.)

**Reality:** Actual tax situation depends on company structure, individual circumstances, and future tax law changes.

---

### 7. No Major Repairs

**Assumption:** Maintenance provision (1% of value or 10% of rent) covers all maintenance.

**Reality:** Major repairs (roof, HVAC, etc.) can occur unpredictably and exceed provision.

---

## Formula Relationships

```
┌─────────────────────────────────────────────────────────────┐
│                    Property Investment                      │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
        ┌──────────────────────────────────────┐
        │      Annual Rental Income            │
        └──────────────────────────────────────┘
                              │
            ┌─────────────────┴─────────────────┐
            ▼                                   ▼
    ┌──────────────────┐              ┌──────────────────┐
    │ Operating Costs │              │ Mortgage Payment │
    └──────────────────┘              └──────────────────┘
                                             │
                            ┌─────────────────┴─────────────────┐
                            ▼                                   ▼
                    ┌──────────────┐                  ┌──────────────┐
                    │   Interest   │                  │   Principal  │
                    │   (Cost)     │                  │   (Equity)   │
                    └──────────────┘                  └──────────────┘
                            │                                   │
                            ▼                                   ▼
        ┌───────────────────────────────────────────────────────┐
        │      Net Income Before Tax                            │
        │  = Rent - Operating Costs - Interest                 │
        └───────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────────────────────────┐
        │      Corporation Tax (on taxable profit)               │
        └───────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────────────────────────┐
        │      Net Income After Tax                             │
        │  = Net Income Before Tax - Tax                       │
        └───────────────────────────────────────────────────────┘
                            │
            ┌───────────────┴───────────────┐
            ▼                               ▼
    ┌───────────────┐              ┌───────────────┐
    │ Monthly Cash  │              │    Returns    │
    │    Flow       │              │  Calculations │
    │ = (After Tax │              │               │
    │  - Principal) │              │ + Equity      │
    │   / 12        │              │ + Rentals     │
    └───────────────┘              │ - Costs       │
                                   │ - Initial Inv │
                                   └───────────────┘
```

---

## Example Calculation Walkthrough

### Inputs:
- Monthly Rent: £1,500
- Property Price: £300,000
- Mortgage: 75% LTV, 4.5% interest, 25 years
- Operating Costs: £3,000/year
- Target Net Yield: 3%

### Step-by-Step:

1. **Loan Amount:**
   ```
   Loan = £300,000 × 0.75 = £225,000
   Deposit = £300,000 × 0.25 = £75,000
   ```

2. **Annual Mortgage Payment:**
   ```
   r = 0.045 / 12 = 0.00375
   n = 25 × 12 = 300
   Monthly = £225,000 × (0.00375 × 1.00375^300) / (1.00375^300 - 1)
   Annual ≈ £16,200
   ```

3. **Actual Amortization Split (First Year):**
   ```
   # Using calculate_first_year_interest_principal(£225,000, 4.5%, 25)
   # Calculates actual monthly amortization:
   # - Monthly payment ≈ £1,350
   # - First month: Interest = £225,000 × 0.00375 = £843.75
   # - First month: Principal = £1,350 - £843.75 = £506.25
   # ... continues for 12 months ...
   Annual Interest ≈ £10,080 (62% - typical for first year)
   Annual Principal ≈ £6,120 (38% - typical for first year)
   ```
   *Note: Actual values depend on interest rate. Early years have higher interest percentage due to larger outstanding balance.*

4. **Net Income Before Tax:**
   ```
   Annual Rent = £1,500 × 12 = £18,000
   Net Income = £18,000 - £3,000 - £10,080 = £4,920
   ```
   *Note: Using actual first-year interest of £10,080 instead of simplified £8,100*

5. **Net Rental Yield:**
   ```
   Net Income with Equity = £4,920 + £6,120 = £11,040
   Yield = (£11,040 / £300,000) × 100 = 3.68%
   ```
   *Note: This is more accurate than the simplified calculation, showing lower yield due to higher interest costs in early years.*

6. **If Target is 3%:** Calculator would search for a price around £500,000 to achieve 3% yield (lower yield = higher price for same income).

---

## Summary

The calculator uses standard financial formulas with some simplifications:

✅ **Accurate:**
- Annuity mortgage payment formula
- Remaining balance calculations
- Tax calculations (UK corporation tax)
- Yield and cash-on-cash return definitions

⚠️ **Simplified:**
- Fixed costs and rent over time (no inflation adjustments)
- No major repair events
- No refinancing scenarios

✅ **Accurate:**
- Interest/principal split now uses proper amortization calculations

The remaining simplifications provide reasonable estimates for investment analysis but should be validated and adjusted for inflation when making real investment decisions.

---

*Last Updated: Based on code analysis of `company_property_investing.py`*

