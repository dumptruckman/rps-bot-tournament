ARG RPS_BUILD_TOOLCHAIN
ARG RPS_BASE_RUNTIME
FROM ${RPS_BUILD_TOOLCHAIN} AS build

COPY --from=team / /opt/rps/team/
COPY organizer/rps_wrapper.clj /opt/rps/organizer/rps_wrapper.clj
COPY organizer/dependencies.lock /opt/rps/dependencies.lock
RUN sha256sum -c /opt/rps/dependencies.lock && \
    mkdir -p /opt/rps/lib && \
    cp /root/.m2/repository/org/clojure/clojure/1.12.5/clojure-1.12.5.jar /opt/rps/lib/ && \
    cp /root/.m2/repository/org/clojure/core.specs.alpha/0.4.74/core.specs.alpha-0.4.74.jar /opt/rps/lib/ && \
    cp /root/.m2/repository/org/clojure/spec.alpha/0.5.238/spec.alpha-0.5.238.jar /opt/rps/lib/ && \
    java -cp '/opt/rps/lib/*' clojure.main -e "(doseq [path [\"/opt/rps/team/strategy.clj\" \"/opt/rps/organizer/rps_wrapper.clj\"]] (with-open [reader (java.io.PushbackReader. (clojure.java.io/reader path))] (loop [] (when-not (= ::eof (read {:eof ::eof} reader)) (recur)))))"

FROM ${RPS_BASE_RUNTIME} AS artifact
COPY --from=build /opt/rps/lib/ /opt/rps/lib/
COPY --from=build /opt/rps/organizer/ /opt/rps/organizer/
COPY --from=build /opt/rps/team/ /opt/rps/team/
WORKDIR /opt/rps/team
USER 65532:65532
ENTRYPOINT ["/opt/java/openjdk/bin/java", "-XX:+UseSerialGC", "-XX:TieredStopAtLevel=1", "-Xms32m", "-Xmx128m", "-cp", "/opt/rps/lib/*:/opt/rps/team:/opt/rps/organizer", "clojure.main", "-m", "rps-wrapper"]
