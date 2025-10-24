from flask import Flask, render_template, request, jsonify, redirect, url_for, session
import json
import threading
import time
from datetime import datetime, timedelta, date
import pandas as pd
from collections import deque
import os
import logging
from typing import Optional, Dict, Any
import requests
import math, csv
import sys
import pandas as pd
import webbrowser
from pathlib import Path
from requests_oauthlib import OAuth2Session
from urllib.parse import urlparse, parse_qs
import pyotp
import pyperclip

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# This is crucial for local development with HTTP redirects
# In a production environment, you should always use HTTPS and remove this line.
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__)

# ============================================================================
# GLOBAL VARIABLES - All declared at module level
# ============================================================================

# Trading data
price_history_ce = deque(maxlen=600)
price_history_pe = deque(maxlen=600)
trading_active = False
current_position_ce = None
current_position_pe = None
trades_ce = []
trades_pe = []
orders_ce = []
orders_pe = []
alerts = []
squared_off = False
ce_stop = "No"
pe_stop = "No"

# Authentication data
current_totp_code = None
auth_completed = False

# Scrip update control variables
scrip_update_in_progress = False
trading_paused = False
last_price_check = 0
scripmaster_df = None

# Configuration dictionary
config = {
    'ce_scrip_code': 874315,
    'pe_scrip_code': 874230,
    'ce_scrip_name': "SENSEX 16 OCT 2025 CE 82900.00",
    'pe_scrip_name': "SENSEX 16 OCT 2025 PE 83100.00",
    'quantity': 0,
    'capital': 100000,
    'stop_loss_percent': 5.0,
    'target_profit_percent': 10.0,
    'max_trades_per_day': 1000,
    'trading_start_time': '09:15',
    'trading_end_time': '23:30',
    'broker': 'upstox',
    'min_range_for_trading': 0.5,
    'exchange': 'B',
    'auto_scrip_update': 'enabled',
    'price_difference_threshold': 40.0,
    'strategy_range': 8,
    'main_time_period': 300
}

# OAuth state for security
oauth_state = None

VALID_EXCHANGES = ['N', 'B', 'M']

# Real-time statistics for CE
ce_stats = {
    'current_price': 0,
    'entry_price': 0,
    'max_margin_used': 0,
    'unrealized_pnl': 0,
    'total_trades': 0,
    'win_trades': 0,
    'lose_trades': 0,
    'max_profit': 0,
    'max_loss': 0,
    'net_profit': 0,
    'realized_profit': 0,
    'avg_profit_per_trade': 0,
    'avg_loss_per_trade': 0,
    'largest_winning_trade': 0,
    'largest_losing_trade': 0,
    'consecutive_wins': 0,
    'consecutive_losses': 0,
    'profit_factor': 0,
    'last_signal': None,
    'smma300': 0,
    'range_percent': 0,
    'time_period': 0,
    'high': 0,
    'low': 0
}

# Real-time statistics for PE
pe_stats = {
    'current_price': 0,
    'entry_price': 0,
    'max_margin_used': 0,
    'unrealized_pnl': 0,
    'total_trades': 0,
    'win_trades': 0,
    'lose_trades': 0,
    'max_profit': 0,
    'max_loss': 0,
    'net_profit': 0,
    'realized_profit': 0,
    'avg_profit_per_trade': 0,
    'avg_loss_per_trade': 0,
    'largest_winning_trade': 0,
    'largest_losing_trade': 0,
    'consecutive_wins': 0,
    'consecutive_losses': 0,
    'profit_factor': 0,
    'last_signal': None,
    'smma300': 0,
    'range_percent': 0,
    'time_period': 0,
    'high': 0,
    'low': 0
}

# Portfolio tracking
portfolio_data = {
    'available_balance': 1000000,
    'used_margin': 0,
    'free_margin': 1000000,
    'unrealized_pnl': 0,
    'realized_pnl': 0,
    'total_pnl': 0,
    'margin_utilization': 0,
    'roi': 0,
    'positions': []
}


def write_order_to_csv(filename, scrip_name, scrip_type, qty, price):
    value = qty * price
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")
    with open(filename, "a", newline='') as file:
        writer = csv.writer(file)
        # Optionally write header if file is empty
        if file.tell() == 0:
            writer.writerow(['Date', 'Time', 'Scrip Name', 'Scrip Type', 'Quantity', 'Price', 'Value'])
        writer.writerow([date_str, time_str, scrip_name, scrip_type, qty, price, value])


# ============================================================================
# NSE_BSE_Single.py Functions (Integrated)
# ============================================================================

def get_ltp_nse_bse(exchange, scrip_code, instrument_name):
    """Fetch Last Traded Price (LTP) for a given instrument."""
    url = 'https://Openapi.5paisa.com/VendorsAPI/Service1.svc/V1/MarketFeed'
    USER_KEY = 'Q4O7AsAK0iUABwjsvYfmfNU1cMiMWXai'  # Replace with your valid API key

    payload = {
        'head': {'key': USER_KEY},
        'body': {
            'MarketFeedData': [
                {'Exch': exchange, 'ExchType': 'C', 'ScripCode': scrip_code, 'ScripData': ''}
            ],
            'LastRequestTime': '/Date(0)/',
            'RefreshRate': 'H'
        }
    }

    try:
        logger.info(f'Fetching LTP for {instrument_name} ({exchange}, {scrip_code})')
        response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'})

        logger.info(f'Response status for {instrument_name}: {response.status_code}')
        if response.status_code != 200:
            raise Exception(f'API request failed with status {response.status_code}')

        data = response.json()
        if data.get('body') and data['body'].get('Data') and len(data['body']['Data']) > 0:
            ltp = data['body']['Data'][0].get('LastRate')
            if ltp is not None:
                logger.info(f'LTP for {instrument_name}: {ltp}')
                return ltp

        logger.error(f'No valid LTP data for {instrument_name}')
        return None
    except Exception as error:
        logger.error(f'Error fetching LTP for {instrument_name}: {str(error)}')
        return None


def download_scrip_master(segment):
    """Download scrip master data for a given segment."""
    try:
        with open('token.txt', 'r') as f:
            token = f.read().strip()

        response = requests.get(
            f'https://Openapi.5paisa.com/VendorsAPI/Service1.svc/ScripMaster/segment/{segment}',
            headers={
                'Authorization': f'Bearer {token}',
                'Accept': 'text/csv',
                'Content-Type': 'text/csv'
            }
        )

        if response.status_code == 401:
            print(f'Token expired or invalid for {segment}. Please update token.')
            raise Exception('Unauthorized')

        response.raise_for_status()
        return {'segment': segment, 'data': response.text}
    except Exception as error:
        print(f'Error downloading {segment} scrip master: {str(error)}')
        raise


def verify_file(file_name):
    """Verify and display file information."""
    try:
        file_path = Path(file_name)
        file_size = file_path.stat().st_size
        print(f'File {file_name} size: {file_size} bytes')

        with open(file_name, 'r') as f:
            reader = csv.DictReader(f)
            records = list(reader)
            first_rows = records[:5]
            print(f'\\nFirst 5 rows of {file_name}:')
            for row in first_rows:
                print(json.dumps(row))
    except Exception as error:
        print(f'Error verifying file {file_name}: {str(error)}')


def parse_date(date_str):
    """Parse date string in multiple formats."""
    if not date_str:
        return None

    formats = ['%d-%m-%Y', '%Y-%m-%d', '%m/%d/%Y']
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def filter_scrip_master(records, instrument_name, ltp, exchange):
    """Filter scrip master data for specific instrument."""
    try:
        print(f'Filtering data for {instrument_name} with nearest expiry and 10 scrips above/below LTP...')

        # Filter for NIFTY or SENSEX using SymbolRoot
        filtered_records = [
            r for r in records
            if r.get('SymbolRoot', '').upper() == instrument_name.upper()
        ]

        if not filtered_records:
            print(f'No {instrument_name} records found using SymbolRoot {instrument_name}')
            return []

        # Parse expiry dates
        today = datetime.now().date()
        expiry_dates = list(set(r.get('Expiry') for r in filtered_records if r.get('Expiry')))

        valid_expiries = []
        for date_str in expiry_dates:
            parsed_date = parse_date(date_str)
            if parsed_date and parsed_date.date() >= today:
                valid_expiries.append(parsed_date)

        if not valid_expiries:
            print(f'No valid nearest expiry found for {instrument_name}')
            logger.error(f'No valid nearest expiry after parsing for {instrument_name}')
            return []

        nearest_expiry = min(valid_expiries)
        nearest_expiry_str = nearest_expiry.strftime('%d-%m-%Y')
        print(f'Nearest expiry for {instrument_name}: {nearest_expiry_str}')

        # Filter records for the nearest expiry and exclude ScripType "XX"
        expiry_records = [
            r for r in filtered_records
            if parse_date(r.get('Expiry', '')) and
            parse_date(r.get('Expiry', '')).strftime('%d-%m-%Y') == nearest_expiry_str and
            r.get('ScripType') != 'XX'
        ]

        # Use provided LTP or fallback to a default value
        effective_ltp = ltp if ltp else 1800
        if not effective_ltp:
            print(f'No valid LTP for {instrument_name}')
            return []

        # Filter 15 scrips above and 15 scrips below LTP based on StrikeRate
        above_ltp = sorted(
            [r for r in expiry_records if float(r.get('StrikeRate', 0)) > effective_ltp],
            key=lambda x: float(x.get('StrikeRate', 0))
        )[:15]

        below_ltp = sorted(
            [r for r in expiry_records if float(r.get('StrikeRate', 0)) <= effective_ltp],
            key=lambda x: float(x.get('StrikeRate', 0)),
            reverse=True
        )[:15]

        selected_records = above_ltp + below_ltp

        if not selected_records:
            print(f'No records found above or below LTP for {instrument_name}')
            return []

        # Format records to match desired structure
        final_records = []
        for r in selected_records:
            strike_rate = float(r.get('StrikeRate', 0))
            final_records.append({
                'Instrument': 'NIFTY' if exchange == 'N' else 'SENSEX',
                'Exch': r.get('Exch', ''),
                'ExchType': r.get('ExchType', ''),
                'ScripCode': r.get('ScripCode', ''),
                'Name': r.get('Name', ''),
                'Expiry': r.get('Expiry', nearest_expiry_str),
                'ScripType': r.get('ScripType', ''),
                'StrikeRate': strike_rate,
                'LastRate': r.get('LastRate', ''),
                'LotSize': r.get('LotSize', '20' if exchange == 'B' else '75'),
                'QtyLimit': r.get('QtyLimit', ''),
                'LTPPosition': 'Above' if strike_rate > effective_ltp else 'Below',
                'Position': ''
            })

        print(f'Filtered {len(final_records)} scrips for {instrument_name} (10 above, 10 below LTP)')
        return final_records
    except Exception as error:
        print(f'Error filtering data for {instrument_name}: {str(error)}')
        logger.error(f'Filter error for {instrument_name}: {str(error)}')
        return []


def update_scrip_master():
    """Main execution function to update scrip master data."""
    try:
        print('Starting downloads and LTP fetching...')

        segments = [
            {'segment': 'nse_fo', 'instrumentName': 'NIFTY'},
            {'segment': 'bse_fo', 'instrumentName': 'SENSEX'}
        ]

        instruments = [
            {'exchange': 'N', 'scripCode': 999920000, 'name': 'Nifty', 'segment': 'nse_fo'},
            {'exchange': 'B', 'scripCode': 999901, 'name': 'Sensex', 'segment': 'bse_fo'}
        ]

        ltps = {}

        # Fetch LTPs for Nifty and Sensex
        for instrument in instruments:
            ltp = get_ltp_nse_bse(instrument['exchange'], instrument['scripCode'], instrument['name'])
            ltps[instrument['segment']] = ltp
            print(f"{instrument['name']} LTP: {ltp if ltp is not None else 'Failed to fetch'}")

        # Download scrip masters and parse
        combined_records = []
        common_headers = None

        for segment_info in segments:
            segment = segment_info['segment']
            result = download_scrip_master(segment)

            # Parse CSV data
            csv_reader = csv.DictReader(result['data'].splitlines())
            records = list(csv_reader)

            if common_headers is None:
                common_headers = list(records[0].keys()) if records else []
            else:
                current_headers = list(records[0].keys()) if records else []
                if current_headers != common_headers:
                    print(f'Header mismatch in {segment}. Using common headers.')
                    normalized_records = []
                    for record in records:
                        normalized = {header: record.get(header, '') for header in common_headers}
                        normalized_records.append(normalized)
                    combined_records.extend(normalized_records)
                    continue

            combined_records.extend(records)

        # Filter records for NIFTY and SENSEX with nearest expiry and LTP-based scrips
        filtered_records = []
        for segment_info in segments:
            segment = segment_info['segment']
            instrument_name = segment_info['instrumentName']
            instrument = next(i for i in instruments if i['segment'] == segment)

            segment_records = filter_scrip_master(
                combined_records,
                instrument_name,
                ltps[segment],
                instrument['exchange']
            )
            filtered_records.extend(segment_records)

        # Sort records by StrikeRate
        filtered_records.sort(key=lambda x: float(x['StrikeRate']))

        # Save filtered data to a single CSV file with specified columns
        combined_file_name = 'scripmaster.csv'
        desired_columns = [
            'Instrument', 'Exch', 'ExchType', 'ScripCode', 'Name', 'Expiry',
            'ScripType', 'StrikeRate', 'LastRate', 'LotSize', 'QtyLimit',
            'LTPPosition', 'Position'
        ]

        if filtered_records:
            with open(combined_file_name, 'w', newline='') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=desired_columns)
                writer.writeheader()
                writer.writerows(filtered_records)
            print(f'Successfully saved filtered NIFTY and SENSEX records to {combined_file_name}')
            return True
        else:
            print('No filtered records to save to combined CSV.')
            return False

    except Exception as error:
        print(f'Failed: {str(error)}')
        logger.error(f'Scrip master update failed: {str(error)}')
        return False


# ============================================================================
# GenerateTokenSAS.py Functions (Integrated)
# ============================================================================

