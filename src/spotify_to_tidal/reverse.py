#!/usr/bin/env python3
""" Transfer Tidal playlists and favorites to Spotify. """

import asyncio
import json
import time
from typing import Dict, List, Optional, Sequence

import spotipy
import tidalapi
from tqdm import tqdm

from .sync import match
from .tidalapi_patch import get_all_favorites, get_all_playlists, get_all_playlist_tracks

SPOTIFY_PLAYLIST_CHUNK = 100
SPOTIFY_LIBRARY_CHUNK = 50
SPOTIFY_SEARCH_LIMIT = 10
SEARCH_DELAY_SECONDS = 0.1


def _escape_query(value: str) -> str:
    """ Strip characters that would break a Spotify field filter. """
    return value.replace('"', ' ').replace('\\', ' ').strip()


def _chunks(items: Sequence, size: int):
    for start in range(0, len(items), size):
        yield items[start:start + size]


class SpotifyTrackCache:
    """ Maps Tidal track ids to the best matching Spotify track (or None).

    Persisted to disk so a run that hits Spotify's quota can resume without
    searching the same tracks again.
    """

    def __init__(self, path: str = '.cache-spotify.json'):
        self.path = path
        self._data: Dict[int, Optional[dict]] = {}
        try:
            with open(path, encoding='utf-8') as cache_file:
                self._data = {int(key): value for key, value in json.load(cache_file).items()}
        except (OSError, ValueError):
            self._data = {}

    def get(self, tidal_id) -> Optional[dict]:
        return self._data.get(tidal_id)

    def has(self, tidal_id) -> bool:
        return tidal_id in self._data

    def insert(self, tidal_id, spotify_track: Optional[dict]):
        self._data[tidal_id] = spotify_track

    def save(self):
        try:
            with open(self.path, 'w', encoding='utf-8') as cache_file:
                json.dump({str(key): value for key, value in self._data.items()}, cache_file)
        except OSError as error:
            print(f"Could not write Spotify match cache: {error}")


def search_spotify_for_track(tidal_track: tidalapi.Track, spotify_session: spotipy.Spotify) -> Optional[dict]:
    """ Find the Spotify track that corresponds to a Tidal track. """
    artists = getattr(tidal_track, 'artists', None) or []
    artist_name = artists[0].name if artists else ''
    name = _escape_query(tidal_track.name)
    queries = [
        f'track:"{name}" artist:"{_escape_query(artist_name)}"',
        f'{name} {_escape_query(artist_name)}',
    ]
    seen = set()
    for query in queries:
        try:
            results = spotify_session.search(q=query, type='track', limit=SPOTIFY_SEARCH_LIMIT)
        except spotipy.SpotifyException:
            raise
        for candidate in results['tracks']['items']:
            if not candidate or candidate['id'] in seen:
                continue
            seen.add(candidate['id'])
            if match(tidal_track, candidate):
                return candidate
        time.sleep(SEARCH_DELAY_SECONDS)
    return None


def plan_playlist_update(current: Sequence[str], desired: Sequence[str]) -> dict:
    """ Work out the smallest write needed to turn current into desired. """
    current, desired = list(current), list(desired)
    if current == desired:
        return {'action': 'none', 'items': []}
    if desired[:len(current)] == current:
        return {'action': 'append', 'items': desired[len(current):]}
    return {'action': 'replace', 'items': desired}


def apply_playlist_update(spotify_session: spotipy.Spotify, playlist_id: str, plan: dict, dry_run: bool = False):
    """ Apply a plan from plan_playlist_update to a Spotify playlist. """
    action, items = plan['action'], plan['items']
    if action == 'none':
        print("No changes to write to Spotify playlist")
        return
    if dry_run:
        print(f"[dry-run] would {action} {len(items)} track(s) on Spotify playlist {playlist_id}")
        return
    if action == 'append':
        for chunk in _chunks(items, SPOTIFY_PLAYLIST_CHUNK):
            spotify_session.playlist_add_items(playlist_id, chunk)
        return
    # A replace request accepts at most 100 uris, so write the first page and
    # append the remainder afterwards.
    spotify_session.playlist_replace_items(playlist_id, items[:SPOTIFY_PLAYLIST_CHUNK])
    for chunk in _chunks(items[SPOTIFY_PLAYLIST_CHUNK:], SPOTIFY_PLAYLIST_CHUNK):
        spotify_session.playlist_add_items(playlist_id, chunk)


