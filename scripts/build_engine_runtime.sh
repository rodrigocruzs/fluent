#!/usr/bin/env bash
# Assembles the self-contained Python runtime that release.sh bundles into
# Fluent.app (Contents/Resources/engine-runtime).
# See docs/superpowers/specs/2026-07-17-bundled-python-runtime-design.md.
#
# Output:  build/engine-runtime/   (relocatable CPython + engine deps)
# Re-runs are no-ops unless this script or the requirements change.
#   FORCE=1             rebuild even when cached
#   SKIP_ENGINE_TESTS=1 skip the pytest gate (debug escape hatch)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENGINE_SRC="$REPO_ROOT/fluent-engine"
OUT="$REPO_ROOT/build/engine-runtime"
CACHE="$REPO_ROOT/build/engine-runtime-cache"
STAMP="$OUT/.stamp"

# ── Pinned inputs ─────────────────────────────────────────────────────────────
PBS_TAG="20260623"
PBS_PY="3.12.13"
PBS_NAME="cpython-${PBS_PY}+${PBS_TAG}-aarch64-apple-darwin-install_only_stripped.tar.gz"
PBS_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PBS_TAG}/${PBS_NAME}"
PBS_SHA256="41df7d3ae4757e84b97874f76d634268456aaa271740d33f968d826374998fb7"

PA_VERSION="19.7.0"
PA_NAME="portaudio-${PA_VERSION}.tar.gz"
PA_URL="https://github.com/PortAudio/portaudio/archive/refs/tags/v${PA_VERSION}.tar.gz"
PA_SHA256="5af29ba58bbdbb7bbcefaaecc77ec8fc413f0db6f4c4e286c40c3e1b83174fa0"

PYAUDIO_VERSION="0.2.14"

# Must match the app's MACOSX_DEPLOYMENT_TARGET (fluent/project.yml).
# The min-OS gate below enforces it on every shipped Mach-O.
export MACOSX_DEPLOYMENT_TARGET="14.0"

stamp_value() {
    shasum -a 256 "$0" \
        "$ENGINE_SRC/requirements-common.txt" \
        "$ENGINE_SRC/requirements-mac.txt" | shasum -a 256 | cut -d' ' -f1
}

if [ "${FORCE:-0}" != "1" ] && [ -f "$STAMP" ] && [ "$(cat "$STAMP")" = "$(stamp_value)" ]; then
    echo "[runtime] up to date ($OUT) — FORCE=1 to rebuild"
    exit 0
fi

rm -rf "$OUT"
mkdir -p "$OUT" "$CACHE"

fetch() { # <url> <sha256> <dest>
    local url="$1" sha="$2" dest="$3"
    if [ ! -f "$dest" ] || ! echo "$sha  $dest" | shasum -a 256 -c - >/dev/null 2>&1; then
        echo "[runtime] downloading $(basename "$dest") ..."
        curl -fL --retry 3 -o "$dest" "$url"
    fi
    echo "$sha  $dest" | shasum -a 256 -c - >/dev/null \
        || { echo "[runtime] ERROR: checksum mismatch for $dest" >&2; exit 1; }
}

# ── 1. Relocatable CPython ────────────────────────────────────────────────────
fetch "$PBS_URL" "$PBS_SHA256" "$CACHE/$PBS_NAME"
tar -xzf "$CACHE/$PBS_NAME" -C "$OUT" --strip-components=1   # tarball root: python/
PY="$OUT/bin/python3"
echo "[runtime] $("$PY" -V)"
"$PY" -m pip --version >/dev/null 2>&1 || "$PY" -m ensurepip --upgrade

# ── 2. portaudio from source ──────────────────────────────────────────────────
# Homebrew's bottle has minos 15.0 (> app target 14.0), so build our own.
fetch "$PA_URL" "$PA_SHA256" "$CACHE/$PA_NAME"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
PA_PREFIX="$WORK/portaudio-prefix"
tar -xzf "$CACHE/$PA_NAME" -C "$WORK"
echo "[runtime] building portaudio $PA_VERSION ..."
(
    cd "$WORK/portaudio-$PA_VERSION"
    # portaudio's darwin configure branch hard-codes -Werror and discards any
    # CFLAGS we pass before appending its own (see src/hostapi/coreaudio case).
    # Several genuinely-dead locals in its CoreAudio backend (unimplemented
    # dither-converter stubs in pa_converters.c, unused OSStatus results in
    # pa_mac_core*.c) trip -Wunused-but-set-variable on Apple Clang 17 (Xcode
    # 26.3), which -Werror then turns fatal — this portaudio release predates
    # that stricter diagnostic. CFLAGS is clobbered, but CC is not, so demote
    # just that one diagnostic to a warning via CC rather than suppressing it
    # (keeps -Werror meaningful for anything else). Upstream issue in
    # portaudio 19.7.0, unrelated to our packaging.
    ./configure --prefix="$PA_PREFIX" --disable-static \
        CC="cc -Wno-error=unused-but-set-variable" \
        CFLAGS="-arch arm64 -mmacosx-version-min=$MACOSX_DEPLOYMENT_TARGET" \
        LDFLAGS="-arch arm64" >/dev/null
    make -j"$(sysctl -n hw.ncpu)" >/dev/null
    make install >/dev/null
)

