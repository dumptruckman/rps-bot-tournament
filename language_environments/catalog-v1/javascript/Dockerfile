ARG RPS_BUILD_TOOLCHAIN
ARG RPS_BASE_RUNTIME
FROM ${RPS_BUILD_TOOLCHAIN} AS build

COPY --from=team / /opt/rps/team/
COPY organizer/RpsWrapper.js /opt/rps/RpsWrapper.js
RUN node --check /opt/rps/RpsWrapper.js && \
    node --check /opt/rps/team/strategy.js && \
    find /opt/rps/team -type f -name '*.js' ! -name strategy.js \
      -exec node --check '{}' ';'

FROM ${RPS_BASE_RUNTIME} AS artifact
COPY --from=build /opt/rps/RpsWrapper.js /opt/rps/RpsWrapper.js
COPY --from=build /opt/rps/team/ /opt/rps/team/

WORKDIR /opt/rps/team
USER 65532:65532
ENTRYPOINT ["/usr/local/bin/node", "/opt/rps/RpsWrapper.js"]
