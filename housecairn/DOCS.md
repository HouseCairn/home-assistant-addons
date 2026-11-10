# Housecairn

Housecairn plans the maintenance and the renovation work of a home: what to do,
in which room, when, with what material and for how much. This app runs it next
to Home Assistant, with its data in the app's own folder. The documentation of
Housecairn itself is at <https://docs.housecairn.app>.

**Experimental.** This first version opens Housecairn on its own port, in plain
HTTP, on your local network. It does not appear in the Home Assistant sidebar
yet (see [Limits](#limits)).

## Install

1. Add the repository: **Settings** > **Apps** > **Install app**, top-right
   menu, **Repositories**, then
   `https://github.com/HouseCairn/home-assistant-addons`.
2. Select **Housecairn**, then **Install**. The Supervisor builds the app on
   your device, over Housecairn's published image: it takes a minute or so,
   mostly to download that image.
3. On the **Configuration** tab, check **Host names** (below), then save.
4. On the **Info** tab, select **Start**, then **Open web UI**.

The app runs on 64-bit systems only: `amd64` (most PCs and mini PCs) and
`aarch64` (Raspberry Pi 4 and 5, Home Assistant Green and Yellow, with a 64-bit
system).

## Options

Only **Host names** is required. An option you leave empty keeps Housecairn's
default; where Housecairn also has the setting in its own administration
screens, it stays editable there. An option you set locks that field in
Housecairn: change it here.

| Option | What it does |
| --- | --- |
| Host names (`allowed_hosts`) | The names and addresses you type in the browser to reach Home Assistant, such as `homeassistant.local` or `192.0.2.10`, one per line. Housecairn refuses any other. An IPv6 address goes in brackets: `[2001:db8::1]`. `*` is refused. |
| Default language (`default_language`) | `en` or `fr`, for browsers that ask for no language Housecairn offers. |
| Time zone (`time_zone`) | Such as `Europe/Paris`: it decides what "today" is. Empty: the time zone of Home Assistant. |
| Open sign-up (`signup_open`) | Lets anyone create an account from the sign-up page. Leave it off: it needs outgoing email and HTTPS (see [Limits](#limits)). Housecairn does not start with open sign-up and no outgoing email server configured, and the email settings are in its administration screens, which need a first administrator: leave it off at first. |
| Single sign-on (`oidc_server_url`, `oidc_client_id`, `oidc_client_secret`, `oidc_provider_name`) | An OpenID Connect provider for sign-in. `oidc_server_url` is the issuer, an `https://` address; the client identifier is then required. See [Single sign-on](https://docs.housecairn.app/administration/oidc/). |
| First administrator (`bootstrap_admin_email`) | With single sign-on: only the person with this address, verified by the provider, can become the first administrator. |

The secret key of the instance is not an option: Housecairn creates it on first
start, in its data folder.

Other settings, such as outgoing email, are in Housecairn's own administration
screens once you are signed in.

## First start

Housecairn creates no account and has no default password. The first
administrator comes from one of these:

- **Single sign-on.** Set the single sign-on options, preferably with
  **First administrator**, and restart the app. The first person to sign in
  through the provider becomes the administrator. Register this redirect
  address at the provider, with the host name and port you use:
  `http://homeassistant.local:8000/accounts/oidc/oidc/login/callback/`. Many
  providers only accept `https://` redirect addresses outside `localhost`:
  check yours.
- **A local account, from the command line.** This needs a shell with access
  to Docker on the host (for example the community SSH app with protection
  mode off). Find the name of the container with `docker ps` (it ends with
  `housecairn`), then:

  ```sh
  docker exec -it <container> /usr/local/bin/python3 -I \
    /usr/local/lib/housecairn-app/run.py manage createsuperuser
  ```

  Go through the app's start script as shown: it runs the command as
  Housecairn's user, not as root.

Then open the web UI and sign in.

## Data and backups

Everything Housecairn writes is in the app's data folder: the database
(SQLite), the uploaded photos and files, and the secret key. A Home Assistant
backup that includes the app contains all of it, and restoring it brings the
instance back as it was.

The app is stopped while it is backed up, for a consistent copy of the
database, then started again: Housecairn is unavailable for that time.

Uninstalling the app deletes its data, unless you choose to keep it. Back it up
first.

## Update

1. Read the changelog of the app (and the release notes of Housecairn it
   links to).
2. Make a backup that includes the app.
3. Update the app. The Supervisor builds it again over the new Housecairn
   image; the database is migrated when it starts.

Going back to an older version after a migration needs the backup.

## Limits

- **No ingress yet**: Housecairn is not in the Home Assistant sidebar, and is
  reached on port 8000 of the host. This comes in a later version.
- **Plain HTTP**: passwords and session cookies cross your local network in
  clear. Use the app on a network you trust; do not expose port 8000 to the
  Internet.
- **No passkeys, no open sign-up**: both need a secure connection (HTTPS) in
  the browser. Sign in with a password, or through single sign-on.
- **SQLite only**: the app does not offer PostgreSQL.
- **No AppArmor profile of its own yet**: the app runs with Docker's default
  profile.

## Help and source

Report a problem in the
[issues of this repository](https://github.com/HouseCairn/home-assistant-addons/issues),
or of [Housecairn](https://github.com/HouseCairn/housecairn/issues) when it is
not about the app. The design choices of the app are in
[docs/decisions.md](https://github.com/HouseCairn/home-assistant-addons/blob/main/docs/decisions.md).

## License

Housecairn, by Robvred. This app is licensed under the GNU Affero General
Public License, version 3 only, with the additional terms of
[NOTICE](https://github.com/HouseCairn/home-assistant-addons/blob/main/NOTICE).
