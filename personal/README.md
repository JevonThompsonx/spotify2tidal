# Personal branch

This is the working copy for the private Forgejo repo. `main` is the generic
branch that is also pushed to GitHub.

## Layout

- Code and docs: identical to `main`.
- `personal/config.personal.yml`: non-secret personal defaults.
- `personal/publish.sh`: publishes this branch and refreshes the generic one.

The real `config.yml`, `.session.yml`, `.cache.db`, `.cache-spotify.json` and
the Spotify token cache stay untracked. Never commit them.

## Publishing

```bash
./personal/publish.sh
```

It pushes `personal` to Forgejo, then merges it into `main` **without** the
`personal/` directory and pushes `main` to GitHub.

Do not merge `main` back into `personal`; that would delete the overlay. Make
code changes on `personal`, publish, and the generic branch follows.
