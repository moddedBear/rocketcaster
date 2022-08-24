import os
from datetime import datetime
import typing
import re
import requests
import jinja2
from jetforce import JetforceApplication, Request, Response, Status, RateLimiter
from jetforce.app.base import EnvironDict, RoutePattern, RouteHandler
from twisted.internet.threads import deferToThread
from .models import User, Certificate, Post, Comment, Notification
import podcastindex

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), 'templates')

template_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(TEMPLATE_DIR),
    undefined=jinja2.StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)

# $PODCAST_INDEX_API_KEY and $PODCAST_INDEX_API_SECRET
pi_config = podcastindex.get_config_from_env()
index = podcastindex.init(pi_config)

RESERVED_NAMES = ['admin', 'all']
MAX_FILE_SIZE = 1024 * 1024 * 200  # 200MB max file size for proxied episodes

proxy_rate_limiter = RateLimiter('2/m')


def readable_timedelta(value):
    minutes = int(value.total_seconds() // 60)
    if minutes <= 1:
        return "1 minute"
    elif minutes < 60:
        return f"{minutes} minutes"

    hours = minutes // 60
    if hours == 1:
        return "1 hour"
    elif hours < 24:
        return f"{hours} hours"

    days = hours // 24
    if days == 1:
        return '1 day'
    elif days < 30:
        return f'{days} days'

    months = days // 30
    if months == 1:
        return '1 month'
    elif months < 12:
        return f'{months} months'

    years = months // 12
    if years == 1:
        return '1 year'
    else:
        return f'{years} years'


def readable_duration(value):
    minutes = value // 60
    if minutes < 60:
        return f'{minutes} min'
    hours = minutes / 60
    return f'{hours:0.1f} hours'


def timestamp_to_date(value):
    return datetime.fromtimestamp(value).strftime('%Y-%m-%d')


def strip_formatting_main(text):
    regex = r"(^(#+)|(=>)|(```)|(\*)|(>)|(^\n))"
    return re.sub(regex, '', text, flags=re.MULTILINE)


def strip_formatting_post(text):
    regex = r"(^(#+)|(```))"
    return re.sub(regex, '', text, flags=re.MULTILINE)


def strip_html(text):
    p_regex = r"(?<!^)<p>"
    br_regex = r"(?<!^)<br ?/?>"
    strip_regex = r"</? ?[a-zA-Z0-9]* ?/?>"
    text = re.sub(r"\n", '', text)
    text = re.sub(p_regex, '\n\n', text)
    text = re.sub(br_regex, '\n', text)
    text = re.sub(strip_regex, '', text)
    return text


template_env.filters['readable_timedelta'] = readable_timedelta
template_env.filters['readable_duration'] = readable_duration
template_env.filters['timestamp_to_date'] = timestamp_to_date
template_env.filters['strip_formatting_main'] = strip_formatting_main
template_env.filters['strip_formatting_post'] = strip_formatting_post
template_env.filters['strip_html'] = strip_html


def parse_mentions(post=None, comment=None):
    regex = "(?:^|[^\w\d])(?:@)([a-zA-Z0-9_-]+)"
    if post is not None:
        usernames = re.findall(regex, post.content)
        for username in usernames:
            try:
                user = User.select().where(User.name ** username).get()
            except:
                user = None
            if user is not None:
                Notification.create(
                    user=user,
                    post=post,
                    message=f"{post.author.name} mentioned you in a post",
                    created=datetime.now()
                )
    elif comment is not None:
        usernames = re.findall(regex, comment.content)
        for username in usernames:
            if str.lower(username) == 'all':
                try:
                    users = User.get_commenters(comment.post.id)
                except:
                    users = []
                for user in users:
                    if user == comment.post.author or user == comment.author:
                        continue
                    Notification.create(
                        user=user,
                        comment=comment,
                        message=f"{comment.author.name} mentioned you in a comment by tagging @all",
                        created=datetime.now()
                    )
            else:
                try:
                    user = User.select().where(User.name ** username).get()
                except:
                    user = None
                if user is not None:
                    Notification.create(
                        user=user,
                        comment=comment,
                        message=f"{comment.author.name} mentioned you in a comment",
                        created=datetime.now()
                    )


def render_template(name: str, *args, **kwargs) -> str:
    return template_env.get_template(name).render(*args, **kwargs)


class AuthenticatedRequest(Request):
    user: User
    cert: Certificate

    def __init__(self, environ: EnvironDict, cert: Certificate):
        super().__init__(environ)
        if cert:
            self.cert = cert
            self.user = cert.user
        else:
            self.cert = None
            self.user = None

    def render_template(self, name: str, *args, **kwargs) -> str:
        kwargs['request'] = self
        return render_template(name, *args, **kwargs)


class RocketCasterApplication(JetforceApplication):
    def auth_route(self, path):
        route_pattern = RoutePattern(path)

        def wrap(func: RouteHandler):
            authenticated_func = authenticated_route(func)
            app.routes.append((route_pattern, authenticated_func))
            return func

        return wrap

    def optional_auth_route(self, path):
        route_pattern = RoutePattern(path)

        def wrap(func: RouteHandler):
            authenticated_func = optional_authenticated_route(func)
            app.routes.append((route_pattern, authenticated_func))
            return func

        return wrap


def authenticated_route(func: RouteHandler):
    def wrapped(request: Request, **kwargs):
        if 'REMOTE_USER' not in request.environ:
            return Response(Status.CLIENT_CERTIFICATE_REQUIRED, "You must attach a client certificate to do this.")
        else:
            fingerprint = typing.cast(
                str, request.environ['TLS_CLIENT_HASH_B64'])

        cert = User.login(fingerprint)
        if cert is None:
            return Response(Status.REDIRECT_TEMPORARY, '/register')

        request = AuthenticatedRequest(request.environ, cert)
        response = func(request, **kwargs)
        return response

    return wrapped


def optional_authenticated_route(func: RouteHandler):
    def wrapped(request: Request, **kwargs):
        if 'REMOTE_USER' not in request.environ:
            cert = None
        else:
            fingerprint = typing.cast(
                str, request.environ['TLS_CLIENT_HASH_B64'])
            cert = User.login(fingerprint)
        request = AuthenticatedRequest(request.environ, cert)
        response = func(request, **kwargs)
        return response

    return wrapped


app = RocketCasterApplication()


@app.optional_auth_route('')
def index_view(request):
    posts = Post.most_recent()
    body = render_template('index.gmi', user=request.user,
                           posts=posts, now=datetime.now())
    return Response(Status.SUCCESS, 'text/gemini', body)


@app.route('/podcast/(?P<feed_id>[0-9]+)')
def podcast_view(request, feed_id: str):
    feed_result = index.podcastByFeedId(feedId=feed_id)
    feed = feed_result['feed']
    if not feed:
        return Response(Status.NOT_FOUND)
    episodes_result = index.episodesByFeedId(
        feedId=feed_id, max_results=feed['episodeCount'])
    episodes = episodes_result['items']

    body = render_template(
        'podcast.gmi', title=feed['title'], author=feed['author'], description=feed['description'], feed=feed['url'], link=feed['link'], categories=feed['categories'].values(), episodes=episodes)
    return Response(Status.SUCCESS, 'text/gemini', body)


@app.route('/episode/(?P<episode_id>[0-9]+)')
def episode_view(request, episode_id: str):
    episode_result = index.episodeById(id=episode_id)
    episode = episode_result['episode']
    if not episode:
        return Response(Status.NOT_FOUND)
    feed_result = index.podcastByFeedId(feedId=episode['feedId'])
    feed = feed_result['feed']

    all_recent_posts = Post.most_recent()
    recent_post = None
    for post in all_recent_posts:
        if post.episode_id == episode_id:
            recent_post = post
            break

    body = render_template('episode.gmi', feed_title=feed['title'], author=feed['author'], episode_title=episode['title'], season=episode['season'], episode_num=episode['episode'],
                           episode_url=episode['enclosureUrl'], duration=episode['duration'], published=episode['datePublishedPretty'], description=episode['description'], feed_id=feed['id'], episode_id=episode_id, recent_post=recent_post, now=datetime.now())
    return Response(Status.SUCCESS, 'text/gemini', body)


@app.route('/episode/(?P<episode_id>[0-9]+)/play')
@proxy_rate_limiter.apply
def episode_play_view(request, episode_id: str):

    def download_episode(url):
        def get_content(url):
            return requests.get(url).content

        yield deferToThread(get_content, url)

    episode_result = index.episodeById(id=episode_id)
    episode = episode_result['episode']
    if not episode:
        return Response(Status.NOT_FOUND)
    episode_url = episode['enclosureUrl']

    r = requests.head(episode_url, allow_redirects=True)
    if r.status_code == 200:
        # check file size
        if int(r.headers['content-length']) > MAX_FILE_SIZE:
            return Response(Status.PROXY_ERROR, 'Episode file size is too large')
        return Response(Status.SUCCESS, r.headers['content-type'], download_episode(episode_url))
    else:
        return Response(Status.PROXY_ERROR, 'Error downloading episode')


@app.route('/search')
def search_view(request):
    if not request.query:
        return Response(Status.INPUT, "Enter a search term")

    search_result = index.search(request.query)

    body = render_template(
        'search.gmi', count=search_result['count'], search_term=request.query, results=search_result['feeds'])
    return Response(Status.SUCCESS, 'text/gemini', body)


@app.route('/about')
def about_view(request):
    body = render_template('about.gmi')
    return Response(Status.SUCCESS, 'text/gemini', body)


@app.route('/robots.txt')
def robots_view(request):
    body = render_template('robots.txt')
    return Response(Status.SUCCESS, 'text/plain', body)


@app.route('/register')
def register_view(request):
    if 'REMOTE_USER' not in request.environ:
        return Response(Status.CLIENT_CERTIFICATE_REQUIRED, "You must attach a client certificate to register. Look up help for your browser on how to do so.")

    cert = request.environ['client_certificate']
    fingerprint = request.environ['TLS_CLIENT_HASH_B64']
    if Certificate.select().where(Certificate.fingerprint == fingerprint).exists():
        return Response(Status.CERTIFICATE_NOT_AUTHORISED, "A user with the given certificate already exists.")

    if not request.query:
        return Response(Status.INPUT, "Choose a username")
    username = request.query

    if len(username) > 32:
        return Response(Status.INPUT, "Username must be less than 32 characters")
    if not username.isascii() or re.search('[^a-zA-Z0-9_-]', username):
        return Response(Status.INPUT, "Username contains invalid characters. Only letters, numbers, underscores, and hyphens are allowed.")
    if User.select().where(User.name ** username).exists():
        return Response(Status.INPUT, "Username is already taken")
    if str.lower(username) in RESERVED_NAMES:
        return Response(Status.INPUT, "Username is reserved")

    user = User.register(name=username)
    Certificate.create(
        user=user,
        fingerprint=fingerprint,
        subject=cert.subject.rfc4514_string(),
        not_valid_before=cert.not_valid_before,
        not_valid_after=cert.not_valid_after,
    )

    return Response(Status.REDIRECT_TEMPORARY, '/')


@app.auth_route('/share/(?P<episode_id>[0-9]+)')
def share_view(request, episode_id: str):
    # check for recent posts of the same episode
    recent_posts = Post.most_recent()
    for post in recent_posts:
        if post.episode_id == episode_id:
            return Response(Status.REDIRECT_TEMPORARY, f'/post/{post.id}')

    username = request.user.name
    if not request.query:
        return Response(Status.INPUT, f"Starting discussion as {username}. Enter a comment.")
    content = request.query

    episode_result = index.episodeById(id=episode_id)
    episode = episode_result['episode']
    if not episode:
        return Response(Status.NOT_FOUND)
    episode_title = episode['title']
    feed_result = index.podcastByFeedId(feedId=episode['feedId'])
    feed = feed_result['feed']
    if not feed:
        return Response(Status.NOT_FOUND)
    podcast_title = feed['title']
    podcast_id = feed['id']

    post = Post.create(
        author=request.user,
        episode_id=episode_id,
        episode_title=episode_title,
        podcast_id=podcast_id,
        podcast_title=podcast_title,
        content=content,
        created=datetime.now()
    )
    parse_mentions(post=post)
    return Response(Status.REDIRECT_TEMPORARY, f'/post/{post.id}')


@app.optional_auth_route('/post/(?P<post_id>[0-9]+)')
def post_view(request, post_id: str):
    try:
        post = Post.get(Post.id == post_id)
    except Post.DoesNotExist:
        return Response(Status.NOT_FOUND, "Post not found")
    comments = post.comments.order_by(Comment.created.desc())
    body = render_template('post.gmi', user=request.user, post=post,
                           comments=comments, now=datetime.now())
    return Response(Status.SUCCESS, 'text/gemini', body)


@app.auth_route('/comment/(?P<post_id>[0-9]+)')
def comment_view(request, post_id: str):
    username = request.user.name
    if not request.query:
        return Response(Status.INPUT, f"Commenting as {username}")
    content = request.query

    try:
        post = Post.get(Post.id == post_id)
    except Post.DoesNotExist:
        return Response(Status.NOT_FOUND, "Post not found")
    comment = Comment.create(
        author=request.user,
        post=post,
        content=content,
        created=datetime.now()
    )

    # notify post author
    if post.author != comment.author:
        Notification.create(
            user=post.author,
            comment=comment,
            message=f"{comment.author.name} commented on {post.episode_title}",
            created=datetime.now()
        )

    parse_mentions(comment=comment)
    return Response(Status.REDIRECT_TEMPORARY, f'/post/{post_id}')


@app.auth_route('/post/(?P<post_id>[0-9]+)/delete')
def post_delete_view(request, post_id: str):
    try:
        post = Post.get(Post.id == post_id)
    except Post.DoesNotExist:
        return Response(Status.NOT_FOUND, "Post not found")
    author_certificate = Certificate.get(Certificate.user == post.author)
    if not author_certificate.fingerprint == request.environ['TLS_CLIENT_HASH_B64']:
        return Response(Status.CERTIFICATE_NOT_AUTHORISED, "You don't have permission to do that.")

    if not request.query or str.lower(request.query) != 'yes':
        return Response(Status.INPUT, 'Are you sure you want to delete this post? Type "yes" to confirm.')

    Notification.delete().where((Notification.post == post) |
                                (Notification.comment << post.comments)).execute()
    Comment.delete().where(Comment.post == post).execute()
    post.delete_instance(recursive=True)
    return Response(Status.REDIRECT_TEMPORARY, '/')


@app.auth_route('/comment/(?P<comment_id>[0-9]+)/delete')
def comment_delete_view(request, comment_id: str):
    try:
        comment = Comment.get(Comment.id == comment_id)
    except Comment.DoesNotExist:
        return Response(Status.NOT_FOUND, "Comment not found")
    author_certificate = Certificate.get(Certificate.user == comment.author)
    if not author_certificate.fingerprint == request.environ['TLS_CLIENT_HASH_B64']:
        return Response(Status.CERTIFICATE_NOT_AUTHORISED, "You don't have permission to do that.")

    if not request.query or str.lower(request.query) != 'yes':
        return Response(Status.INPUT, 'Are you sure you want to delete this comment? Type "yes" to confirm.')

    post_id = comment.post.id
    Notification.delete().where(Notification.comment == comment).execute()
    comment.delete_instance(recursive=True)
    return Response(Status.REDIRECT_TEMPORARY, f'/post/{post_id}')


@app.auth_route('/notifications')
def notifications_view(request):
    notifications = Notification.select().where(
        Notification.user == request.user)
    body = render_template('notifications.gmi',
                           user=request.user, notifications=notifications, now=datetime.now())
    return Response(Status.SUCCESS, 'text/gemini', body)


@app.auth_route('/notifications/clear')
def notifications_clear_view(request):
    Notification.delete().where(Notification.user == request.user).execute()
    return Response(Status.REDIRECT_TEMPORARY, '/')


@app.route('/archive')
def archive_view(request):
    posts = Post.most_recent(count=None)
    body = render_template('archive.gmi', posts=posts)
    return Response(Status.SUCCESS, 'text/gemini', body)
