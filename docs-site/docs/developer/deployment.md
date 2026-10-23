# Deployment

## 🚢 The Docker image

The image is defined in `docker/Dockerfile`. It keeps all data in `/data`, listens on port 5000, and serves the app with Waitress. Mount a volume on `/data` so the collection survives a new container:

```sh
docker run -d --name sleeve-shelf -p 127.0.0.1:5000:5000 \
  -v sleeve-shelf-data:/data ghcr.io/mark-me/sleeve-shelf:latest
```

`docker/docker-compose.yml` runs a pinned release on port 5000; `docker/docker-compose.test.yml` runs the latest build of the `test` branch on port 5001 with its own volume, so the two can run side by side. Both publish their port on `127.0.0.1` only: Docker opens a published port past the host's own firewall (on NixOS too), so `5000:5000` would put the app, without HTTPS, before the whole local network. A proxy on the same machine passes visitors on.

The image is built on `python:3.13-slim-trixie` (Debian 13) since 2026-10-24: on Debian 12 the scan listed 255 known vulnerabilities without a fix in the system packages, on Debian 13 164, none of them critical.

Both shield the container: `read_only: true` with `/tmp` in memory, so only `/data` can be written; `no-new-privileges` and `cap_drop: [ALL]`, so the app can gain no rights; and limits of 512 MB of memory and 200 processes. The app needs about 135 MB. With `docker run` the same is:

```sh
docker run -d --name sleeve-shelf -p 127.0.0.1:5000:5000 -v sleeve-shelf-data:/data \
  --read-only --tmpfs /tmp --security-opt no-new-privileges:true --cap-drop ALL \
  --memory 512m --pids-limit 200 ghcr.io/mark-me/sleeve-shelf:latest
```

## 🏷️ Versions and tags

A GitHub Actions workflow (`.github/workflows/docker.yml`) runs the tests, then builds and publishes the image to the GitHub Container Registry:

| Push | Tags | Platforms |
| --- | --- | --- |
| to `test` | `:test` | amd64 |
| to `main` | `:main`, `:latest` | amd64, arm64 |
| a tag `vX.Y.Z` on `main` | `:X.Y.Z` | amd64, arm64 |

Every image is also tagged with its short commit SHA. The build stamps the image with a version that the app shows under Settings: `X.Y.Z` for a release, `X.Y.Z+main.<commits since release>.<sha>` on `main`, `X.Y.Z+test.<sha>` on `test`.

## 🔍 Vulnerability scan

