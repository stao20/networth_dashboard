# Net Worth Dashboard

A Streamlit-based dashboard for tracking your net worth across different accounts and categories. Features Google OAuth authentication and Supabase for data storage.

## Features

- 🔐 Secure Google OAuth authentication
- 📊 Interactive charts and visualizations
- 📱 Responsive design
- 🗄️ Category and account management
- 📈 Net worth tracking over time
- 📊 Distribution analysis
- 🔄 Real-time updates

## Prerequisites

- Python 3.8+
- Docker Desktop (for Supabase local development)
- Node.js and npm (for Supabase CLI)

## Setup Instructions

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd networth_dashboard
   ```

2. **Set up Python environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Install Supabase CLI**
   ```bash
   npm install supabase --save-dev
   ```

4. **Configure Google OAuth**
   - Go to [Google Cloud Console](https://console.cloud.google.com)
   - Create a new project or select an existing one
   - Enable the Google OAuth2 API
   - Configure the OAuth consent screen
   - Create OAuth 2.0 credentials (Web application type)
   - Add authorized redirect URIs:
     - `http://localhost:8501/oauth2callback` (for local development)
     - Your production URL if deploying

5. **Configure Streamlit secrets**
   Create `.streamlit/secrets.toml` with your Google OAuth credentials:
   ```toml
   [auth]
   providers = ["google"]
   cookie_secret = "your-random-secret"
   client_id = "your-google-client-id"
   client_secret = "your-google-client-secret"
   redirect_uri = "http://localhost:8501/oauth2callback"
   server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
   ```

   ### Account value sync (optional)

   Add to `.streamlit/secrets.toml`:

   ```toml
   [sync]
   credentials_key = "<fernet-key-from-cryptography.fernet.Fernet.generate_key()>"

   [gocardless]
   secret_id = "..."
   secret_key = "..."
   ```

   GitHub Actions month-end job needs repository secrets:
   `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SYNC_CREDENTIALS_KEY`.

   Optional repository secrets `GOCARDLESS_SECRET_ID` and `GOCARDLESS_SECRET_KEY`
   (same values as `[gocardless]` above) let the job refresh Open Banking tokens.
   Without them the job can only use each connection's stored refresh token, and
   connections whose refresh token has expired are marked "needs re-authentication".

   The job exits non-zero when any user's sync is partial or failed, including
   mapped accounts on connections that need re-authentication or are in error,
   so a red workflow run means some balances were not updated.

   **Local Trading 212 smoke (no Streamlit Cloud / no Supabase writes):**

   ```bash
   TRADING212_API_KEY=... TRADING212_API_SECRET=... \
     uv run python scripts/smoke_trading212_sync.py
   # optional: TRADING212_DEMO=1 for demo.trading212.com keys
   ```

   This calls the real Trading 212 API but keeps connections/sync runs in memory.

6. **Initialize Supabase project**
   ```bash
   npx supabase init
   npx supabase start
   ```

## Running the Application

1. **Start the application**
   ```bash
   streamlit run src/app.py
   ```

2. **Access the dashboard**
   Open your browser and navigate to:
   ```
   http://localhost:8501
   ```

## Development

The project structure is organized as follows:

```
networth_dashboard/
├── .streamlit/
│   └── secrets.toml
├── src/
│   ├── app.py
│   ├── config.py
│   ├── pages/
│   │   └── networth_tracker.py
│   └── utils/
│       ├── auth.py
│       ├── db.py
│       └── models.py
├── requirements.txt
└── README.md
```

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.
