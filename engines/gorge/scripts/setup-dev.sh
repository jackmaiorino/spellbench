#!/bin/sh
# Writes the git-ignored go.work that resolves gorge to the local pinned clone.
set -eu
want=26257e0eda1779d739a07e835c6500b9c4dabc62
got=$(git -C "$GORGE_SRC" rev-parse HEAD)
[ "$got" = "$want" ] || { echo "gorge at $got, pinned $want" >&2; exit 1; }
cat > go.work <<EOF
go 1.25.8

use .

replace github.com/adams-shaun/gorge => $GORGE_SRC
EOF
echo "go.work -> $GORGE_SRC ($got)"
