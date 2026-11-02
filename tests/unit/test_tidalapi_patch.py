# tests/unit/test_tidalapi_patch.py

import requests

from spotify_to_tidal.tidalapi_patch import add_multiple_tracks_to_playlist


def _http_error(status_code):
    response = requests.Response()
    response.status_code = status_code
    return requests.exceptions.HTTPError(response=response)


def test_add_multiple_tracks_retries_on_stale_etag(mocker):
    mocker.patch("spotify_to_tidal.tidalapi_patch.time.sleep")

    class FakePlaylist:
        _etag = 'stale'

        def __init__(self):
            self.calls = 0
            self.added = []

        def add(self, track_ids):
            self.calls += 1
            if self.calls == 1:
                raise _http_error(412)
            self.added.extend(track_ids)

    playlist = FakePlaylist()

    add_multiple_tracks_to_playlist(playlist, [1, 2, 3])

    assert playlist.added == [1, 2, 3]
    assert playlist.calls == 2


def test_add_multiple_tracks_raises_other_http_errors(mocker):
    mocker.patch("spotify_to_tidal.tidalapi_patch.time.sleep")

    class FakePlaylist:
        _etag = 'current'

        def add(self, track_ids):
            raise _http_error(500)

    playlist = FakePlaylist()

    try:
        add_multiple_tracks_to_playlist(playlist, [1])
    except requests.exceptions.HTTPError as error:
        assert error.response.status_code == 500
    else:
        raise AssertionError("expected HTTPError to propagate")
