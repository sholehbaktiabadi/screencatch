# Contributing to ScreenCatch

Thanks for helping out! Bug reports, ideas and pull requests are all welcome.

## Reporting bugs

Open an issue at <https://github.com/sholehbaktiabadi/screencatch/issues> and include:

- your distribution and desktop (for example Ubuntu 24.04, GNOME, Wayland),
- the ScreenCatch version (`screencatch --version`),
- the output of `screencatch --debug` while reproducing the problem.

## Development setup

Install the build and runtime dependencies (Debian/Ubuntu):

```sh
sudo apt install meson python3-gi python3-gi-cairo python3-cairo \
    gir1.2-gtk-4.0 gir1.2-adw-1 desktop-file-utils appstream libglib2.0-bin \
    debhelper devscripts lintian
```

Run the app straight from the source tree (it is installed into `_build/dev-install`):

```sh
./run-dev.sh --home          # main window
./run-dev.sh                 # region capture
./run-dev.sh some.png        # open an image in the editor
```

## Checks

```sh
make test   # unit tests + desktop/AppStream/GSettings validation
make lint   # ruff check (install ruff with pipx or uv)
make deb    # builds dist/screencatch_<version>_all.deb
```

Ubuntu 24.04 is the oldest supported platform (GTK 4.14, libadwaita 1.5), so please stay within
those APIs.

## Code layout

| Path | Purpose |
| --- | --- |
| `src/screencatch/main.py` | Application, command line, capture flow |
| `src/screencatch/capture.py` | XDG screenshot portal client |
| `src/screencatch/overlay.py` | Full-screen region selection |
| `src/screencatch/editor/` | Annotation editor: shapes, document, undo history, canvas, window |
| `src/screencatch/export.py` | File naming and PNG saving |
| `src/screencatch/shortcut.py` | GNOME custom keybinding registration |
| `data/` | Desktop entry, AppStream metadata, GSettings schema, icons, man page |
| `debian/` | Debian packaging |

`editor/shapes.py`, `editor/document.py`, `editor/history.py` and `export.py` only use cairo and
Pango, so they can be unit tested without a display.

## Releasing

1. Bump the version in `meson.build`, `src/screencatch/__init__.py`, `debian/changelog`
   (`dch -v X.Y.Z`), the `<releases>` list in the metainfo file, `data/screencatch.1` and `CHANGELOG.md`.
   `meson test` fails if they disagree.
2. Build and check the package: `make test && make deb && lintian dist/*.deb`.
3. Commit, then tag and push: `git tag vX.Y.Z && git push origin vX.Y.Z`.
4. Publish the release with the `.deb` attached, either on the GitHub Releases page or with
   `gh release create vX.Y.Z dist/screencatch_X.Y.Z_all.deb --title "ScreenCatch X.Y.Z"`
   (use the matching `CHANGELOG.md` section as the notes).
