# Changelog

All notable changes of the Housecairn app. The version of the app is the tag of
the Housecairn image it is built from.

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