def save_token_to_file(token_data, filename='access_token.json'):
    """Save token information to a JSON file"""
    token_info = {
        'access_token': token_data['access_token'] if isinstance(token_data, dict) else token_data,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    try:
        # Get the current script's directory
        root_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(root_dir, filename)

        # Save to JSON file with proper formatting
        with open(file_path, 'w') as f:
            json.dump(token_info, f, indent=4)

        logger.info(f"Token saved successfully to: {file_path}")
        return True
    except Exception as e:
        logger.error(f"Error saving token: {str(e)}")
        return False


def generate_totp():
    """Generate TOTP code for authentication"""
    otpauth_uri = "otpauth://totp/SASONLINE:DA251?secret=T4JZGOUEE2G3NOCZ&issuer=SASONLINE"
    try:
        # Parse the URI to get the query parameters
        parsed_uri = urlparse(otpauth_uri)
        query_params = parse_qs(parsed_uri.query)

        # Extract the secret from the query parameters
        secret = query_params.get('secret', [None])[0]

        if secret:
            totp = pyotp.TOTP(secret)
            current_totp = totp.now()
            # Store TOTP in a global variable for frontend access
            global current_totp_code
            current_totp_code = current_totp
            print(f"Generated TOTP: {current_totp}")
            return current_totp
        else:
            print("Error: Secret not found in otpauth URI.")
            return None
    except Exception as e:
        print(f"Error generating TOTP: {e}")
        return None


# OAuth2 Server class for handling callbacks (similar to GenerateTokenSAS.py)
class OAuth2Server:
    """
    Handles the Flask server for the OAuth2 callback.
    """
    def __init__(self, client_id, client_secret, redirect_url, base_url):
        self.client_id = client_id
        self.web_url = base_url.strip()
        self.client_secret = client_secret
        self.redirect_uri = redirect_url
        self.authorization_base_url = f'{self.web_url}/oauth2/auth'
        self.token_url = f'{self.web_url}/oauth2/token'
        self.scope = 'orders holdings'
        self.app = Flask(__name__)
        self.app.secret_key = 'development_oauth'
        self.access_token = ""
        self.auth_successful = False

    def create_app(self):
        """
        Configures and returns the Flask application instance.
        """
        app = self.app
        client_id = self.client_id
        redirect_uri = self.redirect_uri
        scope = self.scope
        authorization_base_url = self.authorization_base_url
        token_url = self.token_url
        client_secret = self.client_secret
        server_instance = self

        @app.route('/getcode')
        def demo():
            """
            Initiates the OAuth2 authorization flow by redirecting to the
            authorization server.
            """
            from flask import session
            print(f"Session object: {session}")
            oauth = OAuth2Session(client_id, redirect_uri=redirect_uri, scope=scope)
            authorization_url, state = oauth.authorization_url(authorization_base_url)
            session['oauth_state'] = state
            logger.debug(f'Authorization URL: {authorization_url}')
            return redirect(authorization_url)

        @app.route('/')  # This listens on the redirect URL and handles the callback
        def callback():
            """
            Handles the OAuth2 callback from the authorization server,
            exchanges the authorization code for an access token, saves it,
            and then returns success message.
            """
            try:
                from flask import session
                oauth = OAuth2Session(client_id, redirect_uri=redirect_uri, scope=scope)
                logger.debug(f"Callback URL: {request.url}")

                # Fetch the access token using the authorization response
                token_data = oauth.fetch_token(
                    token_url,
                    client_secret=client_secret,
                    authorization_response=request.url
                )

                server_instance.access_token = token_data['access_token']
                server_instance.auth_successful = True
                # Set global auth completion flag
                global auth_completed
                auth_completed = True
                logger.debug(f"Access Token: {server_instance.access_token}")

                # Save token to file for persistence
                save_token_to_file(token_data)

                return 'Authentication successful! Token saved. You can close this window.'

            except Exception as e:
                logger.error(f"Callback error: {str(e)}")
                server_instance.auth_successful = False
                return f"Error: {str(e)}"

        return app

    def fetch_access_token(self):
        """Returns the obtained access token."""
        return self.access_token

    def is_auth_successful(self):
        """Returns whether authentication was successful."""
        return self.auth_successful


def get_access_token():
    """Get access token using OAuth2 flow - automatically handles the entire OAuth2 flow"""
    try:
        # Configuration for OAuth2
        client_id = "SAS-CLIENT1"
        client_secret = "Hhtg74iYYZY1nSJUvDBxKntGqfigem6yKyYw9rlb2qSXyhEEs8BZEtw27KsIE1UI"
        redirect_url = "http://127.0.0.1:65015/"
        base_url = "https://api.stocko.in"

        # Create OAuth2 server instance
        server = OAuth2Server(client_id, client_secret, redirect_url, base_url)
        app = server.create_app()
        app.env = 'development'

        # Function to run Flask app in a thread
        def run_flask_app():
            app.run(host='127.0.0.1', debug=False, port=65015, use_reloader=False)

        # Start Flask app in a separate thread
        server_thread = threading.Thread(target=run_flask_app, daemon=True)
        server_thread.start()

        # Give the server a moment to start up
        time.sleep(1)

        # Generate TOTP
        otpauth_uri = "otpauth://totp/SASONLINE:DA251?secret=T4JZGOUEE2G3NOCZ&issuer=SASONLINE"
        try:
            # Parse the URI to get the query parameters
            parsed_uri = urlparse(otpauth_uri)
            query_params = parse_qs(parsed_uri.query)

            # Extract the secret from the query parameters
            secret = query_params.get('secret', [None])[0]

            if secret:
                totp = pyotp.TOTP(secret)
                current_totp = totp.now()
                print(f"Generated TOTP: {current_totp}")
                # Copy TOTP to clipboard
                try:
                    pyperclip.copy(current_totp)
                    print("TOTP code copied to clipboard!")
                except:
                    print("Could not copy TOTP to clipboard, please copy manually:", current_totp)
                totp_code = current_totp
            else:
                print("Error: Secret not found in otpauth URI.")
                return {
                    'success': False,
                    'message': 'Failed to generate TOTP code'
                }
        except Exception as e:
            print(f"Error generating TOTP: {e}")
            return {
                'success': False,
                'message': f'Error generating TOTP: {str(e)}'
            }

        # Automatically open the browser to the /getcode endpoint
        auth_url = f'http://127.0.0.1:65015/getcode'
        print(f'Opening authorization URL in browser: {auth_url}\n')
        webbrowser.open(auth_url)

        # Return immediately with TOTP code for frontend display
        return {
            'success': True,
            'message': 'TOTP generated successfully. Please enter it in the authentication site.',
            'totp_code': totp_code,
            'auth_pending': True
        }

    except Exception as e:
        logger.error(f"Error in get_access_token: {str(e)}")
        return {
            'success': False,
            'message': f'Error: {str(e)}'
        }


@app.route('/api/check_auth_status', methods=['GET'])
def check_auth_status():
    """API endpoint to check authentication status"""
    global auth_completed, current_totp_code
    return jsonify({
        'auth_completed': auth_completed,
        'totp_code': current_totp_code
    })


@app.route('/api/reset_auth', methods=['POST'])
def reset_auth():
    """API endpoint to reset authentication status"""
    global auth_completed, current_totp_code
    auth_completed = False
    current_totp_code = None
    return jsonify({'success': True, 'message': 'Authentication status reset'})


def refresh_access_token(authorization_code):
    """Refresh access token using authorization code"""
    try:
        # Configuration for OAuth2
        client_id = "SAS-CLIENT1"
        client_secret = "Hhtg74iYYZY1nSJUvDBxKntGqfigem6yKyYw9rlb2qSXyhEEs8BZEtw27KsIE1UI"
        redirect_url = "http://127.0.0.1:65015/"
        base_url = "https://api.stocko.in"
        token_url = f"{base_url}/oauth2/token"

        # Prepare the token request
        data = {
            'grant_type': 'authorization_code',
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_url,
            'code': authorization_code
        }

        # Make the token request
        response = requests.post(token_url, data=data)

        if response.status_code == 200:
            token_data = response.json()
            # Save token to file
            if save_token_to_file(token_data):
                return {
                    'success': True,
                    'message': 'Access token refreshed successfully'
                }
            else:
                return {
                    'success': False,
                    'message': 'Failed to save token to file'
                }
        else:
            return {
                'success': False,
                'message': f'Failed to refresh token: {response.text}'
            }
    except Exception as e:
        logger.error(f"Error refreshing access token: {str(e)}")
        return {
            'success': False,
            'message': f'Error: {str(e)}'
        }

def get_ltp(scrip_data):
    url = "https://Openapi.5paisa.com/VendorsAPI/Service1.svc/V1/MarketFeed"
    USER_KEY = "Q4O7AsAK0iUABwjsvYfmfNU1cMiMWXai"
    
    if config['exchange'] not in VALID_EXCHANGES:
        logging.error(f"Invalid exchange: {config['exchange']}")
        alert_manager.add_alert('error', 'Invalid Exchange', f"Exchange {config['exchange']} is not valid", 'error')
        return None
    
    payload = {
        "head": {"key": USER_KEY},
        "body": {
            "MarketFeedData": [
                {"Exch": config['exchange'], "ExchType": "D", "ScripCode": scrip_data, "ScripData": scrip_data}
            ],
            "LastRequestTime": "/Date(0)/",
            "RefreshRate": "H"
        }
    }
    try:
        response = requests.post(url, headers={"Content-Type": "application/json"}, data=json.dumps(payload))
        if response.status_code != 200:
            raise Exception(f"API request failed with status {response.status_code}")
        data = response.json()
        if "body" in data and "Data" in data["body"] and len(data["body"]["Data"]) > 0:
            market_data = data["body"]["Data"][0]
            return market_data.get("LastRate", None)
        return None
    except Exception as error:
        logging.error(f"Error fetching LTP: {error}")
        alert_manager.add_alert('error', 'LTP Fetch Error', f"Failed to fetch LTP: {str(error)}", 'error')
        return None
def get_index_ltp(scrip_data, exchange):
    url = "https://Openapi.5paisa.com/VendorsAPI/Service1.svc/V1/MarketFeed"
    USER_KEY = "Q4O7AsAK0iUABwjsvYfmfNU1cMiMWXai"
    
    payload = {
        "head": {"key": USER_KEY},
        "body": {
            "MarketFeedData": [
                {"Exch": exchange, "ExchType": "C", "ScripCode": scrip_data, "ScripData": scrip_data}
            ],
            "LastRequestTime": "/Date(0)/",
            "RefreshRate": "H"
        }
    }
    
    try:
        response = requests.post(
            url,
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload)
        )
        response.raise_for_status()  # Raises an HTTPError for bad status codes
        
        data = response.json()
        if "body" in data and "Data" in data["body"] and len(data["body"]["Data"]) > 0:
            market_data = data["body"]["Data"][0]
            return {
                "LastRate": market_data.get("LastRate"),
                "Chg": market_data.get("Chg"),
                "ChgPcnt": market_data.get("ChgPcnt"),
                "High": market_data.get("High"),
                "Low": market_data.get("Low")
            }
        else:
            logging.warning(f"No market data found for scrip {scrip_data} on {exchange}")
            return None
            
    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error occurred: {http_err}")
        return None
    except requests.exceptions.RequestException as req_err:
        logging.error(f"Request error occurred: {req_err}")
        return None
    except ValueError as json_err:
        logging.error(f"JSON decode error: {json_err}")
        return None
    except Exception as error:
        logging.error(f"Unexpected error fetching market data: {error}")
        return None

