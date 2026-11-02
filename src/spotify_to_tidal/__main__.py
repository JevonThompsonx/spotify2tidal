import argparse
import sys

import yaml

from . import auth as _auth
from . import reverse as _reverse
from . import sync as _sync


def _should_sync_favorites(args, config) -> bool:
    if args.sync_favorites is not None:
        return args.sync_favorites
    if args.uri:
        # a single playlist was requested, don't touch the favorites
        return False
    return config.get('sync_favorites_default', True)


def sync_to_tidal(args, config, spotify_session, tidal_session):
    if args.uri:
        # if a playlist ID is explicitly provided as a command line argument then use that
        spotify_playlist = spotify_session.playlist(args.uri)
        tidal_playlists = _sync.get_tidal_playlists_wrapper(tidal_session)
        tidal_playlist = _sync.pick_tidal_playlist_for_spotify_playlist(spotify_playlist, tidal_playlists)
        _sync.sync_playlists_wrapper(spotify_session, tidal_session, [tidal_playlist], config)
    elif config.get('sync_playlists', None):
        # if the config contains a sync_playlists list of mappings then use that
        _sync.sync_playlists_wrapper(spotify_session, tidal_session,
                                     _sync.get_playlists_from_config(spotify_session, tidal_session, config), config)
    else:
        # otherwise sync all the user playlists in the Spotify account
        _sync.sync_playlists_wrapper(spotify_session, tidal_session,
                                     _sync.get_user_playlist_mappings(spotify_session, tidal_session, config), config)


def sync_to_spotify(args, config, spotify_session, tidal_session, cache, dry_run):
    if args.uri:
        tidal_playlist = tidal_session.playlist(args.uri)
        spotify_playlists = _reverse.get_owned_spotify_playlists(spotify_session)
        spotify_playlist = _reverse.find_spotify_playlist_by_name(spotify_playlists, tidal_playlist.name)
        _reverse.sync_playlist_to_spotify(spotify_session, tidal_session, tidal_playlist,
                                          spotify_playlist, cache, dry_run)
        return
    if config.get('sync_playlists', None):
        for spotify_playlist, tidal_playlist in _sync.get_playlists_from_config(spotify_session, tidal_session, config):
            _reverse.sync_playlist_to_spotify(spotify_session, tidal_session, tidal_playlist,
                                              spotify_playlist, cache, dry_run)
        return
    spotify_playlists = _reverse.get_owned_spotify_playlists(spotify_session)
    for tidal_playlist in _reverse.get_tidal_playlists(tidal_session):
        spotify_playlist = _reverse.find_spotify_playlist_by_name(spotify_playlists, tidal_playlist.name)
        _reverse.sync_playlist_to_spotify(spotify_session, tidal_session, tidal_playlist,
                                          spotify_playlist, cache, dry_run)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.yml', help='location of the config file')
    parser.add_argument('--uri', help='synchronize a specific playlist id or uri instead of the ones in the config')
    parser.add_argument('--sync-favorites', action=argparse.BooleanOptionalAction, help='synchronize the favorites')
    parser.add_argument('--direction', choices=['to-tidal', 'to-spotify', 'both'],
                        help='transfer direction (default: to-tidal, or the direction set in the config)')
    parser.add_argument('--dry-run', action='store_true', help='show what would change without writing anything')
    parser.add_argument('--list', action='store_true', help='list playlists on both services and exit')
    args = parser.parse_args()

    if args.uri and args.direction == 'both':
        parser.error('--uri can only be used with a single --direction')

    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)

    direction = args.direction or config.get('direction', 'to-tidal')
    dry_run = args.dry_run or config.get('dry_run', False)
    config['dry_run'] = dry_run

    print("Opening Spotify session")
    spotify_session = _auth.open_spotify_session(config['spotify'])
    print("Opening Tidal session")
    tidal_session = _auth.open_tidal_session()
    if not tidal_session.check_login():
        sys.exit("Could not connect to Tidal")

    if args.list:
        _reverse.print_status(spotify_session, tidal_session)
        return

    cache = _reverse.SpotifyTrackCache()
    if direction in ('to-tidal', 'both'):
        sync_to_tidal(args, config, spotify_session, tidal_session)
    if direction in ('to-spotify', 'both'):
        sync_to_spotify(args, config, spotify_session, tidal_session, cache, dry_run)

    if _should_sync_favorites(args, config):
        if direction in ('to-tidal', 'both'):
            _sync.sync_favorites_wrapper(spotify_session, tidal_session, config)
        if direction in ('to-spotify', 'both'):
            _reverse.sync_favorites_to_spotify(spotify_session, tidal_session, cache, dry_run)


if __name__ == '__main__':
    main()
    sys.exit(0)
