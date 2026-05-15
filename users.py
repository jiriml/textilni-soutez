from extensions import db


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

class Design(db.Model):
    __tablename__ = "designs"

    id = db.Column(db.BigInteger, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey("users.id"))

    front_key = db.Column(db.String)
    back_key = db.Column(db.String)
    color = db.Column(db.String)

def can_upload(user_id):
    return Design.query.filter_by(user_id=user_id).count() < 3

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

    db.session.delete(design)
    db.session.commit()

    return True, "success"


def get_user_designs(user_id):
    return Design.query.filter_by(user_id=user_id).all()
