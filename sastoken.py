import os
import threading
import webbrowser
import time
import json
import logging
from datetime import datetime
from urllib.parse import urlparse
from flask import Flask, request, redirect, session
from requests_oauthlib import OAuth2Session
import pyotp
import pyperclip

# Setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'  # For local HTTP only


# === HARDCODED CONFIG (Only you use this) ===
CLIENT_ID = "SAS-CLIENT1"
CLIENT_SECRET = "Hhtg74iYYZY1nSJUvDBxKntGqfigem6yKyYw9rlb2qSXyhEEs8BZEtw27KsIE1UI"
LOCAL_REDIRECT_URL = "http://127.0.0.1:65015/"
DEPLOYED_REDIRECT_URL = "/api/sas_oauth_callback"
BASE_URL = "https://api.stocko.in"
TOTP_SECRET = "T4JZGOUEE2G3NOCZ"
TOKEN_FILE = "access_token.json"

# Use PORT environment variable for Render deployment, fallback to 65015 for local development
# Only start OAuth service if NOT in consolidated mode (CONSOLIDATED_OAUTH not set)
PORT = int(os.environ.get('SAS_PORT', 65015))
HOST = '0.0.0.0' if os.environ.get('SAS_PORT') else '127.0.0.1'
START_OAUTH_SERVICE = not os.environ.get('CONSOLIDATED_OAUTH')


def get_oauth_authorization_url(redirect_url=None):
    """
    Get the OAuth authorization URL for SASOnline.
    Returns: authorization URL
    """
    # Use provided redirect_url or default based on environment
    if redirect_url is None:
        # Check if we're running in deployed environment or consolidated mode
        if os.environ.get('SAS_PORT') or not START_OAUTH_SERVICE:
            # For deployed environments or consolidated mode, we can't generate a proper URL without knowing the base URL
            # This function should be called with a proper redirect_url in these environments
            raise ValueError("In deployed environment or consolidated mode, redirect_url must be provided")
        else:
            redirect_url = LOCAL_REDIRECT_URL

    oauth = OAuth2Session(CLIENT_ID, redirect_uri=redirect_url, scope='orders holdings')
    auth_url, _ = oauth.authorization_url(f'{BASE_URL}/oauth2/auth')
    return auth_url


def generate_totp():
    """Generate TOTP code for SASOnline login"""
    try:
        totp = pyotp.TOTP(TOTP_SECRET)
        code = totp.now()
        pyperclip.copy(code)
        print(f"TOTP: {code} → Copied to clipboard!")
        return code
    except Exception as e:
        print(f"TOTP generation failed: {e}")
        return None

def exchange_code_for_token(authorization_response, redirect_uri=None):
    """
    Exchange authorization code for access token
    Returns: access token or None
    """
    try:
        if redirect_uri is None:
            redirect_uri = LOCAL_REDIRECT_URL

        oauth = OAuth2Session(CLIENT_ID, redirect_uri=redirect_uri, scope='orders holdings')
        token = oauth.fetch_token(
            f'{BASE_URL}/oauth2/token',
            client_secret=CLIENT_SECRET,
            authorization_response=authorization_response
        )
        return token.get('access_token')
    except Exception as e:
        logger.error(f"Error exchanging code for token: {e}")
        return None

