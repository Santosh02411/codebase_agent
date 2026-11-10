FROM golang:1.22
ENV GOFLAGS=-mod=mod GOCACHE=/tmp/gocache GOPATH=/tmp/gopath GOTOOLCHAIN=local
WORKDIR /work
