FROM library/golang:1.24.8-bookworm@sha256:4ed690d6649d63c312b99a6120025ec79ce3b542968a37da53d6236c7c61a848 AS build
ENV GOTOOLCHAIN=local CGO_ENABLED=0
ADD --checksum=sha256:be6d0bd3696c3a13a35f02d3a0280b64319c67918b4501c5c3d87f96d000085c https://github.com/minio/minio/archive/refs/tags/RELEASE.2025-10-15T17-29-55Z.tar.gz /tmp/minio.tar.gz
ADD --checksum=sha256:29db22500374169a43951c7cef09daf19e7291ea5ba00ac10f321371b0a35b32 https://github.com/minio/mc/archive/refs/tags/RELEASE.2025-08-13T08-35-41Z.tar.gz /tmp/mc.tar.gz
RUN mkdir /src /mc && tar -xzf /tmp/minio.tar.gz -C /src --strip-components=1 && tar -xzf /tmp/mc.tar.gz -C /mc --strip-components=1
WORKDIR /src
RUN go build -mod=readonly -trimpath -buildvcs=false -o /out/minio .
WORKDIR /mc
RUN go build -mod=readonly -trimpath -buildvcs=false -o /out/mc .
FROM library/python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS runtime
COPY --from=build /out/minio /out/mc /usr/local/bin/
COPY scripts/bootstrap_storage.py /bootstrap_storage.py
COPY --from=build /src/LICENSE /usr/share/doc/minio/LICENSE
COPY --from=build /mc/LICENSE /usr/share/doc/mc/LICENSE
RUN useradd --uid 10001 --create-home floatchat && mkdir /data && chown 10001:10001 /data
USER 10001
EXPOSE 9000
CMD ["minio", "server", "/data", "--console-address", ":9001"]
