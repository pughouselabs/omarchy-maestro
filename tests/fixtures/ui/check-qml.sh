#!/usr/bin/env bash
set -euo pipefail
repo=$(cd -- "$(dirname -- "$0")/../../.." && pwd)
source "$repo/tests/fixtures/ui/isolation.sh"
exec /usr/lib/qt6/bin/qmltestrunner -platform offscreen -input "$repo/tests/fixtures/ui/qml"
