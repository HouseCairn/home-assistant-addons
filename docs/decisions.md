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

## D5. The web interface on its own port, in plain HTTP, until ingress

This first version opens HouseCairn on port 8000 of the host
(`webui: http://[HOST]:[PORT:8000]`), without ingress, which needs a change of
HouseCairn first (serving under a path prefix).

HouseCairn's defaults enforce HTTPS: redirection, HSTS, cookies sent over
HTTPS only. On a port without TLS they would make the instance unusable, so
`config.yaml` sets `SECURE_SSL_REDIRECT=false`, `SECURE_HSTS_SECONDS=0`,
`SESSION_COOKIE_SECURE=false` and `CSRF_COOKIE_SECURE=false`, and nothing else.
What follows, written in `DOCS.md`:

- passwords and session cookies cross the local network in clear: use it on a
  network you trust, not from the Internet;
- passkeys and the anti-robot check of open sign-up need a secure context
  (HTTPS, or `localhost`), so they do not work this way.

## D6. Least privilege

No `map` (only the app's private `/data`, which the Supervisor always mounts),
no host network, no added Linux capability, no device, no access to the
Supervisor or Home Assistant APIs, protection mode left on. `/tmp` is in
memory (`tmpfs: true`), as in HouseCairn's `compose.yaml`.

AppArmor: the Supervisor applies Docker's default profile. The documentation
recommends a profile of the app's own, but asks to write it by running the app
with the profile in complain mode and reading the audit log. That needs a real
installation, so no `apparmor.txt` is shipped yet: an untested profile would
either block HouseCairn or protect nothing.

Security rating, as the Supervisor computes it: 5 (the starting value; no
bonus, since a port is mapped to the host and there is no ingress yet).

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