def sasonline_oauth_login() -> dict:
    """
    One-click SASOnline OAuth2 login.
    Returns: dict with success status and message
    """
    # Use global config
    REDIRECT_URL = LOCAL_REDIRECT_URL
    PORT = 65015
    TOKEN_FILE = "access_token.json"

    access_token = [None]
    shutdown_event = threading.Event()



    # Flask App
    app = Flask(__name__)
    app.secret_key = 'development'

    @app.route('/')
    def callback():
        try:
            # Use appropriate redirect URL based on environment
            if os.environ.get('SAS_PORT') or not START_OAUTH_SERVICE:
                # For deployed environments or consolidated mode, use the main app's OAuth callback
                redirect_url = request.url_root.rstrip('/') + DEPLOYED_REDIRECT_URL
            else:
                redirect_url = LOCAL_REDIRECT_URL

            oauth = OAuth2Session(CLIENT_ID, redirect_uri=redirect_url, scope='orders holdings')
            token = oauth.fetch_token(
                f'{BASE_URL}/oauth2/token',
                client_secret=CLIENT_SECRET,
                authorization_response=request.url
            )
            access_token[0] = token['access_token']
            shutdown_event.set()
            return "<h2>Success!</h2><p>Token saved. Close this tab.</p>"
        except Exception as e:
            return f"<h3>Error:</h3> {e}"

    @app.route('/start')
    def start():
        # Use appropriate redirect URL based on environment
        if os.environ.get('SAS_PORT') or not START_OAUTH_SERVICE:
            # For deployed environments or consolidated mode, use the main app's OAuth callback
            redirect_url = request.url_root.rstrip('/') + DEPLOYED_REDIRECT_URL
        else:
            redirect_url = LOCAL_REDIRECT_URL

        oauth = OAuth2Session(CLIENT_ID, redirect_uri=redirect_url, scope='orders holdings')
        auth_url, _ = oauth.authorization_url(f'{BASE_URL}/oauth2/auth')
        return redirect(auth_url)

    # Only start the OAuth service when not in deployed environment and not in consolidated mode
    if not os.environ.get('SAS_PORT') and START_OAUTH_SERVICE:
        # Run server
        def run_server():
            app.run(host=HOST, port=PORT, debug=False, use_reloader=False)

        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        time.sleep(1.5)  # Wait for server

        # Generate & Copy TOTP (only in non-consolidated mode)
        if START_OAUTH_SERVICE:
            try:
                totp = pyotp.TOTP(TOTP_SECRET)
                code = totp.now()
                pyperclip.copy(code)
                print(f"TOTP: {code} → Copied to clipboard!")
            except:
                print("TOTP failed")
        else:
            print("Running in consolidated mode. TOTP will not be generated automatically.")

        # Open browser (only in non-consolidated mode)
        if START_OAUTH_SERVICE:
            print("Opening browser...")
            webbrowser.open(f'http://{HOST if HOST != "0.0.0.0" else "127.0.0.1"}:{PORT}/start')
        else:
            print("Running in consolidated mode. Browser will not be opened automatically.")
    else:
        # In deployed environment or consolidated mode, return a message indicating OAuth should be handled differently
        if not START_OAUTH_SERVICE:
            print("Running in consolidated mode. OAuth flow should be initiated through the main app.")
            return {"success": False, "message": "OAuth flow should be initiated through the main app in consolidated mode"}
        else:
            print("Running in deployed environment. OAuth flow should be initiated through the main app.")
            return {"success": False, "message": "OAuth flow should be initiated through the main app in deployed environment"}

    # Wait for login (only in non-deployed environment and not in consolidated mode)
    if not os.environ.get('SAS_PORT') and START_OAUTH_SERVICE:
        if shutdown_event.wait(timeout=180):
            if access_token[0]:
                # Instead of saving to file, we'll store in a global variable
                # Import app module to set the global variable
                try:
                    import app
                    app.access_token = access_token[0]
                    print("Login Success!")
                    print(app.access_token)
                    return {"success": True, "message": "Login successful and token stored in memory"}
                except ImportError:
                    # If direct import fails, return token for app to handle
                    print("Login Success!")
                    return {"success": True, "message": "Login successful and token stored in memory", "token": access_token[0]}
            else:
                return {"success": False, "message": "No token received"}
        else:
            return {"success": False, "message": "Login timed out after 3 minutes"}
    else:
        # In deployed environment or consolidated mode, OAuth flow is handled differently
        if not START_OAUTH_SERVICE:
            return {"success": False, "message": "OAuth flow should be initiated through the main app in consolidated mode"}
        else:
            return {"success": False, "message": "OAuth flow should be initiated through the main app in deployed environment"}