# ── 3. PyAudio wheel, repaired so libportaudio is vendored ───────────────────
# Tooling (delocate, pytest) goes into a throwaway --target dir, NOT the
# runtime's site-packages — pip can't cleanly uninstall transitive deps, and
# some (typing-extensions) are shared with real runtime deps.
TOOLS="$WORK/tools"
"$PY" -m pip install --quiet --target "$TOOLS" delocate pytest
WHEELS="$WORK/wheels"
echo "[runtime] building PyAudio wheel ..."
CFLAGS="-I$PA_PREFIX/include" LDFLAGS="-L$PA_PREFIX/lib" ARCHFLAGS="-arch arm64" \
    "$PY" -m pip wheel --quiet "pyaudio==$PYAUDIO_VERSION" \
    --no-deps --no-binary :all: -w "$WHEELS"
PYTHONPATH="$TOOLS" "$TOOLS/bin/delocate-wheel" -w "$WHEELS/repaired" "$WHEELS"/[Pp]y[Aa]udio*.whl
"$PY" -m pip install --quiet "$WHEELS/repaired"/[Pp]y[Aa]udio*.whl

# ── 4. Engine dependencies ────────────────────────────────────────────────────
echo "[runtime] installing engine deps ..."
"$PY" -m pip install --quiet \
    -r "$ENGINE_SRC/requirements-common.txt" \
    -r "$ENGINE_SRC/requirements-mac.txt"

# ── 5. Engine test suite under the assembled runtime ─────────────────────────
if [ "${SKIP_ENGINE_TESTS:-0}" != "1" ]; then
    echo "[runtime] running engine tests under the assembled runtime ..."
    (cd "$ENGINE_SRC" && PYTHONPATH="$TOOLS" "$PY" -m pytest tests -q)
fi

# ── 6. Manifest (before pip is pruned) ───────────────────────────────────────
{
    echo "python: $("$PY" -V 2>&1) (python-build-standalone $PBS_TAG)"
    echo "portaudio: $PA_VERSION (source build, min macOS $MACOSX_DEPLOYMENT_TARGET)"
    "$PY" -m pip freeze
} > "$OUT/MANIFEST.txt"

# ── 7. Prune ──────────────────────────────────────────────────────────────────
"$PY" -m pip uninstall --quiet -y pip setuptools wheel 2>/dev/null || true
rm -f "$OUT"/bin/pip* "$OUT"/bin/wheel* "$OUT"/bin/idle* "$OUT"/bin/pydoc*
find "$OUT/lib" -type d \( -name tests -o -name test -o -name __pycache__ \) \
    -prune -exec rm -rf {} +

# ── 8. Precompile (the bundle is read-only at runtime) ───────────────────────
"$PY" -m compileall -q "$OUT/lib"

# ── 9. Portability + min-OS gate ─────────────────────────────────────────────
echo "[runtime] scanning Mach-O files ..."
BAD=0
while IFS= read -r -d '' f; do
    file -b "$f" | grep -q "Mach-O" || continue
    while IFS= read -r dep; do
        case "$dep" in
            @rpath/*|@loader_path/*|@executable_path/*|/usr/lib/*|/System/*) ;;
            *) echo "[runtime] BAD LINK: $f -> $dep"; BAD=1 ;;
        esac
    done < <(otool -l "$f" \
        | awk '/cmd LC_(LOAD_DYLIB|LOAD_WEAK_DYLIB|REEXPORT_DYLIB)/{grab=1}
               grab && $1=="name"{print $2; grab=0}')
    minos=$(otool -l "$f" | awk '/minos/{print $2; exit}')
    if [ -n "${minos:-}" ] && \
       [ "$(printf '%s\n' "$minos" "$MACOSX_DEPLOYMENT_TARGET" | sort -V | tail -1)" \
         != "$MACOSX_DEPLOYMENT_TARGET" ]; then
        echo "[runtime] BAD MIN-OS ($minos > $MACOSX_DEPLOYMENT_TARGET): $f"; BAD=1
    fi
done < <(find "$OUT" -type f \( -perm -111 -o -name '*.so' -o -name '*.dylib' \) -print0)
[ "$BAD" = "0" ] || { echo "[runtime] ERROR: portability gate failed" >&2; exit 1; }

# ── 10. Import check with a stripped environment ─────────────────────────────
echo "[runtime] import check (clean env) ..."
(cd / && env -i HOME=/tmp PATH=/usr/bin:/bin "$PY" - <<'PYCHECK'
import sys
mods = ["anthropic", "pyaudio", "httpx", "AVFoundation", "CoreAudio", "Cocoa"]
missing = []
for m in mods:
    try:
        __import__(m)
    except Exception as e:
        missing.append(f"{m}: {e}")
if missing:
    sys.stderr.write("Import check failed:\n" + "\n".join(missing) + "\n")
    sys.exit(1)
PYCHECK
)

stamp_value > "$STAMP"
echo "[runtime] done: $OUT ($(du -sh "$OUT" | cut -f1))"
