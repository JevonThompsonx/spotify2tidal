import asyncio
import math
import re
import time
from typing import List
import requests
import tidalapi
from tidalapi.playlist import Folder
from tqdm import tqdm
from tqdm.asyncio import tqdm as atqdm

SEASONS = {'spring': 'Spring', 'summer': 'Summer', 'fall': 'Fall', 'autumn': 'Fall', 'winter': 'Winter'}

#: Matches "Spring 2026", "2026 Fall", "Summer🍃 2026" and similar names.
SEASON_YEAR = re.compile(r'(spring|summer|fall|autumn|winter)\D{0,3}(\d{4})', re.IGNORECASE)
YEAR_SEASON = re.compile(r'(\d{4})\D{0,3}(spring|summer|fall|autumn|winter)', re.IGNORECASE)


def folder_name_for_playlist(name: str, rules=None) -> str | None:
    """ Return the folder a playlist should live in, or None to leave it at the root.

    Custom rules are matched as case-insensitive substrings before the
    '<Season> <Year>' convention, so a rule can claim e.g. all "princess"
    playlists before the season match applies.
    """
    lowered = name.lower()
    for rule in rules or []:
        if rule.get('match', '').lower() in lowered:
            return rule.get('folder')
    match = SEASON_YEAR.search(name)
    if match:
        return f"{SEASONS[match.group(1).lower()]} {match.group(2)}"
    match = YEAR_SEASON.search(name)
    if match:
        return f"{SEASONS[match.group(2).lower()]} {match.group(1)}"
    return None


def get_or_create_folder(session: tidalapi.Session, name: str) -> Folder:
    """ Find a root-level playlist folder by name, creating it when missing. """
    offset = 0
    while True:
        folders = session.user.favorites.playlist_folders(limit=50, offset=offset, parent_folder_id='root')
        for folder in folders:
            if folder.name.strip().casefold() == name.strip().casefold():
                return folder
        if len(folders) < 50:
            break
        offset += 50
    return session.user.create_folder(name)


def file_playlist_in_folder(session: tidalapi.Session, playlist: tidalapi.UserPlaylist, folder_name: str) -> bool:
    """ Move a playlist into the named folder, creating the folder if needed. """
    folder = get_or_create_folder(session, folder_name)
    return folder.move_items_to_folder([playlist.id], folder.id)



def _retry_on_stale_etag(playlist: tidalapi.UserPlaylist, operation, retries: int = 5):
    """ Run a playlist mutation, retrying when Tidal rejects a stale ETag.

    Tidal answers 412 Precondition Failed when the playlist changed since the
    cached ETag was fetched. That can happen while the server is still applying
    the previous chunk, so drop the validator and try the same request again.
    """
    for attempt in range(retries):
        try:
            return operation()
        except requests.exceptions.HTTPError as error:
            response = error.response
            if response is None or response.status_code != 412 or attempt == retries - 1:
                raise
            playlist._etag = None
            time.sleep(2 ** attempt)


def _remove_indices_from_playlist(playlist: tidalapi.UserPlaylist, indices: List[int]):
    index_string = ",".join(map(str, indices))

    def _delete():
        headers = {'If-None-Match': playlist._etag} if playlist._etag else None
        return playlist.request.request('DELETE', (playlist._base_url + '/items/%s') % (playlist.id, index_string), headers=headers)

    _retry_on_stale_etag(playlist, _delete)
    playlist._reparse()

def clear_tidal_playlist(playlist: tidalapi.UserPlaylist, chunk_size: int=20):
    with tqdm(desc="Erasing existing tracks from Tidal playlist", total=playlist.num_tracks) as progress:
        while playlist.num_tracks:
            indices = range(min(playlist.num_tracks, chunk_size))
            _remove_indices_from_playlist(playlist, indices)
            progress.update(len(indices))
    
def add_multiple_tracks_to_playlist(playlist: tidalapi.UserPlaylist, track_ids: List[int], chunk_size: int=20):
    offset = 0
    with tqdm(desc="Adding new tracks to Tidal playlist", total=len(track_ids)) as progress:
        while offset < len(track_ids):
            count = min(chunk_size, len(track_ids) - offset)
            _retry_on_stale_etag(playlist, lambda: playlist.add(track_ids[offset:offset+chunk_size]))
            offset += count
            progress.update(count)

async def _get_all_chunks(url, session, parser, params={}) -> List[tidalapi.Track]:
    """ 
        Helper function to get all items from a Tidal endpoint in parallel
        The main library doesn't provide the total number of items or expose the raw json, so use this wrapper instead
    """
    def _make_request(offset: int=0):
        new_params = params
        new_params['offset'] = offset
        return session.request.map_request(url, params=new_params)

    first_chunk_raw = _make_request()
    limit = first_chunk_raw['limit']
    total = first_chunk_raw['totalNumberOfItems']
    items = session.request.map_json(first_chunk_raw, parse=parser)

    if len(items) < total:
        offsets = [limit * n for n in range(1, math.ceil(total/limit))]
        extra_results = await atqdm.gather(
                *[asyncio.to_thread(lambda offset: session.request.map_json(_make_request(offset), parse=parser), offset) for offset in offsets],
            desc="Fetching additional data chunks"
        )
        for extra_result in extra_results:
            items.extend(extra_result)
    return items

async def get_all_favorites(favorites: tidalapi.Favorites, order: str = "NAME", order_direction: str = "ASC", chunk_size: int=100) -> List[tidalapi.Track]:
    """ Get all favorites from Tidal playlist in chunks """
    params = {
        "limit": chunk_size,
        "order": order,
        "orderDirection": order_direction,
    }
    return await _get_all_chunks(f"{favorites.base_url}/tracks", session=favorites.session, parser=favorites.session.parse_track, params=params)

async def get_all_playlists(user: tidalapi.User, chunk_size: int=10) -> List[tidalapi.Playlist]:
    """ Get all user playlists from Tidal in chunks """
    print(f"Loading playlists from Tidal user")
    params = {
        "limit": chunk_size,
    }
    return await _get_all_chunks(f"users/{user.id}/playlists", session=user.session, parser=user.playlist.parse_factory, params=params)

async def get_all_playlist_tracks(playlist: tidalapi.Playlist, chunk_size: int=20) -> List[tidalapi.Track]:
    """ Get all tracks from Tidal playlist in chunks """
    params = {
        "limit": chunk_size,
    }
    print(f"Loading tracks from Tidal playlist '{playlist.name}'")
    return await _get_all_chunks(f"{playlist._base_url%playlist.id}/tracks", session=playlist.session, parser=playlist.session.parse_track, params=params)

