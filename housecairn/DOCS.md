# Housecairn

Housecairn plans the maintenance and the renovation work of a home: what to do,
in which room, when, with what material and for how much. This app runs it next
to Home Assistant, with its data in the app's own folder. The documentation of
Housecairn itself is at <https://docs.housecairn.app>.

**Experimental.** Housecairn opens inside Home Assistant, through ingress, and
can be added to the sidebar. It can also be opened on a port of its own, which
is off by default (see [The port](#the-port)).

## Install

1. Add the repository: **Settings** > **Apps** > **Install app**, top-right
   menu, **Repositories**, then
   `https://github.com/HouseCairn/home-assistant-addons`.
2. Select **Housecairn**, then **Install**. The Supervisor builds the app on
   your device, over Housecairn's published image: it takes a minute or so,
   mostly to download that image.
3. On the **Configuration** tab, check **Host names** (below), then save.
4. On the **Info** tab, select **Start**, then **Open web UI**. Turn on
   **Show in sidebar** to keep it at hand.
5. Create the first administrator with the code of the **Log** tab: see
   [First start](#first-start).

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
| Host names (`allowed_hosts`) | The names and addresses you type in the browser to reach Home Assistant, such as `homeassistant.local` or `192.0.2.10`, one per line, including those of remote access (such as `ha.example.com`). Housecairn refuses any other: Home Assistant passes it the name the browser used. An IPv6 address goes in brackets: `[2001:db8::1]`. `*` is refused. |
| Default language (`default_language`) | `en` or `fr`, for browsers that ask for no language Housecairn offers. |
| Time zone (`time_zone`) | Such as `Europe/Paris`: it decides what "today" is. Empty: the time zone of Home Assistant. |
| Open sign-up (`signup_open`) | Lets anyone create an account from the sign-up page. Leave it off: it needs outgoing email and HTTPS (see [Limits](#limits)). Housecairn does not start with open sign-up and no outgoing email server configured, and the email settings are in its administration screens, which need a first administrator: leave it off at first. |
| Public address (`site_url`) | The address that reaches Housecairn without Home Assistant, such as [the port](#the-port) (`http://192.0.2.10:8000`), without a path. The links of invitations, calendar feeds, QR labels and emails are built on it: see [Links meant for outside](#links-meant-for-outside-home-assistant). |
| Single sign-on (`oidc_server_url`, `oidc_client_id`, `oidc_client_secret`, `oidc_provider_name`) | An OpenID Connect provider for sign-in. `oidc_server_url` is the issuer, an `https://` address; the client identifier is then required. See [Single sign-on](https://docs.housecairn.app/administration/oidc/). |
| First administrator (`bootstrap_admin_email`) | With single sign-on: only the person with this address, verified by the provider, can become the first administrator. |

The secret key of the instance is not an option: Housecairn creates it on first
start, in its data folder.

Other settings, such as outgoing email, are in Housecairn's own administration
screens once you are signed in.

## Ingress

**Open web UI** and the sidebar entry show Housecairn inside Home Assistant,
under an address such as `/api/hassio_ingress/<token>/`. Home Assistant checks
that you are signed in to it, then passes the request on; Housecairn accepts
that address, and the forwarded details of the connection (whether you use
HTTPS), from Home Assistant's Supervisor only.

- **Housecairn still asks for its own sign-in.** Its accounts are its own: Home
  Assistant's sign-in only lets you reach it. Users who are not Home Assistant
  administrators see the sidebar entry too.
- **HTTP or HTTPS, as Home Assistant.** Housecairn follows the way you reach
  Home Assistant. Through HTTPS, the connection is encrypted up to Home
  Assistant.
- **The token of the address is set when the app is installed.** It stays the
  same across restarts and updates, and changes if the app is uninstalled and
  installed again.
- **Shown in a frame of Home Assistant.** Housecairn lets a page of the same
  address (scheme, name and port) show it in a frame, as Home Assistant does,
  and no other site.

### Links meant for outside Home Assistant

Calendar feeds, QR labels, invitations, and the links of emails and reminders
are opened by something other than Home Assistant's interface: a calendar app,
a phone that scans a label, a mail client. The ingress address does not work
for them: Home Assistant only lets a request through to the app when it comes
from a browser with an ingress session, which its own interface opens.

So Housecairn never puts the ingress address in these links: it builds them on
its **Public address** (`site_url`), wherever they are created.

1. Turn on [the port](#the-port), or use another address that reaches the app
   without Home Assistant.
2. Set **Public address** to it, such as `http://192.0.2.10:8000`, without a
   path, and add its name or address to **Host names**. Restart the app.

**Without a public address, these links do not work outside Home
Assistant.** Created through ingress, they hold the address of Home Assistant
without the ingress path, which leads nowhere; created on the port, they hold
the port's address. Reminders and report alerts, sent in the background, carry
no link at all.

## The port

Housecairn can also be opened on a port of the host, in plain HTTP, for the
links above or from a device without Home Assistant's interface. It is off by
default; it was on in the first version of the app (see the changelog). To
turn it on, on the **Configuration** tab, under **Network**, give `8000/tcp` a
port number, such as `8000`, save and restart the app. Then open
`http://<address of Home Assistant>:8000`.

- **Open it with another address than Home Assistant**, such as its IP address
  when you reach Home Assistant by name: browsers keep cookies per name, not
  per port, so a sign-in on the port would also be sent to ingress and the two
  would get mixed up.
- Its address must be in **Host names**, as for ingress. Requests on the port
  are never taken for requests of the Supervisor: what they say about HTTPS or
  about the address is ignored.
- Plain HTTP: passwords and session cookies cross your local network in clear.
  Do not expose this port to the Internet.

## First start

Housecairn creates no account and has no default password. The first
administrator comes from one of these:

- **The first-account screen**, the usual way. At each start, while there is
  no administrator, Housecairn writes a one-time code in its log:

  1. On the **Log** tab of the app, find the lines that start with
     `HouseCairn has no administrator yet.` and copy the
     **First-account code** (such as `7QKF-3MZB-XJ2D-...`).
  2. Open the web UI. The sign-in page links to the first-account screen
     (`/setup/`) while it is open: follow the link, give the code, your name,
     your email address and a password.

  The code works once and expires after an hour; restart the app for a new
  one. The address written next to it is that of the **Public address**, or
  just `/setup/` while it is empty: through ingress, use the link of the
  sign-in page instead. Only Home Assistant administrators can read the log.
- **Single sign-on.** Set the single sign-on options, preferably with
  **First administrator**, and restart the app. The first person to sign in
  through the provider becomes the administrator. Single sign-on goes through
  [the port](#the-port): through ingress, the redirect address would hold the
  ingress token. Register this redirect address at the provider, with the
  address and port you use:
  `http://192.0.2.10:8000/accounts/oidc/oidc/login/callback/`. Many
  providers only accept `https://` redirect addresses outside `localhost`:
  check yours.
  The first-account screen and single sign-on both create the first
  administrator; the first one used closes the other.
- **A local account, from the command line**. This needs a shell with access
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

- **Links meant for outside Home Assistant** (calendar feeds, QR labels,
  invitations, emails) need a public address that reaches the app without
  Home Assistant, such as the port: see
  [Links meant for outside](#links-meant-for-outside-home-assistant).
- **Plain HTTP on the port**, and through ingress when Home Assistant itself is
  reached in plain HTTP: passwords and session cookies cross your local network
  in clear. Use it on a network you trust.
- **No passkeys, no open sign-up on the port**: both need a secure connection
  (HTTPS) in the browser. Sign in with a password, or through single sign-on.
- **Sign-in attempts are counted per Home Assistant, not per device, through
  ingress**: Housecairn sees every ingress request come from Home Assistant, so
  a series of failed sign-ins slows down everyone who uses ingress for a while.
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
