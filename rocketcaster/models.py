from datetime import datetime
from peewee import *


def init_db(db_path):
    db = SqliteDatabase(db_path)
    model_list = [User, Certificate, Post, Comment, Notification]
    db.bind(model_list)
    db.create_tables(model_list)


class User(Model):
    name = TextField(unique=True)
    created = DateTimeField()

    @classmethod
    def register(cls, name):
        try:
            user = cls.create(
                name=name,
                created=datetime.now()
            )
            return user
        except IntegrityError:  # username taken
            return None

    @classmethod
    def login(cls, fingerprint):
        query = Certificate.select().where(Certificate.fingerprint == fingerprint)

        try:
            cert = query.get()
        except Certificate.DoesNotExist:
            cert = None

        return cert

    @classmethod
    def get_commenters(cls, post_id):
        query = User.select(User).join(Comment).where(
            Comment.post == post_id).distinct()
        return query


class Certificate(Model):
    user = ForeignKeyField(User, backref='certificate')
    fingerprint = TextField(unique=True, index=True)
    subject = TextField(null=True)
    not_valid_before = DateTimeField(null=True)
    not_valid_after = DateTimeField(null=True)


class Post(Model):
    author = ForeignKeyField(User, backref='posts')
    episode_id = TextField()
    episode_title = TextField()
    podcast_id = TextField()
    podcast_title = TextField()
    content = TextField()
    created = DateTimeField()

    @classmethod
    def most_recent(cls, count=15):
        if count != None:
            return Post.select().order_by(Post.created.desc()).limit(count)
        else:
            return Post.select().order_by(Post.created.desc())


class Comment(Model):
    author = ForeignKeyField(User, backref='comments')
    post = ForeignKeyField(Post, backref='comments')
    content = TextField()
    created = DateTimeField()


class Notification(Model):
    user = ForeignKeyField(User, backref='notifications')
    message = TextField()
    post = ForeignKeyField(Post, backref='mentions', null=True)
    comment = ForeignKeyField(Comment, backref='mentions', null=True)
    created = DateTimeField()

    def clear(cls, user):
        Notification.delete().where(Notification.user == user).execute()
