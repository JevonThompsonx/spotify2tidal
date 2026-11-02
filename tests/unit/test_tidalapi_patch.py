# tests/unit/test_tidalapi_patch.py

import pytest
import requests

from spotify_to_tidal.tidalapi_patch import add_multiple_tracks_to_playlist, folder_name_for_playlist


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


@pytest.mark.parametrize("name,expected", [
    ("Spring 2026 🔥", "Spring 2026"),
    ("Summer🍃 2026", "Summer 2026"),
    ("< Winter 2024 🍃 ", "Winter 2024"),
    ("2026 Fall Party princess 👑", "Fall 2026"),
    ("fall 2025 🔥", "Fall 2025"),
    ("Autumn 2023", "Fall 2023"),
    ("Winter 2025 ❤️", "Winter 2025"),
    ("Lofi ish", None),
    ("AV Party 2025", None),
    ("2000s era", None),
])
def test_folder_name_for_playlist(name, expected):
    assert folder_name_for_playlist(name) == expected


def test_folder_name_for_playlist_rules_take_precedence():
    rules = [{"match": "princess", "folder": "Princess"}]

    assert folder_name_for_playlist("Fall 2026 Princess classics", rules) == "Princess"
    assert folder_name_for_playlist("Spring 2026 🔥", rules) == "Spring 2026"
