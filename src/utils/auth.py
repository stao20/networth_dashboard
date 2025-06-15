import streamlit as st
from typing import Optional, Tuple

class GoogleAuth:
    def __init__(self):
        """Initialize the authentication handler"""
        if "user_info" not in st.session_state:
            st.session_state.user_info = None

    def login_button(self) -> Optional[Tuple[str, str, str]]:
        """Display Google login button and handle authentication flow"""
        try:
            if not st.user.is_logged_in:
                st.write("Please log in to continue:")
                st.button("Login with Google", on_click=st.login, args=("google",))
                return None
            
            # User is authenticated, get user info
            user_info = {
                "id": st.user.sub,  # Google OAuth uses 'sub' as the unique user ID
                "email": st.user.email,
                "name": st.user.name
            }
            st.session_state.user_info = user_info
            return (user_info["id"], user_info["email"], user_info["name"])
            
        except Exception as e:
            st.error(f"Authentication error: {str(e)}")
            if "invalid_client" in str(e):
                st.error("Invalid client configuration. Please check your Google OAuth credentials.")
                st.info("Make sure your client ID and client secret are correct in .streamlit/secrets.toml")
            return None

    def logout(self):
        """Log out the current user"""
        try:
            st.session_state.user_info = None
            st.logout()
        except Exception as e:
            st.error(f"Logout error: {str(e)}")
            st.rerun()