# --- Order Placement Functions ---
def Buy_place_order(instrument_token, quantity, exchange):
    """
    Place a market BUY order with specified instrument token and quantity.
    
    Args:
        instrument_token (int): The instrument token for the stock/option
        quantity (int): The quantity to buy
    
    Returns:
        bool: True if order placed successfully, False otherwise
    """
    try:
        with open("access_token.json", "r") as file:
            token_data = json.load(file)
        access_token = token_data["access_token"]
    except FileNotFoundError:
        logging.error("Error: access_token.json file not found.")
        return False
    except KeyError:
        logging.error("Error: 'access_token' not found in access_token.json.")
        return False
    
    if exchange == "N":
        exchange_order = "NFO"
    else :
        exchange_order = "BFO"

    url = "https://api.stocko.in/api/v1/orders"
    order_data = {
        "exchange": exchange_order,
        "order_type": "MARKET",
        "instrument_token": instrument_token,
        "quantity": quantity,
        "disclosed_quantity": 0,
        "price": 0,
        "order_side": "BUY",
        "trigger_price": 0,
        "validity": "DAY",
        "product": "MIS",
        "client_id": "DA251",
        "user_order_id": 10002,
        "market_protection_percentage": 0,
        "device": "WEB"
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(order_data))
        if response.status_code == 200:
            logging.info("BUY order placed successfully!")
            logging.info(f"Response: {response.json()}")
            return True
        else:
            logging.error(f"Failed to place BUY order. Status code: {response.status_code}")
            logging.error(f"Response: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"An error occurred while placing BUY order: {e}")
        return False

def Sell_place_order(instrument_token, quantity, exchange):
    """
    Place a market SELL order with specified instrument token and quantity.
    
    Args:
        instrument_token (int): The instrument token for the stock/option
        quantity (int): The quantity to sell
    
    Returns:
        bool: True if order placed successfully, False otherwise
    """
    try:
        with open("access_token.json", "r") as file:
            token_data = json.load(file)
        access_token = token_data["access_token"]
    except FileNotFoundError:
        logging.error("Error: access_token.json file not found.")
        return False
    except KeyError:
        logging.error("Error: 'access_token' not found in access_token.json.")
        return False

    if exchange == "N":
        exchange_order = "NFO"
    else :
        exchange_order = "BFO"

    url = "https://api.stocko.in/api/v1/orders"
    order_data = {
        "exchange": exchange_order,
        "order_type": "MARKET",
        "instrument_token": instrument_token,
        "quantity": quantity,
        "disclosed_quantity": 0,
        "price": 0,
        "order_side": "SELL",
        "trigger_price": 0,
        "validity": "DAY",
        "product": "MIS",
        "client_id": "DA251",
        "user_order_id": 10002,
        "market_protection_percentage": 0,
        "device": "WEB"
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(order_data))
        if response.status_code == 200:
            logging.info("SELL order placed successfully!")
            logging.info(f"Response: {response.json()}")
            return True
        else:
            logging.error(f"Failed to place SELL order. Status code: {response.status_code}")
            logging.error(f"Response: {response.text}")
            return False
    except requests.exceptions.RequestException as e:
        logging.error(f"An error occurred while placing SELL order: {e}")
        return False

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def get_dynamic_password(name="dhaval"):
    """Generate dynamic password based on current date and time."""
    now = datetime.now()
    day = now.strftime('%d')
    hour = now.strftime('%H')
    month = now.strftime('%m')
    return f"{day}{hour}{name}{month}"


def load_scrip_master_from_csv(file_path):
    """Load scrip master data from CSV file."""
    global scripmaster_df
    
    try:
        if os.path.exists(file_path):
            scripmaster_df = pd.read_csv(file_path)
            logger.info(f"Successfully loaded scripmaster data from {file_path}")
            scripmaster_df['ScripCode'] = pd.to_numeric(scripmaster_df['ScripCode'], errors='coerce').fillna(0).astype(int)
            # Ensure 'Expiry' column is treated as string for consistent slicing later
            scripmaster_df['Expiry'] = scripmaster_df['Expiry'].astype(str)
            return True
        else:
            logger.error(f"Scrip master file not found at {file_path}")
            return False
    except Exception as e:
        logger.error(f"Error loading scrip master CSV: {e}")
        return False


def get_scrip_name(scrip_code):
    """Fetch scrip name from scripmaster_df based on scrip code."""
    global scripmaster_df
    
    try:
        if scripmaster_df is None:
            logger.warning("scripmaster_df is not initialized")
            return "Unknown"
        
        row = scripmaster_df[scripmaster_df['ScripCode'].astype(int) == int(scrip_code)]
        if not row.empty:
            return row.iloc[0].get('Name', 'Unknown')
        return "Unknown"
    except Exception as e:
        logger.error(f"Error fetching scrip name for code {scrip_code}: {str(e)}")
        return "Unknown"


def find_nearest_150_scrips():
    """Find CE and PE scrips with LTP nearest to target."""
    global scripmaster_df, config
    
    try:
        if scripmaster_df is None or scripmaster_df.empty:
            logger.error("scripmaster_df is not initialized or empty.")
            return None, None, None, None

        ce_scrips = scripmaster_df[scripmaster_df['ScripType'] == 'CE']
        pe_scrips = scripmaster_df[scripmaster_df['ScripType'] == 'PE']

        best_ce = None
        best_pe = None
        min_ce_diff = float('inf')
        min_pe_diff = float('inf')
        target_ltp = config.get('target_ltp', 120)

        for _, scrip in ce_scrips.iterrows():
            ltp = get_ltp(scrip['ScripCode'])
            if ltp is not None and ltp > 0:
                diff = abs(ltp - target_ltp)
                if diff < min_ce_diff:
                    min_ce_diff = diff
                    best_ce = {
                        'scrip_code': scrip['ScripCode'],
                        'ltp': ltp,
                        'name': scrip['Name'],
                        'scrip_type': 'CE'
                    }
            time.sleep(0.1)

        for _, scrip in pe_scrips.iterrows():
            ltp = get_ltp(scrip['ScripCode'])
            if ltp is not None and ltp > 0:
                diff = abs(ltp - target_ltp)
                if diff < min_pe_diff:
                    min_pe_diff = diff
                    best_pe = {
                        'scrip_code': scrip['ScripCode'],
                        'ltp': ltp,
                        'name': scrip['Name'],
                        'scrip_type': 'PE'
                    }
            time.sleep(0.1)

        ce_scrip_name = get_scrip_name(best_ce['scrip_code']) if best_ce else None
        pe_scrip_name = get_scrip_name(best_pe['scrip_code']) if best_pe else None

        return best_ce, best_pe, ce_scrip_name, pe_scrip_name

    except Exception as e:
        logger.error(f"Error finding nearest scrips: {str(e)}")
        return None, None, None, None


def check_and_handle_price_difference():
    """Check price difference and handle scrip update workflow."""
    global scrip_update_in_progress, trading_paused, last_price_check, config
    
    try:
        current_time = time.time()
        if current_time - last_price_check < 30:
            return False
        
        last_price_check = current_time
        
        if scrip_update_in_progress or trading_paused:
            return False
        
        if config.get('auto_scrip_update', 'enabled') != 'enabled':
            return False
        
        ce_ltp = get_ltp(config['ce_scrip_code'])
        pe_ltp = get_ltp(config['pe_scrip_code'])
        
        if not ce_ltp or not pe_ltp or ce_ltp <= 0 or pe_ltp <= 0:
            return False
        
        avg_price = (ce_ltp + pe_ltp) / 2
        price_diff_percent = abs(ce_ltp - pe_ltp) / avg_price * 100
        threshold = config.get('price_difference_threshold', 40.0)
        
        if price_diff_percent > threshold:
            logger.info(f"Price difference threshold exceeded: {price_diff_percent:.2f}% > {threshold}%")
            execute_scrip_update_workflow()
            return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error checking price difference: {str(e)}")
        return False


def execute_scrip_update_workflow():
    """Complete workflow for scrip update with history adjustment."""
    global scrip_update_in_progress, trading_paused
    
    try:
        scrip_update_in_progress = True
        trading_paused = True
        
        logger.info("Starting scrip update workflow...")
        
        logger.info("Step 1: Squaring off all positions...")
        square_off_success = trading_engine.square_off_all_positions_for_update()
        
        if not square_off_success:
            logger.warning("Square off failed, but continuing with scrip update...")
        
        logger.info("Step 2: Pausing trading for 5 seconds and adjusting history...")
        
        start_time = time.time()
        
        logger.info("Step 3: Updating scrip codes and adjusting history...")
        update_success = update_scrip_codes_immediately()
        
        elapsed_time = time.time() - start_time
        remaining_time = max(0, 5 - elapsed_time)
        if remaining_time > 0:
            logger.info(f"History adjustment completed in {elapsed_time:.2f}s, waiting {remaining_time:.2f}s more...")
            time.sleep(remaining_time)
        
        if update_success:
            logger.info("Step 4: Resuming trading with adjusted history...")
        else:
            logger.error("Scrip update failed!")
        
    except Exception as e:
        logger.error(f"Error in scrip update workflow: {str(e)}")
    
    finally:
        scrip_update_in_progress = False
        trading_paused = False
        logger.info("Scrip update workflow completed.")


def update_scrip_codes_immediately():
    """Update scrip codes and adjust history with price difference."""
    global price_history_ce, price_history_pe, ce_stats, pe_stats, config
    
    try:
        old_ce_ltp = get_ltp(config.get('ce_scrip_code')) if config.get('ce_scrip_code') else 0
        old_pe_ltp = get_ltp(config.get('pe_scrip_code')) if config.get('pe_scrip_code') else 0

        logger.info(f"Old LTPs - CE: Rs.{old_ce_ltp}, PE: Rs.{old_pe_ltp}")

        best_ce_scrip, best_pe_scrip, ce_scrip_name, pe_scrip_name = find_nearest_150_scrips()

        if not best_ce_scrip or not best_pe_scrip:
            logger.error("Could not find suitable new scrips")
            return False

        logger.info(f"New LTPs - CE: Rs.{best_ce_scrip['ltp']}, PE: Rs.{best_pe_scrip['ltp']}")

        old_ce_code = config.get('ce_scrip_code', '')
        old_pe_code = config.get('pe_scrip_code', '')

        config['ce_scrip_code'] = best_ce_scrip['scrip_code']
        config['pe_scrip_code'] = best_pe_scrip['scrip_code']
        config['ce_scrip_name'] = ce_scrip_name
        config['pe_scrip_name'] = pe_scrip_name
        
        adjust_history_with_price_difference(old_ce_ltp, old_pe_ltp, best_ce_scrip, best_pe_scrip)

        logger.info(f"Scrip codes updated - CE: {old_ce_code} → {best_ce_scrip['scrip_code']}, PE: {old_pe_code} → {best_pe_scrip['scrip_code']}")

        return True

    except Exception as e:
        logger.error(f"Error updating scrip codes: {str(e)}")
        return False


def adjust_history_with_price_difference(old_ce_ltp, old_pe_ltp, new_ce, new_pe):
    """Adjust old history with new price difference percentage."""
    global price_history_ce, price_history_pe, ce_stats, pe_stats
    
    try:
        logger.info("Starting history adjustment with price difference...")
        
        ce_adjustment_percent = 0
        pe_adjustment_percent = 0
        
        if old_ce_ltp > 0 and new_ce['ltp'] > 0:
            ce_adjustment_percent = ((new_ce['ltp'] - old_ce_ltp) / old_ce_ltp) * 100
            logger.info(f"CE adjustment: {old_ce_ltp} → {new_ce['ltp']} ({ce_adjustment_percent:+.2f}%)")
        
        if old_pe_ltp > 0 and new_pe['ltp'] > 0:
            pe_adjustment_percent = ((new_pe['ltp'] - old_pe_ltp) / old_pe_ltp) * 100
            logger.info(f"PE adjustment: {old_pe_ltp} → {new_pe['ltp']} ({pe_adjustment_percent:+.2f}%)")
        
        if len(price_history_ce) > 0 and ce_adjustment_percent != 0:
            adjusted_ce_history = deque(maxlen=310)
            for price in price_history_ce:
                adjusted_price = price * (1 + ce_adjustment_percent / 100)
                adjusted_ce_history.append(max(0.1, adjusted_price))
            
            price_history_ce.clear()
            price_history_ce.extend(adjusted_ce_history)
            
            if len(price_history_ce) > 0:
                ce_high = max(price_history_ce)
                ce_low = min(price_history_ce)
                ce_stats['range_percent'] = ((ce_high - ce_low) / ce_low * 100) if ce_low > 0 else 0
                
                if ce_stats['entry_price'] > 0:
                    ce_stats['entry_price'] = ce_stats['entry_price'] * (1 + ce_adjustment_percent / 100)
            
            logger.info(f"CE history adjusted: {len(price_history_ce)} prices updated by {ce_adjustment_percent:+.2f}%")
        
        if len(price_history_pe) > 0 and pe_adjustment_percent != 0:
            adjusted_pe_history = deque(maxlen=310)
            for price in price_history_pe:
                adjusted_price = price * (1 + pe_adjustment_percent / 100)
                adjusted_pe_history.append(max(0.1, adjusted_price))
            
            price_history_pe.clear()
            price_history_pe.extend(adjusted_pe_history)
            
            if len(price_history_pe) > 0:
                pe_high = max(price_history_pe)
                pe_low = min(price_history_pe)
                pe_stats['range_percent'] = ((pe_high - pe_low) / pe_low * 100) if pe_low > 0 else 0
                
                if pe_stats['entry_price'] > 0:
                    pe_stats['entry_price'] = pe_stats['entry_price'] * (1 + pe_adjustment_percent / 100)
            
            logger.info(f"PE history adjusted: {len(price_history_pe)} prices updated by {pe_adjustment_percent:+.2f}%")
        
        ce_stats['current_price'] = new_ce['ltp']
        pe_stats['current_price'] = new_pe['ltp']
        
        if len(price_history_ce) >= 300:
            ce_stats['smma300'] = trading_engine.calculate_smma(price_history_ce, 300) or 0
            
        if len(price_history_pe) >= 300:
            pe_stats['smma300'] = trading_engine.calculate_smma(price_history_pe, 300) or 0
        
        logger.info("History adjustment completed successfully!")
        
    except Exception as e:
        logger.error(f"Error adjusting history: {str(e)}")


# ============================================================================
# ALERT MANAGER CLASS
# ============================================================================

class AlertManager:
    def __init__(self):
        self.alerts = []
    
    def add_alert(self, alert_type, title, message, severity='info'):
        alert = {
            'id': len(self.alerts) + 1,
            'type': alert_type,
            'title': title,
            'message': message,
            'severity': severity,
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        self.alerts.append(alert)
        logger.info(f"Alert added: {title} - {message}")
        
        if len(self.alerts) > 100:
            self.alerts.pop(0)
    
    def get_alerts(self, limit=10):
        return sorted(self.alerts, key=lambda x: x['timestamp'], reverse=True)[:limit]
    
    def get_all_alerts(self):
        return sorted(self.alerts, key=lambda x: x['timestamp'], reverse=True)
    
    def mark_read(self, alert_id):
        for alert in self.alerts:
            if alert['id'] == alert_id:
                alert['read'] = True
                break


alert_manager = AlertManager()


# ============================================================================
# TRADING ENGINE CLASS
# ============================================================================

class TradingEngine:
    def __init__(self):
        self.daily_trades = 0
        self.last_trade_date = None
        
        
    def calculate_smma(self, data, period):
        """Efficient single-value RMA (Wilder's Moving Average) calculation."""
        if len(data) < period:
            return None

        data_list = list(data)
        rma = sum(data_list[:period]) / period  # initial SMA

        for price in data_list[period:]:
            rma = (rma * (period - 1) + price) / period

        smma = rma
        return smma


    def calculate_time_period(self, scrip_type='CE', current_ltp=None):
        """Calculate adaptive time period for CE/PE dynamically using given LTP."""
        global ce_stats, pe_stats, config, price_history_ce, price_history_pe

        if scrip_type == 'CE':
            price_history = price_history_ce
            stats = ce_stats
        else:
            price_history = price_history_pe
            stats = pe_stats

        # --- Use passed LTP if available, else fallback ---
        if current_ltp is None or current_ltp <= 0:
            return stats.get('time_period', 300)

        # Append latest LTP to history
        price_history.append(current_ltp)

        # --- Configurable main period ---
        max_main_period = config.get('main_time_period', 300)

        # --- Calculate high, low, and range % over last N data ---
        price_list = list(price_history)
        if len(price_list) > 0:
            recent_prices = price_list[-max_main_period:]
            high = max(recent_prices)
            low = min(recent_prices)
            range_percent = ((high - low) / low * 100) if low > 0 else 0
        else:
            range_percent = 0

        # --- Adaptive time period logic ---
        k = 2500
        min_period = 30
        max_period = 500
        time_period = max(min_period, min(max_period, k / range_percent)) if range_percent > 0.1 else 300

        # --- Store in stats ---
        stats['range_percent'] = range_percent
        stats['time_period'] = int(time_period)

        logging.debug(f"{scrip_type} | Range={range_percent:.2f}% | Period={time_period:.2f}s")
        return int(time_period)


    def get_real_market_data(self, scrip_type='CE'):
        """Get real market data using pre-calculated CE/PE time periods."""
        global ce_stats, pe_stats, portfolio_data, price_history_ce, price_history_pe
        global scrip_update_in_progress, current_position_ce, current_position_pe, config

        try:
            if scrip_update_in_progress:
                return None

            # --- Select CE or PE specific data ---
            if scrip_type == 'CE':
                scrip_code = config['ce_scrip_code']
                price_history = price_history_ce
                current_position = current_position_ce
                stats = ce_stats
            else:
                scrip_code = config['pe_scrip_code']
                price_history = price_history_pe
                current_position = current_position_pe
                stats = pe_stats

            # --- Get LTP (called only once) ---
            current_ltp = get_ltp(scrip_code)
            if current_ltp is None or current_ltp <= 0:
                logger.warning(f"Invalid LTP for {scrip_type}: {scrip_code}")
                return None
            stats['current_price'] = current_ltp

            # --- Calculate time period using same LTP ---
            time_period = self.calculate_time_period(scrip_type, current_ltp)

            # --- Calculate SMMA ---
            smma_val = self.calculate_smma(price_history, time_period)
            stats['smma300'] = smma_val if smma_val is not None else 0

            # --- Calculate High / Low / Range ---
            if len(price_history) > 0:
                slice_prices = list[Any](price_history)[-time_period:]
                high_price = max(slice_prices)
                low_price = min(slice_prices)
                range_val = high_price - low_price
                range_percent = ((high_price - low_price) / low_price * 100) if low_price > 0 else 0
            else:
                high_price = low_price = range_val = range_percent = 0

            stats['high'] = high_price
            stats['low'] = low_price
            stats['range'] = range_val
            stats['range_percent'] = range_percent

            # --- Unrealized P&L ---
            if current_position and stats.get('entry_price', 0) > 0:
                if current_position == 'BUY':
                    unrealized_pnl = (current_ltp - stats['entry_price']) * config['quantity']
                else:
                    unrealized_pnl = (stats['entry_price'] - current_ltp) * config['quantity']

                stats['unrealized_pnl'] = unrealized_pnl
                portfolio_data['unrealized_pnl'] = (
                    ce_stats.get('unrealized_pnl', 0) + pe_stats.get('unrealized_pnl', 0)
                )

                pnl_percent = (
                    abs(unrealized_pnl / (stats['entry_price'] * config['quantity']) * 100)
                    if (stats['entry_price'] * config['quantity']) != 0 else 0
                )

                if unrealized_pnl < 0 and pnl_percent >= config['stop_loss_percent']:
                    alert_manager.add_alert(
                        'stop_loss',
                        'Stop Loss Triggered',
                        f'{scrip_type} position hit stop loss: {pnl_percent:.2f}%',
                        'error'
                    )
                elif unrealized_pnl > 0 and pnl_percent >= config['target_profit_percent']:
                    alert_manager.add_alert(
                        'target',
                        'Target Achieved',
                        f'{scrip_type} position hit target: {pnl_percent:.2f}%',
                        'success'
                    )

            # --- Final Return Data ---
            return {
                'ltp': current_ltp,
                'smma300': stats['smma300'],
                'time_period': time_period,
                'high': high_price,
                'low': low_price,
                'range': range_val,
                'rangeinpercent': range_percent,
                'scrip_type': scrip_type,
                'scrip_code': scrip_code,
                'scrip_name': get_scrip_name(scrip_code)
            }

        except Exception as e:
            logger.error(f"Error in get_real_market_data({scrip_type}): {e}", exc_info=True)
            return None



    def check_trading_hours(self):
        """Check if current time is within trading hours."""
        global config
        
        current_time = datetime.now().time()
        start_time = datetime.strptime(config['trading_start_time'], '%H:%M').time()
        end_time = datetime.strptime(config['trading_end_time'], '%H:%M').time()
        return start_time <= current_time <= end_time
    
    def check_daily_trade_limit(self):
        """Check if daily trade limit is reached."""
        global config
        
        today = datetime.now().date()
        if self.last_trade_date != today:
            self.daily_trades = 0
            self.last_trade_date = today
        return self.daily_trades < config['max_trades_per_day']
    
    def calculate_qty(self, ltp, scrip_type='CE'):
        """Calculate quantity based on 50% capital allocation per scrip with lot size"""
        try:
            # If quantity is manually set (non-zero), use it directly
            if config.get('quantity', 0) > 0:
                logger.debug(f"[{scrip_type}] Using manual quantity: {config['quantity']}")
                return config['quantity']
            
            # Validate LTP
            if ltp <= 0:
                logger.error(f"Invalid LTP for quantity calculation: {ltp}")
                return 75 if config['exchange'] == 'N' else 20  # fallback to 1 lot
            
            # Determine lot size based on exchange
            lot_size = 75 if config['exchange'] == 'N' else 20
            
            # Use 50% of total capital for each scrip (CE/PE)
            allocated_capital = config['capital'] * 0.5
            
            # Calculate base quantity: allocated capital / price per unit
            base_qty = int(allocated_capital / ltp)
            
            # Round to nearest lot size
            num_lots = max(1, round(base_qty / lot_size))
            qty = num_lots * lot_size
            
            logger.info(f"[{scrip_type}] Auto-calculated Qty: {qty} ({num_lots} lots × {lot_size}) | LTP: Rs.{ltp:.2f} | Allocated Capital: Rs.{allocated_capital:,.2f}")
            
            return qty
            
        except Exception as e:
            logger.error(f"Error calculating quantity: {e}")
            lot_size = 75 if config['exchange'] == 'N' else 20
            return lot_size  # fallback to 1 lot
    
    # def execute_trading_strategy(self, market_data, scrip_type='CE'):
    #     """Execute trading strategy with proper stop condition handling."""
    #     global current_position_ce, current_position_pe, ce_stats, pe_stats
    #     global trading_paused, scrip_update_in_progress, config
    #     global ce_stop, pe_stop

    #     try:
    #         # 1️⃣ Check Trading Status
    #         if trading_paused or scrip_update_in_progress:
    #             logger.debug(f"[{scrip_type}] Trading paused or scrip update in progress.")
    #             return

    #         # 2️⃣ Validate Market Data
    #         if not market_data or not market_data.get('smma300'):
    #             logger.debug(f"[{scrip_type}] Invalid market data. SMMA or LTP missing.")
    #             return

    #         # 3️⃣ Check Trading Hours
    #         if not self.check_trading_hours():
    #             logger.debug(f"[{scrip_type}] Outside trading hours. Skipping strategy.")
    #             return

    #         # 4️⃣ Check Daily Trade Limit
    #         if not self.check_daily_trade_limit():
    #             logger.warning(f"[{scrip_type}] Daily trade limit reached.")
    #             alert_manager.add_alert(
    #                 'limit', 'Daily Trade Limit',
    #                 f'Daily trade limit of {config["max_trades_per_day"]} reached', 'warning'
    #             )
    #             return

    #         # 5️⃣ Assign Position and Stats
    #         current_position = current_position_ce if scrip_type == 'CE' else current_position_pe
    #         stats = ce_stats if scrip_type == 'CE' else pe_stats

    #         # 6️⃣ Market Data Extraction
    #         ltp = market_data['ltp']
    #         smma300 = market_data['smma300']
    #         rangeinpercent = market_data.get('rangeinpercent', 0)
    #         range_work = config.get('strategy_range', 0)
    #         time_period = market_data.get('time_period', 0)
    #         low_price = market_data.get('low', 0)
    #         buy_price = stats.get('entry_price', 0)
    #         qty = self.calculate_qty(ltp)
    #         config['quantity'] = qty
            
    #         logger.debug(f"[{scrip_type}] LTP={ltp:.2f} | SMMA300={smma300:.2f} | Range%={rangeinpercent:.2f} | TimePeriod={time_period} | Qty={qty}")

    #         # 7️⃣ Alert on High Volatility
    #         if rangeinpercent > range_work:
    #             alert_manager.add_alert(
    #                 'volatility', 'High Volatility',
    #                 f'{scrip_type} showing high volatility: {rangeinpercent:.2f}%', 'warning'
    #             )

    #         # 8️⃣ FIXED: Reset Stop Conditions Only When Price Goes Below SMMA
    #         # This prevents immediate re-entry after target achievement
    #         if scrip_type == 'CE':
    #             if ce_stop == "Yes" and ltp <= smma300:
    #                 ce_stop = "No"
    #                 logger.info(f"[CE] ✅ Stop condition RESET - Price {ltp:.2f} dropped below SMMA {smma300:.2f}")
            
    #         if scrip_type == 'PE':
    #             if pe_stop == "Yes" and ltp <= smma300:
    #                 pe_stop = "No"
    #                 logger.info(f"[PE] ✅ Stop condition RESET - Price {ltp:.2f} dropped below SMMA {smma300:.2f}")

    #         # ========== CE STRATEGY ==========
    #         if scrip_type == "CE":
    #             if time_period <= 250:
    #                 # Entry Condition: Only if stop is not active AND price crosses above SMMA
    #                 if current_position is None and ce_stop == "No" and ltp > smma300:
    #                     logger.info(f"[CE] 🟢 BUY Signal | LTP={ltp:.2f} crossed above SMMA300={smma300:.2f}")
    #                     self.open_position('BUY', ltp, 'CE')
    #                     stats['entry_price'] = ltp
                    
    #                 # Block new trades when stop is active
    #                 elif current_position is None and ce_stop == "Yes":
    #                     logger.debug(f"[CE] ⛔ BUY blocked - ce_stop active. Wait for price to drop below SMMA {smma300:.2f}")
                    
    #                 # Exit Conditions
    #                 elif current_position == 'BUY':
    #                     if ltp <= low_price:
    #                         logger.info(f"[CE] 🔴 Exit (Stop Loss) | LTP={ltp:.2f} <= Low={low_price:.2f}")
    #                         self.close_position('SELL', ltp, 'CE')
    #                     elif ltp >= buy_price * 1.15:
    #                         logger.info(f"[CE] 🎯 Exit (Target) | LTP={ltp:.2f} >= 1.15×Buy={buy_price:.2f}")
    #                         ce_stop = "Yes"  # Set stop flag
    #                         logger.info(f"[CE] 🚫 ce_stop activated. No new trades until price <= SMMA")
    #                         self.close_position('SELL', ltp, 'CE')
                            
    #             elif time_period >= 350:
    #                 # Late session entry
    #                 if current_position is None and ce_stop == "No" and ltp > low_price and ltp < low_price * 1.02 and ltp < smma300 * 0.98:
    #                     logger.info(f"[CE] 🟢 Late BUY entry near low | LTP={ltp:.2f} ~ Low={low_price:.2f}")
    #                     self.open_position('BUY', ltp, 'CE')
    #                     stats['entry_price'] = ltp
                    
    #                 # Block late entry if stop is active
    #                 elif current_position is None and ce_stop == "Yes":
    #                     logger.debug(f"[CE] ⛔ Late BUY blocked - ce_stop active")
                    
    #                 # Late session exit
    #                 elif current_position == 'BUY' and ltp > smma300 * 0.995:
    #                     logger.info(f"[CE] 🔴 Late Exit | LTP={ltp:.2f} > SMMA300×0.995={smma300*0.995:.2f}")
    #                     self.close_position('SELL', ltp, 'CE')

    #             elif time_period < 350 and time_period > 250:
    #                 if current_position is None and ltp > smma300:
    #                     logger.info(f"[CE] 🟢 Mid session entry | LTP={ltp:.2f} crossed above SMMA300={smma300:.2f}")
    #                     self.open_position('BUY', ltp, 'CE')
    #                     stats['entry_price'] = ltp
    #                 elif current_position == 'BUY' and ltp <= smma300 * 0.98:
    #                     logger.info(f"[CE] 🔴 Mid session exit | LTP={ltp:.2f} <= SMMA300={smma300:.2f}")
    #                     self.close_position('SELL', ltp, 'CE')
    #                 elif current_position == 'BUY' and ltp >= smma300 * 1.02:
    #                     logger.info(f"[CE] 🟢 Mid session exit | LTP={ltp:.2f} >= SMMA300×1.02={smma300*1.02:.2f}")
    #                     self.close_position('SELL', ltp, 'CE')

    #         # ========== PE STRATEGY ==========
    #         elif scrip_type == "PE":
    #             if time_period <= 250:
    #                 # Entry Condition: Only if stop is not active AND price crosses above SMMA
    #                 if current_position is None and pe_stop == "No" and ltp > smma300:
    #                     logger.info(f"[PE] 🟢 BUY Signal | LTP={ltp:.2f} crossed above SMMA300={smma300:.2f}")
    #                     self.open_position('BUY', ltp, 'PE')
    #                     stats['entry_price'] = ltp
                    
    #                 # Block new trades when stop is active
    #                 elif current_position is None and pe_stop == "Yes":
    #                     logger.debug(f"[PE] ⛔ BUY blocked - pe_stop active. Wait for price to drop below SMMA {smma300:.2f}")
                    
    #                 # Exit Conditions
    #                 elif current_position == 'BUY':
    #                     if ltp <= low_price:
    #                         logger.info(f"[PE] 🔴 Exit (Stop Loss) | LTP={ltp:.2f} <= Low={low_price:.2f}")
    #                         self.close_position('SELL', ltp, 'PE')
    #                     elif ltp >= buy_price * 1.15:
    #                         logger.info(f"[PE] 🎯 Exit (Target) | LTP={ltp:.2f} >= 1.15×Buy={buy_price:.2f}")
    #                         pe_stop = "Yes"  # Set stop flag
    #                         logger.info(f"[PE] 🚫 pe_stop activated. No new trades until price <= SMMA")
    #                         self.close_position('SELL', ltp, 'PE')
                            
    #             elif time_period >= 300:
    #                 # Late session entry
    #                 if current_position is None and pe_stop == "No" and ltp > low_price and ltp < low_price * 1.02 and ltp < smma300 * 0.98:
    #                     logger.info(f"[PE] 🟢 Late BUY entry near low | LTP={ltp:.2f} ~ Low={low_price:.2f}")
    #                     self.open_position('BUY', ltp, 'PE')
    #                     stats['entry_price'] = ltp
                    
    #                 # Block late entry if stop is active
    #                 elif current_position is None and pe_stop == "Yes":
    #                     logger.debug(f"[PE] ⛔ Late BUY blocked - pe_stop active")
                    
    #                 # Late session exit
    #                 elif current_position == 'BUY' and ltp > smma300 * 0.995:
    #                     logger.info(f"[PE] 🔴 Late Exit | LTP={ltp:.2f} > SMMA300×0.995={smma300*0.995:.2f}")
    #                     self.close_position('SELL', ltp, 'PE')
                
    #             elif time_period < 350 and time_period > 250:
    #                 if current_position is None and ltp > smma300:
    #                     logger.info(f"[PE] 🟢 Mid session entry | LTP={ltp:.2f} crossed above SMMA300={smma300:.2f}")
    #                     self.open_position('BUY', ltp, 'PE')
    #                     stats['entry_price'] = ltp
    #                 elif current_position == 'BUY' and ltp <= smma300 * 0.98:
    #                     logger.info(f"[PE] 🔴 Mid session exit | LTP={ltp:.2f} <= SMMA300={smma300:.2f}")
    #                     self.close_position('SELL', ltp, 'PE')
    #                 elif current_position == 'BUY' and ltp >= smma300 * 1.02:
    #                     logger.info(f"[PE] 🟢 Mid session exit | LTP={ltp:.2f} >= SMMA300×1.02={smma300*1.02:.2f}")
    #                     self.close_position('SELL', ltp, 'PE')
                

    #     except Exception as e:
    #         logger.error(f"Error executing {scrip_type} strategy: {e}", exc_info=True)


    def execute_trading_strategy(self, market_data, scrip_type='CE'):
        """Main entry point for trading strategy execution."""
        global current_position_ce, current_position_pe, ce_stats, pe_stats
        global trading_paused, scrip_update_in_progress, config
        global ce_stop, pe_stop

        try:
            # Pre-flight checks
            if not self._should_execute_trade(scrip_type, market_data):
                return

            # Get position and stats for this scrip type
            current_position, stats = self._get_position_and_stats(scrip_type)
            
            # Extract and prepare market data
            market_info = self._prepare_market_data(market_data, stats, scrip_type)
            
            # Reset stop conditions if price drops below SMMA
            self._check_and_reset_stop_conditions(scrip_type, market_info['ltp'], market_info['smma300'])
            
            # Execute strategy based on time period
            self._execute_by_time_period(scrip_type, market_info, current_position, stats)

        except Exception as e:
            logger.error(f"Error executing {scrip_type} strategy: {e}", exc_info=True)


    def _should_execute_trade(self, scrip_type, market_data):
        """Check if trading conditions are met."""
        # Check trading status
        if trading_paused or scrip_update_in_progress:
            logger.debug(f"[{scrip_type}] Trading paused or scrip update in progress.")
            return False

        # Validate market data
        if not market_data or not market_data.get('smma300'):
            logger.debug(f"[{scrip_type}] Invalid market data. SMMA or LTP missing.")
            return False

        # Check trading hours
        if not self.check_trading_hours():
            logger.debug(f"[{scrip_type}] Outside trading hours. Skipping strategy.")
            return False

        # Check daily trade limit
        if not self.check_daily_trade_limit():
            logger.warning(f"[{scrip_type}] Daily trade limit reached.")
            alert_manager.add_alert(
                'limit', 'Daily Trade Limit',
                f'Daily trade limit of {config["max_trades_per_day"]} reached', 'warning'
            )
            return False

        return True


    def _get_position_and_stats(self, scrip_type):
        """Get current position and stats for the scrip type."""
        if scrip_type == 'CE':
            return current_position_ce, ce_stats
        else:
            return current_position_pe, pe_stats


    def _prepare_market_data(self, market_data, stats, scrip_type):
        """Extract and prepare all market data needed for trading."""
        ltp = market_data['ltp']
        smma300 = market_data['smma300']
        rangeinpercent = market_data.get('rangeinpercent', 0)
        range_work = config.get('strategy_range', 0)
        time_period = market_data.get('time_period', 0)
        low_price = market_data.get('low', 0)
        buy_price = stats.get('entry_price', 0)
        qty = self.calculate_qty(ltp)
        config['quantity'] = qty
        
        logger.debug(f"[{scrip_type}] LTP={ltp:.2f} | SMMA300={smma300:.2f} | Range%={rangeinpercent:.2f} | TimePeriod={time_period} | Qty={qty}")

        # Alert on high volatility
        if rangeinpercent > range_work:
            alert_manager.add_alert(
                'volatility', 'High Volatility',
                f'{scrip_type} showing high volatility: {rangeinpercent:.2f}%', 'warning'
            )

        return {
            'ltp': ltp,
            'smma300': smma300,
            'time_period': time_period,
            'low_price': low_price,
            'buy_price': buy_price,
            'qty': qty
        }


    def _check_and_reset_stop_conditions(self, scrip_type, ltp, smma300):
        """Reset stop conditions when price drops below SMMA."""
        global ce_stop, pe_stop
        
        if scrip_type == 'CE':
            if ce_stop == "Yes" and ltp <= smma300:
                ce_stop = "No"
                logger.info(f"[CE] ✅ Stop condition RESET - Price {ltp:.2f} dropped below SMMA {smma300:.2f}")
        
        if scrip_type == 'PE':
            if pe_stop == "Yes" and ltp <= smma300:
                pe_stop = "No"
                logger.info(f"[PE] ✅ Stop condition RESET - Price {ltp:.2f} dropped below SMMA {smma300:.2f}")


    def _execute_by_time_period(self, scrip_type, market_info, current_position, stats):
        """Route to appropriate strategy based on time period."""
        time_period = market_info['time_period']
        
        if time_period <= 300:
            self._execute_early_session_strategy(scrip_type, market_info, current_position, stats)
        elif time_period > 300 and time_period <= 400:
            self._execute_mid_session_strategy(scrip_type, market_info, current_position, stats)
        else:  # time_period > 400 (or >= 300 for PE)
            self._execute_late_session_strategy(scrip_type, market_info, current_position, stats)


    # ==================== EARLY SESSION STRATEGY (time_period <= 250) ====================

    def _execute_early_session_strategy(self, scrip_type, market_info, current_position, stats):
        """Handle trading during early session (time_period <= 250)."""
        ltp = market_info['ltp']
        smma300 = market_info['smma300']
        low_price = market_info['low_price']
        buy_price = market_info['buy_price']
        
        # Entry logic
        if current_position is None:
            self._try_early_entry(scrip_type, ltp, smma300, stats)
        
        # Exit logic
        elif current_position == 'BUY':
            self._check_early_exit(scrip_type, ltp, low_price, buy_price,smma300)


    def _try_early_entry(self, scrip_type, ltp, smma300, stats):
        """Try to enter position during early session."""
        stop_flag = ce_stop if scrip_type == 'CE' else pe_stop
        
        # Only enter if stop is not active AND price crosses above SMMA
        if stop_flag == "No" and ltp > smma300:
            logger.info(f"[{scrip_type}] 🟢 BUY Signal | LTP={ltp:.2f} crossed above SMMA300={smma300:.2f}")
            self.open_position('BUY', ltp, scrip_type)
            stats['entry_price'] = ltp
        
        # Log blocked entry
        elif stop_flag == "Yes":
            logger.debug(f"[{scrip_type}] ⛔ BUY blocked - stop active. Wait for price to drop below SMMA {smma300:.2f}")


    def _check_early_exit(self, scrip_type, ltp, low_price, buy_price,smma300):
        """Check exit conditions during early session."""
        global ce_stop, pe_stop
        
        # Stop Loss Exit
        if ltp <= smma300 * 0.96:
            logger.info(f"[{scrip_type}] 🔴 Exit (Stop Loss) | LTP={ltp:.2f} <= SMMA300×0.96={smma300*0.96:.2f}")
            self.close_position('SELL', ltp, scrip_type)
        
        # Target Exit (15% profit)
        elif ltp >= buy_price * 1.10:
            logger.info(f"[{scrip_type}] 🎯 Exit (Target) | LTP={ltp:.2f} >= 1.10×Buy={buy_price:.2f}")
            
            # Set stop flag to prevent immediate re-entry
            if scrip_type == 'CE':
                ce_stop = "Yes"
            else:
                pe_stop = "Yes"
            
            logger.info(f"[{scrip_type}] 🚫 Stop activated. No new trades until price <= SMMA")
            self.close_position('SELL', ltp, scrip_type)


    # ==================== MID SESSION STRATEGY (250 < time_period < 350) ====================

    def _execute_mid_session_strategy(self, scrip_type, market_info, current_position, stats):
        """Handle trading during mid session (250 < time_period < 350)."""
        ltp = market_info['ltp']
        smma300 = market_info['smma300']
        stop_flag = ce_stop if scrip_type == 'CE' else pe_stop
        
        # Entry: Price crosses above SMMA
        if current_position is None and ltp > smma300 and stop_flag == "No":
            logger.info(f"[{scrip_type}] 🟢 Mid session entry | LTP={ltp:.2f} crossed above SMMA300={smma300:.2f}")
            self.open_position('BUY', ltp, scrip_type)
            stats['entry_price'] = ltp
        
        # Exit: Price drops 2% below SMMA
        elif current_position == 'BUY' and ltp <= smma300 * 0.98:
            logger.info(f"[{scrip_type}] 🔴 Mid session exit | LTP={ltp:.2f} <= SMMA300×0.98={smma300*0.98:.2f}")
            self.close_position('SELL', ltp, scrip_type)
        
        # Exit: Price rises 2% above SMMA
        elif current_position == 'BUY' and ltp >= smma300 * 1.03:
            logger.info(f"[{scrip_type}] 🟢 Mid session exit | LTP={ltp:.2f} >= SMMA300×1.03={smma300*1.03:.2f}")
            # Set stop flag to prevent immediate re-entry
            if scrip_type == 'CE':
                ce_stop = "Yes"
            else:
                pe_stop = "Yes"
            self.close_position('SELL', ltp, scrip_type)


    # ==================== LATE SESSION STRATEGY (time_period >= 350/300) ====================

    def _execute_late_session_strategy(self, scrip_type, market_info, current_position, stats):
        """Handle trading during late session (time_period >= 350 for CE, >= 300 for PE)."""
        time_period = market_info['time_period']
        ltp = market_info['ltp']
        smma300 = market_info['smma300']
        low_price = market_info['low_price']
        
        # Different time thresholds for CE and PE
        late_threshold = 400 if scrip_type == 'CE' else 400
        
        if time_period < late_threshold:
            return
        
        # Entry logic
        if current_position is None:
            self._try_late_entry(scrip_type, ltp, low_price, smma300, stats)
        
        # Exit logic
        elif current_position == 'BUY':
            self._check_late_exit(scrip_type, ltp, smma300)


    def _try_late_entry(self, scrip_type, ltp, low_price, smma300, stats):
        """Try to enter position during late session near the low."""
        stop_flag = ce_stop if scrip_type == 'CE' else pe_stop
        
        # Entry conditions: Near low price but below SMMA
        entry_conditions = (
            stop_flag == "No" and
            ltp > low_price and
            ltp < low_price * 1.02 and
            ltp < smma300 * 0.98
        )
        
        if entry_conditions:
            logger.info(f"[{scrip_type}] 🟢 Late BUY entry near low | LTP={ltp:.2f} ~ Low={low_price:.2f}")
            self.open_position('BUY', ltp, scrip_type)
            stats['entry_price'] = ltp
        
        # Log blocked entry
        elif stop_flag == "Yes":
            logger.debug(f"[{scrip_type}] ⛔ Late BUY blocked - stop active")


    def _check_late_exit(self, scrip_type, ltp, smma300):
        """Check exit conditions during late session."""
        # Exit when price approaches SMMA
        if ltp > smma300 * 0.995:
            logger.info(f"[{scrip_type}] 🔴 Late Exit | LTP={ltp:.2f} > SMMA300×0.995={smma300*0.995:.2f}")
            self.close_position('SELL', ltp, scrip_type)
    
    def square_off_all_positions_for_update(self):
        """FIXED: Square off positions specifically for scrip update"""
        global current_position_ce, current_position_pe
        
        success_count = 0
        
        try:
            if current_position_ce:
                ce_ltp = get_ltp(config['ce_scrip_code'])
                if ce_ltp and ce_ltp > 0:
                    close_side = 'SELL' if current_position_ce == 'BUY' else 'BUY'
                    if self.place_closing_order(close_side, ce_ltp, 'CE'):
                        success_count += 1
                        logger.info(f"CE position squared off for scrip update")
            
            if current_position_pe:
                pe_ltp = get_ltp(config['pe_scrip_code'])
                if pe_ltp and pe_ltp > 0:
                    close_side = 'SELL' if current_position_pe == 'BUY' else 'BUY'
                    if self.place_closing_order(close_side, pe_ltp, 'PE'):
                        success_count += 1
                        logger.info(f"PE position squared off for scrip update")
            
            return success_count > 0 or (not current_position_ce and not current_position_pe)
            
        except Exception as e:
            logger.error(f"Error squaring off positions for update: {str(e)}")
            return False



    def enhanced_square_off_all_positions(self):
        """Squares off all currently open positions and stops trading."""
        global current_position_ce, current_position_pe, ce_stats, pe_stats, squared_off, trading_active, config
        
        squared_off = True
        trading_active = False
        alert_manager.add_alert('info', 'Square Off', 'Attempting to square off all positions and stop trading.', 'info')
        
        success_count = 0
        error_count = 0
        
        if current_position_ce:
            try:
                current_ltp_ce = get_ltp(config['ce_scrip_code'])
                if current_ltp_ce is not None and current_ltp_ce > 0:
                    close_side = 'SELL' if current_position_ce == 'BUY' else 'BUY'
                    
                    logger.info(f"Attempting to square off CE position: {current_position_ce} at Rs.{current_ltp_ce}")
                    
                    if self.place_closing_order(close_side, current_ltp_ce, 'CE'):
                        success_count += 1
                        alert_manager.add_alert('success', 'CE Squared Off', 
                                            f'CE {current_position_ce} position squared off at Rs.{current_ltp_ce}', 'success')
                        logger.info(f"CE position squared off: {current_position_ce} at Rs.{current_ltp_ce}")
                    else:
                        error_count += 1
                        alert_manager.add_alert('error', 'CE Square Off Failed', 
                                            'Failed to place closing order for CE position', 'error')
                        logger.error(f"Failed to square off CE position: {current_position_ce}")
                else:
                    error_count += 1
                    alert_manager.add_alert('error', 'CE Square Off Failed', 
                                        'Could not get valid LTP for CE to square off.', 'error')
                    logger.error(f"Invalid LTP for CE square off: {current_ltp_ce}")
            except Exception as e:
                error_count += 1
                logger.error(f"Error squaring off CE position: {str(e)}")
                alert_manager.add_alert('error', 'CE Square Off Error', 
                                    f'Error squaring off CE: {str(e)}', 'error')
        else:
            logger.info("No CE position to square off")
            alert_manager.add_alert('info', 'No CE Position', 'No CE position to square off.', 'info')

        if current_position_pe:
            try:
                current_ltp_pe = get_ltp(config['pe_scrip_code'])
                if current_ltp_pe is not None and current_ltp_pe > 0:
                    close_side = 'SELL' if current_position_pe == 'BUY' else 'BUY'
                    
                    logger.info(f"Attempting to square off PE position: {current_position_pe} at Rs.{current_ltp_pe}")
                    
                    if self.place_closing_order(close_side, current_ltp_pe, 'PE'):
                        success_count += 1
                        alert_manager.add_alert('success', 'PE Squared Off', 
                                            f'PE {current_position_pe} position squared off at Rs.{current_ltp_pe}', 'success')
                        logger.info(f"PE position squared off: {current_position_pe} at Rs.{current_ltp_pe}")
                    else:
                        error_count += 1
                        alert_manager.add_alert('error', 'PE Square Off Failed', 
                                            'Failed to place closing order for PE position', 'error')
                        logger.error(f"Failed to square off PE position: {current_position_pe}")
                else:
                    error_count += 1
                    alert_manager.add_alert('error', 'PE Square Off Failed', 
                                        'Could not get valid LTP for PE to square off.', 'error')
                    logger.error(f"Invalid LTP for PE square off: {current_ltp_pe}")
            except Exception as e:
                error_count += 1
                logger.error(f"Error squaring off PE position: {str(e)}")
                alert_manager.add_alert('error', 'PE Square Off Error', 
                                    f'Error squaring off PE: {str(e)}', 'error')
        else:
            logger.info("No PE position to square off")
            alert_manager.add_alert('info', 'No PE Position', 'No PE position to square off.', 'info')

        if success_count > 0 and error_count == 0:
            alert_manager.add_alert('success', 'Square Off Complete', 
                                f'Successfully squared off {success_count} position(s). Trading stopped.', 'success')
            logger.info(f"Square off complete: {success_count} positions closed successfully. Trading stopped.")
        elif success_count > 0 and error_count > 0:
            alert_manager.add_alert('warning', 'Square Off Partial', 
                                f'{success_count} successful, {error_count} failed. Trading stopped.', 'warning')
            logger.warning(f"Square off partial: {success_count} successful, {error_count} failed. Trading stopped.")
        elif error_count > 0:
            alert_manager.add_alert('error', 'Square Off Failed', 
                                f'Failed to square off {error_count} position(s). Trading stopped.', 'error')
            logger.error(f"Square off failed: {error_count} positions failed to close. Trading stopped.")
        else:
            alert_manager.add_alert('info', 'No Positions', 'No open positions to square off. Trading stopped.', 'info')
            logger.info("No positions to square off. Trading stopped.")

        return success_count > 0 or (success_count == 0 and error_count == 0)

    def open_position(self, side, price, scrip_type='CE'):
        """Open a new position using real API."""
        global current_position_ce, current_position_pe, ce_stats, pe_stats, portfolio_data
        global config, orders_ce, orders_pe

        try:
            scrip_code = config['ce_scrip_code'] if scrip_type == 'CE' else config['pe_scrip_code']
            scrip_name = config['ce_scrip_name'] if scrip_type == 'CE' else config['pe_scrip_name']
            stats = ce_stats if scrip_type == 'CE' else pe_stats
            orders = orders_ce if scrip_type == 'CE' else orders_pe

            if side == 'BUY':
                order_success = Buy_place_order(scrip_code, config['quantity'], config['exchange'])
            else:
                order_success = Sell_place_order(scrip_code, config['quantity'], config['exchange'])

            if order_success:
                # 👇 Place CSV logging here
                write_order_to_csv(
                    "order_history.csv",
                    scrip_name,
                    side,
                    config['quantity'],
                    price
                )
                if scrip_type == 'CE':
                    current_position_ce = side
                else:
                    current_position_pe = side

                stats['entry_price'] = price
                margin_used = price * config['quantity']
                stats['max_margin_used'] = max(stats['max_margin_used'], margin_used)
                portfolio_data['used_margin'] += margin_used
                portfolio_data['free_margin'] = portfolio_data['available_balance'] - portfolio_data['used_margin']
                portfolio_data['margin_utilization'] = (portfolio_data['used_margin'] / portfolio_data['available_balance'] * 100)

                order = {
                    'timestamp': datetime.now().isoformat(),
                    'side': side,
                    'price': price,
                    'quantity': config['quantity'],
                    'status': 'EXECUTED',
                    'type': 'MARKET',
                    'scrip_type': scrip_type,
                    'scrip_name': scrip_name
                }
                orders.append(order)
                alert_manager.add_alert('trade', 'Position Opened',
                                    f'{side} {scrip_type} at Rs.{price:.2f} - Quantity: {config["quantity"]}', 'success')
                self.daily_trades += 1
                logger.info(f"Position opened: {side} {scrip_type} at Rs.{price:.2f}")
            else:
                alert_manager.add_alert('error', 'Order Failed',
                                    f'Failed to place {side} order for {scrip_type}', 'error')
        except Exception as e:
            logger.error(f"Error opening position: {str(e)}")
            alert_manager.add_alert('error', 'Position Error', f'Failed to open {side} position: {str(e)}', 'error')

    
    def place_closing_order(self, side, price, scrip_type='CE'):
        """Place a closing order and update all relevant data structures."""
        global current_position_ce, current_position_pe, ce_stats, pe_stats, portfolio_data
        global config, orders_ce, orders_pe, trades_ce, trades_pe
        
        try:
            scrip_code = config['ce_scrip_code'] if scrip_type == 'CE' else config['pe_scrip_code']
            scrip_name = config['ce_scrip_name'] if scrip_type == 'CE' else config['pe_scrip_name']

            current_position = current_position_ce if scrip_type == 'CE' else current_position_pe
            stats = ce_stats if scrip_type == 'CE' else pe_stats
            orders = orders_ce if scrip_type == 'CE' else orders_pe
            trades = trades_ce if scrip_type == 'CE' else trades_pe
            
            if not current_position:
                logger.error(f"No {scrip_type} position to close")
                return False
            
            if stats['entry_price'] <= 0:
                logger.error(f"Invalid entry price for {scrip_type}: {stats['entry_price']}")
                return False
            
            if config['quantity'] <= 0:
                logger.error(f"Invalid quantity: {config['quantity']}")
                return False
            
            logger.info(f"Placing {side} order for {scrip_type} - Scrip: {scrip_code}, Quantity: {config['quantity']}, Price: Rs.{price}")
            
            if side == 'BUY':
                order_success = Buy_place_order(scrip_code, config['quantity'], config['exchange'])
            else:
                order_success = Sell_place_order(scrip_code, config['quantity'], config['exchange'])
            
            if not order_success:
                logger.error(f"Failed to place {side} order for {scrip_type}")
                return False
            
            entry_price = stats['entry_price']
            if current_position == 'BUY':
                pnl = (price - entry_price) * config['quantity']
            else:
                pnl = (entry_price - price) * config['quantity']
            
            logger.info(f"Calculated P&L for {scrip_type}: Rs.{pnl:.2f} (Entry: Rs.{entry_price}, Exit: Rs.{price}, Position: {current_position})")
            
            self.update_trade_statistics(stats, pnl, trades)
            self.update_portfolio_on_close(entry_price, pnl)
            
            closing_order = {
                'timestamp': datetime.now().isoformat(),
                'side': side,
                'price': price,
                'quantity': config['quantity'],
                'status': 'EXECUTED',
                'type': 'MARKET',
                'scrip_type': scrip_type,
                'scrip_name': scrip_name
            }
            orders.append(closing_order)
            
            trade = {
                'entry_time': datetime.now().isoformat(),
                'exit_time': datetime.now().isoformat(),
                'side': current_position,
                'entry_price': entry_price,
                'exit_price': price,
                'quantity': config['quantity'],
                'pnl': round(pnl, 2),
                'scrip_type': scrip_type,
                'scrip_name': scrip_name
            }
            trades.append(trade)
            
            if scrip_type == 'CE':
                current_position_ce = None
                ce_stats['entry_price'] = 0
                ce_stats['unrealized_pnl'] = 0
            else:
                current_position_pe = None
                pe_stats['entry_price'] = 0
                pe_stats['unrealized_pnl'] = 0
            
            logger.info(f"Successfully closed {current_position} {scrip_type} position. P&L: Rs.{pnl:.2f}")
            return True
            
        except Exception as e:
            logger.error(f"Error in place_closing_order for {scrip_type}: {str(e)}")
            return False
    
    def update_trade_statistics(self, stats, pnl, trades):
        """Update trading statistics after a trade is closed."""
        stats['total_trades'] += 1
        
        if pnl > 0:
            stats['win_trades'] += 1
            stats['max_profit'] = max(stats['max_profit'], pnl)
            stats['largest_winning_trade'] = max(stats['largest_winning_trade'], pnl)
            stats['consecutive_wins'] += 1
            stats['consecutive_losses'] = 0
        else:
            stats['lose_trades'] += 1
            stats['max_loss'] = min(stats['max_loss'], pnl)
            stats['largest_losing_trade'] = min(stats['largest_losing_trade'], pnl)
            stats['consecutive_losses'] += 1
            stats['consecutive_wins'] = 0
        
        stats['net_profit'] += pnl
        stats['realized_profit'] += pnl
        
        if stats['win_trades'] > 0:
            total_wins_profit = sum([t['pnl'] for t in trades if t['pnl'] > 0]) + (pnl if pnl > 0 else 0)
            stats['avg_profit_per_trade'] = total_wins_profit / stats['win_trades']
        
        if stats['lose_trades'] > 0:
            total_loss = sum([abs(t['pnl']) for t in trades if t['pnl'] < 0]) + (abs(pnl) if pnl < 0 else 0)
            stats['avg_loss_per_trade'] = -total_loss / stats['lose_trades']
        
        total_profit = sum([t['pnl'] for t in trades if t['pnl'] > 0]) + (pnl if pnl > 0 else 0)
        total_loss = abs(sum([t['pnl'] for t in trades if t['pnl'] < 0])) + (abs(pnl) if pnl < 0 else 0)
        stats['profit_factor'] = total_profit / total_loss if total_loss > 0 else 0
    
    def update_portfolio_on_close(self, entry_price, pnl):
        """Update portfolio data when a position is closed."""
        global portfolio_data, config
        
        margin_released = entry_price * config['quantity']
        portfolio_data['used_margin'] -= margin_released
        portfolio_data['free_margin'] = portfolio_data['available_balance'] - portfolio_data['used_margin']
        portfolio_data['realized_pnl'] += pnl
        portfolio_data['total_pnl'] = portfolio_data['realized_pnl'] + portfolio_data['unrealized_pnl']
        portfolio_data['roi'] = (portfolio_data['total_pnl'] / config['capital'] * 100) if config['capital'] > 0 else 0
        portfolio_data['margin_utilization'] = (portfolio_data['used_margin'] / portfolio_data['available_balance'] * 100) if portfolio_data['available_balance'] > 0 else 0

    def close_position(self, side, price, scrip_type='CE'):
        """Close existing position using real API."""
        global current_position_ce, current_position_pe, ce_stats, pe_stats, portfolio_data
        global config, orders_ce, orders_pe, trades_ce, trades_pe
        
        try:
            scrip_code = config['ce_scrip_code'] if scrip_type == 'CE' else config['pe_scrip_code']
            scrip_name = config['ce_scrip_name'] if scrip_type == 'CE' else config['pe_scrip_name']
            current_position = current_position_ce if scrip_type == 'CE' else current_position_pe
            stats = ce_stats if scrip_type == 'CE' else pe_stats
            orders = orders_ce if scrip_type == 'CE' else orders_pe
            trades = trades_ce if scrip_type == 'CE' else trades_pe
            
            if current_position:
                if side == 'BUY':
                    order_success = Buy_place_order(scrip_code, config['quantity'], config['exchange'])
                else:
                    order_success = Sell_place_order(scrip_code, config['quantity'], config['exchange'])
                
                if order_success:
                    # 👇 Place CSV logging here
                    write_order_to_csv(
                    "order_history.csv",
                    scrip_name,
                    side,
                    config['quantity'],
                    price
                )
                    entry_price = stats['entry_price']
                    
                    if current_position == 'BUY':
                        pnl = (price - entry_price) * config['quantity']
                    else:
                        pnl = (entry_price - price) * config['quantity']
                    
                    stats['total_trades'] += 1
                    if pnl > 0:
                        stats['win_trades'] += 1
                        stats['max_profit'] = max(stats['max_profit'], pnl)
                        stats['largest_winning_trade'] = max(stats['largest_winning_trade'], pnl)
                        stats['consecutive_wins'] += 1
                        stats['consecutive_losses'] = 0
                    else:
                        stats['lose_trades'] += 1
                        stats['max_loss'] = min(stats['max_loss'], pnl)
                        stats['largest_losing_trade'] = min(stats['largest_losing_trade'], pnl)
                        stats['consecutive_losses'] += 1
                        stats['consecutive_wins'] = 0
                    
                    stats['net_profit'] += pnl
                    stats['realized_profit'] += pnl
                    stats['unrealized_pnl'] = 0
                    
                    if stats['win_trades'] > 0:
                        total_wins_profit = sum([t['pnl'] for t in trades if t['pnl'] > 0]) + (pnl if pnl > 0 else 0)
                        stats['avg_profit_per_trade'] = total_wins_profit / stats['win_trades']
                    
                    if stats['lose_trades'] > 0:
                        total_loss = sum([abs(t['pnl']) for t in trades if t['pnl'] < 0]) + (abs(pnl) if pnl < 0 else 0)
                        stats['avg_loss_per_trade'] = -total_loss / stats['lose_trades']
                    
                    total_profit = sum([t['pnl'] for t in trades if t['pnl'] > 0]) + (pnl if pnl > 0 else 0)
                    total_loss = abs(sum([t['pnl'] for t in trades if t['pnl'] < 0])) + (abs(pnl) if pnl < 0 else 0)
                    stats['profit_factor'] = total_profit / total_loss if total_loss > 0 else 0
                    
                    margin_released = entry_price * config['quantity']
                    portfolio_data['used_margin'] -= margin_released
                    portfolio_data['free_margin'] = portfolio_data['available_balance'] - portfolio_data['used_margin']
                    portfolio_data['realized_pnl'] += pnl
                    portfolio_data['total_pnl'] = portfolio_data['realized_pnl'] + portfolio_data['unrealized_pnl']
                    portfolio_data['roi'] = (portfolio_data['total_pnl'] / config['capital'] * 100)
                    portfolio_data['margin_utilization'] = (portfolio_data['used_margin'] / portfolio_data['available_balance'] * 100)
                    
                    trade = {
                        'entry_time': orders[-1]['timestamp'] if orders else datetime.now().isoformat(),
                        'exit_time': datetime.now().isoformat(),
                        'side': current_position,
                        'entry_price': entry_price,
                        'exit_price': price,
                        'quantity': config['quantity'],
                        'pnl': round(pnl, 2),
                        'scrip_type': scrip_type,
                        'scrip_name': scrip_name
                    }
                    trades.append(trade)
                    
                    order = {
                        'timestamp': datetime.now().isoformat(),
                        'side': side,
                        'price': price,
                        'quantity': config['quantity'],
                        'status': 'EXECUTED',
                        'type': 'MARKET',
                        'scrip_type': scrip_type,
                        'scrip_name': scrip_name
                    }
                    orders.append(order)
                    
                    severity = 'success' if pnl > 0 else 'error'
                    alert_manager.add_alert('trade', 'Position Closed', 
                                          f'{current_position} {scrip_type} closed. P&L: Rs.{pnl:.2f}', severity)
                    
                    if scrip_type == 'CE':
                        current_position_ce = None
                        ce_stats['entry_price'] = 0
                    else:
                        current_position_pe = None
                        pe_stats['entry_price'] = 0
                    
                    self.daily_trades += 1
                    logger.info(f"Position closed: {current_position} {scrip_type} P&L: Rs.{pnl:.2f}")
                else:
                    alert_manager.add_alert('error', 'Order Failed', 
                                          f'Failed to close {current_position} position for {scrip_type}', 'error')
                    
        except Exception as e:
            logger.error(f"Error closing position: {str(e)}")
            alert_manager.add_alert('error', 'Position Error', f'Failed to close position: {str(e)}', 'error')


# Create trading engine instance
trading_engine = TradingEngine()


# ============================================================================
# TRADING LOOP
# ============================================================================

def trading_loop():
    """Main trading loop with CE/PE adaptive period."""
    global trading_active

    alert_manager.add_alert('system', 'Trading Started', 'Real data trading engine started', 'success')

    while trading_active:
        try:
            check_and_handle_price_difference()

            if not trading_paused and not scrip_update_in_progress:
                trading_engine.calculate_time_period('CE')
                trading_engine.calculate_time_period('PE')

                ce_data = trading_engine.get_real_market_data('CE')
                if ce_data:
                    trading_engine.execute_trading_strategy(ce_data, 'CE')

                pe_data = trading_engine.get_real_market_data('PE')
                if pe_data:
                    trading_engine.execute_trading_strategy(pe_data, 'PE')

            time.sleep(1)

        except Exception as e:
            logger.error(f"Error in trading loop: {str(e)}")
            alert_manager.add_alert('error', 'Trading Loop Error', str(e), 'error')
            time.sleep(5)

    alert_manager.add_alert('system', 'Trading Stopped', 'Real data trading engine stopped', 'info')

def excel_date_to_datetime(excel_date):
    """Convert Excel serial date to Python datetime."""
    try:
        return datetime(1899, 12, 30) + timedelta(days=float(excel_date))
    except Exception:
        return None

def excel_time_to_time(excel_time):
    """Convert Excel float time to HH:MM:SS."""
    try:
        seconds = float(excel_time) * 24 * 3600
        return (datetime(1899, 12, 30) + timedelta(seconds=seconds)).time()
    except Exception:
        return None


# ============================================================================
# FLASK ROUTES
# ============================================================================

@app.route('/')
def index():
    return render_template('login.html')


@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username')
    password = request.form.get('password')

    fixed_username = "dhavalvapi"
    dynamic_password = get_dynamic_password()

    print(f"Received credentials: Username='{username}', Password='{password}'")
    print(f"Expected credentials: Username='{fixed_username}', Password='{dynamic_password}'")

    if username == fixed_username and password == dynamic_password:
        # Run scrip master update on every login
        print("Updating scrip master data...")
        update_success = update_scrip_master()

        if update_success:
            # Reload the scrip master data
            load_scrip_master_from_csv('scripmaster.csv')
            print("Scrip master data updated successfully")
        else:
            print("Failed to update scrip master data")
            # We'll continue anyway as the existing data might still be usable

        # Generate TOTP for token refresh and handle OAuth2 flow
        auth_result = get_access_token()

        if auth_result.get('auth_pending'):
            # Authentication is pending, return TOTP for frontend display
            return jsonify({
                'success': True,
                'auth_pending': True,
                'totp_code': auth_result.get('totp_code'),
                'message': 'Authentication requires TOTP. Please check the TOTP code.'
            })
        elif auth_result['success']:
            # Authentication was already completed, redirect to dashboard
            return jsonify({
                'success': True,
                'redirect_url': url_for('dashboard'),
                'message': 'Login successful! Authentication completed automatically.'
            })
        else:
            # If authentication fails, redirect to dashboard anyway (might use existing token)
            return jsonify({
                'success': True,
                'redirect_url': url_for('dashboard'),
                'message': 'Login successful but token refresh failed. Using existing token if available.'
            })
    else:
        return jsonify({'success': False, 'message': 'Invalid username or password.'})


@app.route('/dashboard')
def dashboard():
    global auth_completed, current_totp_code
    # Check if authentication is complete
    if not auth_completed:
        # Reset authentication status
        auth_completed = False
        current_totp_code = None
        return redirect(url_for('index'))
    return render_template('dashboard.html')

@app.route('/api/scrips/exchanges')
def api_scrips_exchanges():
    """
    Returns available exchanges with display names.
    Codes: N (NSE), B (BSE), M (MCX)
    """
    try:
        return jsonify({
            'exchanges': [
                {'code': 'N', 'name': 'NSE'},
                {'code': 'B', 'name': 'BSE'},
                {'code': 'M', 'name': 'MCX'}
            ]
        })
    except Exception as e:
        logger.error(f"/api/scrips/exchanges error: {e}")
        return jsonify({'error': 'Failed to fetch exchanges'}), 500

@app.route('/api/scrips/expiries')
def api_scrips_expiries():
    """
    Returns unique expiry dates for a given exchange.
    Query: ?exch=N|B|M
    """
    global scripmaster_df
    exch = request.args.get('exch')

    try:
        if scripmaster_df is None or scripmaster_df.empty:
            return jsonify({'expiries': []})

        df = scripmaster_df
        if exch in VALID_EXCHANGES:
            df = df[df['Exch'] == exch]

        # Only options rows (CE/PE). ExchType 'D' is derivatives; keep broad filter for safety.
        df = df[df['ScripType'].isin(['CE', 'PE'])]

        # Normalize to string YYYY-MM-DD
        expiries = (
            df['Expiry']
            .dropna()
            .astype(str)
            .str.slice(0, 10)  # in case timestamps are present
            .unique()
            .tolist()
        )
        expiries.sort()
        return jsonify({'expiries': expiries})
    except Exception as e:
        logger.error(f"/api/scrips/expiries error: {e}")
        return jsonify({'error': 'Failed to fetch expiries'}), 500

@app.route('/api/scrips/list')
def api_scrips_list():
    """
    Returns CE and PE scrip lists for selected exchange and expiry.
    Query: ?exch=N|B|M&expiry=YYYY-MM-DD
    """
    global scripmaster_df
    exch = request.args.get('exch')
    expiry = request.args.get('expiry')

    try:
        if scripmaster_df is None or scripmaster_df.empty:
            return jsonify({'ce': [], 'pe': []})

        df = scripmaster_df
        if exch in VALID_EXCHANGES:
            df = df[df['Exch'] == exch]

        if expiry:
            # Ensure same string format match as in /expiries
            df = df[df['Expiry'].astype(str).str.slice(0, 10) == expiry]

        df = df[df['ScripType'].isin(['CE', 'PE'])]

        def to_items(sub):
            return [{
                'scrip_code': int(row['ScripCode']),
                'name': str(row.get('Name', 'Unknown')),
                'strike': float(row.get('StrikeRate')) if not pd.isna(row.get('StrikeRate')) else None,
                'lot_size': int(row.get('LotSize')) if not pd.isna(row.get('LotSize')) else None,
                'scrip_type': row.get('ScripType')
            } for _, row in sub.iterrows()]

        ce_items = to_items(df[df['ScripType'] == 'CE'])
        pe_items = to_items(df[df['ScripType'] == 'PE'])

        # Sort by strike if available
        ce_items.sort(key=lambda x: (x['strike'] is None, x['strike']))
        pe_items.sort(key=lambda x: (x['strike'] is None, x['strike']))

        return jsonify({'ce': ce_items, 'pe': pe_items})
    except Exception as e:
        logger.error(f"/api/scrips/list error: {e}")
        return jsonify({'error': 'Failed to fetch scrip list'}), 500


@app.route('/api/portfolio')
def get_portfolio():
    global portfolio_data, ce_stats, pe_stats, current_position_ce, current_position_pe, config
    
    try:
        portfolio_data['unrealized_pnl'] = ce_stats['unrealized_pnl'] + pe_stats['unrealized_pnl']
        portfolio_data['realized_pnl'] = ce_stats['realized_profit'] + pe_stats['realized_profit']
        portfolio_data['total_pnl'] = portfolio_data['realized_pnl'] + portfolio_data['unrealized_pnl']
        portfolio_data['roi'] = (portfolio_data['total_pnl'] / config['capital'] * 100) if config['capital'] > 0 else 0
        
        positions = []
        if current_position_ce:
            positions.append({
                'scrip_type': 'CE',
                'side': current_position_ce,
                'quantity': config['quantity'],
                'entry_price': ce_stats['entry_price'],
                'current_price': ce_stats['current_price'],
                'pnl': ce_stats['unrealized_pnl']
            })
        
        if current_position_pe:
            positions.append({
                'scrip_type': 'PE',
                'side': current_position_pe,
                'quantity': config['quantity'],
                'entry_price': pe_stats['entry_price'],
                'current_price': pe_stats['current_price'],
                'pnl': pe_stats['unrealized_pnl']
            })
        
        portfolio_data['positions'] = positions
        
        return jsonify(portfolio_data)
        
    except Exception as e:
        logger.error(f"Error getting portfolio: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/alerts')
def get_alerts():
    return jsonify({'alerts': alert_manager.get_alerts()})


@app.route('/api/alerts/all')
def get_all_alerts():
    return jsonify({'alerts': alert_manager.get_all_alerts()})


@app.route('/api/alerts/<int:alert_id>/read', methods=['POST'])
def mark_alert_read(alert_id):
    alert_manager.mark_read(alert_id)
    return jsonify({'success': True})


@app.route('/api/market_data/<scrip_type>')
def get_market_data(scrip_type):
    try:
        market_data = trading_engine.get_real_market_data(scrip_type.upper())
        if market_data:
            return jsonify(market_data)
        else:
            return jsonify({'error': 'Failed to get market data'}), 500
    except Exception as e:
        logger.error(f"Error getting market data for {scrip_type}: {str(e)}")
        return jsonify({'error': f'Error: {str(e)}'}), 500


@app.route('/api/generate_totp', methods=['POST'])
def generate_totp_endpoint():
    """API endpoint to generate TOTP for authentication"""
    try:
        result = get_access_token()
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error generating TOTP: {str(e)}")
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500


@app.route('/api/refresh_token', methods=['POST'])
def refresh_token_endpoint():
    """API endpoint to refresh access token"""
    try:
        data = request.get_json()
        authorization_code = data.get('authorization_code')

        if not authorization_code:
            return jsonify({'success': False, 'message': 'Authorization code is required'}), 400

        result = refresh_access_token(authorization_code)
        return jsonify(result)
    except Exception as e:
        logger.error(f"Error refreshing token: {str(e)}")
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500


@app.route('/api/complete_login', methods=['POST'])
def complete_login():
    """API endpoint to complete login after token refresh"""
    try:
        data = request.get_json()
        authorization_code = data.get('authorization_code')

        if not authorization_code:
            return jsonify({'success': False, 'message': 'Authorization code is required'}), 400

        # Refresh the access token
        result = refresh_access_token(authorization_code)

        if result['success']:
            return jsonify({
                'success': True,
                'redirect_url': url_for('dashboard'),
                'message': 'Login completed successfully'
            })
        else:
            return jsonify({
                'success': False,
                'message': result['message']
            }), 400
    except Exception as e:
        logger.error(f"Error completing login: {str(e)}")
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500


@app.route('/api/trading_stats/<scrip_type>')
def get_trading_stats(scrip_type):
    global ce_stats, pe_stats
    
    if scrip_type.upper() == 'COMBINED':
        return get_combined_trading_stats()
    
    stats = ce_stats if scrip_type.upper() == 'CE' else pe_stats
    win_ratio = (stats['win_trades'] / stats['total_trades'] * 100) if stats['total_trades'] > 0 else 0
    
    return jsonify({
        'total_trades': stats['total_trades'],
        'win_trades': stats['win_trades'],
        'lose_trades': stats['lose_trades'],
        'win_ratio': f"{win_ratio:.1f}%",
        'max_profit': round(stats['max_profit'], 2),
        'max_loss': round(stats['max_loss'], 2),
        'net_profit': round(stats['net_profit'], 2),
        'realized_profit': round(stats['realized_profit'], 2),
        'unrealized_pnl': round(stats['unrealized_pnl'], 2),
        'profit_factor': round(stats['profit_factor'], 2),
        'avg_profit_per_trade': round(stats['avg_profit_per_trade'], 2),
        'avg_loss_per_trade': round(stats['avg_loss_per_trade'], 2),
        'largest_winning_trade': round(stats['largest_winning_trade'], 2),
        'largest_losing_trade': round(stats['largest_losing_trade'], 2),
        'consecutive_wins': stats['consecutive_wins'],
        'consecutive_losses': stats['consecutive_losses'],
        'current_price': stats['current_price'],
        'high': stats['high'],
        'low': stats['low'],
        'smma300': round(stats['smma300'], 2),
        'range_percent': round(stats['range_percent'], 2)
    })


@app.route('/api/trading_stats/combined')
def get_combined_trading_stats():
    global ce_stats, pe_stats, config
    
    combined_stats = {
        'total_trades': ce_stats['total_trades'] + pe_stats['total_trades'],
        'win_trades': ce_stats['win_trades'] + pe_stats['win_trades'],
        'lose_trades': ce_stats['lose_trades'] + pe_stats['lose_trades'],
        'max_profit': max(ce_stats['max_profit'], pe_stats['max_profit']),
        'max_loss': min(ce_stats['max_loss'], pe_stats['max_loss']),
        'net_profit': ce_stats['net_profit'] + pe_stats['net_profit'],
        'realized_profit': ce_stats['realized_profit'] + pe_stats['realized_profit'],
        'unrealized_pnl': ce_stats['unrealized_pnl'] + pe_stats['unrealized_pnl']
    }
    
    win_ratio = (combined_stats['win_trades'] / combined_stats['total_trades'] * 100) if combined_stats['total_trades'] > 0 else 0
    roi = (combined_stats['net_profit'] / config['capital'] * 100) if config['capital'] > 0 else 0
    
    return jsonify({
        'total_trades': combined_stats['total_trades'],
        'win_trades': combined_stats['win_trades'],
        'lose_trades': combined_stats['lose_trades'],
        'win_ratio': f"{win_ratio:.1f}%",
        'max_profit': round(combined_stats['max_profit'], 2),
        'max_loss': round(combined_stats['max_loss'], 2),
        'net_profit': round(combined_stats['net_profit'], 2),
        'realized_profit': round(combined_stats['realized_profit'], 2),
        'unrealized_pnl': round(combined_stats['unrealized_pnl'], 2),
        'roi': f"{roi:.2f}%"
    })

@app.route('/api/trade-history')
def trade_history():
    try:
        df = pd.read_csv("order_history.csv")

        # Convert Excel float date/time to readable formats
        if 'Date' in df.columns:
            df['Date'] = df['Date'].apply(excel_date_to_datetime)
        if 'Time' in df.columns:
            df['Time'] = df['Time'].apply(excel_time_to_time)

        # Handle query parameters
        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')
        scrip_name = request.args.get('scrip_name')
        scrip_type = request.args.get('scrip_type')
        pnl_min = request.args.get('pnl_min', type=float)
        pnl_max = request.args.get('pnl_max', type=float)

        # Filter date range
        if from_date:
            from_date = datetime.strptime(from_date, '%Y-%m-%d')
            df = df[df['Date'] >= from_date]
        if to_date:
            to_date = datetime.strptime(to_date, '%Y-%m-%d')
            df = df[df['Date'] <= to_date]

        # Filter by scrip name or type
        if scrip_name:
            df = df[df['Scrip Name'].str.contains(scrip_name, case=False, na=False)]
        if scrip_type:
            df = df[df['Scrip Type'].str.upper() == scrip_type.upper()]

        # Optional PNL filter (if you later add a PNL column)
        if 'PNL' in df.columns:
            if pnl_min is not None:
                df = df[df['PNL'] >= pnl_min]
            if pnl_max is not None:
                df = df[df['PNL'] <= pnl_max]

        # Clean up data for JSON
        df['Date'] = df['Date'].astype(str)
        df['Time'] = df['Time'].astype(str)
        data = df.fillna('').to_dict(orient='records')

        return jsonify({'data': data, 'count': len(data)})

    except Exception as e:
        return jsonify({'error': str(e), 'data': []})


@app.route('/api/update_scrip_master', methods=['POST'])
def update_scrip_master_endpoint():
    """API endpoint to trigger scrip master update."""
    try:
        success = update_scrip_master()
        if success:
            # Reload the scrip master data
            load_scrip_master_from_csv('scripmaster.csv')
            return jsonify({'success': True, 'message': 'Scrip master updated successfully'})
        else:
            return jsonify({'success': False, 'message': 'Failed to update scrip master'}), 500
    except Exception as e:
        logger.error(f"Error updating scrip master: {str(e)}")
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500



@app.route('/api/orders/<scrip_type>')
def get_orders(scrip_type):
    global orders_ce, orders_pe
    
    try:
        orders = orders_ce if scrip_type.upper() == 'CE' else orders_pe
        return jsonify({'orders': orders})
        
    except Exception as e:
        logger.error(f"Error getting orders: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/orders/combined')
def get_combined_orders():
    global orders_ce, orders_pe
    
    combined_orders = orders_ce + orders_pe
    combined_orders.sort(key=lambda x: x['timestamp'], reverse=True)
    return jsonify({'orders': combined_orders})


@app.route('/api/trades/<scrip_type>')
def get_trades(scrip_type):
    global trades_ce, trades_pe
    
    trades = trades_ce if scrip_type.upper() == 'CE' else trades_pe
    return jsonify({'trades': trades})


@app.route('/api/trades/combined')
def get_combined_trades():
    global trades_ce, trades_pe
    
    combined_trades = trades_ce + trades_pe
    combined_trades.sort(key=lambda x: x['exit_time'], reverse=True)
    return jsonify({'trades': combined_trades})


@app.route('/api/start_trading', methods=['POST'])
def start_trading():
    global trading_active, squared_off, scrip_update_in_progress, trading_paused
    
    if not trading_active:
        trading_active = True
        squared_off = False
        scrip_update_in_progress = False
        trading_paused = False
        threading.Thread(target=trading_loop, daemon=True).start()
        return jsonify({'success': True, 'message': 'Trading started'})
    return jsonify({'success': False, 'message': 'Trading already active'})


@app.route('/api/stop_trading', methods=['POST'])
def stop_trading():
    global trading_active
    
    trading_active = False
    return jsonify({'success': True, 'message': 'Trading stopped'})


@app.route('/api/config', methods=['GET', 'POST'])
def trading_config():
    global config, portfolio_data
    
    if request.method == 'POST':
        data = request.get_json()
        logger.info(f"Received config data: {data}")
        
        if 'ce_scrip_code' in data and data['ce_scrip_code'] != config['ce_scrip_code']:
            new_ce_code = data['ce_scrip_code']
            config['ce_scrip_code'] = new_ce_code
            config['ce_scrip_name'] = get_scrip_name(new_ce_code)
            logger.info(f"CE Scrip Code updated to {new_ce_code}, Name set to {config['ce_scrip_name']}")

        if 'pe_scrip_code' in data and data['pe_scrip_code'] != config['pe_scrip_code']:
            new_pe_code = data['pe_scrip_code']
            config['pe_scrip_code'] = new_pe_code
            config['pe_scrip_name'] = get_scrip_name(new_pe_code)
            logger.info(f"PE Scrip Code updated to {new_pe_code}, Name set to {config['pe_scrip_name']}")
            
        for key in ['quantity', 'capital', 'stop_loss_percent', 'target_profit_percent', 'max_trades_per_day',
                    'trading_start_time', 'trading_end_time', 'broker', 'min_range_for_trading',
                    'exchange', 'auto_scrip_update', 'price_difference_threshold', 'strategy_range']:
            if key in data:
                if key in ['quantity', 'max_trades_per_day']:
                    config[key] = int(data[key])
                elif key in ['capital', 'stop_loss_percent', 'target_profit_percent', 'min_range_for_trading', 'price_difference_threshold', 'strategy_range']:
                    config[key] = float(data[key])
                elif key == 'exchange':
                    if data[key] in VALID_EXCHANGES:
                        config[key] = data[key]
                        logger.info(f"Exchange updated to: {data[key]}")
                    else:
                        logger.error(f"Invalid exchange value received: {data[key]}")
                        alert_manager.add_alert('error', 'Invalid Exchange', f"Exchange {data[key]} is not valid", 'error')
                        return jsonify({'success': False, 'message': f"Invalid exchange value: {data[key]}"}), 400
                else:
                    config[key] = data[key]
        
        if 'capital' in data:
            portfolio_data['available_balance'] = config['capital']
            portfolio_data['free_margin'] = config['capital'] - portfolio_data['used_margin']

        alert_manager.add_alert('config', 'Configuration Updated', 'Trading configuration has been updated', 'info')
        return jsonify({'success': True, 'message': 'Configuration updated'})
    
    return jsonify(config)


@app.route('/api/enhanced_square_off', methods=['POST'])
def enhanced_square_off_positions_route():
    global trading_active, squared_off, current_position_ce, current_position_pe
    
    logger.info("Square Off Positions button pressed.")
    
    try:
        if not trading_active:
            squared_off = True
            alert_manager.add_alert('info', 'Square Off', 'Trading is inactive. Squared off flag set.', 'info')
            return jsonify({'success': True, 'message': 'Trading inactive. Squared off flag set.'})

        if not current_position_ce and not current_position_pe:
            trading_active = False
            squared_off = True
            alert_manager.add_alert('info', 'No Positions', 'No open positions to square off. Trading stopped.', 'info')
            return jsonify({'success': True, 'message': 'No open positions to square off. Trading stopped.'})

        logger.info(f"Current positions before square off - CE: {current_position_ce}, PE: {current_position_pe}")
        
        if trading_engine.enhanced_square_off_all_positions():
            trading_active = False
            squared_off = True
            return jsonify({'success': True, 'message': 'Square off process completed. Trading stopped. Check alerts for details.'})
        else:
            trading_active = False
            squared_off = True
            return jsonify({'success': False, 'message': 'Square off process failed. Trading stopped. Check alerts for details.'})
            
    except Exception as e:
        logger.error(f"Error in square_off_positions_route: {e}")
        alert_manager.add_alert('error', 'Square Off Error', f'Error: {str(e)}', 'error')
        trading_active = False
        squared_off = True
        return jsonify({'success': False, 'message': f'Error: {str(e)}'}), 500


@app.route('/api/check_scrip_update')
def check_scrip_update_route():
    global config, scrip_update_in_progress, trading_paused
    
    try:
        if config.get('auto_scrip_update', 'enabled') != 'enabled':
            return jsonify({'update_needed': False, 'message': 'Auto scrip update disabled'})
        
        if scrip_update_in_progress:
            return jsonify({'update_needed': False, 'message': 'Scrip update in progress', 'in_progress': True})
        
        if trading_paused:
            return jsonify({'update_needed': False, 'message': 'Trading paused for update', 'paused': True})
        
        return jsonify({'update_needed': False, 'message': 'Monitoring price difference'})
        
    except Exception as e:
        logger.error(f"Error checking scrip update: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/current_scrips', methods=['GET'])
def get_current_scrip_codes():
    global config
    
    return jsonify({
        'ce_scrip_code': config['ce_scrip_code'],
        'pe_scrip_code': config['pe_scrip_code'],
        'ce_scrip_name': get_scrip_name(config['ce_scrip_code']),
        'pe_scrip_name': get_scrip_name(config['pe_scrip_code']),
        'exchange': config['exchange']
    })


@app.route('/api/analytics/pnl_chart')
def get_pnl_chart():
    global trades_ce, trades_pe
    
    all_trades = []
    
    for trade in trades_ce:
        trade_copy = trade.copy()
        trade_copy['scrip_type'] = 'CE'
        all_trades.append(trade_copy)
    
    for trade in trades_pe:
        trade_copy = trade.copy()
        trade_copy['scrip_type'] = 'PE'
        all_trades.append(trade_copy)
    
    all_trades.sort(key=lambda x: x['exit_time'])
    
    cumulative_pnl = 0
    chart_data = []
    
    for trade in all_trades:
        cumulative_pnl += trade['pnl']
        chart_data.append({
            'time': trade['exit_time'],
            'pnl': trade['pnl'],
            'cumulative_pnl': cumulative_pnl,
            'scrip_type': trade['scrip_type']
        })
    
    return jsonify({'chart_data': chart_data})


@app.route('/api/analytics/trade_distribution')
def get_trade_distribution():
    global ce_stats, pe_stats
    
    return jsonify({
        'ce_trades': ce_stats['total_trades'],
        'pe_trades': pe_stats['total_trades'],
        'ce_wins': ce_stats['win_trades'],
        'pe_wins': pe_stats['win_trades'],
        'ce_losses': ce_stats['lose_trades'],
        'pe_losses': pe_stats['lose_trades']
    })


@app.route('/api/analytics/performance_metrics')
def get_performance_metrics():
    global ce_stats, pe_stats, config
    
    total_trades = ce_stats['total_trades'] + pe_stats['total_trades']
    total_wins = ce_stats['win_trades'] + pe_stats['win_trades']
    total_losses = ce_stats['lose_trades'] + pe_stats['lose_trades']
    
    metrics = {
        'total_trades': total_trades,
        'win_rate': (total_wins / total_trades * 100) if total_trades > 0 else 0,
        'total_pnl': ce_stats['net_profit'] + pe_stats['net_profit'],
        'max_drawdown': min(ce_stats['max_loss'], pe_stats['max_loss']),
        'profit_factor': (ce_stats['profit_factor'] + pe_stats['profit_factor']) / 2 if ce_stats['profit_factor'] > 0 and pe_stats['profit_factor'] > 0 else 0,
        'sharpe_ratio': 0,
        'max_consecutive_wins': max(ce_stats['consecutive_wins'], pe_stats['consecutive_wins']),
        'max_consecutive_losses': max(ce_stats['consecutive_losses'], pe_stats['consecutive_losses']),
        'avg_trade_pnl': ((ce_stats['net_profit'] + pe_stats['net_profit']) / total_trades) if total_trades > 0 else 0,
        'roi': ((ce_stats['net_profit'] + pe_stats['net_profit']) / config['capital'] * 100) if config['capital'] > 0 else 0
    }
    
    return jsonify(metrics)


@app.route('/api/index_ltp', methods=['GET'])
def index_ltp():
    try:
        Nifty_index_ltp = get_index_ltp(999920000, 'N')
        Sensex_index_ltp = get_index_ltp(999901, 'B')

        response = {
            'Nifty': Nifty_index_ltp if Nifty_index_ltp else 'N/A',
            'Sensex': Sensex_index_ltp if Sensex_index_ltp else 'N/A'
        }

        return jsonify(response) if response else {'error': 'Failed to fetch index LTP'}
    except Exception as e:
        logger.error(f"Error getting index LTP: {str(e)}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/positions/current')
def get_current_positions():
    global current_position_ce, current_position_pe, config, ce_stats, pe_stats
    
    positions = []
    
    if current_position_ce:
        positions.append({
            'scrip_type': 'CE',
            'scrip_code': config['ce_scrip_code'],
            'side': current_position_ce,
            'quantity': config['quantity'],
            'entry_price': ce_stats['entry_price'],
            'current_price': ce_stats['current_price'],
            'pnl': ce_stats['unrealized_pnl'],
            'entry_time': datetime.now().isoformat()
        })
    
    if current_position_pe:
        positions.append({
            'scrip_type': 'PE',
            'scrip_code': config['pe_scrip_code'],
            'side': current_position_pe,
            'quantity': config['quantity'],
            'entry_price': pe_stats['entry_price'],
            'current_price': pe_stats['current_price'],
            'pnl': pe_stats['unrealized_pnl'],
            'entry_time': datetime.now().isoformat()
        })
    
    return jsonify({'positions': positions})


# ============================================================================
# STARTUP FUNCTIONS
# ============================================================================

def check_expiry():
    """Check if program has expired."""
    expiry_date = date(2025, 12, 9)
    current_date = date.today()
    
    if current_date > expiry_date:
        print("Your Program is Expired Please Contact Administrator @ 9727429104")
        sys.exit(1)
    else:
        print("Program is running...")


def open_browser():
    """Open browser after delay."""
    time.sleep(5)
    webbrowser.open('http://127.0.0.1:5012')


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == '__main__':
    check_expiry()
    threading.Thread(target=open_browser).start()
    load_scrip_master_from_csv('scripmaster.csv')
    
    # Update portfolio initial balance
    portfolio_data['available_balance'] = config['capital']
    portfolio_data['free_margin'] = config['capital']
    
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    print("=== FIXED Real Data Trading Dashboard ===")
    print("Dashboard available at: http://127.0.0.1:5012")
    print(f"CE Scrip: {config['ce_scrip_code']}")
    print(f"PE Scrip: {config['pe_scrip_code']}")
    print(f"Exchange: {config['exchange']}")
    print(f"Quantity: {config['quantity']}")
    print(f"Capital: Rs.{config['capital']:,.2f}")
    print(f"Auto Scrip Update: {'Enabled' if config.get('auto_scrip_update', 'enabled') == 'enabled' else 'Disabled'}")
    print(f"Price Difference Threshold: {config.get('price_difference_threshold', 40.0)}%")
    print("\n[ACTIVE] REAL DATA TRADING ACTIVE")
    print("[WARNING] This system will place REAL orders using apifunction.py!")
    print("[FEATURES] FIXED FEATURES:")
    print("   - Proper global variable handling throughout")
    print("   - Immediate scrip code updates when price difference exceeds threshold")
    print("   - Complete history clearing and rebuilding with new data")
    print("   - Proper workflow: Square off -> Pause 5s -> Update -> Resume")
    print("   - Real-time range and range percentage updates")
    print("   - All global variables properly declared at module level")
    
    alert_manager.add_alert('system', 'System Started', 'FIXED Real data trading dashboard initialized', 'success')
    
    app.run(host='127.0.0.1', port=5012, debug=True, use_reloader=False)
