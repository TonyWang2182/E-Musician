# Model assets

Install model weights from the sources listed in [Models](MODELS.md). The source repository contains configuration and worker code, not a copy of a personal GPU server.

For assets you have permission to redistribute, attach them to a release in this repository:

1. Prepare an archive containing only the intended weights or example data, its license, and a short manifest with model revision and file sizes.
2. Remove credentials, SSH keys, logs, job databases, and private audio.
3. Split archives larger than 2 GiB into smaller files and calculate SHA-256 checksums.
4. Open **Releases → Edit → Attach binaries** and upload the parts and checksum file.
5. Add the download and restore instructions to the release notes.

GitHub release assets must each be smaller than 2 GiB. Ordinary Git uploads reject files over 100 MiB. Use release assets for distributable model data; keep personal machine backups private. See [GitHub release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases) and [large-file guidance](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github).

Gated access to a checkpoint does not grant redistribution rights. For those models, provide the official download link and let each user obtain access.
