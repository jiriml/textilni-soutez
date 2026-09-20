import sys, os, boto3, secrets, PIL.Image, requests, sqlalchemy, math
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, request, redirect, session, render_template, jsonify
from flask_wtf import CSRFProtect
from flask_wtf.csrf import generate_csrf, validate_csrf
from extensions import db
from storage import Storage
import users
from botocore.config import Config as BotoConfig

#Secrets and flask app init
app = Flask(__name__)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("REDIRECT_URI", "").startswith("https://")
app.secret_key = os.environ.get("FLASK_SECRET")
csrf = CSRFProtect(app)
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

    inspector = sqlalchemy.inspect(db.engine)
    settings_columns = {
        column["name"] for column in inspector.get_columns("settings")
    }
    if "mode" not in settings_columns:
        db.session.execute(sqlalchemy.text(
            "ALTER TABLE settings ADD COLUMN mode VARCHAR(20)"
        ))
        db.session.execute(sqlalchemy.text(
            "UPDATE settings SET mode = CASE WHEN voting_open THEN 'voting' "
            "ELSE 'designing' END WHERE mode IS NULL"
        ))
        db.session.commit()

    design_columns = {
        column["name"] for column in inspector.get_columns("designs")
    }
    if "created_at" not in design_columns:
        db.session.execute(sqlalchemy.text(
            "ALTER TABLE designs ADD COLUMN created_at TIMESTAMP"
        ))
        db.session.execute(sqlalchemy.text(
            "UPDATE designs SET created_at = CURRENT_TIMESTAMP "
            "WHERE created_at IS NULL"
        ))
        db.session.commit()

    # Older PostgreSQL databases used a one-vote-per-user constraint.
    if db.engine.dialect.name == "postgresql":
        inspector = sqlalchemy.inspect(db.engine)
        for constraint in inspector.get_unique_constraints("votes"):
            if constraint.get("column_names") == ["user_id"] and constraint.get("name"):
                db.session.execute(sqlalchemy.text(
                    f'ALTER TABLE votes DROP CONSTRAINT "{constraint["name"]}"'
                ))
        db.session.commit()



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
def is_admin_session():
    return session.get("admin") == "yes"


def can_view_all_designs():
    return session.get("admin") == "yes"


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
    if user_info.get("hd")!="bigycb.cz" and user_info.get("hd")!="bigy-cb.cz":
        return render_template("onerror.html", errormessage= "Přístup do této aplikace je omezen jen na emaily končící na @bigycb.cz nebo @bigy-cb.cz"), 400

    # 5) save session
    user_info["BIGY_ID"] = users.getOrCreateUser(user_info["email"]).id
    session["user"] = user_info
    print(user_info, "<<<")
    return redirect("/workspace")

@app.route("/admin")
def adminPage():
    session.pop("admin", None)
    session.pop("impersonating", None)
    return render_template("admin.html")
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")


@app.route("/workspace")
def workspace():
    if "user" not in session:
        return redirect("/")

    # generate a per-session CSRF token and pass it to the workspace template
    csrf_token = generate_csrf()
    return render_template(
        "workspace/index.html",
        user=session.get("user"),
        csrf_token=csrf_token,
        is_admin=is_admin_session(),
        max_votes=users.MAX_VOTES_PER_USER,
        competition_mode=users.getMode(),
    )




