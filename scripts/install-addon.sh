#!/bin/bash
# Install/reinstall the Fusion360MCP add-in via symlink (for development)
# Usage: ./scripts/install-addon.sh

set -e

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
ADD_IN_NAME="$(basename "$ADDON_SRC"/*.manifest .manifest)"

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
