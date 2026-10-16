#!/bin/bash
# Move raw_bids from this Mac to the MusicProject server:
#   1. set aside any older raw_bids already on the server (renamed, not deleted)
#   2. copy with rsync (rerun this script to resume if interrupted)
#   3. compare file counts and sizes
#   4. delete the local copy only if they match AND you type "yes"
#
# Connect to the server first (see bottom of this file), then run:
#   bash move_bids_to_server.sh

LOCAL=/Users/nickathios/Documents/research/musicaltraining_gradients/raw_bids
SERVER_PARENT=/Volumes/MusicProject/Longitudinal_study/gradient_analysis_BIDS
DEST=${SERVER_PARENT}/raw_bids

[ -d "$LOCAL" ] || { echo "ERROR: local folder not found: $LOCAL"; exit 1; }
[ -d "$SERVER_PARENT" ] || { echo "ERROR: server not connected (no $SERVER_PARENT)"; exit 1; }

# An older raw_bids from the first test conversion may already be on the server.
# Rename it once so the two don't get mixed; the marker file means it's this script's copy.
if [ -d "$DEST" ] && [ ! -f "$DEST/.copied_from_mac" ]; then
    OLD="${DEST}_OLD_$(date +%Y%m%d)"
    echo "Renaming existing server folder to $(basename "$OLD")"
    mv "$DEST" "$OLD" || exit 1
fi
mkdir -p "$DEST" && touch "$DEST/.copied_from_mac"

echo "Copying... (rerun this script to resume if it stops)"
rsync -rt --progress --exclude '.DS_Store' "$LOCAL/" "$DEST/" || { echo "ERROR: rsync failed; rerun to resume"; exit 1; }

count () { find "$1" -type f -not -name '.DS_Store' -not -name '.copied_from_mac' | wc -l | tr -d ' '; }
bytes () { find "$1" -type f -not -name '.DS_Store' -not -name '.copied_from_mac' -exec stat -f %z {} + | awk '{s+=$1} END {print s+0}'; }
LC=$(count "$LOCAL"); DC=$(count "$DEST")
LB=$(bytes "$LOCAL"); DB=$(bytes "$DEST")
echo "Local:  $LC files, $LB bytes"
echo "Server: $DC files, $DB bytes"
if [ "$LC" != "$DC" ] || [ "$LB" != "$DB" ]; then
    echo "MISMATCH: keeping the local copy. Rerun this script to finish the copy."
    exit 1
fi

read -r -p "Copy verified. Delete the local raw_bids? Type yes to delete: " ans
if [ "$ans" = "yes" ]; then
    rm -rf "$LOCAL" && echo "Local copy deleted. raw_bids now lives at $DEST"
else
    echo "Local copy kept."
fi

# --- Connecting to the server (VPN first if off campus) ---
#   open "smb://kathios@10.136.96.41/MusicProject"
# If that fails, check it's reachable:
#   nc -z -G 5 10.136.96.41 445 && echo reachable || echo "not reachable"
