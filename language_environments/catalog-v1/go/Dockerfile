ARG RPS_BUILD_TOOLCHAIN
ARG RPS_BASE_RUNTIME
FROM ${RPS_BUILD_TOOLCHAIN} AS build

COPY --from=team / /opt/rps/team/
COPY organizer/wrapper.go /opt/rps/build/wrapper.go
RUN cp /opt/rps/team/*.go /opt/rps/build/ && \
    cd /opt/rps/build && \
    CGO_ENABLED=0 GO111MODULE=off GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off \
      go build -trimpath -buildvcs=false -ldflags='-s -w' -o /opt/rps/bin/bot .

FROM ${RPS_BASE_RUNTIME} AS artifact
COPY --from=build /opt/rps/bin/bot /opt/rps/bin/bot
COPY --from=build /opt/rps/team/ /opt/rps/team/

WORKDIR /opt/rps/team
USER 65532:65532
ENTRYPOINT ["/opt/rps/bin/bot"]
