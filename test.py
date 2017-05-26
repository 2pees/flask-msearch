import logging
import unittest
from unittest import TestCase
from tempfile import mkdtemp
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_msearch import Search
from sqlalchemy.ext.hybrid import hybrid_property

# do not clutter output with log entries
logging.disable(logging.CRITICAL)

db = None

titles = [
    'watch a movie', 'read a book', 'write a book', 'listen to a music',
    'I have a book'
]


class ModelSaveMixin(object):
    def save(self):
        if not self.id:
            db.session.add(self)
            db.session.commit()
        else:
            db.session.commit()

    def delete(self):
        db.session.delete(self)
        db.session.commit()


class SearchTestBase(TestCase):
    def setUp(self):
        class TestConfig(object):
            SQLALCHEMY_TRACK_MODIFICATIONS = True
            SQLALCHEMY_DATABASE_URI = 'sqlite://'
            DEBUG = True
            TESTING = True
            MSEARCH_INDEX_NAME = mkdtemp()
            # MSEARCH_BACKEND = 'simple'

        self.app = Flask(__name__)
        self.app.config.from_object(TestConfig())
        # we need this instance to be:
        #  a) global for all objects we share and
        #  b) fresh for every test run
        global db
        db = SQLAlchemy()
        self.search = Search(db=db)
        db.init_app(self.app)
        self.search.init_app(self.app)
        self.Post = None

    def init_data(self):
        if self.Post is None:
            self.fail('Post class not defined')
        with self.app.test_request_context():
            db.create_all()
            for (i, title) in enumerate(titles, 1):
                post = self.Post(title=title, content='content%d' % i)
                post.save()

    def tearDown(self):
        with self.app.test_request_context():
            db.drop_all()
            db.metadata.clear()


class TestMixin(object):
    def test_basic_search(self):
        with self.app.test_request_context():
            results = self.Post.query.msearch('book').all()
            self.assertEqual(len(results), 3)
            self.assertEqual(results[0].title, titles[1])
            self.assertEqual(results[1].title, titles[2])
            results = self.Post.query.msearch('movie').all()
            self.assertEqual(len(results), 1)

    def test_search_limit(self):
        with self.app.test_request_context():
            results = self.Post.query.msearch('book', limit=2).all()
            self.assertEqual(len(results), 2)

    def test_boolean_operators(self):
        with self.app.test_request_context():
            results = self.Post.query.msearch('book movie', or_=False).all()
            self.assertEqual(len(results), 0)
            results = self.Post.query.msearch('book movie', or_=True).all()
            self.assertEqual(len(results), 4)

    def test_delete(self):
        with self.app.test_request_context():
            self.Post.query.filter_by(title='read a book').delete()
            results = self.Post.query.msearch('book').all()
            self.assertEqual(len(results), 2)

    def test_update(self):
        with self.app.test_request_context():
            post = self.Post.query.filter_by(title='write a book').one()
            post.title = 'write a novel'
            post.save()
            results = self.Post.query.msearch('book').all()
            self.assertEqual(len(results), 2)


class TestSearch(TestMixin, SearchTestBase):
    def setUp(self):
        super(TestSearch, self).setUp()

        class Post(db.Model, ModelSaveMixin):
            __tablename__ = 'basic_posts'
            __searchable__ = ['title', 'content']

            id = db.Column(db.Integer, primary_key=True)
            title = db.Column(db.String(49))
            content = db.Column(db.Text)

            def __repr__(self):
                return '<Post:{}>'.format(self.title)

        self.Post = Post
        self.init_data()

    def test_field_search(self):
        with self.app.test_request_context():
            title1 = 'add one user'
            content1 = 'add one user content 1'
            title2 = 'add two user'
            content2 = 'add two content 2'
            post1 = self.Post(title=title1, content=content1)
            post1.save()

            post2 = self.Post(title=title2, content=content2)
            post2.save()

            results = self.Post.query.msearch('user').all()
            self.assertEqual(len(results), 2)

            results = self.Post.query.msearch('user', fields=['title']).all()
            self.assertEqual(len(results), 2)

            results = self.Post.query.msearch('user', fields=['content']).all()
            self.assertEqual(len(results), 1)


