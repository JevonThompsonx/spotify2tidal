# tests/unit/test_sync.py

import asyncio

from spotify_to_tidal.sync import (
    _fetch_all_from_spotify_in_chunks,
    _playlist_entry_track,
    get_tracks_from_spotify_playlist,
)


def _track(track_id):
    return {'id': track_id, 'name': track_id}


def test_playlist_entry_track_reads_new_api_shape():
    assert _playlist_entry_track({'item': _track('a')}) == _track('a')


def test_playlist_entry_track_reads_legacy_api_shape():
    assert _playlist_entry_track({'track': _track('a')}) == _track('a')


def test_playlist_entry_track_skips_null_entries():
    assert _playlist_entry_track({'item': None, 'track': None}) is None
    assert _playlist_entry_track({}) is None


def test_fetch_all_from_spotify_in_chunks_handles_both_shapes():
    pages = {
        0: {
            'limit': 2,
            'total': 3,
            'next': 'next',
            'items': [{'item': _track('a')}, {'track': _track('b')}],
        },
        2: {
            'limit': 2,
            'total': 3,
            'next': None,
            'items': [{'item': None}, {'item': _track('c')}],
        },
    }

    result = asyncio.run(_fetch_all_from_spotify_in_chunks(lambda offset: pages[offset]))

    assert [track['id'] for track in result] == ['a', 'b', 'c']


def test_get_tracks_from_spotify_playlist_uses_items_endpoint():
    track = {
        'id': 'a',
        'name': 'Test Song',
        'type': 'track',
        'album': {'name': 'Test Album', 'artists': [{'name': 'Test Artist'}]},
        'artists': [{'name': 'Test Artist'}],
    }
    page = {'limit': 50, 'total': 1, 'next': None, 'items': [{'item': track}]}
    calls = []

    class FakeSpotify:
        def playlist_items(self, playlist_id, offset=0, additional_types=('track',)):
            calls.append((playlist_id, offset, additional_types))
            return page

    result = asyncio.run(
        get_tracks_from_spotify_playlist(FakeSpotify(), {'id': 'playlist-id', 'name': 'Test'})
    )

    assert [item['id'] for item in result] == ['a']
    assert calls == [('playlist-id', 0, ('track',))]
