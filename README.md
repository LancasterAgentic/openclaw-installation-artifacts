# OpenClaw installation artifacts

Client-free Linux/amd64 stock image archives and an unbooted Ubuntu Hyper-V template. Each release records exact archive hashes, byte counts and build provenance in `manifest.json` and `SHA256SUMS`.

The base, common sandbox and browser images come from unchanged OpenClaw recipes at commit `1391f7cd2d40ab5bbcf2f5f831d3a64f520e72d7`. The template is an offline conversion of Canonical's signed Ubuntu Noble cloud image dated 2026-09-11. Its guest-visible disk content and virtual geometry match that source; the converted template has never booted.

Before loading an archive, verify its byte count and SHA256 against the reviewed installation pin. After loading a stock image, verify its exact image ID and Linux/amd64 platform. These archives retain Docker 29 containerd OCI identities; a classic image store may expose a different ID and must fail the identity check.

Refresh stock images only for an intentional underlying-package refresh or an accepted change to the upstream sandbox recipes and their supporting files. Refresh the template when intentionally accepting a newer dated Canonical image. Publish new release assets and reviewed pins; never overwrite an existing archive to match unexpected bytes.

OpenClaw's license and third-party notices are included unchanged. Distribution packages and bundled tools retain their respective upstream licenses; see [Debian licensing](https://www.debian.org/legal/licenses/) and [Canonical's policy](https://canonical.com/legal/intellectual-property-policy). No blanket license is assigned to the binary archives.
