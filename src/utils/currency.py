import streamlit as st
import requests
from typing import Dict, List, Optional

# Common currencies with their codes and symbols
CURRENCIES = {
    'GBP': {'name': 'British Pound', 'symbol': '£'},
    'USD': {'name': 'US Dollar', 'symbol': '$'},
    'EUR': {'name': 'Euro', 'symbol': '€'},
    'JPY': {'name': 'Japanese Yen', 'symbol': '¥'},
    'CAD': {'name': 'Canadian Dollar', 'symbol': 'C$'},
    'AUD': {'name': 'Australian Dollar', 'symbol': 'A$'},
    'CHF': {'name': 'Swiss Franc', 'symbol': 'CHF'},
    'CNY': {'name': 'RMB (CNY)', 'symbol': '¥'},
    'SEK': {'name': 'Swedish Krona', 'symbol': 'kr'},
    'NOK': {'name': 'Norwegian Krone', 'symbol': 'kr'},
    'DKK': {'name': 'Danish Krone', 'symbol': 'kr'},
    'PLN': {'name': 'Polish Zloty', 'symbol': 'zł'},
    'CZK': {'name': 'Czech Koruna', 'symbol': 'Kč'},
    'HUF': {'name': 'Hungarian Forint', 'symbol': 'Ft'},
    'RUB': {'name': 'Russian Ruble', 'symbol': '₽'},
    'INR': {'name': 'Indian Rupee', 'symbol': '₹'},
    'BRL': {'name': 'Brazilian Real', 'symbol': 'R$'},
    'MXN': {'name': 'Mexican Peso', 'symbol': '$'},
    'KRW': {'name': 'South Korean Won', 'symbol': '₩'},
    'SGD': {'name': 'Singapore Dollar', 'symbol': 'S$'},
    'HKD': {'name': 'Hong Kong Dollar', 'symbol': 'HK$'},
    'NZD': {'name': 'New Zealand Dollar', 'symbol': 'NZ$'},
    'ZAR': {'name': 'South African Rand', 'symbol': 'R'},
    'TRY': {'name': 'Turkish Lira', 'symbol': '₺'},
    'AED': {'name': 'UAE Dirham', 'symbol': 'د.إ'},
    'SAR': {'name': 'Saudi Riyal', 'symbol': 'ر.س'},
    'QAR': {'name': 'Qatari Riyal', 'symbol': 'ر.ق'},
    'KWD': {'name': 'Kuwaiti Dinar', 'symbol': 'د.ك'},
    'BHD': {'name': 'Bahraini Dinar', 'symbol': 'د.ب'},
    'OMR': {'name': 'Omani Rial', 'symbol': 'ر.ع.'},
}

def get_currency_list() -> List[str]:
    """Get list of currency codes for dropdown"""
    return list(CURRENCIES.keys())

def get_currency_display_name(currency_code: str) -> str:
    """Get display name for currency code"""
    return CURRENCIES.get(currency_code, {}).get('name', currency_code)

def get_currency_symbol(currency_code: str) -> str:
    """Get symbol for currency code"""
    return CURRENCIES.get(currency_code, {}).get('symbol', currency_code)

def convert_currency(amount: float, from_currency: str, to_currency: str = 'GBP') -> Optional[float]:
    """
    Convert currency using a free API
    Falls back to cached rates if API fails
    """
    if from_currency == to_currency:
        return amount
    
    try:
        # Try to get real-time rates from exchangerate-api.com (free tier)
        response = requests.get(f"https://api.exchangerate-api.com/v4/latest/{from_currency}", timeout=5)
        if response.status_code == 200:
            rates = response.json()['rates']
            if to_currency in rates:
                return amount * rates[to_currency]
    except Exception as e:
        st.warning(f"Could not fetch real-time exchange rates: {str(e)}")
    
    # Fallback to cached rates (you could implement a simple cache here)
    # For now, return None to indicate conversion failed
    return None

def format_currency(amount: float, currency_code: str) -> str:
    """Format amount with currency symbol"""
    symbol = get_currency_symbol(currency_code)
    if currency_code in ['JPY', 'KRW']:  # No decimal places for these currencies
        return f"{symbol}{amount:,.0f}"
    else:
        return f"{symbol}{amount:,.2f}"