`.github/workflows/security.yml` checks the Python packages the app runs on for known vulnerabilities, with [Trivy](https://trivy.dev/). Only what goes into the image counts: `uv export --no-dev` lists the packages `uv.lock` pins for the app, without the development tools such as pytest and Zensical. Every run lists all it finds, of every severity; a **HIGH** or **CRITICAL** vulnerability for which a fixed version exists fails the run. One without a fix is listed but does not fail it, as updating cannot resolve it.

It runs on pull requests, on pushes to other branches than `main` and `test`, every Monday, and by hand. The Docker workflow calls the same scan, and builds and publishes no image when it fails.

Trivy runs in an empty folder holding only that list. It reads a `.trivyignore` or `trivy.yaml` from the folder it runs in, and a pull request could add one to hide a finding; in the empty folder there is none to read. Trivy itself is a fixed release, checked against its published checksum.

To try it locally, with Trivy installed:

```sh
mkdir -p /tmp/scan && uv export --frozen --no-dev --no-hashes --no-emit-project \
  --format requirements-txt -o /tmp/scan/requirements.txt
cd /tmp/scan && trivy fs --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 .
```

A finding is resolved by moving the package to its fixed version: `uv lock --upgrade-package <name>`.

The Docker workflow also scans **the image itself**, after building it for amd64 and before publishing anything: the Debian packages of the base image and the Python installation, which the package scan does not see. The same rule applies; Debian lists many vulnerabilities without a fix, which are shown but cannot fail it. The published `:latest` is scanned again every Monday, as the image gets new vulnerabilities while it stays the same. pip is removed from the image: the app does not need it once installed, and the packages it carries along were the only fixable findings. Trivy is installed by `.github/actions/install-trivy`, for both workflows.

```sh
docker build -f docker/Dockerfile -t sleeve-shelf:scan .
mkdir -p /tmp/scan-image && cd /tmp/scan-image
trivy image --scanners vuln --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 sleeve-shelf:scan
```

## 🆙 Keeping dependencies current

Dependabot (`.github/dependabot.yml`) opens pull requests every Monday for the Python packages in `uv.lock`, the GitHub Actions, and the base images in `docker/Dockerfile`. Minor and patch updates of the packages and of the actions come grouped in one pull request each; a new major version comes on its own. Every action in the workflows is pinned to a commit, with its version noted beside it; Dependabot moves both together. Trivy's version in `security.yml` is set by hand.

Every stage of the Dockerfile runs on the same Python image, and uv comes from its own image at a fixed version: the virtual environment made in the build stage only works with the Python it was made for. Dependabot does not propose a new Python version (3.13 to 3.14); that goes together with `.python-version`, on which the tests run, and is done by hand in both places. Should the stages still differ, the build stops at `import sleeve_shelf, waitress` instead of the container failing at its start.

## 🌍 Public through tsdproxy

The app is meant to be reachable from the internet (decided 2026-10-16, confirmed 2026-10-24); visitors can only look the collection up once the owner's password is set. [tsdproxy](https://almeidapaulopt.github.io/tsdproxy/) gives a container a name of its own on the tailnet, with HTTPS, and *funnel* opens it to the internet. It reaches the container over the Docker network, so no port has to be published:

```yaml
services:
  sleeve-shelf:
    image: ghcr.io/mark-me/sleeve-shelf:0.6.1
    restart: unless-stopped
    environment:
      - TZ=Europe/Amsterdam
      - SLEEVE_SHELF_PROXIES=1    # tsdproxy says who a visitor is
    volumes:
      - /data/sleeve-shelf:/data  # writable for uid 1000
    read_only: true
    tmpfs:
      - /tmp
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    mem_limit: 512m
    pids_limit: 200
    labels:
      tsdproxy.enable: "true"
      tsdproxy.name: "sleeve-shelf"
      tsdproxy.port.1: "443/https:5000/http"
      tsdproxy.funnel: "true"
```

Set the password before turning funnel on: `docker exec -it sleeve-shelf python -m sleeve_shelf set-password`. Without `SLEEVE_SHELF_PROXIES`, every visitor arrives from tsdproxy's address, and one visitor guessing passwords or playing many previews holds up everyone. Keep `/data/sleeve-shelf` in your backups: it is the whole collection, the pictures you added included.

## 🔐 Configuration and secrets

`config.yaml` in the data directory holds the settings, the Discogs personal access token and the hash of the owner's password. It is git-ignored and never baked into the image; the UI only shows the token's last four characters. It is written readable by the app's own user only (600), and a copy written earlier with wider permissions is put right when the app starts. On a running container, load a workbook from the command line. The container is read-only, so the file goes into the data volume — the one place `docker cp` can write to — and is removed again afterwards:

```sh
docker cp layout.xlsx sleeve-shelf:/data/layout.xlsx
docker exec sleeve-shelf python -m sleeve_shelf load /data/layout.xlsx
docker exec sleeve-shelf rm /data/layout.xlsx
```

## 🧾 The log

The container's output (`docker logs sleeve-shelf`) names every login, failed login and visitor held up for too many requests, with the address:

```text
[2026-10-17 09:12:03,412] WARNING in login: Failed login from 203.0.113.66
[2026-10-17 09:12:40,007] WARNING in login: Login refused, too many attempts, from 203.0.113.66
[2026-10-17 09:15:21,950] WARNING in login: Visitor held up for too many requests from 198.51.100.7
[2026-10-17 09:20:11,301] INFO in login: Owner logged in from 192.0.2.10
```

A visitor opens at most 300 pages a minute (`VISITOR_PAGES_PER_WINDOW` in `web/login.py`); files and the login page are not counted. Where the app is reached directly or behind your own reverse proxy, fail2ban can block an address on `Failed login from <HOST>`. Behind Tailscale Funnel blocking on the host does not help, as every visitor arrives through Tailscale; the app's own limits hold there.

Installing the app on a phone needs HTTPS, which the app does not provide itself: put it behind Tailscale or a reverse proxy.
