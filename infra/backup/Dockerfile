FROM alpine:3.20
RUN apk add --no-cache postgresql16-client age rclone curl bash tzdata \
 && curl -fsSL https://dl.min.io/client/mc/release/linux-amd64/mc -o /usr/local/bin/mc \
 && chmod +x /usr/local/bin/mc
COPY backup.sh restore.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/backup.sh /usr/local/bin/restore.sh
# Run the backup on the configured cron schedule (default 02:00 UTC, see docker-compose.yml).
CMD ["sh", "-c", "echo \"${BACKUP_CRON} /usr/local/bin/backup.sh >> /proc/1/fd/1 2>&1\" > /etc/crontabs/root && crond -f -l 8"]
