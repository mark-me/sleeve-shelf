# Security Policy

## Supported versions

Only the latest release, and the `main` branch, receive security fixes. If you run an older version, please update before reporting.

## Reporting a vulnerability

Please **do not open a public issue** for a security problem.

Report it privately through GitHub: on the [Security tab](https://github.com/mark-me/sleeve-shelf/security) of the repository, choose **Report a vulnerability**. Describe what you found, how to reproduce it and what an attacker could do with it.

This is a one-person project maintained in spare time. You can expect an acknowledgement within a week; a fix follows as soon as possible, and you will be credited in the release notes unless you prefer not to be.

## What is in scope

Sleeve & Shelf is meant to be self-hosted, and may be opened to the internet with an owner's password set (for example behind Tailscale Funnel). Of particular interest are:

- anything that lets a visitor without the password change data, or see what only the owner may see;
- getting around the per-address limits on pages, listening, photos and failed logins;
- cross-site scripting or other ways around the Content-Security-Policy;
- the upload of a photo to recognise a sleeve, the one file a visitor may send;
- leaking the Discogs token or the owner's password hash kept in `config.yaml`.

Out of scope are problems that need access to the server or its data directory, and running the app without a password on an open network, which makes everyone the owner by design.

## How the project keeps its dependencies safe

The Python packages the app runs on are scanned with Trivy for known vulnerabilities on every pull request and push, and weekly; the Docker image is scanned before it is published, and the published image weekly. A high or critical vulnerability with a fix stops the image from being built. Dependabot proposes updates.