@app.route("/api/design/upload", methods=["POST"])
@csrf.exempt
def design_upload():
    if "user" not in session:
        return "FATAL"
    if users.getMode() != "designing":
        return "CLOSED", 403
    BIGY_ID = session.get("user",{}).get("BIGY_ID")


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

    user_id = session.get("user",{}).get("BIGY_ID")

    if not user_id:
        return jsonify({"error": "unauthorized"}), 401

    designs = (
        users.Design.query
        .filter(users.Design.user_id == user_id)
        .order_by(users.Design.id.desc())
        .limit(93)
        .all()
    )

    return jsonify({
        "designs": [{"id":d.id,"color":d.color,"back":STORAGE.get_url(d.back_key),"front":STORAGE.get_url(d.front_key)} for d in designs]
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

    if users.getMode() == "finished":
        return "CLOSED", 403

    # CSRF validation (expect token in header or form)
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    try:
        validate_csrf(token)
    except Exception:
        return "CSRF", 403

    user_id = session.get("user",{}).get("BIGY_ID")

    design = users.Design.query.filter_by(id=design_id).first()

    if not design:
        return "NOT_FOUND", 404

    print(user_id,design.user_id)

    is_owner = design.user_id == user_id

    if not (is_owner or is_admin_session()):
        return "FORBIDDEN", 403

    users.delete_design(design_id=design_id, storage=STORAGE)

    return "SUCCESS", 200

@app.route("/admin/voting", methods=["POST"])
@csrf.exempt
def set_voting():
    data = request.get_json()
    ADMIN_KEY = os.getenv("ADMIN_KEY")
    key = request.headers.get("X-ADMIN-KEY")
    if key != ADMIN_KEY:
        return "FAIL", 403

    open_state = data.get("open")

    if open_state is None:
        return "FAIL", 400

    users.setVoting(bool(open_state))

    return "SUCCESS"


@app.route("/admin/mode", methods=["POST"])
@csrf.exempt
def set_mode():
    if request.headers.get("X-ADMIN-KEY") != os.getenv("ADMIN_KEY"):
        return "FAIL", 403

    mode = (request.get_json() or {}).get("mode")
    if not users.setMode(mode):
        return "FAIL", 400

    return "SUCCESS"


@app.route("/admin/state")
def admin_state():
    if request.headers.get("X-ADMIN-KEY") != os.getenv("ADMIN_KEY"):
        return jsonify({"error": "forbidden"}), 403
    return jsonify({"mode": users.getMode()})


@app.route("/admin/jailbreak", methods=["POST"])
@csrf.exempt
def admin_jailbreak():
    ADMIN_KEY = os.getenv("ADMIN_KEY")
    key = request.headers.get("X-ADMIN-KEY")
    if key != ADMIN_KEY:
        return "FORBIDDEN", 403

    data = request.get_json()

    user = None

    # 🔍 lookup
    if data.get("id"):
        user = users.getUserByID(data.get("id"))

    elif data.get("email"):
        user = users.getUserByEmail(data.get("email"))

    if not user:
        return "NOT_FOUND", 404

    session["user"] = {
        "email": user.email,
        "BIGY_ID": user.id
    }
    session["admin"] = "yes"
    session["impersonating"] = "yes"

    return "SUCCESS"

@app.route("/api/best-designs")
def get_best_designs():

    is_admin = is_admin_session()
    can_view_all = can_view_all_designs()
    mode = users.getMode()

    user_id = session.get("user", {}).get("BIGY_ID")

    if mode == "designing" and not can_view_all:
        return jsonify({
            "status": "designing",
            "mode": mode,
            "designs": [],
            "voted": [],
            "max_votes": users.MAX_VOTES_PER_USER,
        })

    try:
        page = int(request.args.get("page", 1))
    except:
        page = 1

    if page < 1:
        page = 1

    PER_PAGE = 6

    total = users.Design.query.count()
    max_page = max(1, math.ceil(total / PER_PAGE))
    page = min(page, max_page)

    query = (
        db.session.query(
            users.Design,
            sqlalchemy.func.count(users.Vote.id).label("votes")
        )
        .outerjoin(users.Vote, users.Vote.design_id == users.Design.id)
        .group_by(users.Design.id)
    )
    if mode == "finished":
        query = query.order_by(
            sqlalchemy.func.count(users.Vote.id).desc(),
            users.Design.id.desc()
        )
    else:
        query = query.order_by(
            users.Design.created_at.desc().nullslast(),
            users.Design.id.desc()
        )
    query = query.offset((page - 1) * PER_PAGE).limit(PER_PAGE)

    rows = query.all()

    result = []

    for d, votes in rows:

        if not d.front_key or not d.back_key:
            continue

        design_data = {
            "id": d.id,
            "uid": d.user_id,
            "color": d.color,

            "front": STORAGE.get_url(d.front_key),
            "back": STORAGE.get_url(d.back_key),
        }
        if is_admin or mode == "finished":
            design_data["votes"] = votes
        result.append(design_data)

    voted = []
    if user_id:
        voted = [
            vote.design_id
            for vote in users.Vote.query.filter_by(user_id=user_id).all()
        ]

    return jsonify({
        "status": "open",
        "page": page,
        "has_next": page < max_page,
        "designs": result,
        "voted": voted,
        "max_votes": users.MAX_VOTES_PER_USER,
        "mode": mode,
    })


@app.route("/api/vote", methods=["POST"])
def vote():

    # CSRF validation (expect token in header or form)
    token = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token")
    try:
        validate_csrf(token)
    except Exception:
        return "CSRF", 403

    user_id = session.get("user", {}).get("BIGY_ID")
    if not user_id:
        return "ERROR"

    if users.getMode() != "voting":
        return "LOCKED", 403

    data = request.get_json()
    design_id = data.get("design_id")

    if not design_id:
        return "ERROR"

    result = users.voteSwitch(user_id, design_id)
    if result == "limit":
        return "LIMIT", 400
    return result


if __name__ == "__main__": # DO NOT USE IN PRODUCTION
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

