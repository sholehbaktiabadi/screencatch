#!/bin/sh
# Build, install into ./_build/dev-install and run ScreenCatch from the source tree.
# Usage: ./run-dev.sh [screencatch options], e.g. ./run-dev.sh --home --debug
set -eu
cd "$(dirname "$0")"
BUILD_DIR=_build/dev
PREFIX="$PWD/_build/dev-install"
if [ ! -d "$BUILD_DIR" ]; then
    meson setup "$BUILD_DIR" --prefix="$PREFIX"
fi
meson install -C "$BUILD_DIR" --quiet
exec "$PREFIX/bin/screencatch" "$@"
