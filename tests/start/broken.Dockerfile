# Negative control of the start test (D14): the app with a migration that
# fails. The start test must fail on it.
ARG BASE=housecairn-app:test
# hadolint ignore=DL3006
FROM ${BASE}
RUN migrations=$(/app/.venv/bin/python -c \
        'import os, housecairn.accounts.migrations as m; print(os.path.dirname(m.__file__))') \
    && printf '\nraise RuntimeError("a migration broken on purpose")\n' >>"$migrations/0002_instance_setup.py"
