ARG RPS_BUILD_TOOLCHAIN
ARG RPS_BASE_RUNTIME
FROM ${RPS_BUILD_TOOLCHAIN} AS build

COPY --from=team / /opt/rps/team/
COPY organizer/wrapper.rb /opt/rps/build/wrapper.rb
RUN cp /opt/rps/team/*.rb /opt/rps/build/ && \
    for source in /opt/rps/build/*.rb; do ruby -c "$source" || exit 1; done && \
    printf '#!/bin/sh\nexec ruby /opt/rps/wrapper.rb\n' > /opt/rps/bot && \
    chmod 0555 /opt/rps/bot

FROM ${RPS_BASE_RUNTIME} AS artifact
COPY --from=build /opt/rps/bot /opt/rps/bin/bot
COPY --from=build /opt/rps/build/ /opt/rps/
COPY --from=build /opt/rps/team/ /opt/rps/team/
WORKDIR /opt/rps/team
USER 65532:65532
ENTRYPOINT ["/opt/rps/bin/bot"]
