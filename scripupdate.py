import requests
import csv
from datetime import datetime
import json
from pathlib import Path
from typing import Optional, List, Dict

token = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1bmlxdWVfbmFtZSI6IjU2OTkwOTE4Iiwicm9sZSI6Ijc3MzMiLCJTdGF0ZSI6IiIsIlJlZGlyZWN0U2VydmVyIjoiQSIsIm5iZiI6MTc1MjcyMDgwNiwiZXhwIjoxNzUyNzc2OTk5LCJpYXQiOjE3NTI3MjA4MDZ9.uievAi8ilKE6MsCfnVF-X3lUyRDUJdPaQ1BQ8Ru6wiU'

def scripmaster_get_ltp(exchange: str, scrip_code: int, instrument_name: str) -> Optional[float]:
    """Fetch Last Traded Price (LTP) for a given instrument."""
    url = 'https://Openapi.5paisa.com/VendorsAPI/Service1.svc/V1/MarketFeed'
    USER_KEY = 'Q4O7AsAK0iUABwjsvYfmfNU1cMiMWXai'

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
        response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'})
        response.raise_for_status()

        data = response.json()
        ltp = data.get('body', {}).get('Data', [{}])[0].get('LastRate')
        if ltp is not None:
            return float(ltp)
        return None
    except Exception:
        return None


def download_scrip_master(segment: str, token: str) -> str:
    """Download scrip master CSV for a segment."""
    url = f'https://Openapi.5paisa.com/VendorsAPI/Service1.svc/ScripMaster/segment/{segment}'
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'text/csv',
        'Content-Type': 'text/csv'
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.text


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse date in multiple formats."""
    if not date_str:
        return None
    formats = ['%d-%m-%Y', '%Y-%m-%d', '%m/%d/%Y']
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def filter_scrip_master(
    records: List[Dict],
    instrument_name: str,
    ltp: Optional[float],
    exchange: str
) -> List[Dict]:
    """Filter records for nearest expiry and ±15 strikes around LTP."""
    try:
        filtered = [r for r in records if r.get('SymbolRoot', '').upper() == instrument_name.upper()]
        if not filtered:
            return []

        today = datetime.now().date()
        expiries = {parse_date(r.get('Expiry', '')) for r in filtered}
        valid_expiries = [d for d in expiries if d and d.date() >= today]
        if not valid_expiries:
            return []

        nearest_expiry = min(valid_expiries)
        nearest_str = nearest_expiry.strftime('%d-%m-%Y')

        expiry_records = [
            r for r in filtered
            if parse_date(r.get('Expiry', '')) == nearest_expiry and r.get('ScripType') != 'XX'
        ]

        effective_ltp = ltp or 1800
        strikes = [float(r.get('StrikeRate', 0)) for r in expiry_records]

        above = sorted([r for r in expiry_records if float(r.get('StrikeRate', 0)) > effective_ltp],
                       key=lambda x: float(x['StrikeRate']))[:15]
        below = sorted([r for r in expiry_records if float(r.get('StrikeRate', 0)) <= effective_ltp],
                       key=lambda x: float(x['StrikeRate']), reverse=True)[:15]

        selected = above + below
        final = []
        for r in selected:
            strike = float(r['StrikeRate'])
            final.append({
                'Instrument': 'NIFTY' if exchange == 'N' else 'SENSEX',
                'Exch': r.get('Exch', ''),
                'ExchType': r.get('ExchType', ''),
                'ScripCode': r.get('ScripCode', ''),
                'Name': r.get('Name', ''),
                'Expiry': nearest_str,
                'ScripType': r.get('ScripType', ''),
                'StrikeRate': strike,
                'LastRate': r.get('LastRate', ''),
                'LotSize': r.get('LotSize', '75' if exchange == 'N' else '20'),
                'QtyLimit': r.get('QtyLimit', ''),
                'LTPPosition': 'Above' if strike > effective_ltp else 'Below',
                'Position': ''
            })

        return final

    except Exception:
        return []


def generate_scripmaster_csv(
    token: str = token,
    output_file: str = 'scripmaster.csv',
    user_key: str = 'Q4O7AsAK0iUABwjsvYfmfNU1cMiMWX2i'
) -> Path:
    """
    Main function to generate combined scrip master CSV with NIFTY & SENSEX options.
    """
    global USER_KEY
    USER_KEY = user_key

    instruments = [
        {'exchange': 'N', 'scripCode': 999920000, 'name': 'Nifty', 'segment': 'nse_fo', 'root': 'NIFTY'},
        {'exchange': 'B', 'scripCode': 999901, 'name': 'Sensex', 'segment': 'bse_fo', 'root': 'SENSEX'}
    ]

    try:
        # Step 1: Fetch LTPs
        ltps = {}
        for inst in instruments:
            ltp = scripmaster_get_ltp(inst['exchange'], inst['scripCode'], inst['name'])
            ltps[inst['segment']] = ltp
            print(f"{inst['name']} LTP: {ltp if ltp else 'N/A'}")

        # Step 2: Download scrip masters
        all_records = []
        common_headers = None

        for inst in instruments:
            csv_data = download_scrip_master(inst['segment'], token)
            reader = csv.DictReader(csv_data.splitlines())
            records = list(reader)

            if common_headers is None:
                common_headers = list(records[0].keys()) if records else []
            else:
                current = list(records[0].keys()) if records else []
                if current != common_headers:
                    records = [{h: r.get(h, '') for h in common_headers} for r in records]

            all_records.extend(records)

        # Step 3: Filter per instrument
        filtered_records = []
        for inst in instruments:
            segment_records = filter_scrip_master(
                all_records,
                inst['root'],
                ltps.get(inst['segment']),
                inst['exchange']
            )
            filtered_records.extend(segment_records)

        # Step 4: Sort and save
        filtered_records.sort(key=lambda x: x['StrikeRate'])

        desired_columns = [
            'Instrument', 'Exch', 'ExchType', 'ScripCode', 'Name', 'Expiry',
            'ScripType', 'StrikeRate', 'LastRate', 'LotSize', 'QtyLimit',
            'LTPPosition', 'Position'
        ]

        output_path = Path(output_file)
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=desired_columns)
            writer.writeheader()
            writer.writerows(filtered_records)

        print(f"\nGenerated: {output_path.resolve()}")
        print(f"Total Records: {len(filtered_records)}")

        return output_path

    except Exception as e:
        print(f"Failed to generate scrip master: {e}")
        raise

