FROM library/postgres:17.6-bookworm@sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3 AS build
USER root
RUN apt-get update && apt-get install -y --no-install-recommends build-essential postgresql-server-dev-17 && rm -rf /var/lib/apt/lists/*
ADD --checksum=sha256:69f4019389af05dc1c9548deb8628e62878e6e207c03907f2b8af2016472cdaa https://github.com/pgvector/pgvector/archive/refs/tags/v0.8.2.tar.gz /tmp/vector.tar.gz
RUN tar -xzf /tmp/vector.tar.gz -C /tmp && cd /tmp/pgvector-0.8.2 && make OPTFLAGS="" && make install DESTDIR=/extension
FROM library/postgres:17.6-bookworm@sha256:f3bd19c606e442c3d7bdfa8002e03fe260a1023351e0ea4598032022b68dd6e3 AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-17-postgis-3 && rm -rf /var/lib/apt/lists/*
COPY --from=build /extension/ /
