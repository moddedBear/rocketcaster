import os
from datetime import datetime
import jinja2
from jetforce import JetforceApplication, Request, Response, Status
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


def readable_timedelta(value):
    minutes = int(value.total_seconds() // 60)
    if minutes == 1:
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


template_env.filters['readable_timedelta'] = readable_timedelta
template_env.filters['readable_duration'] = readable_duration
template_env.filters['timestamp_to_date'] = timestamp_to_date


def render_template(name: str, *args, **kwargs) -> str:
    return template_env.get_template(name).render(*args, **kwargs)


app = JetforceApplication()


@app.route('')
def index_view(request):
    body = render_template('index.gmi')
    return Response(Status.SUCCESS, 'text/gemini', body)


@app.route('/podcast/(?P<feed_id>[0-9]+)')
def podcast_view(request, feed_id: str):
    feed_result = index.podcastByFeedId(feedId=feed_id)
    feed = feed_result['feed']
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
    feed_result = index.podcastByFeedId(feedId=episode['feedId'])
    feed = feed_result['feed']

    body = render_template('episode.gmi', feed_title=feed['title'], author=feed['author'], episode_title=episode['title'], season=episode['season'], episode_num=episode['episode'],
                           episode_url=episode['enclosureUrl'], duration=episode['duration'], published=episode['datePublishedPretty'], description=episode['description'], feed_id=feed['id'])
    return Response(Status.SUCCESS, 'text/gemini', body)


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
