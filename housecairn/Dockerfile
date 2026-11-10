# Housecairn as a Home Assistant app (docs/decisions.md, D2).
#
# Built by the Supervisor on the device: a thin layer over HouseCairn's
# published image, which brings everything else (application, dependencies,
# static files). Nothing is downloaded but that image. The base is pinned by
# its tag, which is also `version` in config.yaml, and by the digest of its
# multi-architecture index: Docker picks linux/amd64 or linux/arm64 from it.
FROM ghcr.io/housecairn/housecairn:sha-623e794@sha256:673defbae2e6123cbf3bc817c0ed3f5240b59d45b9571480c34ed2b73f5865df

# The start script runs as root, only to read /data/options.json (written by
# the Supervisor, mode 600) and to give /data to 10001:10001; it then drops
# root before HouseCairn starts (run.py). It is owned by root and read-only
# for the application user.
USER root
COPY rootfs /

# The system Python of the image, in isolated mode: no PYTHON* variable, no
# user site, and not the virtual environment of the application.
ENTRYPOINT ["/usr/local/bin/python3", "-I", "/usr/local/lib/housecairn-app/run.py"]
CMD ["run"]

# Same probe and timings as HouseCairn's image, through run.py, which gives the
# probe a host name of allowed_hosts (they are options, not variables of the
# container).
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --start-interval=2s --retries=3 \
    CMD ["/usr/local/bin/python3", "-I", "/usr/local/lib/housecairn-app/run.py", "healthcheck"]

LABEL org.opencontainers.image.title="Housecairn (Home Assistant app)" \
    org.opencontainers.image.description="Housecairn, built for the Home Assistant Supervisor." \
    org.opencontainers.image.source="https://github.com/HouseCairn/home-assistant-addons" \
    org.opencontainers.image.licenses="AGPL-3.0-only"
