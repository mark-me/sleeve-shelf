# Deployment

## 🚢 The Docker image

The image is defined in `docker/Dockerfile`. It keeps all data in `/data`, listens on port 5000, and serves the app with Waitress. Mount a volume on `/data` so the collection survives a new container:

```sh
docker run -d --name sleeve-shelf -p 5000:5000 \
  -v sleeve-shelf-data:/data ghcr.io/mark-me/sleeve-shelf:latest
```

`docker/docker-compose.yml` runs a pinned release on port 5000; `docker/docker-compose.test.yml` runs the latest build of the `test` branch on port 5001 with its own volume, so the two can run side by side.

## 🏷️ Versions and tags

A GitHub Actions workflow (`.github/workflows/docker.yml`) runs the tests, then builds and publishes the image to the GitHub Container Registry:

| Push | Tags | Platforms |
| --- | --- | --- |
| to `test` | `:test` | amd64 |
| to `main` | `:main`, `:latest` | amd64, arm64 |
| a tag `vX.Y.Z` on `main` | `:X.Y.Z` | amd64, arm64 |

Every image is also tagged with its short commit SHA. The build stamps the image with a version that the app shows under Settings: `X.Y.Z` for a release, `X.Y.Z+main.<commits since release>.<sha>` on `main`, `X.Y.Z+test.<sha>` on `test`.

## 🔍 Vulnerability scan

`.github/workflows/security.yml` checks the Python packages the app runs on — the ones locked in `uv.lock`, not the development tools — for known vulnerabilities, with [Trivy](https://trivy.dev/). Every run lists all it finds, of every severity; a **HIGH** or **CRITICAL** vulnerability for which a fixed version exists fails the run. One without a fix is listed but does not fail it, as updating cannot resolve it.

It runs on pull requests, on pushes to other branches than `main` and `test`, every Monday, and by hand. The Docker workflow calls the same scan, and builds and publishes no image when it fails. The Trivy action is pinned to a commit rather than a tag, as a tag can later be pointed at other code.

To try it locally, with Trivy installed:

```sh
trivy fs --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 uv.lock
```

A finding is resolved by moving the package to its fixed version: `uv lock --upgrade-package <name>`.

## 🔐 Configuration and secrets

`config.yaml` in the data directory holds the settings and the Discogs personal access token. It is git-ignored and never baked into the image; the UI only shows the token's last four characters. On a running container, load a workbook from the command line with:

```sh
docker cp layout.xlsx sleeve-shelf:/tmp/layout.xlsx
docker exec sleeve-shelf python -m sleeve_shelf load /tmp/layout.xlsx
```

Installing the app on a phone needs HTTPS, which the app does not provide itself: put it behind Tailscale or a reverse proxy.
