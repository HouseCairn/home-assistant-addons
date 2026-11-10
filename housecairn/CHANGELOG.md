# Changelog

All notable changes of the Housecairn app. The version of the app is the tag of
the Housecairn image it is built from.

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
