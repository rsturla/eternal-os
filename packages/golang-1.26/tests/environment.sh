# shellcheck shell=bash
# Sourced by each isolated test; every cache belongs to that invocation.
go=${1:?Go command}
gofmt=${2:?gofmt command}
version=${3:?expected version}
export go gofmt version
unset GOROOT GOFLAGS GOEXPERIMENT GOFIPS140 GODEBUG GOLANG_NATIVE_HOSTFIPS_OVERRIDE
export GOENV=off GOTOOLCHAIN=local GOPROXY=off GOSUMDB=off GOTELEMETRY=off
export GOCACHE="$PWD/go-cache" GOPATH="$PWD/gopath" GOMAXPROCS="${JOBS:-2}"
test "$("$go" env GOVERSION)" = "go$version"
