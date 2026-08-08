# syntax=docker/dockerfile:1
ARG RPS_BASE_RUNTIME
FROM ${RPS_BASE_RUNTIME} AS artifact

COPY source/ /opt/rps/team/
COPY organizer/wrapper.py /opt/rps/wrapper.py

WORKDIR /opt/rps/team
USER 65532:65532
ENTRYPOINT ["python3", "-I", "/opt/rps/wrapper.py"]
