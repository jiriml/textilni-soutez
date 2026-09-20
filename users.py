import datetime
import os

from extensions import db


try:
    MAX_VOTES_PER_USER = max(1, int(os.environ.get("MAX_VOTES_PER_USER", "1")))
except ValueError:
    MAX_VOTES_PER_USER = 1


class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.BigInteger, primary_key=True)

    email = db.Column(
        db.String,
        unique=True,
        nullable=False
    )

def getUserByEmail(email):

    return User.query.filter_by(
        email=email
    ).first()


def getUserByID(user_id):

    return db.session.get(
        User,
        user_id
    )


def createUser(email):

    user = User(email=email)

    db.session.add(user)
    db.session.commit()

    return user


def getOrCreateUser(email):

    user = getUserByEmail(email)

    if user:
        return user

    return createUser(email)

# Design
class Design(db.Model):
    __tablename__ = "designs"

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"))

    front_key = db.Column(db.String)
    back_key = db.Column(db.String)
    color = db.Column(db.String)
    created_at = db.Column(
        db.DateTime,
        nullable=True,
        default=datetime.datetime.utcnow
    )

def can_upload(user_id):
    return Design.query.filter_by(user_id=user_id).count() < 93

def upload_design(user_id, front_file, back_file, color, storage):
    try:
        if not can_upload(user_id):
            return None, "max_reached"

        design = Design(user_id=user_id)
        db.session.add(design)
        db.session.commit()

        front_key = f"{user_id}/{design.id}/front.png"
        back_key = f"{user_id}/{design.id}/back.png"

        storage.upload_image(front_file, front_key)
        storage.upload_image(back_file, back_key)

        design.front_key = front_key
        design.back_key = back_key
        design.color = color

        db.session.commit()

        return design, None
    except Exception as e:

        print(e)

        db.session.delete(design)
        db.session.commit()

        return None, "upload_failed"

def delete_design(design_id, storage=None):

    design = Design.query.filter_by(id=design_id).first()

    if not design:
        return False, "not_found"

    try:
        if storage and design.front_key:
            storage.client.delete_object(
                Bucket=storage.bucket,
                Key=design.front_key
            )

        if storage and design.back_key:
            storage.client.delete_object(
                Bucket=storage.bucket,
                Key=design.back_key
            )

    except Exception as e:
        print("Storage delete failed:", e)
        return False, "storage_error"

    Vote.query.filter_by(design_id=design_id).delete(
        synchronize_session=False
    )
    db.session.delete(design)
    db.session.commit()

    return True, "success"


def get_user_designs(user_id):
    return Design.query.filter_by(user_id=user_id).all()


# AppConfig

class Settings(db.Model):
    __tablename__ = "settings"
    id = db.Column(
        db.Integer,
        primary_key=True
    )

    voting_open = db.Column(
        db.Boolean,
        nullable=False,
        default=False
    )

    mode = db.Column(
        db.String(20),
        nullable=False,
        default="designing"
    )

MODES = {"designing", "voting", "finished"}


def setMode(mode):
    if mode not in MODES:
        return False

    settings = Settings.query.first()

    if not settings:
        settings = Settings(voting_open=mode == "voting", mode=mode)
        db.session.add(settings)
    else:
        settings.mode = mode
        settings.voting_open = mode == "voting"

    db.session.commit()
    return True


def getMode():
    try:
        settings = Settings.query.first()
        if not settings:
            setMode("designing")
            return "designing"
        return settings.mode
    except:
        return "designing"


def setVoting(yesorno):
    return setMode("voting" if yesorno else "designing")


def getVoting():
    return getMode() == "voting"
    

class Vote(db.Model):
    __tablename__ = "votes"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"), nullable=False)
    design_id = db.Column(db.BigInteger, db.ForeignKey("designs.id"))
    __table_args__ = (
    db.UniqueConstraint("user_id", "design_id"),
    )


def voteSwitch(userId, designId):


    design = Design.query.get(designId)
    if not design:
        return "ERROR"

    if design.user_id == userId:
        return "ERROR"

    existing = Vote.query.filter_by(user_id=userId, design_id=designId).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        return "unvoted"

    vote_count = Vote.query.filter_by(user_id=userId).count()
    if vote_count >= MAX_VOTES_PER_USER:
        return "limit"

    db.session.add(Vote(user_id=userId, design_id=designId))
    db.session.commit()
    return "voted"