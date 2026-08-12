ARG RPS_BUILD_TOOLCHAIN
ARG RPS_BASE_RUNTIME
FROM ${RPS_BUILD_TOOLCHAIN} AS build

COPY --from=team / /opt/rps/team/
COPY organizer/wrapper.rs /opt/rps/build/wrapper.rs
RUN cp /opt/rps/team/*.rs /opt/rps/build/ && \
    cd /opt/rps/build && \
    rustc --edition=2024 -C opt-level=3 -C strip=symbols \
      -o /opt/rps/bot wrapper.rs

FROM ${RPS_BASE_RUNTIME} AS artifact
COPY --from=build /opt/rps/bot /opt/rps/bin/bot
COPY --from=build /opt/rps/team/ /opt/rps/team/

WORKDIR /opt/rps/team
USER 65532:65532
ENTRYPOINT ["/opt/rps/bin/bot"]
