ARG RPS_BUILD_TOOLCHAIN
ARG RPS_BASE_RUNTIME
FROM ${RPS_BUILD_TOOLCHAIN} AS build

COPY --from=team / /opt/rps/team/
COPY organizer/interpreter.py /opt/rps/interpreter.py
COPY organizer/wrapper.py /opt/rps/wrapper.py
RUN python3 -m py_compile /opt/rps/interpreter.py /opt/rps/wrapper.py && \
    python3 -c "import sys; sys.path.insert(0, '/opt/rps'); from interpreter import compile_program; compile_program(open('/opt/rps/team/strategy.bf', encoding='ascii').read())"

FROM ${RPS_BASE_RUNTIME} AS artifact
COPY --from=build /opt/rps/interpreter.py /opt/rps/interpreter.py
COPY --from=build /opt/rps/wrapper.py /opt/rps/wrapper.py
COPY --from=build /opt/rps/team/ /opt/rps/team/

WORKDIR /opt/rps/team
USER 65532:65532
ENTRYPOINT ["/usr/local/bin/python3", "-I", "/opt/rps/wrapper.py"]
