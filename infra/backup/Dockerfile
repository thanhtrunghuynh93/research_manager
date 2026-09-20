FROM alpine:3.20

# The MinIO client, which backup.sh uses to mirror the object bucket. Two traps here, both of
# which produce a backup that appears to work:
#
#  1. dl.min.io's unversioned .../linux-amd64/mc now answers 410 Gone, so this image stopped
#     building — the same withdrawal that already moved the server image to quay.io
#     (see infra/docker-compose.yml). The release is pinned, like the server image, and comes
#     from the GitHub release that publishes a checksum beside it.
#  2. Alpine's own `mc` package is Midnight Commander, a file manager. `apk add mc` installs
#     something that is not this, and `mc mirror` against it does not mean what backup.sh means.
#
# The checksum is verified because this binary is fetched over the network at build time and then
# trusted with every object in the store. The old line piped an unverified download straight to
# chmod +x.
ARG MC_RELEASE=RELEASE.2025-08-13T08-35-41Z
ARG MC_SHA256=01f866e9c5f9b87c2b09116fa5d7c06695b106242d829a8bb32990c00312e891
RUN apk add --no-cache postgresql16-client age rclone curl bash tzdata \
 && curl -fsSL "https://github.com/minio/mc/releases/download/${MC_RELEASE}/mc.linux-amd64.${MC_RELEASE}" -o /usr/local/bin/mc \
 && echo "${MC_SHA256}  /usr/local/bin/mc" | sha256sum -c - \
 && chmod +x /usr/local/bin/mc \
 && mc --version
COPY backup.sh restore.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/restore.sh
# Run the backup on the configured cron schedule (default 02:00 UTC, see docker-compose.yml).
CMD ["sh", "-c", "echo \"${BACKUP_CRON} /usr/local/bin/backup.sh >> /proc/1/fd/1 2>&1\" > /etc/crontabs/root && crond -f -l 8"]
