SHELL := /bin/bash

RPMX ?= rpmx
OUT ?= out
SITE ?= site
RELEASE ?= rolling
ARCH ?= x86_64
BASE ?= origin/HEAD
BOOTSTRAP ?= bootstrap/bootstrap.yaml

.PHONY: help bootstrap bootstrap-plan bootstrap-build bootstrap-clean doctor check lint arches affected hash build build-affected build-all test test-tools lock lock-check repo all ci clean

help:
	@echo "Eternal Linux"
	@echo
	@echo "  make bootstrap       Install the pinned rpmx revision (.rpmx-revision)"
	@echo "  make bootstrap-plan  Print the bootstrap ladder plan"
	@echo "  make bootstrap-build Run the bootstrap ladder for $(ARCH)"
	@echo "  make bootstrap-clean Remove bootstrap roots and locks (root-owned files included)"
	@echo "  make doctor          Check the host toolchain"
	@echo "  make check           pre-commit + commit checks + helper tests + lint (same as CI)"
	@echo "  make lint            Validate every recipe"
	@echo "  make arches          List target architectures from the profile"
	@echo "  make affected        List packages affected since $(BASE)"
	@echo "  make hash            Print content hashes for every package"
	@echo "  make build           Build packages whose content hash changed"
	@echo "  make build-affected  Build only packages affected since $(BASE)"
	@echo "  make build-all       Force a rebuild of every package"
	@echo "  make test            Run runtime tests against existing RPMs for $(ARCH)"
	@echo "  make test-tools      Test repository helpers without building RPMs"
	@echo "  make lock            Write local package.lock.json files"
	@echo "  make lock-check      Fail when a local lock is stale (network)"
	@echo "  make repo            Assemble $(SITE)/$(RELEASE)/<arch>/ from $(OUT)/"
	@echo "  make all             check + build + repo"
	@echo "  make ci              Alias for 'make all'"
	@echo "  make clean           Remove build and publish output"

bootstrap:
	./scripts/install-rpmx.sh

bootstrap-plan:
	$(RPMX) bootstrap plan $(BOOTSTRAP) --arch $(ARCH)

bootstrap-build:
	$(RPMX) bootstrap build $(BOOTSTRAP) --arch $(ARCH)

bootstrap-clean:
	podman unshare rm -rf bootstrap/.work 2>/dev/null || rm -rf bootstrap/.work

doctor:
	$(RPMX) doctor

check:
	pre-commit run --all-files --show-diff-on-failure
	./scripts/check-commits.sh --base $(BASE)
	./scripts/test-tools.sh
	RPMX=$(RPMX) ./scripts/lint-all.sh

lint:
	RPMX=$(RPMX) ./scripts/lint-all.sh

arches:
	./scripts/list-arches.sh

affected:
	RPMX=$(RPMX) ./scripts/affected.sh --base $(BASE)

hash:
	RPMX=$(RPMX) ./scripts/package-hash.sh

build:
	RPMX=$(RPMX) ./scripts/build-all.sh --output $(OUT)

build-affected:
	RPMX=$(RPMX) ./scripts/build-all.sh --affected --since $(BASE) --output $(OUT)

build-all:
	RPMX=$(RPMX) ./scripts/build-all.sh --all --force --output $(OUT)

test:
	RPMX=$(RPMX) ./scripts/test-all.sh --rpms $(OUT) --arch $(ARCH)

test-tools:
	./scripts/test-tools.sh

lock:
	RPMX=$(RPMX) ./scripts/lock-all.sh

lock-check:
	RPMX=$(RPMX) ./scripts/lock-all.sh --check

repo: build
	./scripts/publish-repo.sh \
		--packages $(OUT) \
		--output $(SITE) \
		--release $(RELEASE)

all: check build repo

ci: all

clean:
	rm -rf $(OUT) $(SITE)
