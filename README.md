# TeleLite

A lightweight Telegram client for feature phones — the kind of phone you fall
back on when your smartphone is lost, stolen, or broken. One self-hosted
backend, three ways to reach it: a no-install browser page, a KaiOS app, and
a J2ME app for older Java ME phones. Text-only, no media, kept deliberately
small for slow connections and low-power devices.

## Status

| Component | Status |
|---|---|
| Backend (Flask + Telethon relay) | Working, tested |
| Browser client (no JS) | Working, tested |
| J2ME app (`.jar`/`.jad`) | Working, tested end-to-end incl. login/2FA, chat list, conversation, reply, logout, persistence |
| KaiOS app | Built, **not yet verified running** — see note below |

**KaiOS note**: the KaiOS app is code-complete and shares the exact same
backend contract as the other two clients (it went through the same
broadcast-channel and self-hosting fixes), but it has not actually been run
successfully in a simulator or on real KaiOS hardware yet. Testing got stuck
on a broken first-run tutorial screen in the available legacy simulator
tooling. Treat it as "should work, unverified" until someone confirms it on
an actual device or a working simulator.

## Quick start

See **[SELF_HOSTING.md](SELF_HOSTING.md)** for running the backend, the
security must-dos before exposing it beyond localhost, and how to point each
client at your own deployment.

## Layout

```
telelite/         Flask backend (Telegram relay via Telethon) + browser client templates
kaios-app/        KaiOS client (vanilla HTML/CSS/JS)
j2me-app/         J2ME client (Maven project, MIDP 2.0 / CLDC 1.1)
tests/            Backend test suite (pytest)
scripts/          Manual test helpers (cli_test.py)
run.py            Local dev entrypoint for the backend
```

## Running the backend locally

```
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your Telegram API credentials, see comments in the file
python run.py
```

## Running the tests

```
pip install -r requirements-dev.txt
pytest
```

## Building the J2ME client

```
cd j2me-app
mvn -Djdk8.home=$JDK8_HOME clean verify
```
Requires a JDK 8 install (`JDK8_HOME` pointing at it) — the backend server
itself doesn't need this, only building the J2ME client does. See
`SELF_HOSTING.md` for pointing a build at your own server URL instead of
localhost.

## Security model, briefly

Telegram session strings are encrypted at rest, sessions have a sliding
expiry, and logout revokes immediately. Full details in
[SELF_HOSTING.md](SELF_HOSTING.md#4-whats-stored-and-for-how-long).

## License

MIT — see [LICENSE](LICENSE).
