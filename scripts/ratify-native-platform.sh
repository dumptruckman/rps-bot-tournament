#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
    echo "usage: scripts/ratify-native-platform.sh PLATFORM REPORT_DIRECTORY" >&2
    exit 64
fi

target_platform=$1
report_directory=$2
case "$target_platform" in
    linux/arm64) validation_mode=organizer-final ;;
    linux/amd64) validation_mode=github-advisory ;;
    *)
        echo "platform must be linux/arm64 or linux/amd64" >&2
        exit 64
        ;;
esac

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
work_directory=$(mktemp -d "${TMPDIR:-/tmp}/rps-native-ratification.XXXXXX")
cleanup() {
    chmod -R u+w "$work_directory" 2>/dev/null || true
    rm -rf -- "$work_directory"
}
trap cleanup EXIT HUP INT TERM

catalog="$project_root/language_environments/catalog-v1/catalog.json"
source_directory="$work_directory/source"
bundle_directory="$work_directory/bundle"
candidate_directory="$work_directory/candidate"
certified_directory="$work_directory/certified"
mkdir -p "$source_directory" "$report_directory"
cp "$project_root/scripts/portable_strategy.py" "$source_directory/strategy.py"

python3 -m rps_runner.source_cli \
    --catalog "$catalog" \
    --environment python \
    --source "$source_directory" \
    --bundle "$bundle_directory" \
    > "$report_directory/source-bundle-result.json"
python3 -m rps_runner.artifact_cli \
    --catalog "$catalog" \
    --bundle "$bundle_directory" \
    --platform "$target_platform" \
    --candidate "$candidate_directory" \
    > "$report_directory/artifact-candidate-result.json"
python3 -m rps_runner.certification_cli \
    --catalog "$catalog" \
    --candidate "$candidate_directory" \
    --mode "$validation_mode" \
    --platform "$target_platform" \
    --profile docker-execution-v1 \
    --output "$certified_directory" \
    > /dev/null
python3 -m rps_runner.profile_probe \
    --catalog "$catalog" \
    --platform "$target_platform" \
    --output "$report_directory/python-profile-probe.json" \
    > /dev/null

cp "$certified_directory/bot-artifact-manifest.json" "$report_directory/"
cp "$certified_directory/validation-report.json" "$report_directory/"
echo "native $target_platform portability and profile ratification passed"
