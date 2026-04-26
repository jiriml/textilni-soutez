import sys
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, request, redirect, session, render_template
import requests
import os
import secrets
print("PORT FROM ENV:", os.environ.get("PORT","FAILED"))


app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "")

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

REDIRECT_URI = os.environ.get("REDIRECT_URI", "http://localhost:1234/callback") 

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


@app.route("/")
def index():
    return render_template("index.html")
@app.route("/ping")
def ping():
    return "pong"
@app.route("/terms-of-use")
def termsOfUse():
    return render_template("terms-of-use/index.html")

@app.route("/login")
def login():
    # CSRF protection
    if "user" in session:
        return redirect("/workspace")

    state = secrets.token_urlsafe(16)
    session["oauth_state"] = state

    scope = "https://www.googleapis.com/auth/userinfo.email"

    auth_url = (
        f"{GOOGLE_AUTH_URL}"
        f"?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}"
        f"&response_type=code"
        f"&scope={scope}"
        f"&state={state}"
        f"&access_type=online"
        f"&prompt=consent"
    )

    return redirect(auth_url)


@app.route("/callback")
def callback():
    # 1) error check
    if request.args.get("error"):
        return render_template("onerror.html", errormessage=f"OAuth error: {request.args.get('error')}")

    # 2) state check (important!)
    state = request.args.get("state")
    expected_state = session.get("oauth_state")

    if not state:
        return render_template("onerror.html", errormessage="Chyba přihlášení: chybí bezpečnostní parametr (state).\n"
            "Možná máte blokované cookies nebo soukromý režim prohlížeče.")


    if state != expected_state:
        return render_template("onerror.html", errormessage= "Systém detekoval kryptografickou nesrovnalost mezi začátkem a koncem přihlašování.\n"
            "Přístup byl odmítnut."), 400

    code = request.args.get("code")
    if not code:
        return render_template("onerror.html", errormessage= "Missing authorization code"), 400


    # 3) exchange code for token
    token_res = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
    )

    token_data = token_res.json()

    access_token = token_data.get("access_token")
    if not access_token:
        return f"Token error: {token_data}", 400

    # 4) get user info
    user_res = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
    )

    user_info = user_res.json()
    if user_info["email"][-10:]!="@bigycb.cz":
        return render_template("onerror.html", errormessage= "Přístup do této aplikace je omezen jen na emaily končící na @bigycb.cz"), 400

    # 5) save session
    session["user"] = user_info

    return redirect("/workspace")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/workspace")
def workspace():
    if "user" not in session:
        return redirect("/")

    return render_template("workspace/index.html", user=session.get("user"))

    return f"""
    <h1>Workspace</h1>
    <pre>{session["user"]}</pre>
    <a href="/logout">Logout</a>
    """


if __name__ == "__main__": # DO NOT USE IN PRODUCTION
    app.run(port=1234, host="0.0.0.0")