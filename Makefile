# Convenience targets. The real build system is meson; packaging uses debian/.
VERSION := $(shell sed -n "s/^  version: '\(.*\)',/\1/p" meson.build)

.PHONY: all run test lint deb clean

all: test

run:
	./run-dev.sh --home

test:
	PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -t . -v
	desktop-file-validate data/*.desktop
	appstreamcli validate --no-net data/*.metainfo.xml
	glib-compile-schemas --strict --dry-run data

lint:
	ruff check .

deb:
	dpkg-buildpackage -us -uc -b
	mkdir -p dist
	mv ../screencatch_$(VERSION)_all.deb dist/
	rm -f ../screencatch_$(VERSION)_*.buildinfo ../screencatch_$(VERSION)_*.changes
	@echo "Built dist/screencatch_$(VERSION)_all.deb"

clean:
	rm -rf _build dist obj-* debian/.debhelper debian/screencatch debian/files debian/*.substvars debian/debhelper-build-stamp
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
