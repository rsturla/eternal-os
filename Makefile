SHELL := /bin/bash

RPMX ?= rpmx
OUT ?= out
SITE ?= site
RELEASE ?= 44
ARCH ?= x86_64
IMAGE ?= ghcr.io/rsturla/eternal-os/base
TAG ?= $(RELEASE)
PACKAGES ?= $(shell cat images/base/packages.txt)

.PHONY: help bootstrap doctor check lint build lock repo image push all ci clean

help:
	@echo "Eternal Linux"
	@echo
	@echo "  make bootstrap   Install the pinned rpmx revision (.rpmx-revision)"
	@echo "  make doctor      Check the host toolchain"
	@echo "  make check       pre-commit + lint every recipe (same as CI)"
	@echo "  make lint        Validate every recipe"
	@echo "  make build       Build every package into $(OUT)/<arch>/"
	@echo "  make lock        Write package.lock.json for every recipe"
	@echo "  make repo        Assemble $(SITE)/$(RELEASE)/<arch>/ from $(OUT)/"
	@echo "  make image       Compose $(IMAGE):$(TAG) from $(SITE)/"
	@echo "  make push        Push $(IMAGE):$(TAG)"
	@echo "  make all         check + build + repo + image"
	@echo "  make ci          Alias for 'make all'"
	@echo "  make clean       Remove build and publish output"

bootstrap:
	./scripts/install-rpmx.sh

doctor:
	$(RPMX) doctor

check:
	pre-commit run --all-files --show-diff-on-failure
	RPMX=$(RPMX) ./scripts/lint-all.sh

lint:
	RPMX=$(RPMX) ./scripts/lint-all.sh

build:
	RPMX=$(RPMX) ./scripts/build-all.sh --output $(OUT)

lock:
	RPMX=$(RPMX) ./scripts/lock-all.sh

repo: build
	./scripts/publish-repo.sh \
		--packages $(OUT) \
		--output $(SITE) \
		--release $(RELEASE)

image: repo
	./scripts/build-image.sh \
		--repo $(SITE)/$(RELEASE)/$(ARCH) \
		--packages "$(PACKAGES)" \
		--releasever $(RELEASE) \
		--arch $(ARCH) \
		--tag $(IMAGE):$(TAG)

push:
	podman push $(IMAGE):$(TAG)

all: check build repo image

ci: all

clean:
	rm -rf $(OUT) $(SITE)
