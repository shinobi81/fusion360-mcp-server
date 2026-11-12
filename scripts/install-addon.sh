#!/bin/bash
# Install/reinstall the add-in via symlink (for development)
# Usage: ./scripts/install-addon.sh

set -e
# No `set -u` here on purpose: before bash 4.4, expanding an empty array's elements is
# an unbound-variable error under nounset, and `addon/` may legitimately hold none while
# the count check below is deciding to refuse. `set -e` is the only mode this relies on.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
ADDON_SRC="$REPO_DIR/addon"

# Determine Fusion 360 AddIns folder
if [[ "$OSTYPE" == "darwin"* ]]; then
    ADDINS_DIR="$HOME/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns"
elif [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "win32" ]]; then
    ADDINS_DIR="$APPDATA/Autodesk/Autodesk Fusion 360/API/AddIns"
else
    echo "Unsupported OS: $OSTYPE"
    exit 1
fi

# The add-in's name comes from its manifest: Fusion loads <name>.py beside
# <name>.manifest, and this script links addon/ in as <name>.  One source, so the
# folder installed and the instructions printed below cannot disagree.
#
# The two checks below are not tidiness.  Without them, an addon/ holding no manifest
# would leave ADD_IN_NAME empty, TARGET the AddIns directory itself, and the reinstall
# path running `rm -rf` on every installed add-in; two manifests would install
# silently under whichever the glob lists first, naming the add-in after a manifest
# nobody chose.  With the checks, both stop here: the count is reported on stderr, and
# the matches are listed when there are any.  Names beginning with a dot never match
# the glob, so a lone dot-prefixed manifest is refused as "found 0", and one beside a
# real manifest is ignored.
shopt -s nullglob
ADD_IN_MANIFESTS=("$ADDON_SRC"/*.manifest)
shopt -u nullglob

if [ "${#ADD_IN_MANIFESTS[@]}" -ne 1 ]; then
    echo "addon/ must hold exactly one *.manifest; found ${#ADD_IN_MANIFESTS[@]}" >&2
    for manifest in "${ADD_IN_MANIFESTS[@]}"; do
        echo "  ${manifest##*/}" >&2
    done
    exit 1
fi

# The glob does not stat its matches, so a directory - or a dangling symlink - called
# <something>.manifest counts as the one manifest and would name the add-in after a
# file Fusion cannot load.
if [ ! -f "${ADD_IN_MANIFESTS[0]}" ]; then
    echo "addon/${ADD_IN_MANIFESTS[0]##*/} is not a regular file" >&2
    exit 1
fi

ADD_IN_NAME="$(basename "${ADD_IN_MANIFESTS[0]}" .manifest)"

TARGET="$ADDINS_DIR/$ADD_IN_NAME"

echo "Installing $ADD_IN_NAME add-in..."
echo "  Source: $ADDON_SRC"
echo "  Target: $TARGET"

# Remove existing installation
if [ -e "$TARGET" ] || [ -L "$TARGET" ]; then
    echo "  Removing existing installation..."
    rm -rf "$TARGET"
fi

# Create symlink for development (changes reflect immediately)
ln -s "$ADDON_SRC" "$TARGET"

echo "  ✓ Installed via symlink"
echo ""
echo "Next steps:"
echo "  1. Open Fusion 360"
echo "  2. Press Shift+S to open Scripts and Add-Ins"
echo "  3. Find '$ADD_IN_NAME' in the Add-Ins tab"
echo "  4. Click 'Run' to start the add-in"
echo ""
echo "The add-in will listen on localhost:9876"
