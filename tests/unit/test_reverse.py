# tests/unit/test_reverse.py

from types import SimpleNamespace

from spotify_to_tidal import reverse


class FakeArtist:
    def __init__(self, name):
        self.name = name


class FakeTidalTrack:
    def __init__(self, name='Song', artist='Artist', duration=200, isrc=None, tid=1):
        self.id = tid
        self.name = name
        self.duration = duration
        self.isrc = isrc
        self.version = None
        self.available = True
        self.artists = [FakeArtist(artist)]


def spotify_track(track_id='sp1', name='Song', artist='Artist', duration_ms=200_000):
    return {
        'id': track_id,
        'uri': f'spotify:track:{track_id}',
        'name': name,
        'duration_ms': duration_ms,
        'artists': [{'name': artist}],
        'external_ids': {},
    }


def test_plan_playlist_update_no_change():
    assert reverse.plan_playlist_update(['a', 'b'], ['a', 'b']) == {'action': 'none', 'items': []}


def test_plan_playlist_update_appends_when_prefix_matches():
    assert reverse.plan_playlist_update(['a', 'b'], ['a', 'b', 'c']) == {'action': 'append', 'items': ['c']}


def test_plan_playlist_update_replaces_when_order_changes():
    assert reverse.plan_playlist_update(['a', 'b'], ['b', 'a']) == {'action': 'replace', 'items': ['b', 'a']}


def test_search_spotify_for_track_returns_matching_candidate(mocker):
    mocker.patch("spotify_to_tidal.reverse.time.sleep")
    session = SimpleNamespace(search=lambda **kwargs: {'tracks': {'items': [
        spotify_track('wrong', name='Other'),
        spotify_track('right'),
    ]}})

    result = reverse.search_spotify_for_track(FakeTidalTrack(), session)

    assert result['id'] == 'right'


def test_search_spotify_for_track_returns_none_when_nothing_matches(mocker):
    mocker.patch("spotify_to_tidal.reverse.time.sleep")
    session = SimpleNamespace(search=lambda **kwargs: {'tracks': {'items': [spotify_track('wrong', name='Other')]}})

    assert reverse.search_spotify_for_track(FakeTidalTrack(), session) is None


def test_apply_playlist_update_appends_in_chunks():
    class FakeSpotify:
        def __init__(self):
            self.added = []
            self.replaced = None

        def playlist_add_items(self, playlist_id, items):
            self.added.append(items)

        def playlist_replace_items(self, playlist_id, items):
            self.replaced = items

    session = FakeSpotify()
    reverse.apply_playlist_update(session, 'pl', {'action': 'append', 'items': list(range(150))})

    assert session.replaced is None
    assert [len(chunk) for chunk in session.added] == [100, 50]


def test_apply_playlist_update_replaces_then_appends_remainder():
    class FakeSpotify:
        def __init__(self):
            self.added = []
            self.replaced = None

        def playlist_add_items(self, playlist_id, items):
            self.added.append(items)

        def playlist_replace_items(self, playlist_id, items):
            self.replaced = items

    session = FakeSpotify()
    reverse.apply_playlist_update(session, 'pl', {'action': 'replace', 'items': list(range(150))})

    assert session.replaced == list(range(100))
    assert session.added == [list(range(100, 150))]


def test_apply_playlist_update_dry_run_writes_nothing(capsys):
    class FakeSpotify:
        def playlist_add_items(self, playlist_id, items):
            raise AssertionError('should not write on a dry run')

        def playlist_replace_items(self, playlist_id, items):
            raise AssertionError('should not write on a dry run')

    reverse.apply_playlist_update(FakeSpotify(), 'pl', {'action': 'append', 'items': ['a']}, dry_run=True)

    assert '[dry-run]' in capsys.readouterr().out


def test_match_existing_tracks_pairs_by_isrc():
    tidal = FakeTidalTrack(isrc='GB123')
    candidate = spotify_track('sp1')
    candidate['external_ids'] = {'isrc': 'GB123'}

    assert reverse.match_existing_tracks([tidal], [candidate]) == {1: candidate}


def test_match_existing_tracks_does_not_reuse_a_candidate():
    first, second = FakeTidalTrack(tid=1), FakeTidalTrack(tid=2)
    candidate = spotify_track('sp1')

    matched = reverse.match_existing_tracks([first, second], [candidate])

    assert matched == {1: candidate}


def test_resolve_spotify_tracks_uses_existing_without_searching():
    calls = []

    def search(**kwargs):
        calls.append(kwargs)
        raise AssertionError('should not search when the track is already in the playlist')

    session = SimpleNamespace(search=search)
    candidate = spotify_track('sp1')
    tidal = FakeTidalTrack()

    result = reverse.resolve_spotify_tracks(
        [tidal], session, reverse.SpotifyTrackCache(), 'test', existing={tidal.id: candidate}
    )

    assert result == [candidate]
    assert calls == []


def test_spotify_track_cache_round_trip(tmp_path):
    path = tmp_path / 'cache.json'
    cache = reverse.SpotifyTrackCache(str(path))
    cache.insert(1, spotify_track('sp1'))
    cache.insert(2, None)
    cache.save()

    reloaded = reverse.SpotifyTrackCache(str(path))

    assert reloaded.get(1)['id'] == 'sp1'
    assert reloaded.has(2)
    assert reloaded.get(2) is None
