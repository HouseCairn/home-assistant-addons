# Changelog

All notable changes of the Housecairn app. The version of the app is the tag of
the Housecairn image it is built from.

## 0.3.1

Built from `ghcr.io/housecairn/housecairn:0.3.1`, a release of Housecairn. Read
its [release notes](https://github.com/HouseCairn/housecairn/releases/tag/v0.3.1).
It only fixes the public demonstration instance of Housecairn, which the app
does not expose: nothing changes for a Home Assistant user and there is no
migration.

## 0.3.0

Built from `ghcr.io/housecairn/housecairn:0.3.0`, a release of Housecairn. Read
its [release notes](https://github.com/HouseCairn/housecairn/releases/tag/v0.3.0)
before updating, and make a backup that includes the app, as for every update.
Housecairn is still alpha software. What it brings to the app, among the rest:

- **Four database migrations run on the first start after the update.** All are
  reversible and none changes existing data. Nothing to change in the app's
  configuration.
- **Planned cost of a task now counts the stock.** A stock item can have a unit
  price, and the planned cost of a task adds the quantity of each stock item it
  lists times its price. The figures of your budget may go up for tasks that
  list priced stock items.
- **Testing a notification channel and adding a link no longer hold the
  screen.** Both are done by the background worker, which runs in the app: the
  screen answers at once, then shows the result (reload the page if it does not
  change by itself). The API answers `202` for the channel test instead of the
  result.
- **Restore the archive of a home as a copy**, next to the original, which is
  not touched. Use it to duplicate a home or to check a backup.
- **Notifications on the device (Web Push)**, off by default: an administrator
  turns on **Notifications on the device** in Housecairn, under **Instance
  administration**, **Settings**, **Notifications**. Not tested through
  Home Assistant's ingress.
- **Every reviewed Apprise service for notification channels** (137), a search
  field with chips to choose several rooms or items, and an installable
  application with Today and the task list readable offline.
- **Fixes**: sign-up and the other emails no longer end in a server error when
  the mail server fails; a refused restore leaves no file behind; tabs fit on a
  320 px screen.

The demonstration mode of Housecairn (`HOUSECAIRN_DEMO`) is not exposed by the
app: it erases all data every night and is meant for a public demonstration
instance only.

## 0.2.0

Built from `ghcr.io/housecairn/housecairn:0.2.0`, the next release of
Housecairn. Read its
[release notes](https://github.com/HouseCairn/housecairn/releases/tag/v0.2.0)
before updating, and make a backup that includes the app, as for every update.
What it brings to the app, among the rest:

- **Two defaults changed, both for safety.** Notification channels on a
  private network, such as a ntfy or a Gotify on your local network, are
  refused until an administrator allows them: if you use one, turn on
  **Channels on the local network** in Housecairn, under **Instance
  administration**, **Settings**, **Notifications**; its test says why it is
  refused until then. Housecairn's own instance backup no longer holds the
  secret key; a Home Assistant backup of the app still copies its whole data
  folder, key included, and restores alone as before.
- **The 400 page of a refused host name says what to do**: add the name. Through
  ingress alone every name is accepted; on the published port, the name goes
  in **Host names**, on the app's **Configuration** tab.
- **The provider of a maintenance contract is a contractor of the home.** On
  the first start after the update, Housecairn migrates its database once: each
  provider written as a text becomes a contractor of the same home, created
  when the home has none of that name. Nothing is lost, and the archive of a
  home moves to format 3.
- **A refused form says why, at the top**, with a summary linked to each field.
- **Add a room, an item or a stock item from the task form**, and up to 50
  material lines.
- One date format per language, and a clear message for a comma in a number
  in English.

In the app itself:

- **Host names is no longer needed through ingress.** At each start, the app
  asks the Supervisor whether its port is open on the host. While it is
  closed, the default, Housecairn can only be reached through Home Assistant's
  ingress and accepts every name or address you use for Home Assistant: an IP
  address or a remote access domain no longer gets "Bad request" on the first
  start. **Host names** is now empty by default and only used once the port
  is open, where it keeps its role, through ingress as on the port; the app
  then refuses to start while it is empty, and its log names the option to
  fill. Nothing to change if you set Host names already: it is kept, and used
  whenever the port is open.
- The app reads its own information from the Supervisor for this (the host
  port of `8000/tcp`), which every app may do: still no access to the
  Supervisor's or Home Assistant's API beyond that.

## 0.1.0

The first version of the app with a version number: it is now built from
`ghcr.io/housecairn/housecairn:0.1.0`, a release of Housecairn, instead of
an image of a single commit. Its updates follow Housecairn's releases: 0.1.x
for fixes, 0.2.0 for the next features. What Housecairn 0.1.0 brings since
`sha-4be6010` is in its
[release notes](https://github.com/HouseCairn/housecairn/releases/tag/v0.1.0),
among them:

- **Import tables from CSV files**, with a preview that writes nothing, then
  every row in one go.
- **Task templates**: about twenty common tasks of a home, in English and in
  French.
- **Repetition in one sentence** on the task form, and estimated durations up
  to a year; the contractor of a task is chosen in a list.
- **API tokens for a home that requires a sign-in provider**, as the Home
  Assistant integration uses, and tasks without a date in the API.
- Back links, **Cancel** and breadcrumbs that lead back to where you came from.

Nothing to change in the app's configuration. On the first start after the
update, Housecairn migrates its database: the heating season of a task or a
project becomes a custom season of the same months, so nothing changes for
them. Make a backup first, as for every update.

## sha-4be6010

**Backward-incompatible: port 8000 is closed by default.** If you used
Housecairn on `http://<address>:8000` with the first version, it is no longer
there after this update, unless you had set the port number yourself on the
**Configuration** tab (**Network**). To keep it, give `8000/tcp` a port number
there, save and restart the app. Housecairn now opens inside Home Assistant
(ingress); the port is only needed for links meant to be opened outside it.

- Housecairn built from `ghcr.io/housecairn/housecairn:sha-4be6010`, which
  serves the application under a path prefix, can be shown in a frame of the
  same origin, builds the links meant for outside on its public address, and
  creates the first administrator on a web screen.
- **Ingress**: Housecairn opens inside Home Assistant, and can be added to the
  sidebar, for administrators and other users. It still asks for its own
  sign-in.
- **First administrator without a shell**: at each start without an
  administrator, Housecairn writes a one-time code in the app's **Log** tab;
  give it on the `/setup/` screen.
- **New option, Public address** (`site_url`): links of invitations, calendar
  feeds, QR labels and emails are built on it. Set it to an address that
  reaches Housecairn without Home Assistant, such as the port.
- The forwarded headers (path prefix, HTTPS) are trusted from the Supervisor
  only, and only a page of the same origin may show Housecairn in a frame.

## sha-623e794

First version, experimental.

- Housecairn built from `ghcr.io/housecairn/housecairn:sha-623e794`, for
  `amd64` and `aarch64`.
- Web interface on port 8000, in plain HTTP, without ingress.
- Options: host names, default language, time zone (Home Assistant's by
  default), open sign-up, single sign-on (OpenID Connect) and its first
  administrator.
- Database, files and secret key in the app's data folder, included in Home
  Assistant backups (the app stops during a backup).
