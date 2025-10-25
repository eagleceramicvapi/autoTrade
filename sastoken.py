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
PORT = 65015


def get_oauth_authorization_url(redirect_url=None):
    """
    Get the OAuth authorization URL for SASOnline.
    Returns: authorization URL
    """
    # Use provided redirect_url or default to local redirect URL
    if redirect_url is None:
        redirect_url = LOCAL_REDIRECT_URL

    oauth = OAuth2Session(CLIENT_ID, redirect_uri=redirect_url, scope='orders holdings')
    auth_url, _ = oauth.authorization_url(f'{BASE_URL}/oauth2/auth')
    return auth_url


def sasonline_oauth_login() -> dict:
    """
    One-click SASOnline OAuth2 login.
    Returns: dict with success status and message
    """
    # === HARDCODED CONFIG (Only you use this) ===
    CLIENT_ID = "SAS-CLIENT1"
    CLIENT_SECRET = "Hhtg74iYYZY1nSJUvDBxKntGqfigem6yKyYw9rlb2qSXyhEEs8BZEtw27KsIE1UI"
    BASE_URL = "https://api.stocko.in"
    TOTP_SECRET = "T4JZGOUEE2G3NOCZ"
    TOKEN_FILE = "access_token.json"
    PORT = 65015

    access_token = [None]
    shutdown_event = threading.Event()

    

    # Flask App
    app = Flask(__name__)
    app.secret_key = 'development'

    @app.route('/')
    def callback():
        try:
            oauth = OAuth2Session(CLIENT_ID, redirect_uri=LOCAL_REDIRECT_URL, scope='orders holdings')
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
        oauth = OAuth2Session(CLIENT_ID, redirect_uri=LOCAL_REDIRECT_URL, scope='orders holdings')
        auth_url, _ = oauth.authorization_url(f'{BASE_URL}/oauth2/auth')
        return redirect(auth_url)

    # Run server
    def run_server():
        app.run(host='127.0.0.1', port=PORT, debug=False, use_reloader=False)

    thread = threading.Thread(target=run_server, daemon=True)
    thread.start()
    time.sleep(1.5)  # Wait for server

    # Generate & Copy TOTP
    try:
        totp = pyotp.TOTP(TOTP_SECRET)
        code = totp.now()
        pyperclip.copy(code)
        print(f"TOTP: {code} → Copied to clipboard!")
    except:
        print("TOTP failed")

    # Open browser
    print("Opening browser...")
    webbrowser.open(f'http://127.0.0.1:{PORT}/start')

    # Wait for login
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

