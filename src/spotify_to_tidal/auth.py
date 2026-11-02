#!/usr/bin/env python3

import os
import sys
import spotipy
import tidalapi
import webbrowser
import yaml

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

__all__ = [
    'open_spotify_session',
    'open_tidal_session'
]

#: Refuse to sleep longer than this for a single retry (Spotify dev-mode
#: quota exhaustion can otherwise park the process for most of a day).
MAX_RETRY_AFTER_SECONDS = 600


class _CappedRetry(Retry):
    """ urllib3 retry policy that refuses very long Retry-After waits. """

    def sleep(self, response=None):
        header = response.headers.get('Retry-After') if response is not None else None
        if header is not None:
            try:
                seconds = float(header)
            except ValueError:
                seconds = 0
            if seconds > MAX_RETRY_AFTER_SECONDS:
                raise requests.exceptions.RetryError(
                    f"Spotify rate limit exceeded for {int(seconds)}s "
                    "(development-mode quota). Try again later."
                )
        return super().sleep(response)


def _spotify_http_session() -> requests.Session:
    session = requests.Session()
    retry = _CappedRetry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=0.3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=frozenset(['GET', 'POST', 'PUT', 'DELETE']),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('http://', adapter)
    session.mount('https://', adapter)
    return session

SPOTIFY_SCOPES = ('playlist-read-private, user-library-read, '
                  'playlist-modify-public, playlist-modify-private, user-library-modify')


def _token_lacks_scopes(credentials_manager, scopes: str) -> bool:
    """ True when the cached token predates the scopes we now require. """
    try:
        token = credentials_manager.cache_handler.get_cached_token()
    except Exception:
        return False
    if not token:
        return False
    cached = set((token.get('scope') or '').split())
    required = set(scopes.replace(',', ' ').split())
    return not required.issubset(cached)

def _has_graphical_browser() -> bool:
    """ Whether opening a URL in a browser is likely to work.

    On a headless Linux host webbrowser.open() can fall back to a console
    browser, which blocks the login flow waiting for input.
    """
    if sys.platform in ('darwin', 'win32', 'cygwin'):
        return True
    return bool(os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))

def open_spotify_session(config) -> spotipy.Spotify:
    credentials_manager = spotipy.SpotifyOAuth(username=config['username'],
       scope=SPOTIFY_SCOPES,
       client_id=config['client_id'],
       client_secret=config['client_secret'],
       redirect_uri=config['redirect_uri'],
       requests_timeout=2,
       open_browser=config.get('open_browser', True))
    if _token_lacks_scopes(credentials_manager, SPOTIFY_SCOPES):
        print("Cached Spotify token is missing write scopes, re-authenticating")
        cache_path = getattr(credentials_manager.cache_handler, 'cache_path', None)
        if cache_path and os.path.exists(cache_path):
            os.remove(cache_path)
    try:
        credentials_manager.get_access_token(as_dict=False)
    except spotipy.SpotifyOauthError:
        sys.exit(f"Error opening Spotify session; could not get token for username: {config['username']}")

    return spotipy.Spotify(oauth_manager=credentials_manager, requests_session=_spotify_http_session())

def open_tidal_session(config = None) -> tidalapi.Session:
    try:
        with open('.session.yml', 'r') as session_file:
            previous_session = yaml.safe_load(session_file)
    except OSError:
        previous_session = None

    if config:
        session = tidalapi.Session(config=config)
    else:
        session = tidalapi.Session()
    if previous_session:
        try:
            if session.load_oauth_session(token_type= previous_session['token_type'],
                                   access_token=previous_session['access_token'],
                                   refresh_token=previous_session['refresh_token'] ):
                return session
        except Exception as e:
            print("Error loading previous Tidal Session: \n" + str(e) )

    login, future = session.login_oauth()
    print('Login with the webbrowser: ' + login.verification_uri_complete)
    url = login.verification_uri_complete
    if not url.startswith('https://'):
        url = 'https://' + url
    if _has_graphical_browser():
        webbrowser.open(url)
    future.result()
    with open('.session.yml', 'w') as f:
        yaml.dump( {'session_id': session.session_id,
                   'token_type': session.token_type,
                   'access_token': session.access_token,
                   'refresh_token': session.refresh_token}, f )
    return session


