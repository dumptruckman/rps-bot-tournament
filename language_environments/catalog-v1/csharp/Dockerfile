ARG RPS_BUILD_TOOLCHAIN
ARG RPS_BASE_RUNTIME
FROM ${RPS_BUILD_TOOLCHAIN} AS build

COPY --from=team / /opt/rps/team/
COPY organizer/RpsWrapper.cs /opt/rps/build/RpsWrapper.cs
COPY organizer/RpsBot.runtimeconfig.json /opt/rps/build/RpsBot.runtimeconfig.json
RUN cp /opt/rps/team/*.cs /opt/rps/build/ && \
    mkdir -p /opt/rps/publish && \
    find /usr/share/dotnet/packs/Microsoft.NETCore.App.Ref/10.0.10/ref/net10.0 \
      -name '*.dll' -printf '%p\n' | sed 's|^|-reference:|' \
      > /opt/rps/build/references.rsp && \
    dotnet /usr/share/dotnet/sdk/10.0.302/Roslyn/bincore/csc.dll \
      -noconfig -nostdlib+ -langversion:14 -nullable:enable -target:exe \
      -out:/opt/rps/publish/RpsBot.dll \
      @/opt/rps/build/references.rsp /opt/rps/build/*.cs && \
    cp /opt/rps/build/RpsBot.runtimeconfig.json /opt/rps/publish/

FROM ${RPS_BASE_RUNTIME} AS artifact
COPY --from=build /opt/rps/publish/ /opt/rps/
COPY --from=build /opt/rps/team/ /opt/rps/team/

WORKDIR /opt/rps/team
USER 65532:65532
ENTRYPOINT ["/usr/bin/dotnet", "/opt/rps/RpsBot.dll"]
