A command line tool for importing your Spotify playlists into Tidal. Due to various performance optimisations, it is particularly suited for periodic synchronisation of very large collections.

Installation
-----------
Clone this git repository and then run:

```bash
python3 -m pip install -e .
```

Setup
-----
0. Copy the file example_config.yml to config.yml (`cp example_config.yml config.yml`)
0. Go [here](https://developer.spotify.com/dashboard) and create a new app on developer.spotify.com.
   - Select **Web API** when asked which API/SDKs you plan to use.
   - Copy and paste the exact value of 'redirect_uri' from the config file (`http://127.0.0.1:8888/callback`) into Redirect URIs and press ADD.
   - Copy the client ID and client secret (Settings → View client secret) to the Spotify part of the config file.
   - Development-mode apps require the app owner to have an active Spotify **Premium** subscription; the app stops working if Premium lapses.
   - If you will authorise with a different Spotify account, add it under Settings → User Management (development mode allows up to 5 users).
0. Enter your Spotify username to the config file. It is only used to name the local token cache file.
0. Run `spotify_to_tidal --sync-favorites` (or any other command below) and follow the login prompts for Spotify and Tidal.

Notes:
- Spotify renamed the playlist track endpoints from `/playlists/{id}/tracks` to `/playlists/{id}/items` for apps created after February 2026. This tool handles both response shapes.
- On a headless or remote machine set `open_browser: False`. The tool will print the Spotify authorisation URL and ask you to paste back the URL you were redirected to; open the URL in any browser, approve access, then copy the full `http://127.0.0.1:8888/callback?code=...` URL from the address bar and paste it into the terminal. The Tidal login prints a verification URL you can open on any device; it is only auto-opened when a desktop session is available, so a headless run never blocks on a console browser.
- The Tidal session is cached in `.session.yml` and the Spotify token in a `.cache-*` file. Delete the relevant file to force a fresh login.
- If Spotify returns `403` on every request, confirm the account has Premium and is listed in the app's User Management allowlist.

Usage
----
To synchronize all of your Spotify playlists with your Tidal account run the following from the project root directory
Windows ignores python module paths by default, but you can run them using `python3 -m spotify_to_tidal`

```bash
spotify_to_tidal
```

You can also just synchronize a specific playlist by doing the following:

```bash
spotify_to_tidal --uri 1ABCDEqsABCD6EaABCDa0a # accepts playlist id or full playlist uri
```

or sync just your 'Liked Songs' with:

```bash
spotify_to_tidal --sync-favorites
```

See example_config.yml for more configuration options, and `spotify_to_tidal --help` for more options.

---

#### Join our amazing community as a code contributor
<br><br>
<a href="https://github.com/spotify2tidal/spotify_to_tidal/graphs/contributors">
  <img class="dark-light" src="https://contrib.rocks/image?repo=spotify2tidal/spotify_to_tidal&anon=0&columns=25&max=100&r=true" />
</a>
