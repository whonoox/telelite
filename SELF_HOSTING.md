# Self-hosting TeleLite

TeleLite has no central server and no third-party account required beyond
your own Telegram API credentials. It's just a Flask app + SQLite database
that you run yourself — every deployment is independent, and nobody but you
ever sees your encrypted session data.

## 1. Run the backend

```
git clone <this repo>
cd telelight
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Fill in `.env`:
- `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` — from https://my.telegram.org, using
  your own Telegram account. These identify your deployment to Telegram, not
  any individual user.
- `MASTER_KEY` — encrypts every stored Telegram session at rest. Generate it
  once with the command in `.env.example` and **back it up somewhere safe**:
  losing it makes all existing logged-in sessions permanently undecryptable
  (users would just need to log in again — no data loss beyond that).
- `FLASK_SECRET_KEY` — signs the browser client's session cookie.
- `TELEGRAM_ALLOWED_USER_IDS` — comma-separated Telegram user IDs allowed to
  log in. Leave it empty and anyone with a Telegram account can sign in to
  your server; if it's just for you, set it to your own ID (ask
  @userinfobot on Telegram).

Then:
```
python run.py
```

## 2. Before exposing this beyond localhost

`run.py` binds `127.0.0.1` with Flask's debug mode on — correct for local
development, **not safe to expose directly to the internet** (the debug
mode's interactive debugger allows remote code execution if reachable).
For a real deployment:

- Turn off debug mode and run behind a real WSGI server, e.g.
  `gunicorn -w 2 -b 127.0.0.1:5000 'telelite.app:create_app()'`
  (add `gunicorn` to your own requirements).
- Put a reverse proxy (nginx, Caddy, Render/Railway's built-in proxy, etc.) in
  front of it with HTTPS — plain HTTP means phone numbers, login codes, and
  message text cross the network unencrypted.
- Bind the app itself to `127.0.0.1` (loopback) and let the reverse proxy be
  the only thing exposed publicly.

### Hosts without a persistent disk (Vercel)

The repo's `Dockerfile` deploys to Vercel as-is, but Vercel containers lose
their filesystem whenever an instance scales down, and each instance has its
own. A local SQLite file there means random "login expired" errors and users
getting logged out. Instead:

- Create a Turso database (`turso db create telelite`) and set
  `TURSO_DATABASE_URL` (`turso db show --url telelite`) and
  `TURSO_AUTH_TOKEN` (`turso db tokens create telelite`). Tables are created
  automatically on startup.
- Set `AVATAR_CACHE_PATH=/tmp/avatar_cache`. Only `/tmp` is writable, and the
  cache is safe to lose.
- `data/downloads` isn't in git, so the J2ME download page will be empty
  unless you serve those files from somewhere else.

## 3. Pointing each client at your own server

Every client defaults to `http://127.0.0.1:5000` for local development. To
distribute a build that talks to your real deployment:

- **Browser client**: nothing to change — it's server-rendered from the same
  Flask app, so it always talks to wherever you deployed it.
- **KaiOS app**: edit the one line in `kaios-app/js/config.js`
  (`API_BASE_URL`) to your server's HTTPS URL before packaging the app.
- **J2ME app**: build with your server URL as a Maven property, no source
  changes needed:
  ```
  mvn -Djdk8.home=$JDK8_HOME -Dtelelite.server.url=https://your-domain.example clean verify
  ```
  This gets baked into the generated `.jad` as a `TeleLite-Server-URL`
  property, which the MIDlet reads at startup.

## 4. Letting people install the J2ME app from your server

The backend can serve the J2ME `.jar`/`.jad` itself, so you only need to
share one link. Build pointed at your own server, then drop both files where
the backend expects them:

```
cd j2me-app
mvn -Djdk8.home=$JDK8_HOME -Dtelelite.server.url=https://your-domain.example clean verify
mkdir -p ../data/downloads
cp target/telelite-j2me.jad target/telelite-j2me.jar ../data/downloads/
```

(Filenames must stay exactly `telelite-j2me.jad`/`telelite-j2me.jar` — the
`.jad`'s `MIDlet-Jar-URL` is a relative reference resolved against wherever
the `.jad` itself was fetched from, so the `.jar` has to sit at that same
path/name for a phone's installer to find it. `DOWNLOADS_PATH` in `.env` can
override the `data/downloads` location if you want it elsewhere.)

Once both files are in place, send people to `https://your-domain.example/download/`
— it's a plain HTML page (works on old phone browsers too) with an install
link. Opening that link on the phone itself triggers the OTA install flow.

## 5. What's stored, and for how long

- Telegram session strings are encrypted at rest with `MASTER_KEY` (see
  `telelite/crypto.py`, `telelite/db.py`).
- Logged-in sessions use a sliding expiry (`SESSION_TTL_HOURS`, default 24h):
  any authenticated request extends it; going quiet for that long invalidates
  the token and the row is purged.
- Pending logins (phone number submitted, code not yet entered) expire after
  `PENDING_LOGIN_TTL_MINUTES` (default 10 min).
- Logout (`POST /logout`) deletes the session row immediately — no grace
  period.

None of this requires trusting anyone but yourself: you hold `MASTER_KEY`,
you run the database, you control the server your clients talk to.
