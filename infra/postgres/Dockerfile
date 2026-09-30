FROM postgres:17
RUN mkdir -p /wal-archive /backups \
 && chown postgres:postgres /wal-archive /backups \
 && chmod 700 /wal-archive /backups
COPY infra/postgres/initdb/ /docker-entrypoint-initdb.d/
COPY infra/postgres/scripts/ /usr/local/bin/
RUN sed -i 's/\r$//' /docker-entrypoint-initdb.d/*.sh /usr/local/bin/*.sh \
 && chmod 755 /docker-entrypoint-initdb.d/*.sh /usr/local/bin/*.sh
