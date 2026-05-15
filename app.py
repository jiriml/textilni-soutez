import sys, os, boto3, secrets, PIL.Image, requests
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, request, redirect, session, render_template, jsonify
from extensions import db
from storage import Storage
import users
from botocore.config import Config as BotoConfig

#Secrets and flask app init
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET")
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
REDIRECT_URI = os.environ.get("REDIRECT_URI", "http://localhost:1234/callback") 
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
ZONE = (2687, 4513)

# Database init
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URI")
db.init_app(app)
with app.app_context():
    #db.drop_all() 
    db.create_all()


r2 = boto3.client(
    "s3",
    endpoint_url=os.environ.get("R2_ENDPOINT"),
    aws_access_key_id=os.environ.get("R2_KEY"),
    aws_secret_access_key=os.environ.get("R2_SECRET"),
    config=BotoConfig(signature_version="s3v4")
)

STORAGE = Storage(
    client=r2,
    bucket=os.environ.get("R2_BUCKET")
)



#Routes
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
    if user_info.get("hd")!="bigycb.cz":
        return render_template("onerror.html", errormessage= "Přístup do této aplikace je omezen jen na emaily končící na @bigycb.cz"), 400

    # 5) save session
    user_info["BIGY_ID"] = users.getOrCreateUser(user_info["email"]).id
    session["user"] = user_info
    print(user_info, "<<<")
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




@app.route("/api/design/upload", methods=["POST"])
def design_upload():
    if "user" not in session:
        return "FATAL"
    BIGY_ID = session.get("user").get("BIGY_ID")


    user = users.getUserByID(BIGY_ID)


    front = request.files.get("front")
    back = request.files.get("back")
    color = request.form.get("color")

    if not front or not back:
        return "INVALID"

    def valid_size(file):
        img = PIL.Image.open(file)
        print(img.size)
        zSize = (ZONE[0]-20,ZONE[1]-20)
        return img.size == zSize

    if not valid_size(front) or not valid_size(back):
        return "INVALID"
    front.seek(0)
    back.seek(0)
    if not users.can_upload(BIGY_ID):
        return "LIMIT"


    design, err = users.upload_design(BIGY_ID, front, back, color, STORAGE)
    print("TOTO JE BARVA: ",color)
    if err:
        return "FATAL"

    return "SUCCES"

@app.route("/api/my-designs", methods=["GET"])
def my_designs():

    user_id = session.get("user").get("BIGY_ID")

    if not user_id:
        return jsonify({"error": "unauthorized"}), 401

    designs = (
        users.Design.query
        .filter(users.Design.user_id == user_id)
        .order_by(users.Design.id.desc())
        .limit(3)
        .all()
    )

    return jsonify({
        "design_ids": [d.id for d in designs]
    })

@app.route("/api/design/<int:design_id>", methods=["GET"])  
def get_design(design_id):


    design = users.Design.query.filter_by(id=design_id).first()

    if not design:
        return "NOT_FOUND"

    return jsonify({
        "front": STORAGE.get_url(design.front_key),
        "back": STORAGE.get_url(design.back_key),
        "color": design.color
    })
    
@app.route("/api/design/<int:design_id>", methods=["DELETE"])
def delete_design(design_id):

    user_id = session.get("user").get("BIGY_ID")

    design = users.Design.query.filter_by(id=design_id).first()

    if not design:
        return "NOT_FOUND", 404

    print(user_id,design.user_id)

    is_owner = design.user_id == user_id
    is_admin = False

    if not (is_owner or is_admin):
        return "FORBIDDEN", 403

    users.delete_design(design_id=design_id)

    return "SUCCESS", 200





if __name__ == "__main__": # DO NOT USE IN PRODUCTION
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

