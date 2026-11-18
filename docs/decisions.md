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
| `allowed_hosts` | `ALLOWED_HOSTS` | `*` while the port is not published; refused once it is (D10). Once it is, the app's internal names are added to the option's (D15) |
| `default_language` | `HOUSECAIRN_DEFAULT_LANGUAGE` | `en`, editable in the interface |
| `time_zone` | `TIME_ZONE` | the time zone of Home Assistant (`TZ`, set by the Supervisor) |
| `signup_open` | `HOUSECAIRN_SIGNUP_OPEN` | closed, editable in the interface |
| `site_url` | `HOUSECAIRN_SITE_URL` | the address of each request, editable in the interface; through ingress, links meant for outside do not work (D9) |
| `trusted_origins` | `CSRF_TRUSTED_ORIGINS` | none: the origin of a form must be HouseCairn's own scheme and `Host` (D11) |
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
built from, so users see which HouseCairn they run. Since HouseCairn 0.1.0, the
app uses the `X.Y.Z` tag of a HouseCairn release; before it, HouseCairn
published only `edge`, which moves, and `sha-<commit>` tags, and the app used a
`sha-<commit>` tag. `latest` is never used: the Supervisor would not see an
update, and users would not all run the same image. The base image is also
pinned by digest in the Dockerfile; tag, digest, `version` and the changelog
change in the same commit.

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
no host network, no added Linux capability, no device, no `hassio_api` nor
`homeassistant_api`, protection mode left on. The start script reads the app's
own information from the Supervisor (D10) and sends one discovery message
(D15), which every app may do without them; HouseCairn itself never gets the
Supervisor's token or socket path.
`/tmp` is in memory (`tmpfs: true`), as in HouseCairn's `compose.yaml`.

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
runs the same probe through the start script. The probe does not ask the
Supervisor (every 30 seconds): it sends the first name of `allowed_hosts`,
which the server accepts whether the port is published or not, or
`localhost` when the option is empty, which only happens with `*` (D10).

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
  Assistant passes on unchanged (`X-Forwarded-Host` is not read). With the
  port published, the option lists every name used to reach Home Assistant,
  remote access included, and the address used for the port; without it,
  every name is accepted (D10).
- **`CSRF_TRUSTED_ORIGINS`.** Not needed when Home Assistant receives the
  browser's own `Host` and scheme. The origin of a form is the browser's
  scheme and `Host`; HouseCairn compares it with its own, whose scheme comes
  from the Supervisor's `X-Forwarded-Proto` through ingress, and is HTTP on the
  port, where that header is ignored. A reverse proxy in front of Home
  Assistant can break that: D11.
- **Cookies.** Through ingress, HouseCairn limits its cookies to the ingress
  path; on the port, they are at `/`. Browsers do not tell ports apart, so a
  cookie of the port is also sent to ingress addresses, after the ingress one,
  and Django keeps the last value of a name. `DOCS.md` asks to open the port
  under another name or address than Home Assistant.

Consequences, in `DOCS.md`:

