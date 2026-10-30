#!/usr/bin/env python3
import html
import json
import os
import re
import urllib.request
import zipfile
from pathlib import Path

# --- Configuration ---
WEB_ROOT = Path(os.environ.get("ARTCRAFT_WEB_ROOT", Path(__file__).with_name("output"))).resolve()
INDEX_TEMPLATE = Path(__file__).with_name("index.html.template")
GITHUB_ORG = "storytold"
APPS = [
    "photocraft", "vectorcraft", "filmcraft", "lightcraft",
    "pdfcraft", "effectcraft", "designcraft", "figcraft",
    "wordcraft", "soundcraft", "deckcraft", "cadcraft", "gridcraft"
]
# GitHub API Headers (Add GitHub Token if encountering rate limits)
HEADERS = {
    "User-Agent": "ArtCraft-AutoUpdater",
    "Accept": "application/vnd.github.v3+json"
}
# GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
# if GITHUB_TOKEN:
#     HEADERS["Authorization"] = f"Bearer {GITHUB_TOKEN}"


def fetch_latest_release(app_name):
    url = f"https://api.github.com/repos/{GITHUB_ORG}/{app_name}/releases/latest"
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        print(f"[{app_name}] Failed to fetch release info: {e}")
        return None


def update_app(app_name):
    app_dir = WEB_ROOT / app_name
    version_file = app_dir / ".version"

    # Prefer the last known-good version if the upstream release is temporarily unavailable.
    if version_file.exists():
        cached_version = version_file.read_text().strip()
    else:
        cached_version = None

    release_info = fetch_latest_release(app_name)
    if not release_info:
        if cached_version:
            print(f"[{app_name}] Using cached version {cached_version} because no release was available.")
            return cached_version
        return None

    tag_name = release_info.get("tag_name", "").lstrip("v")
    assets = release_info.get("assets", [])

    # Find asset matching: appname-web-x.x.x.zip
    target_asset = None
    for asset in assets:
        name = asset.get("name", "")
        if name.startswith(f"{app_name}-web-") and name.endswith(".zip"):
            target_asset = asset
            break

    if not target_asset:
        print(f"[{app_name}] No matching WASM zip asset found in release {tag_name}")
        if cached_version:
            print(f"[{app_name}] Retaining cached version {cached_version}.")
            return cached_version
        return None

    cached_indexes = [
        path for path in app_dir.rglob("index.html")
        if path.is_file()
        and any(part.endswith(f"-{tag_name}") for part in path.relative_to(app_dir).parts)
    ] if app_dir.is_dir() else []
    if (
        version_file.exists()
        and version_file.read_text().strip() == tag_name
        and len(cached_indexes) == 1
    ):
        print(f"[{app_name}] Already up to date (v{tag_name}).")
        return tag_name

    download_url = target_asset["browser_download_url"]
    zip_path = WEB_ROOT / f"{app_name}-latest.zip"

    print(f"[{app_name}] Downloading v{tag_name} from {download_url}...")
    req = urllib.request.Request(download_url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req) as resp, open(zip_path, "wb") as f:
            f.write(resp.read())
    except Exception as exc:
        print(f"[{app_name}] Download failed: {exc}")
        if cached_version:
            print(f"[{app_name}] Keeping cached version {cached_version}.")
            return cached_version
        return None

    # Extract archive into target directory
    app_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(app_dir)
    except Exception as exc:
        print(f"[{app_name}] Extraction failed: {exc}")
        if cached_version:
            print(f"[{app_name}] Keeping cached version {cached_version}.")
            return cached_version
        return None

    # Save installed version tag
    version_file.write_text(tag_name)
    zip_path.unlink(missing_ok=True)  # Clean up downloaded archive
    print(f"[{app_name}] Successfully updated to v{tag_name}.")
    return tag_name


def update_index_html(versions):
    index_file = WEB_ROOT / "index.html"
    content = INDEX_TEMPLATE.read_text()

    for app in APPS:
        app_dir = WEB_ROOT / app
        version_file = app_dir / ".version"
        version = versions.get(app)
        if not version and version_file.exists():
            version = version_file.read_text().strip()
        if not version:
            print(f"[{app}] No installed version is available; leaving template card unchanged.")
            continue

        candidates = [
            path for path in app_dir.rglob("index.html")
            if path.is_file()
        ] if app_dir.is_dir() else []
        if version:
            version_candidates = [
                path for path in candidates
                if any(part.endswith(f"-{version}") for part in path.relative_to(app_dir).parts)
            ]
            if version_candidates:
                candidates = version_candidates

        if len(candidates) != 1:
            print(
                f"[{app}] Expected one installed index.html for v{version}, found {len(candidates)}. "
                "Skipping catalog update for this app."
            )
            continue

        href = html.escape(candidates[0].relative_to(WEB_ROOT).as_posix(), quote=True)
        card_pattern = re.compile(
            rf'(<article\b[^>]*\bdata-app="{re.escape(app)}"[^>]*>)(.*?)</article>',
            flags=re.IGNORECASE | re.DOTALL
        )

        card_match = card_pattern.search(content)
        if not card_match:
            print(f"[{app}] No matching app card found in the template.")
            continue

        opening_tag = card_match.group(1)
        version_pattern = re.compile(r'(\bdata-version=")[^"]*(")', re.IGNORECASE)
        opening_tag, version_matches = version_pattern.subn(
            lambda match: f'{match.group(1)}{html.escape(version, quote=True)}{match.group(2)}',
            opening_tag,
            count=1
        )
        if not version_matches:
            print(f"[{app}] App card is missing its data-version attribute.")
            continue

        card_content = card_match.group(2)
        badge_pattern = re.compile(
            r'<span\s+class="app-version">.*?</span>',
            flags=re.IGNORECASE | re.DOTALL
        )
        card_content, badge_matches = badge_pattern.subn(
            f'<span class="app-version">v{html.escape(version)}</span>',
            card_content,
            count=1
        )
        if not badge_matches:
            print(f"[{app}] App card is missing its version badge.")
            continue

        link_pattern = re.compile(
            rf'(<a\b[^>]*\bhref="){re.escape(app)}/[^"]*/index\.html(")',
            flags=re.IGNORECASE
        )
        card_content, link_matches = link_pattern.subn(
            lambda match: f"{match.group(1)}{href}{match.group(2)}",
            card_content
        )
        if not link_matches:
            print(f"[{app}] No app launch links found in the template.")
            continue

        updated_card = f"{opening_tag}{card_content}</article>"
        content = (
            content[:card_match.start()]
            + updated_card
            + content[card_match.end():]
        )

    index_file.write_text(content)
    print(f"Generated {index_file} from {INDEX_TEMPLATE}.")


def main():
    WEB_ROOT.mkdir(parents=True, exist_ok=True)
    installed_versions = {}

    for app in APPS:
        version = update_app(app)
        if version is not None:
            installed_versions[app] = version

    update_index_html(installed_versions)


if __name__ == "__main__":
    main()
