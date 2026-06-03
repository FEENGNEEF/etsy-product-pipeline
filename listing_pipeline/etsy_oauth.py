import os
import base64
import hashlib
import requests
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse as urlparse
import threading
from time import sleep

# Etsy OAuth configuration. Set these through environment variables before use.
CLIENT_ID = os.getenv('ETSY_CLIENT_ID', '')
CLIENT_SECRET = os.getenv('ETSY_CLIENT_SECRET', '')
REDIRECT_URI = os.getenv('ETSY_REDIRECT_URI', 'http://localhost:8080/callback')
SCOPES = 'listings_w listings_r listings_d'
STATE = os.getenv('ETSY_OAUTH_STATE', 'change-this-state-value')

# Soubory, kam se uloží tokeny
ACCESS_TOKEN_FILE = 'access_token.txt'
REFRESH_TOKEN_FILE = 'refresh_token.txt'

auth_code_received = None
code_verifier = None
httpd = None

# ============================================
# Funkce pro generování PKCE (code challenge)
# ============================================

def generate_code_verifier():
    return base64.urlsafe_b64encode(os.urandom(64)).rstrip(b'=').decode('utf-8')

def generate_code_challenge(verifier):
    digest = hashlib.sha256(verifier.encode('utf-8')).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b'=').decode('utf-8')


# ==========================
# Výměna kódu za Access Token
# ==========================

def exchange_code_for_token(authorization_code, code_verifier):
    if not CLIENT_ID:
        raise RuntimeError("Missing ETSY_CLIENT_ID environment variable.")
    #token_url = 'https://api.etsy.com/v3/public/oauth/token?grant_type=authorization_code&client_id='+CLIENT_ID+'&redirect_uri='+REDIRECT_URI+'&code='+authorization_code+'&code_verifier='+code_verifier
    token_url = 'https://api.etsy.com/v3/public/oauth/token'
    data = {
        'grant_type': 'authorization_code',
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'code': authorization_code,
        'code_verifier': code_verifier
    }
    response = requests.post(token_url, headers={"Content-Type": "application/x-www-form-urlencoded"}, data=data)
    print(response)
    if response.status_code == 200:
        token_info = response.json()
        print("Token response received from Etsy.")
        user_id = token_info.get('user_id') or token_info.get('etsy_user_id')
        access_token = token_info.get('access_token', '')
        refresh_token = token_info.get('refresh_token')
        if access_token and '.' not in access_token:
            if user_id:
                access_token = f"{user_id}.{access_token}"
                print("Access token doplnen o user_id prefix.")
            else:
                print("Access token nema user_id prefix a v odpovedi chybi user_id.")
        if refresh_token and '.' not in refresh_token:
            if user_id:
                refresh_token = f"{user_id}.{refresh_token}"
                print("Refresh token doplnen o user_id prefix.")
            else:
                print("Refresh token nema user_id prefix a v odpovedi chybi user_id.")
        # Uložíme tokeny
        with open(ACCESS_TOKEN_FILE, 'w') as f:
            f.write(access_token)
        if refresh_token:
            with open(REFRESH_TOKEN_FILE, 'w') as f:
                f.write(refresh_token)
        print("Access token získán a uložen v", ACCESS_TOKEN_FILE)
        if refresh_token:
            print("Refresh token uložen v", REFRESH_TOKEN_FILE)
        return access_token
    else:
        print("Chyba při získávání tokenu:", response.text)
        return None


# ==========================
# Jednoduchý callback server
# ==========================

class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code_received, httpd
        query = urlparse.urlparse(self.path).query
        params = urlparse.parse_qs(query)

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Authorization response received. You can close this browser tab.")

        if "code" in params:
            authorization_code = params["code"][0]
            print("Authorization code received.")
            auth_code_received = authorization_code
        elif "error" in params:
            error = params["error"][0]
            error_description = params.get("error_description", ["No description"])[0]
            print(f"Authorization failed: {error}, {error_description}")
        else:
            print("Unknown response. No 'code' or 'error' parameter received.")

        # Ukončíme server v novém vlákně
        if httpd:
            threading.Thread(target=httpd.shutdown).start()


def run_server():
    global httpd
    server_address = ("", 8080)
    httpd = HTTPServer(server_address, CallbackHandler)
    print("Server běží na http://localhost:8080/callback - čekám na callback z Etsy...")
    httpd.serve_forever()


# ==========================
# Hlavní logika
# ==========================

if __name__ == '__main__':
    # Vytvoříme code_verifier a code_challenge
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)

    # Složíme autorizační URL
    params = {
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPES,
        'state': STATE,
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256'
    }
    authorization_url = f"https://www.etsy.com/oauth/connect?{urlparse.urlencode(params)}"

    # Spustíme server v samostatném vlákně
    server_thread = threading.Thread(target=run_server, daemon=True)
    server_thread.start()

    # Otevřeme prohlížeč s URL
    print("Otevírám URL v prohlížeči pro autorizaci...")
    webbrowser.open(authorization_url)

    # Čekáme až do 60 sekund na získání autorizačního kódu
    for i in range(60):
        if auth_code_received is not None:
            print("Autorizační kód detekován, získávám přístupový token...")
            break
        sleep(1)

    if auth_code_received is None:
        print("Nepodařilo se získat autorizační kód v časovém limitu (60s).")
        print("Zkontroluj, zda jsi v prohlížeči odsouhlasil přístup a Etsy se vrátila na URL http://localhost:8080/callback")
        exit(1)

    # Výměna kódu za token
    access_token = exchange_code_for_token(auth_code_received, code_verifier)
    if access_token:
        print("Autentizace s Etsy proběhla úspěšně. Access token je uložen.")
        print("Nyní můžeš spustit jiné skripty, které s ním budou pracovat (nahrávání listingů apod.).")
    else:
        print("Nepodařilo se získat access token.")
