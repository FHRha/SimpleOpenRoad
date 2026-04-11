# Release Process

## Goal

Build and publish a Linux release archive that can be installed with the root installer script.

## Archive Naming Convention

The installer expects this exact file pattern:

- simple-open-road-<version>-linux-<arch>.tar.gz

Supported architectures:

- x86_64
- arm64

Example for version 0.1.0:

- simple-open-road-0.1.0-linux-x86_64.tar.gz
- simple-open-road-0.1.0-linux-arm64.tar.gz

## Build Archive

Run on Linux CI or Linux host:

- ./scripts/build_linux_release.sh

Optional explicit version:

- ./scripts/build_linux_release.sh 0.1.0

Output:

- dist/simple-open-road-<version>-linux-<arch>.tar.gz

## Publish to GitHub Release

1. Create release tag:

- v0.1.0

2. Create a GitHub Release for that tag.

3. Upload artifact:

- dist/simple-open-road-0.1.0-linux-x86_64.tar.gz

The tag and archive name must match, otherwise install.sh download URL will fail.

## Automation Behavior

- GitHub Actions builds and uploads the Linux archive when a release is published.
- GitHub Actions uploads both x86_64 and arm64 archives for each published release.
- If you need to rebuild asset for an existing tag, run the workflow manually with `tag` input.

## Install Flow for Users

Latest release:

- curl -fsSL https://raw.githubusercontent.com/FHRha/SimpleOpenRoad/main/install.sh | bash

Specific version:

- curl -fsSL https://raw.githubusercontent.com/FHRha/SimpleOpenRoad/main/install.sh | bash -s -- --version v0.1.0

Override repository (for forks):

- curl -fsSL https://raw.githubusercontent.com/FHRha/SimpleOpenRoad/main/install.sh | bash -s -- --repo <owner>/<repo>

## Update Flow for Installed Servers

Interactive terminal:

- sor
- choose `10) Update SimpleOpenRoad`

CLI:

- sor update
- sor update --version v0.1.1
- sor update --ref main

Updates preserve user-owned state:

- .env
- config/config.yaml
- data/
- provider keys stored in config/config.yaml

The installer refreshes application files from the release archive, reinstalls the editable package in the existing virtual environment, recreates the wrapper binary if needed, and restarts/reinstalls the background service using the existing config path.

By default `sor update` installs the latest GitHub Release. Use `sor update --ref main` only for testing unreleased changes from a branch/source archive.

## Notes

- Installer supports Linux only.
- Installer auto-detects architecture and downloads matching archive.
- Default install path is ~/.local/share/simple-open-road for user installs.
- Default install path is /usr/local/share/simple-open-road for root installs.
- Wrapper binary is created at ~/.local/bin/sor.