def get_spotify_playlist_tracks(spotify_session: spotipy.Spotify, playlist_id: str) -> List[dict]:
    tracks, offset = [], 0
    while True:
        page = spotify_session.playlist_items(playlist_id, offset=offset, additional_types=('track',))
        for entry in page['items']:
            track = entry.get('item') or entry.get('track')
            if track and track.get('id'):
                tracks.append(track)
        if not page['next']:
            break
        offset += page['limit']
    return tracks


def get_spotify_playlist_track_ids(spotify_session: spotipy.Spotify, playlist_id: str) -> List[str]:
    return [track['id'] for track in get_spotify_playlist_tracks(spotify_session, playlist_id)]


def match_existing_tracks(tidal_tracks: Sequence[tidalapi.Track],
                          spotify_tracks: Sequence[dict]) -> Dict[int, dict]:
    """ Pair Tidal tracks with Spotify tracks already in the destination playlist.

    Reusing these avoids a search request per track, which matters because
    Spotify's development-mode quota is small.
    """
    used = set()
    matched: Dict[int, dict] = {}
    for tidal_track in tidal_tracks:
        for candidate in spotify_tracks:
            if candidate['id'] in used:
                continue
            if match(tidal_track, candidate):
                matched[tidal_track.id] = candidate
                used.add(candidate['id'])
                break
    return matched



def get_owned_spotify_playlists(spotify_session: spotipy.Spotify) -> List[dict]:
    me = spotify_session.current_user()['id']
    playlists, offset = [], 0
    while True:
        page = spotify_session.current_user_playlists(limit=50, offset=offset)
        playlists.extend([p for p in page['items'] if p and p['owner']['id'] == me])
        if not page['next']:
            break
        offset += page['limit']
    return playlists


def get_tidal_playlists(tidal_session: tidalapi.Session) -> List[tidalapi.Playlist]:
    return asyncio.run(get_all_playlists(tidal_session.user))


def find_spotify_playlist_by_name(spotify_playlists: Sequence[dict], name: str) -> Optional[dict]:
    for playlist in spotify_playlists:
        if playlist['name'] == name:
            return playlist
    return None


def create_spotify_playlist(spotify_session: spotipy.Spotify, name: str, description: str = '') -> dict:
    return spotify_session.current_user_playlist_create(
        name=name, public=False, description=description or ''
    )


def resolve_spotify_tracks(tidal_tracks: Sequence[tidalapi.Track], spotify_session: spotipy.Spotify,
                           cache: SpotifyTrackCache, description: str,
                           existing: Optional[Dict[int, dict]] = None) -> List[dict]:
    found = []
    existing = existing or {}
    for tidal_track in tqdm(tidal_tracks, desc=description):
        if not tidal_track.available:
            continue
        if tidal_track.id in existing:
            found.append(existing[tidal_track.id])
            continue
        cached = cache.get(tidal_track.id)
        if cache.has(tidal_track.id):
            if cached:
                found.append(cached)
            continue
        spotify_track = search_spotify_for_track(tidal_track, spotify_session)
        cache.insert(tidal_track.id, spotify_track)
        if spotify_track:
            found.append(spotify_track)
    return found


