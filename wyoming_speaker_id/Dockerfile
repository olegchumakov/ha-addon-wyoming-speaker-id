# The base image for each architecture comes from build.yaml (passed in by the builder and CI).
ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY rootfs/usr/src/speaker_id/requirements.txt /usr/src/speaker_id/requirements.txt
RUN python3 -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r /usr/src/speaker_id/requirements.txt

COPY models /usr/share/speaker_id/models
COPY rootfs /
RUN chmod a+x /etc/services.d/speaker-id/run /etc/services.d/speaker-id/finish

WORKDIR /usr/src/speaker_id

ARG BUILD_ARCH BUILD_VERSION
LABEL io.hass.type="addon" io.hass.arch="${BUILD_ARCH}" io.hass.version="${BUILD_VERSION}"
