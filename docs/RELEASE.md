# Release Process

## Goal

Build and publish a Linux release archive that can be installed with the root installer script.

## Archive Naming Convention

The installer expects this exact file pattern:

- simple-open-road-<version>-linux-x86_64.tar.gz

Example for version 0.1.0:

- simple-open-road-0.1.0-linux-x86_64.tar.gz

## Build Archive

Run on Linux CI or Linux host:

- ./scripts/build_linux_release.sh

Optional explicit version:

- ./scripts/build_linux_release.sh 0.1.0

Output:

- dist/simple-open-road-<version>-linux-x86_64.tar.gz

## Publish to GitHub Release

1. Create release tag:

- v0.1.0

2. Create a GitHub Release for that tag.

3. Upload artifact:

- dist/simple-open-road-0.1.0-linux-x86_64.tar.gz

The tag and archive name must match, otherwise install.sh download URL will fail.

## Automation Behavior

- GitHub Actions builds and uploads the Linux archive when a release is published.
- If you need to rebuild asset for an existing tag, run the workflow manually with `tag` input.

## Install Flow for Users

Latest release:

- curl -fsSL https://raw.githubusercontent.com/FHRha/SimpleOpenRoad/main/install.sh | bash

Specific version:

- curl -fsSL https://raw.githubusercontent.com/FHRha/SimpleOpenRoad/main/install.sh | bash -s -- --version v0.1.0

Override repository (for forks):

- curl -fsSL https://raw.githubusercontent.com/FHRha/SimpleOpenRoad/main/install.sh | bash -s -- --repo <owner>/<repo>

## Notes

- Installer supports Linux only.
- Default install path is ~/.local/share/simple-open-road.
- Wrapper binary is created at ~/.local/bin/sor.