- **Links meant for outside Home Assistant.** The ingress address only opens
  in a browser with an ingress session, which Home Assistant's interface
  opens: a calendar app or a phone that scans a label has none. Since
  `sha-4be6010` (HouseCairn #89, ADR 0055), HouseCairn builds every link meant
  to leave it (calendar feeds, QR labels, invitations, emails, reminders) on
  `HOUSECAIRN_SITE_URL` and the fixed `HOUSECAIRN_URL_PREFIX`, never on the
  prefix of the request. The app offers the public address as an option,
  `site_url` (D3), without a path since the fixed prefix is removed: it must
  reach the app without Home Assistant, such as the port. Without it, a link
  made through ingress holds Home Assistant's address without the ingress
  path, which leads nowhere, and reminders carry no link: `DOCS.md` says so.
- **Sign-in rate limits.** The Supervisor appends the address of its own peer,
  Home Assistant Core, to `X-Forwarded-For`; HouseCairn takes the right-most
  address that is not a trusted proxy, so every ingress request counts as Home
  Assistant's. Trusting Core's address as well would let requests on the port
  claim another client address, if they reach the app from the network's
  gateway: not done.
- **HouseCairn's own sign-in, always.** The documentation suggests no second
  sign-in behind ingress, and the Supervisor adds `X-Remote-User-Id` and
  related headers for that. HouseCairn does not read them, and the app will
  never sign anyone in from them (maintainer's decision, 2026-11-10): its
  accounts, roles and homes are its own, and its sign-in stays.
- **Single sign-on** through ingress would need the ingress token in the
  provider's redirect address: it goes through the port.

Rejected:

- **A fixed prefix read from the Supervisor's API** (`ingress_entry` of
  `GET /addons/self/info`) at start-up, as HouseCairn's ADR 0055 suggests. It
  would serve links of reminders that hold the ingress address, which still
  only opens with an ingress session. (That endpoint needs no `hassio_api`,
  as first written here: D10 reads it, for the port.)
- **Keeping the port on by default.** The documentation asks ingress apps to
  deny everything but the Supervisor, and the port is plain HTTP: it is opt-in,
  for the links that need it (maintainer's decision, 2026-11-10, with the
  change written first in the changelog for users of the first version).
- **Single sign-on from the Supervisor's `X-Remote-User-*` headers**, never
  (maintainer's decision, 2026-11-10; above).
- **`panel_admin: true`**, which would hide the sidebar entry from users who
  are not Home Assistant administrators: the whole household uses HouseCairn
  (maintainer's decision, 2026-11-10).
- **A second web server** listening for the Supervisor only: HouseCairn already
  refuses the forwarding headers from anyone else.

Frames: HouseCairn refuses to be shown in any frame unless
`HOUSECAIRN_ALLOW_SAME_ORIGIN_FRAMING` is `true` (from `sha-4be6010`). The app
sets it, and the frame of Home Assistant's ingress panel is of the same
origin as the page around it, so it is allowed and a page of another site is
not. On the port, the same headers apply: only a page of the port's own origin
may frame it.

## D10. Host names: every name through ingress alone, the list once the port is published

Maintainer's decision, 2026-11-11: every host name is accepted by default when
the app is reached through Home Assistant's ingress, and `allowed_hosts`
applies only when the app's port is published on the host. Before it, the
option held `homeassistant.local` by default, and whoever opened Home
Assistant by an IP address or a remote access domain got "Bad request" on the
first start.

**What it rests on: the port bindings of the container, from the
Supervisor.** The Supervisor creates the container with the port bindings of
the app's `network` setting (`ports` of `DockerApp`,
`supervisor/docker/app.py`): a container port without a host port is not
bound at all. It returns the same setting as `network` in the app's own
information, `GET /addons/self/info` (`info_data` in `supervisor/api/apps.py`),
which every app may read without `hassio_api` (`api_bypass` in
`supervisor/api/middleware/security.py`). The start script asks for it once,
on `run`, before HouseCairn starts: on the Supervisor's Unix socket when it
mounts one (`SUPERVISOR_SOCKET`, Supervisor `main` in November 2026: the
socket names the app, no token), else on the internal network with the app's
token (`SUPERVISOR_TOKEN`, Supervisor 2026.11.0). Neither reaches HouseCairn,
and nothing of the answer is logged (it holds the app's options).

- **`8000/tcp` without a host port** (the default): HouseCairn's port is only
  reachable on the Supervisor's internal network, `172.30.32.0/23`, in
  practice by the Supervisor's ingress, behind Home Assistant's sign-in and
  the ingress session. `ALLOWED_HOSTS` is `*`; `allowed_hosts` is not used.
- **`8000/tcp` with a host port**: anyone on the local network may reach the
  port. `ALLOWED_HOSTS` is `allowed_hosts`, for ingress and the port alike
  (one Django setting for one server), as before; the app does not start
  while it is empty. The app's names on the Supervisor's internal network are
  added after the option's (maintainer's decision, 2026-11-18, D15), so that
  Home Assistant reaches the app by the address it announces whatever the
  option holds.
- **No answer** (no socket nor token, an error, an answer without `network`),
  after three attempts: the app acts as if the port were published, the
  stricter case, and says so in the log.

Why it is safe: the mode is set at start from the Supervisor's answer, and
nothing a browser sends changes it. No header is trusted for it: not `Host`
nor `X-Forwarded-Host`, which the browser chooses; not `X-Ingress-Path` nor
the Supervisor's `X-Remote-User-*`, which a browser on the port could send
(HouseCairn removes the first one from any peer but `172.30.32.2`, D9, but
Django checks `Host` before any view, with one list for every request). The
trusted proxy stays `172.30.32.2` alone. `ALLOWED_HOSTS` is not an access
control: software on the internal network (other apps, Home Assistant Core)
could already send any listed name.

What `*` leaves open: without a **Public address** (`site_url`), HouseCairn
builds the links of its emails (invitations, password resets) on the `Host`
of the request that triggers them. Through ingress alone, a signed-in Home
Assistant user, or software on the internal network, could then have such a
link point to another site. Those links do not work through ingress anyway
without a public address (D9), and with `site_url` set, HouseCairn takes its
host from there, never from the request (`on_site` in
`src/housecairn/accounts/adapters.py`).

What the user sees: at each start, the log says whether the port is
published and which names are accepted. A name that is not in the list gets
HouseCairn's "Bad request" (400) page, and the log Django's line
`Invalid HTTP_HOST header: '<name>'. You may need to add '<name>' to
ALLOWED_HOSTS.`; the start message and `DOCS.md` say that the option to fill
is **Host names**. A page that names the option itself would need a change in
HouseCairn.

The healthcheck does not ask the Supervisor (D8). `allowed_hosts` is now
optional in the schema and empty by default; a list already saved is kept.

Rejected:

- **A check per request, by peer address** (any name from `172.30.32.2`, the
  list from anyone else), which would keep ingress open to every name with
  the port published. Django checks one `ALLOWED_HOSTS` for the whole server:
  it needs a change in HouseCairn.
- **`*` in every case.** With the port published, anyone on the network could
  choose the host of the links HouseCairn builds.
- **Keeping `homeassistant.local` as the default.** Harmless, but it reads as
  a restriction that does not apply through ingress alone.

## D11. Trusted origins, for a reverse proxy in front of Home Assistant

Issue #11 reports "Session expired" (403) on the first-account screen: a
refusal of Django's CSRF check. The Ingress chain was read in the code
(Home Assistant Core `homeassistant/components/hassio/ingress.py`, `dev` of
2026-11-02; Supervisor `supervisor/api/ingress.py`, `main` of 2026-10-26).
Core copies every request header but a few hop and encoding ones, `Host`,
`Origin`, `Referer` and `Cookie` included, then sets `X-Ingress-Path`,
`X-Forwarded-For`, and `X-Forwarded-Host` and `X-Forwarded-Proto` from the
incoming headers of the same name, else from its own request (`request.host`,
`request.scheme`). The Supervisor copies every header but its tokens and the
`X-Remote-User-*` ones, which it sets itself, and appends its peer to
`X-Forwarded-For`. HouseCairn reads `Host` (not `X-Forwarded-Host`) and,
from `172.30.32.2` only, `X-Forwarded-Proto` (D9).

A test chain of the same code (aiohttp, both `_init_header` copied, the app
built from `0.3.1` with the environment of `run.py`) gave, for a GET then a
POST of the first-account form sent with the page's own `Origin` (not what a
browser sends there up to 0.3.1: D12):

| Access | Result |
| --- | --- |
| Ingress, Home Assistant in HTTP | accepted |
| Ingress, Home Assistant serving HTTPS itself | accepted |
| Ingress, TLS proxy that passes `Host` and sets `X-Forwarded-Proto` | accepted |
| Ingress, TLS proxy that replaces `Host` | refused, `Origin checking failed` |
| Ingress, TLS proxy that does not set `X-Forwarded-Proto` | refused, `Origin checking failed` |
| The port, and the port and ingress on the same host (shared cookies) | accepted |

Home Assistant Cloud was not run: its tunnel (`snitun`) upgrades each
connection with `loop.start_tls` and hands it to Core's server, so Core's
`request.scheme` is `https`, the second row.

The issue does not say how the reporter reaches Home Assistant: that these
two rows are their case is not confirmed.

Both refusals are the proxy's: Home Assistant can work without either header,
and HouseCairn cannot tell the browser's address otherwise. Fix: an option,
`trusted_origins`, turned into `CSRF_TRUSTED_ORIGINS`. Each entry is one exact
origin, written as a browser writes `Origin` (scheme and name in lower case,
no default port, no trailing slash): no path, no user, no wildcard, `*`
refused, in the schema and in `run.py`. Django then accepts that origin as
well as its own; the token of the form and the CSRF cookie are still checked.
`DOCS.md` names the log line (`Origin checking failed - <origin> does not
match any trusted origins.`) and the two ways out: fix the proxy, or the
option.

Rejected:

- **`USE_X_FORWARDED_HOST`** from the Supervisor: Core fills
  `X-Forwarded-Host` from the `Host` it received when the proxy sets none, so a
  proxy that replaces `Host` without it gains nothing.
- **Trusting every origin through ingress**, or exempting forms from the check:
  it removes the protection.

## D12. `Origin: null` through ingress: the page states its referrer policy

**Cause, for every user up to 0.3.1.** Home Assistant Core gives every response
of its HTTP server, the ingress ones included, `Referrer-Policy: no-referrer`:
`setup_headers` (`homeassistant/components/http/headers.py`, lines 18 to 47,
Core 2026.11.1) adds a middleware that calls
`response.headers.update(added_headers)` on each response, which replaces
HouseCairn's `same-origin` (the ingress proxy, `hassio/ingress.py`, copies the
app's headers first). Under `no-referrer` the browser posts every form with
`Origin: null` (Fetch standard, "append a request `Origin` header") and no
`Referer`; Django refuses it: `Origin checking failed - null does not match
any trusted origins.` The maintainer saw it with Chrome, also with Home
Assistant reached directly on its own port, without any proxy.

**Fix, in HouseCairn** (HouseCairn/housecairn#139, its ADR 0075): every page
states `<meta name="referrer" content="same-origin">`, which the browser
follows over the header; the forms then carry the page's real origin, and the
CSRF check is unchanged. Nothing changes in this repository but the image: the
app takes the fix with the first HouseCairn image that contains it (D4), and
that update closes issue #11.

Test chain, Chromium 156 headless in front of aiohttp copies of Core 2026.11.1
(headers middleware and ingress proxy) and of the Supervisor 2026.11.0, then
HouseCairn under gunicorn with the environment of `run.py` (the Supervisor's
address replaced by `127.0.0.2`): with 0.3.1, the form is refused over HTTP and
HTTPS; with #139, it is accepted (302) over both, and a form posted from
another site under `no-referrer` is still refused.

**The peer `172.30.32.1` of the log.** The access log shows the client address
after HouseCairn has resolved it, not the TCP peer: gunicorn writes
`REMOTE_ADDR` of the request's environment once the response is sent
(`'h'` in `gunicorn/glogging.py`, 26.2.0), and HouseCairn's first middleware
has replaced it there with the client of `X-Forwarded-For` (its ADR 0012). The
request comes from the Supervisor (`172.30.32.2`, trusted), which appends its
own peer, Home Assistant Core, to `X-Forwarded-For`. Core runs on the host's
network and reaches the Supervisor from the gateway of the `hassio` network,
`172.30.32.1` (`DOCKER_IPV4_NETWORK_MASK[1]`, `supervisor/docker/network.py`;
the Supervisor gives Core that address, `supervisor/docker/homeassistant.py`
line 94, 2026.11.0), which is not trusted, so HouseCairn takes it as the
client (D9, sign-in rate limits). Same in the test chain: the log shows the
address of the Core copy, not the Supervisor's. `X-Forwarded-Proto` and
`X-Ingress-Path` are read from the Supervisor, the TCP peer: the scheme of the expected origin is right, and the
prefix appears in the path of the refusal.

Rejected:

- **Accepting `Origin: null` with `Sec-Fetch-Site: same-origin`**, in a
  gunicorn `pre_request` hook loaded by the app. It works over HTTPS (tested:
  302), but browsers send `Sec-Fetch-*` only to a potentially trustworthy URL
  (Fetch Metadata, "append the Fetch metadata headers for a request", step 1):
  over plain HTTP, the usual way to reach Home Assistant at home, Chromium sent
  `Origin: null` and no `Sec-Fetch-Site`, and the form was still refused. It
  also loosens the check for what the page can fix itself.
- **Treating `Origin: null` as no origin**: over HTTP, Django then checks the
  token alone, for a forged form as for a real one.

## D13. A pull request for each Housecairn release

The app is a layer over HouseCairn's image (D2), and its version is the tag of
that image (D4). Dependabot does not follow the image: it would change the
Dockerfile alone, without `version` in `config.yaml` and the changelog. The
workflow `.github/workflows/app-update.yaml` does it instead, every day and
on demand:

1. it compares the latest published release of HouseCairn (the public
   `releases/latest` API, which returns no draft nor pre-release) with the tag
   in the Dockerfile, as version numbers;
2. when the release is newer, it reads the digest of the tag's
   multi-architecture index on ghcr.io (anonymous pull), checks that it is the
   SHA-256 of the index the registry sent and that the index holds
   `linux/amd64` and `linux/arm64`;
3. it verifies the signed build provenance of that digest with
   `gh attestation verify` (Sigstore): built by HouseCairn's `image.yml`
   workflow, from the tag `refs/tags/vX.Y.Z`, on a GitHub-hosted runner, the
   identity that HouseCairn's `docs/security/verify-image.md` documents.
   HouseCairn signs its image with GitHub's artifact attestations, not with a
   separate `cosign sign`: the provenance is the signature to check;
4. it changes the Dockerfile (tag and digest), `version` and the changelog in
   one commit (an entry that points to the release notes; entries under
   "Unreleased" move under the new version), and opens the pull request of
   the branch `app-update/housecairn`, or updates it when a newer release
   comes out before it is merged. There is never more than one.

The pull request says what to check before merging: the release notes and
the "Home Assistant impact" of HouseCairn's pull requests, for an option, a
variable or a behaviour behind Ingress that the app must follow
(`config.yaml`, `run.py`). The start test (D14) runs on it.

**Who opens the pull request: the project's GitHub App.** A pull request
opened with the workflow's `GITHUB_TOKEN` starts no workflow, so its checks
would never run and the rules of `main` would block it. A token of a GitHub
App does start them. The App is installed on this repository only, with
**Contents** and **Pull requests** in read and write and nothing else; the
workflow asks for a token limited to those two and to this repository, valid
for an hour. Its client ID and private key are a variable and a secret of the
`app-update` environment, whose deployment rule allows `main` only: the
workflow runs on `schedule` and `workflow_dispatch` alone, never on a
`pull_request`, so no fork and no pull request can read the key. Until the App
is set up, a run that finds a release stops in red with what to do, after the
checks.

**The schedule can stop without a word.** GitHub disables the `schedule` of a
workflow in a public repository after 60 days without activity in it, and
nothing tells anyone: the app would fall behind without a pull request. A pull
request is an activity, so a repository that is worked on keeps its cron; one
that is left alone does not. Two guards, and a limit:

- the dry run of every pull request (`app_update.py schedule`) reads the state
  of `app-update.yaml` through the public API, no token and no added permission,
  and fails when it is `disabled_inactivity` or `disabled_manually`
  (`disabled_fork`, a fork's default, is no failure; an API that does not answer,
  or a workflow still to be merged, is no failure either, so that an outage
  does not block a merge). Enabling it again is one click (Actions, App update);
- `workflow_dispatch` stays, to run it by hand;
- the limit: nobody is warned while no pull request is opened. A quiet
  repository is only noticed at the next pull request or by looking at the
  Actions tab.

Rejected:

- **`GITHUB_TOKEN` and "Allow GitHub Actions to create and approve pull
  requests"**: the pull request would have no checks, and the setting also
  lets every workflow of the repository approve pull requests.
- **A personal access token**: tied to a person and to everything that person
  can reach, long-lived, and the pull request would be the maintainer's own,
  which the maintainer cannot approve.
- **A deploy key**, to push the branch so that the push starts the checks: it
  writes to the whole repository and needs the pull request opened by another
  token anyway.

The branch is only replaced for a newer release, and only while every commit
on it is the App's: changes made by hand on it (an option the release needs)
are never overwritten; the run then stops and asks for the update by hand.
`lint.yaml` runs the same steps on every pull request, without pushing
anything (**App update (dry run)**): the app against the latest release, then
a copy moved back to 0.3.0, which must be found out of date, resolved,
verified and changed.

## D14. A start test on every pull request

The unit tests of `run.py` check the environment it computes, not that
HouseCairn starts with it, nor what a browser meets through Ingress. Issue #11
showed the gap: Home Assistant Core's `http` component sets
`Referrer-Policy: no-referrer` on every response, the ones it relays from an
app through Ingress included (`homeassistant/components/http/headers.py`,
which replaces the app's own policy); under that policy a browser sends the
form's POST with `Origin: null`, and HouseCairn refused the creation of the
first administrator.

The workflow `.github/workflows/start-test.yaml` (job **Start test (amd64)**)
builds the app for `linux/amd64` on every pull request that changes
`housecairn/` (the App update's, D13, included), and runs
`tests/start/start-test.sh`:

- the app is started as the Supervisor starts it: as root, `/data` with
  `options.json` in mode 600, the `environment` of `config.yaml`,
  `SUPERVISOR_TOKEN`, an init, `/tmp` in memory, on a network shaped like the
  Supervisor's (`172.30.32.0/23`, the Supervisor at `.2`, the app in
  `172.30.33.0/24`), with a stand-in Supervisor that answers
  `/addons/self/info` (D10) and accepts on `/discovery` only the services of
  `discovery` in `config.yaml` (D15); the message must be the app's internal
  address, and, with the port published and **Host names** restricted, the
  internal names must pass Django's host check and another name must not;
- `tests/start/ingress.py` relays Ingress with the header handling of Core
  and of the Supervisor copied from their code, and Core's response headers,
  `Referrer-Policy: no-referrer` first;
- `tests/start/first_admin.py` does what a browser does on the first-account
  page: GET, then POST of the form with the cookies of the page, `Origin` and
  `Referer` as the Fetch standard sets them under the page's effective referrer
  policy (the `Referrer-Policy` header, read by its last valid token, replaced
  by the last valid `<meta name="referrer">` of the page, as the HTML Standard
  says: `content` lowercased and not trimmed, legacy values mapped, a meta in a
  `<template>` ignored; the header
  stays Core's `no-referrer`, so an image without the meta, such as 0.3.1,
  still sends `Origin: null` and fails), and `Sec-Fetch-*`; the administrator
  must be created (302 to the instance's overview, which then opens signed
  in), and the same POST sent by another
  site (`Sec-Fetch-Site: cross-site`, its own origin or `null`), with the
  page's cookie and token, must be refused;
- two ways in, each from an empty `/data` so the migrations run each time:
  Ingress, relayed from the Supervisor's address (`172.30.32.2`, the app's
  peer; Core's address, `172.30.32.1`, is the last entry of
  `X-Forwarded-For`, which HouseCairn logs as the client), and the published
  port;
- it fails when the app does not become healthy, when a migration fails or
  when the form is refused. A negative control runs the same test on the app
  with a migration broken on purpose (`tests/start/broken.Dockerfile`), which
  must fail.

The fix of issue #11 is in HouseCairn, not in this repository (D12,
HouseCairn/housecairn#139): the `trusted_origins` option (D11) does not change
the case this test reproduces, `Origin: null`. Until the app is built on the
first HouseCairn image that contains #139 (0.3.2 expected), the Ingress case
fails on the form's POST, which is the bug the test reports; it passes once
the app is on that image.

The job runs on every pull request and only skips its steps when nothing the
app is built from changed, so that it can be a required check of `main`.
`arm64` is not started: the image is the same multi-architecture index, and
the runner would need emulation.

## D15. Discovery: the app announces its internal address to Home Assistant

Maintainer's decision, 2026-11-18. When Housecairn runs as this app, the
Housecairn integration asked for an address that nobody knows: Home Assistant
reaches the app on the Supervisor's internal network, by the app's host name,
not by a public address. The app now gives Home Assistant that address
itself, through the Supervisor's discovery.

**What the app sends.** At each start (`run`, not the healthcheck nor
`manage`), after reading its own information (D10) and before HouseCairn
starts, the start script sends one message to the Supervisor:

```json
{"service": "housecairn", "config": {"host": "<hostname of the app>", "port": 8000}}
```

on `POST /discovery`, on the Supervisor's socket or with the app's token, as
for D10. `host` is read, not built: it is `hostname` of the app's own
information (`GET /addons/self/info`), which the Supervisor makes of the slug
and the prefix of the repository (`slug.replace("_", "-")`, `hostname` in
`supervisor/apps/model.py`), gives to the container
(`supervisor/docker/app.py`) and registers in its DNS. When the Supervisor did
not answer, the container's own host name, which the Supervisor set, stands in.
`port` is HouseCairn's server in the container, the target of ingress. Nothing
else: no token, no option, no public address. Home Assistant uses plain HTTP
on that network, which never leaves the host.

**Where it goes.** The Supervisor keeps one message per app and service
(`supervisor/discovery/__init__.py`): the same message at each start replaces
nothing and is sent on to Home Assistant only when it changed or when Home
Assistant may have missed it; the Supervisor lists the messages of started
apps only, and deletes them when the app is uninstalled. Home Assistant Core
then starts the config flow of the integration whose domain is the service,
`housecairn`, with the message as `HassioServiceInfo`
(`homeassistant/components/hassio/discovery.py`). Reading that message in the
integration is the integration's change (HouseCairn/home-assistant-housecairn).

**What it needs, and what it allows.** `discovery: [housecairn]` in
`config.yaml`: the Supervisor refuses a service the app does not list (403,
`set_discovery` in `supervisor/api/discovery.py`). **No `hassio_api` and no
`hassio_role`**: `/discovery*` is in `api_bypass` of the Supervisor's
security middleware (`supervisor/api/middleware/security.py`, main of
November 2026, for `/v2` as well), checked before `hassio_api` and the role,
and the developer documentation lists it among the calls an app may make
"without needing to set `hassio_api: true`" (Communication). So D6 still
holds: the app has no Supervisor API access beyond what every app has. What
that path lets an app do: send or replace its own messages, for the services
it lists, and delete its own (`del_discovery` refuses another app's).
Listing and reading messages is for Home Assistant Core only
(`require_home_assistant`). The security rating does not change (7, D6):
`rating_security` does not count `discovery`.

**The internal name is always accepted** (D10). Through ingress alone,
`ALLOWED_HOSTS` is `*`. With the port published, the app's names on the
internal network, `hostname` and the `dns` names of its information (such as
`<hostname>.local.hass.io`), are added after `allowed_hosts`: Home Assistant
must reach the address the app announces even when the option names only the
addresses of the browsers. `allowed_hosts` is still required with the port
published: the internal name is for software on the internal network, not
for a browser on the port. Accepting the internal name opens nothing: the
internal network already reaches the app, and could send any listed name
(D10).

**It never stops the start.** A refused or unanswered announcement (two
attempts, five seconds each) is logged with the address to give the
integration by hand, and HouseCairn starts. The log says, at each start,
either `announced to Home Assistant at http://<hostname>:8000` or why not.

Rejected:

- **`hassio_api: true` with `hassio_role: default`**: not needed for
  `/discovery`, which is in the Supervisor's `api_bypass` list, and it would
  give the start script, and any code that got its token, every `/…/info`
  endpoint of the Supervisor (`ROLE_DEFAULT`).
- **The public address (`site_url`) or the ingress address in the message**:
  the first may be absent or reach the app through a proxy the integration
  does not need, the second only opens with an ingress session.
- **The IP address of the app** (`ip_address` of its information): it can
  change when the app restarts; the host name does not.
- **Announcing from HouseCairn itself**: it would need the Supervisor's token
  or socket in HouseCairn's environment, which D3 keeps out.
