# Changelog

All notable changes of the Housecairn app. The version of the app is the tag of
the Housecairn image it is built from.

## 0.1.1 (unreleased)

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
