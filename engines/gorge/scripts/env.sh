# Source from engines/gorge: toolchain, caches on D:, local gorge and corpus.
export PATH=/d/tools/go1.27.1/go/bin:$PATH
export GOTOOLCHAIN=local CGO_ENABLED=0
export GOCACHE=D:/community/go-cache/build GOMODCACHE=D:/community/go-cache/mod
export GORGE_SRC=${GORGE_SRC:-D:/community/gorge}
export GORGE_CARDS=${GORGE_CARDS:-$GORGE_SRC/.cards}
export GOFLAGS="-overlay=$(pwd)/go-overlay.json"
