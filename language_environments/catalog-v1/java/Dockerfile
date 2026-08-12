ARG RPS_BUILD_TOOLCHAIN
ARG RPS_BASE_RUNTIME
FROM ${RPS_BUILD_TOOLCHAIN} AS build

COPY --from=team / /opt/rps/team/
COPY organizer/RpsWrapper.java /opt/rps/build/RpsWrapper.java
RUN cp /opt/rps/team/*.java /opt/rps/build/ && \
    javac --release 25 -encoding UTF-8 -d /opt/rps/classes /opt/rps/build/*.java

FROM ${RPS_BASE_RUNTIME} AS artifact
COPY --from=build /opt/rps/classes/ /opt/rps/classes/
COPY --from=build /opt/rps/team/ /opt/rps/team/

WORKDIR /opt/rps/team
USER 65532:65532
ENTRYPOINT ["/opt/java/openjdk/bin/java", "-cp", "/opt/rps/classes", "RpsWrapper"]
