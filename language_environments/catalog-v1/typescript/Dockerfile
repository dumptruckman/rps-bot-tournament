ARG RPS_BUILD_TOOLCHAIN
ARG RPS_BASE_RUNTIME
FROM ${RPS_BUILD_TOOLCHAIN} AS build

COPY --from=team / /opt/rps/team/
COPY organizer/RpsWrapper.ts /opt/rps/build/RpsWrapper.ts
COPY organizer/typescript-6.0.3.tgz /opt/rps/build/typescript-6.0.3.tgz
RUN mkdir -p /opt/rps/compiler /opt/rps/dist && \
    tar -xzf /opt/rps/build/typescript-6.0.3.tgz -C /opt/rps/compiler && \
    cp /opt/rps/team/*.ts /opt/rps/build/ && \
    node /opt/rps/compiler/package/lib/tsc.js \
      --strict --target ES2022 --module commonjs \
      --rootDir /opt/rps/build --outDir /opt/rps/dist \
      /opt/rps/build/*.ts

FROM ${RPS_BASE_RUNTIME} AS artifact
COPY --from=build /opt/rps/dist/ /opt/rps/dist/
COPY --from=build /opt/rps/team/ /opt/rps/team/

WORKDIR /opt/rps/team
USER 65532:65532
ENTRYPOINT ["/usr/local/bin/node", "/opt/rps/dist/RpsWrapper.js"]