def sync_playlist_to_spotify(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session,
                             tidal_playlist: tidalapi.Playlist, spotify_playlist: Optional[dict],
                             cache: SpotifyTrackCache, dry_run: bool = False) -> dict:
    """ Sync one Tidal playlist into Spotify. Returns a small summary dict. """

    tidal_tracks = asyncio.run(get_all_playlist_tracks(tidal_playlist))
    if not tidal_tracks:
        print("Tidal playlist is empty, skipping")
        return {'name': tidal_playlist.name, 'matched': 0, 'missing': 0, 'written': 0}

    existing_tracks = (get_spotify_playlist_tracks(spotify_session, spotify_playlist['id'])
                       if spotify_playlist else [])
    already_matched = match_existing_tracks(tidal_tracks, existing_tracks)

    spotify_tracks = resolve_spotify_tracks(
        tidal_tracks, spotify_session, cache, f"Searching Spotify for tracks in '{tidal_playlist.name}'",
        existing=already_matched
    )
    cache.save()
    if not spotify_tracks:
        print("No matching tracks found on Spotify, skipping")
        return {'name': tidal_playlist.name, 'matched': 0, 'missing': len(tidal_tracks), 'written': 0}

    uris, seen = [], set()
    for track in spotify_tracks:
        if track['uri'] in seen:
            continue
        seen.add(track['uri'])
        uris.append(track['uri'])

    if spotify_playlist is None:
        if dry_run:
            print(f"[dry-run] would create Spotify playlist '{tidal_playlist.name}' with {len(uris)} track(s)")
            return {'name': tidal_playlist.name, 'matched': len(uris), 'missing': len(tidal_tracks) - len(spotify_tracks), 'written': 0}
        spotify_playlist = create_spotify_playlist(
            spotify_session, tidal_playlist.name, getattr(tidal_playlist, 'description', '') or ''
        )
        print(f"Created Spotify playlist '{tidal_playlist.name}'")

    current = [track['id'] for track in existing_tracks]
    desired_ids = [uri.split(':')[-1] for uri in uris]
    plan = plan_playlist_update(current, desired_ids)
    apply_playlist_update(spotify_session, spotify_playlist['id'], plan, dry_run)
    return {
        'name': tidal_playlist.name,
        'matched': len(uris),
        'missing': len(tidal_tracks) - len(spotify_tracks),
        'written': 0 if plan['action'] == 'none' else len(plan['items']),
    }


def sync_favorites_to_spotify(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session,
                              cache: SpotifyTrackCache, dry_run: bool = False) -> dict:
    """ Copy Tidal favorite tracks into the Spotify liked songs library. """

    print("Loading favorite tracks from Tidal")
    tidal_tracks = asyncio.run(get_all_favorites(tidal_session.user.favorites, order='DATE'))
    spotify_tracks = resolve_spotify_tracks(
        tidal_tracks, spotify_session, cache, "Searching Spotify for favorite tracks"
    )
    cache.save()
    ids = [track['id'] for track in spotify_tracks]
    if not ids:
        print("No matching favorite tracks found on Spotify")
        return {'matched': 0, 'missing': len(tidal_tracks), 'written': 0}
    if dry_run:
        print(f"[dry-run] would add {len(ids)} track(s) to Spotify liked songs")
        return {'matched': len(ids), 'missing': len(tidal_tracks) - len(ids), 'written': 0}
    for chunk in tqdm(list(_chunks(ids, SPOTIFY_LIBRARY_CHUNK)), desc="Adding new tracks to Spotify liked songs"):
        spotify_session.current_user_saved_tracks_add(chunk)
    return {'matched': len(ids), 'missing': len(tidal_tracks) - len(ids), 'written': len(ids)}


def print_status(spotify_session: spotipy.Spotify, tidal_session: tidalapi.Session):
    """ Print a comparison of both libraries. """
    spotify_playlists = get_owned_spotify_playlists(spotify_session)
    tidal_playlists = get_tidal_playlists(tidal_session)
    spotify_by_name = {p['name']: p for p in spotify_playlists}
    tidal_by_name = {p.name: p for p in tidal_playlists}

    print(f"\nSpotify playlists ({len(spotify_playlists)}) -> Tidal")
    print(f"  {'tracks':>6}  {'tidal':<6}  name")
    for playlist in sorted(spotify_playlists, key=lambda p: p['name'].lower()):
        counterpart = tidal_by_name.get(playlist['name'])
        state = f"{counterpart.num_tracks}" if counterpart else 'missing'
        total = (playlist.get('items') or playlist.get('tracks') or {}).get('total', 0)
        print(f"  {total:>6}  {state:<6}  {playlist['name']}")

    print(f"\nTidal playlists ({len(tidal_playlists)}) -> Spotify")
    print(f"  {'tracks':>6}  {'spotify':<6}  name")
    for playlist in sorted(tidal_playlists, key=lambda p: p.name.lower()):
        counterpart = spotify_by_name.get(playlist.name)
        state = 'yes' if counterpart else 'missing'
        print(f"  {playlist.num_tracks:>6}  {state:<6}  {playlist.name}")
