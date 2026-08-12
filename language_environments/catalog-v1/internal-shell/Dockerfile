ARG RPS_BUILD_TOOLCHAIN
ARG RPS_BASE_RUNTIME
FROM ${RPS_BUILD_TOOLCHAIN} AS build
COPY --from=team / /opt/rps/team/
RUN /bin/sh -n /opt/rps/team/strategy.sh

FROM ${RPS_BASE_RUNTIME} AS artifact
COPY --from=build /opt/rps/team/ /opt/rps/team/
COPY organizer/wrapper.sh /opt/rps/wrapper.sh

WORKDIR /opt/rps/team
USER 65532:65532
ENTRYPOINT ["/bin/sh", "/opt/rps/wrapper.sh"]
