# Design decisions

Choices made for the Housecairn app, with their reasons. The Supervisor
behaviour quoted here was read in the
[developer documentation](https://contributors.home-assistant.io/apps/) and in
the code of the [Supervisor](https://github.com/home-assistant/supervisor)
(main branch, November 2026); the HouseCairn behaviour in the
[main repository](https://github.com/HouseCairn/housecairn)
(`src/housecairn/entrypoint.py`, `src/housecairn/settings.py`,
`docs/administration/`).

## D1. One repository of apps, same license as HouseCairn

The repository follows the layout the Supervisor reads: `repository.yaml` at
the root, one folder per app (`housecairn/`). It is licensed like HouseCairn,
`AGPL-3.0-only`, with the same section 7 terms in `NOTICE`.

## D2. A thin image layer, built on the device

The Supervisor accepts the name of a multi-architecture image in `image`
("Use the name of a multi-architecture image. The placeholder `{arch}` is
still supported for images that are published per architecture"), and
HouseCairn publishes `ghcr.io/housecairn/housecairn` for `linux/amd64` and
`linux/arm64`. That image cannot be used as is, though:

- it runs as user `10001`, and needs to write to `/data`;
- the Supervisor creates the app's data folder as root
  (`path_data.mkdir()` in `supervisor/apps/app.py`), so `/data` belongs to
  root, and HouseCairn stops at once ("the data directory /data is not
  writable");
- the Supervisor writes `/data/options.json` as root with mode 600
  (`write_json_file` in `supervisor/utils/json.py`): user `10001` cannot read
  the options;
- a restored backup is copied back with `shutil.copytree`, which does not keep
  owners: after a restore, the files belong to root again;
- the Supervisor gives the container no user of its choice, nor any hook
  that would run as root before the image's own entry point.

So the app adds one layer to HouseCairn's image: a start script, run as root,
that prepares `/data` and drops root before HouseCairn starts (D3).

That layer is **built by the Supervisor on the device** (`config.yaml` has no
`image`): it only copies one file over HouseCairn's image, pinned by tag and
digest, so the build downloads nothing else and takes seconds. Publishing a
ready image of the app would need its own publication chain (builder actions,
a package on GHCR, signatures), which is not part of this first version.

Rejected: `legacy: true`, with which the Supervisor passes the top-level
options as environment variables. It does not solve the owner of `/data`, it
cannot pass a list (the allowed hosts), and it would turn option names into
variable names.

## D3. Options pass through a start script (choice b)

`housecairn/rootfs/usr/local/lib/housecairn-app/run.py`, standard library only,
run by the system Python of the image in isolated mode (`python3 -I`):

1. reads `/data/options.json` and turns each option into HouseCairn's
   variable; an option left empty sets nothing, so the setting keeps its
   default and, where HouseCairn also has it in its interface, stays editable
   there (a variable that is set locks its field);
2. gives `/data` and everything in it to `10001:10001`, except
   `options.json`, without following symbolic links;
3. removes the Supervisor's API tokens and `SECRET_KEY` from the environment,
   drops root (supplementary groups, group, user, and checks that root cannot
   be regained), then replaces itself with HouseCairn's entry point.

Rejected, choice (a): an option of the main repository to read a file of
options. HouseCairn's user cannot read `options.json` (mode 600, root), nor
write `/data`, so a root step is needed anyway (D2); with that step in place,
turning options into variables is a few lines, and the main repository does
not need to know about the Supervisor. No change to the main repository is
needed.

| Option | Variable | When empty |
| --- | --- | --- |
| `allowed_hosts` (required) | `ALLOWED_HOSTS` | refused: HouseCairn answers to no host otherwise |
| `default_language` | `HOUSECAIRN_DEFAULT_LANGUAGE` | `en`, editable in the interface |
| `time_zone` | `TIME_ZONE` | the time zone of Home Assistant (`TZ`, set by the Supervisor) |
| `signup_open` | `HOUSECAIRN_SIGNUP_OPEN` | closed, editable in the interface |
| `site_url` | `HOUSECAIRN_SITE_URL` | the address of each request, editable in the interface; through ingress, links meant for outside do not work (D9) |
| `oidc_server_url`, `oidc_client_id`, `oidc_client_secret`, `oidc_provider_name` | `OIDC_SERVER_URL`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_PROVIDER_NAME` | no provider from the options; providers can be declared in the interface |
| `bootstrap_admin_email` | `HOUSECAIRN_BOOTSTRAP_ADMIN_EMAIL` | the first account through single sign-on becomes administrator |

The time zone falls back to Home Assistant's rather than to UTC, because it
decides what "today" is for the households. The consequence is that the time
zone field of HouseCairn's interface is always locked in the app: it is
changed in the options.

The secret key is not an option: HouseCairn generates it once, on first start,
in `/data/secret_key` (mode 600) when `SECRET_KEY` is unset, and the start
script makes sure it is unset.

## D4. Version: the tag of HouseCairn's image

`version` in `config.yaml` is the tag of HouseCairn's image the Dockerfile is
built from, so users see which HouseCairn they run. HouseCairn has no release
yet: only `edge`, which moves, and `sha-<commit>` tags are published. The app
uses a `sha-<commit>` tag; it will use `X.Y.Z` once HouseCairn publishes
releases. `latest` is never used: the Supervisor would not see an update, and
users would not all run the same image. The base image is also pinned by
digest in the Dockerfile; tag, digest, `version` and the changelog change in
the same commit.

## D5. Plain HTTP, through ingress and on the optional port

The first version opened HouseCairn on port 8000 of the host, without ingress.
Since D9, ingress is the way in, and the port is optional and off by default.
Both may be plain HTTP: the port always, and ingress when Home Assistant itself
is reached without TLS.

HouseCairn's defaults enforce HTTPS: redirection, HSTS, cookies sent over
HTTPS only. Without TLS they would make the instance unusable, so
`config.yaml` sets `SECURE_SSL_REDIRECT=false`, `SECURE_HSTS_SECONDS=0`,
`SESSION_COOKIE_SECURE=false` and `CSRF_COOKIE_SECURE=false`, and nothing else.
What follows, written in `DOCS.md`:

- passwords and session cookies cross the local network in clear: use it on a
  network you trust, not from the Internet;
- passkeys and the anti-robot check of open sign-up need a secure context
  (HTTPS, or `localhost`), so they do not work this way.

Cookies stay without the `Secure` flag even through ingress over HTTPS: the
same instance may be reached through Home Assistant in plain HTTP.

## D6. Least privilege

No `map` (only the app's private `/data`, which the Supervisor always mounts),
no host network, no added Linux capability, no device, no access to the
Supervisor or Home Assistant APIs, protection mode left on. `/tmp` is in
memory (`tmpfs: true`), as in HouseCairn's `compose.yaml`.

AppArmor: the Supervisor applies Docker's default profile. The documentation
recommends a profile of the app's own, but asks to write it by running the app
with the profile in complain mode and reading the audit log. That needs a real
installation, so no `apparmor.txt` is shipped yet: an untested profile would
either block HouseCairn or protect nothing. It is left to a later version,
written from the audit log of a real installation.

Security rating, as the Supervisor computes it (`rating_security` in
`supervisor/apps/utils.py`): 7, the starting 5 and 2 for ingress. It was 5
without ingress. A profile of the app's own would add 1.

## D7. Backups

Everything HouseCairn writes is in `/data`: the SQLite database, the uploaded
files and the secret key, so a Home Assistant backup of the app contains all
of it. The app is backed up cold (`backup: cold`): the Supervisor stops it
during the backup, so the database and its write-ahead log are copied in a
consistent state, at the cost of a short stop.

Rejected for now: a hot backup with `backup_pre` running HouseCairn's online
backup command (through the start script, since the Supervisor runs it as the
image's user, root). The live database would still be copied as well, and the
copies would pile up in `/data/backups/`, which nothing removes.

## D8. Health

The Supervisor reads the image's `HEALTHCHECK`; `watchdog` is refused by the
app linter. HouseCairn's probe sends a host name of `ALLOWED_HOSTS`, which the
app sets from its options, not as a variable of the container: the Dockerfile
runs the same probe through the start script.

## D9. Ingress, with the prefix of each request, trusted from the Supervisor

The browser reaches the app at `/api/hassio_ingress/<token>/` on Home
Assistant. Home Assistant Core checks the user's session, adds
`X-Ingress-Path: /api/hassio_ingress/<token>`, `X-Forwarded-Host` and
`X-Forwarded-Proto` (`homeassistant/components/hassio/ingress.py`), and passes
the request to the Supervisor, which checks the ingress session cookie and
forwards it, path without the prefix, to the app on its internal network
(`supervisor/api/ingress.py`). Both keep the other request headers, `Host`
included. The Supervisor's address on that network is `172.30.32.2`: "Your
web server only ever sees requests from the Supervisor, at `172.30.32.2`"
(developer documentation, Ingress), and `DOCKER_IPV4_NETWORK_MASK[2]` of
`172.30.32.0/23` in `supervisor/const.py`. The token is generated when the app
is installed and kept with the app's settings (`SCHEMA_APP_USER` in
`supervisor/apps/validate.py`): it stays across restarts and updates, and
changes with a new installation.

`config.yaml`: `ingress: true`, `ingress_port: 8000` (HouseCairn's own web
server, no second server), `panel_icon`, `panel_title`, and
`panel_admin: false`: HouseCairn is for the whole household and has its own
accounts, so a Home Assistant user who is not an administrator may reach its
sign-in page. No `webui`: the app linter refuses it with ingress.

`run.py` sets, after the options, so that nothing overrides them:

| Variable | Value | Why |
| --- | --- | --- |
| `HOUSECAIRN_URL_PREFIX_HEADER` | `X-Ingress-Path` | The token is only known per request: HouseCairn's header mode (its ADR 0055). |
| `HOUSECAIRN_FORWARDED_ALLOW_IPS` | `172.30.32.2` | Only the Supervisor may set the prefix and the forwarding headers, in gunicorn and in Django; from any other peer HouseCairn removes them. Not `*`, not a network, not the loopback. |
| `HOUSECAIRN_BEHIND_TLS_PROXY` | `true` | Through Home Assistant over HTTPS, the browser sends `Origin: https://...`; HouseCairn must read `X-Forwarded-Proto` from the Supervisor to accept that origin (CSRF check). |
| `HOUSECAIRN_ALLOW_SAME_ORIGIN_FRAMING` | `true` | Home Assistant shows ingress in a frame of its own origin (`src/panels/app/ha-panel-app.ts` of its frontend). HouseCairn refuses every frame by default (`X-Frame-Options: DENY`, `frame-ancestors 'none'`); this gives `SAMEORIGIN` and `frame-ancestors 'self'`, so a page of another origin still cannot frame it. |

`HOUSECAIRN_URL_PREFIX` is removed from the environment. With it set,
HouseCairn's cookies would get its path, which ingress addresses do not share,
and the sign-in through ingress would fail.

How ingress and the port share one server:

- **The prefix.** A request on the port comes from the host's network, not from
  the Supervisor: it never gets the ingress prefix, even if it sends the
  header, and is served at the root.
- **`ALLOWED_HOSTS`.** HouseCairn checks the `Host` header, which Home
  Assistant passes on unchanged (`X-Forwarded-Host` is not read): the option
  lists every name used to reach Home Assistant, remote access included, and
  the address used for the port.
- **`CSRF_TRUSTED_ORIGINS`.** Not needed. The origin of a form is the browser's
  scheme and `Host`; HouseCairn compares it with its own, whose scheme comes
  from the Supervisor's `X-Forwarded-Proto` through ingress, and is HTTP on the
  port, where that header is ignored.
- **Cookies.** Through ingress, HouseCairn limits its cookies to the ingress
  path; on the port, they are at `/`. Browsers do not tell ports apart, so a
  cookie of the port is also sent to ingress addresses, after the ingress one,
  and Django keeps the last value of a name. `DOCS.md` asks to open the port
  under another name or address than Home Assistant.

Consequences, in `DOCS.md`:

- **Links meant for outside Home Assistant.** A link built during an ingress
  request holds the ingress address (calendar feeds, QR labels, invitations),
  and the Supervisor only serves it to a browser with an ingress session,
  which Home Assistant's interface opens. Links built in the background
  (reminders) have no request: they use `HOUSECAIRN_URL_PREFIX`, empty here,
  so they lead to the root of HouseCairn's public address, which only the port
  serves. Those links need the port, and the public address set to it.
- **Sign-in rate limits.** The Supervisor appends the address of its own peer,
  Home Assistant Core, to `X-Forwarded-For`; HouseCairn takes the right-most
  address that is not a trusted proxy, so every ingress request counts as Home
  Assistant's. Trusting Core's address as well would let requests on the port
  claim another client address, if they reach the app from the network's
  gateway: not done.
- **HouseCairn's own sign-in.** The documentation suggests no second sign-in
  behind ingress, and the Supervisor adds `X-Remote-User-Id` and related
  headers for that. HouseCairn does not read them: its accounts, roles and
  homes are its own, and its sign-in stays.
- **Single sign-on** through ingress would need the ingress token in the
  provider's redirect address: it goes through the port.

Rejected:

- **A fixed prefix read from the Supervisor's API** (`ingress_entry` of
  `GET /addons/self/info`) at start-up, as HouseCairn's ADR 0055 suggests. It
  needs `hassio_api` and a Supervisor token in the container, for links of
  reminders that would hold the ingress address, which still only opens with
  an ingress session.
- **Keeping the port on by default.** The documentation asks ingress apps to
  deny everything but the Supervisor, and the port is plain HTTP: it is opt-in,
  for the links that need it.
- **A second web server** listening for the Supervisor only: HouseCairn already
  refuses the forwarding headers from anyone else.

Frames: HouseCairn refuses to be shown in any frame unless
`HOUSECAIRN_ALLOW_SAME_ORIGIN_FRAMING` is `true` (from `sha-4be6010`). The app
sets it, and the frame of Home Assistant's ingress panel is of the same
origin as the page around it, so it is allowed and a page of another site is
not. On the port, the same headers apply: only a page of the port's own origin
may frame it.
