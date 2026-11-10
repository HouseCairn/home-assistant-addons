# Changelog

All notable changes of the Housecairn app. The version of the app is the tag of
the Housecairn image it is built from.

## sha-79ca410

- Housecairn built from `ghcr.io/housecairn/housecairn:sha-79ca410`, which
  serves the application under a path prefix.
- **Ingress**: Housecairn opens inside Home Assistant, and can be added to the
  sidebar, for administrators and other users. It still asks for its own
  sign-in.
- **Backward-incompatible: the port is off by default.** After the update,
  Housecairn is no longer on port 8000, unless you had set its port number
  yourself on the Configuration tab (Network): give it one there to keep it.
  Links meant to be opened outside Home Assistant
  (calendar feeds, QR labels, invitations, emails) need it: see the
  documentation.
- The forwarded headers (path prefix, HTTPS) are trusted from the Supervisor
  only.

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