class TestSearchHybridProp(TestMixin, SearchTestBase):
    def setUp(self):
        super(TestSearchHybridProp, self).setUp()

        class PostHybrid(db.Model, ModelSaveMixin):
            __tablename__ = 'hybrid_posts'
            __searchable__ = ['fts_text']

            id = db.Column(db.Integer, primary_key=True)
            title = db.Column(db.String(49))
            content = db.Column(db.Text)

            @hybrid_property
            def fts_text(self):
                return ' '.join([self.title, self.content])

            @fts_text.expression
            def fts_text(cls):
                # sqlite don't support concat
                # return db.func.concat(cls.title, ' ', cls.content)
                return cls.title.op('||')(' ').op('||')(cls.content)

            def __repr__(self):
                return '<Post:{}>'.format(self.title)

        self.Post = PostHybrid
        self.init_data()

    def test_field_search(self):
        with self.app.test_request_context():
            title1 = 'add one user'
            content1 = 'add one user content 1'
            title2 = 'add two user'
            content2 = 'add two content 2'
            post1 = self.Post(title=title1, content=content1)
            post1.save()

            post2 = self.Post(title=title2, content=content2)
            post2.save()

            results = self.Post.query.msearch('user').all()
            self.assertEqual(len(results), 2)


class TestSearchRelation(SearchTestBase):
    def setUp(self):
        super(TestSearchRelation, self).setUp()

        class User(db.Model, ModelSaveMixin):
            __tablename__ = 'users'

            id = db.Column(db.Integer, primary_key=True)
            username = db.Column(db.String(49))

            def __repr__(self):
                return '<User:{}>'.format(self.username)

        class Post(db.Model, ModelSaveMixin):
            __tablename__ = 'posts'
            __searchable__ = ['title', 'user.username', 'replies.content']

            id = db.Column(db.Integer, primary_key=True)
            title = db.Column(db.String(49))
            content = db.Column(db.Text)

            user_id = db.Column(
                db.Integer, db.ForeignKey(
                    'users.id', ondelete="CASCADE"))
            user = db.relationship(
                User,
                backref=db.backref(
                    'topics', cascade='all,delete-orphan', lazy='dynamic'),
                lazy='joined',
                uselist=False)

            def __repr__(self):
                return '<Post:{}>'.format(self.title)

        class Reply(db.Model, ModelSaveMixin):
            __tablename__ = 'replies'

            id = db.Column(db.Integer, primary_key=True)
            content = db.Column(db.Text)

            post_id = db.Column(
                db.Integer, db.ForeignKey(
                    'posts.id', ondelete="CASCADE"))
            post = db.relationship(
                Post,
                backref=db.backref(
                    'replies', cascade='all,delete-orphan', lazy='dynamic'),
                lazy='joined',
                uselist=False)

            def __repr__(self):
                return '<Reply:{}>'.format(self.title)

        self.Post = Post
        self.Reply = Reply
        self.User = User
        self.init_data()

    def init_data(self):
        if self.Post is None:
            self.fail('Post class not defined')
        with self.app.test_request_context():
            db.create_all()
            for (i, title) in enumerate(titles, 1):
                user = self.User(username='username{}'.format(i))
                user.save()
                post = self.Post(
                    title=title, content='content%d' % i, user=user)
                post.save()

    def test_field_search(self):
        with self.app.test_request_context():
            title1 = 'add one user'
            content1 = 'add one user content 1'
            title2 = 'add two user'
            content2 = 'add two content 2'
            post1 = self.Post(title=title1, content=content1)
            post1.save()

            post2 = self.Post(title=title2, content=content2)
            post2.save()

            results = self.Post.query.msearch('user').all()
            self.assertEqual(len(results), 2)


if __name__ == '__main__':
    # test_list = ['test.TestSearch', 'test.TestSearchHybridProp',
    #              'test.TestSearchRelation']
    test_list = ['test.TestSearchRelation']
    suite = unittest.TestLoader().loadTestsFromNames(test_list)
    unittest.TextTestRunner(verbosity=1).run(suite)
