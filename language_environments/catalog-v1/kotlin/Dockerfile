ARG RPS_BUILD_TOOLCHAIN
ARG RPS_BASE_RUNTIME
FROM ${RPS_BUILD_TOOLCHAIN} AS build

COPY --from=team / /opt/rps/team/
COPY organizer/RpsWrapper.kt /opt/rps/build/RpsWrapper.kt
COPY organizer/kotlin-compiler-2.4.10.zip /opt/rps/build/kotlin-compiler-2.4.10.zip
RUN mkdir -p /opt/rps/compiler /opt/rps/output && \
    cd /opt/rps/compiler && \
    jar xf /opt/rps/build/kotlin-compiler-2.4.10.zip && \
    chmod +x /opt/rps/compiler/kotlinc/bin/kotlinc && \
    cp /opt/rps/team/*.kt /opt/rps/build/ && \
    /opt/rps/compiler/kotlinc/bin/kotlinc \
      -jvm-target 25 -include-runtime \
      /opt/rps/build/*.kt -d /opt/rps/output/rps-bot.jar

FROM ${RPS_BASE_RUNTIME} AS artifact
COPY --from=build /opt/rps/output/rps-bot.jar /opt/rps/rps-bot.jar
COPY --from=build /opt/rps/team/ /opt/rps/team/

WORKDIR /opt/rps/team
USER 65532:65532
ENTRYPOINT ["/opt/java/openjdk/bin/java", "-jar", "/opt/rps/rps-bot.jar"]
