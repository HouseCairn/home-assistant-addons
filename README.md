# Housecairn apps for Home Assistant

This repository installs [Housecairn](https://github.com/HouseCairn/housecairn)
on Home Assistant OS, or on any installation with the Supervisor, as an app
(formerly "add-on").

Housecairn is a self-hosted planner for home maintenance and renovation work:
what to do in the house, where, when, with what and for how much. Its
documentation is at <https://docs.housecairn.app>.

[![Open your Home Assistant instance and show the add app repository dialog with a specific repository URL pre-filled.](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2FHouseCairn%2Fhome-assistant-addons)

## Apps

| App | Description |
| --- | --- |
| [Housecairn](housecairn/) | The Housecairn web application, with its data kept in the app's own folder and included in Home Assistant backups. |

## Install

1. In Home Assistant, go to **Settings** > **Apps** and select **Install app**.
2. In the top-right menu, select **Repositories**, enter
   `https://github.com/HouseCairn/home-assistant-addons` and select **Add**
   (or use the button above).
3. Find **Housecairn** in the list, install it, then read its
   **Documentation** tab before you start it.

The app is **experimental**: it opens on its own port, without HTTPS and
without the Home Assistant sidebar for now. See
[housecairn/DOCS.md](housecairn/DOCS.md) for what that means.

## Development

Design choices of this repository are in [docs/decisions.md](docs/decisions.md).
Housecairn is developed with an AI coding agent, under human review; each pull
request states which AI tool and model were used.

## License

Housecairn, by Robvred. This repository is licensed under the GNU Affero
General Public License, version 3 only (`AGPL-3.0-only`), with the additional
terms of [NOTICE](NOTICE). The name and the logo of Housecairn are not covered
by the license (see `NOTICE`).
