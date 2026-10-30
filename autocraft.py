#!/usr/bin/env python3
import html
import json
import os
import re
import shutil
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
    release_info = fetch_latest_release(app_name)
    if not release_info:
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
        return None

    app_dir = WEB_ROOT / app_name
    version_file = app_dir / ".version"

    # Check that the cached version still has its web entry point.
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
    with urllib.request.urlopen(req) as resp, open(zip_path, "wb") as f:
        f.write(resp.read())

    # Extract archive into target directory
    app_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(app_dir)

    # Save installed version tag
    version_file.write_text(tag_name)
    zip_path.unlink(missing_ok=True) # Clean up downloaded archive
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
            raise RuntimeError(f"[{app}] No installed version is available for the catalog.")

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
            raise RuntimeError(
                f"[{app}] Expected one installed index.html for v{version}, found {len(candidates)}."
            )

        href = html.escape(candidates[0].relative_to(WEB_ROOT).as_posix(), quote=True)
        card_pattern = re.compile(
            rf'(<article\b[^>]*\bdata-app="{re.escape(app)}"[^>]*>)(.*?)</article>',
            flags=re.IGNORECASE | re.DOTALL
        )

        card_match = card_pattern.search(content)
        if not card_match:
            raise RuntimeError(f"[{app}] No matching app card found in the template.")

        opening_tag = card_match.group(1)
        version_pattern = re.compile(r'(\bdata-version=")[^"]*(")', re.IGNORECASE)
        opening_tag, version_matches = version_pattern.subn(
            lambda match: f'{match.group(1)}{html.escape(version, quote=True)}{match.group(2)}',
            opening_tag,
            count=1
        )
        if not version_matches:
            raise RuntimeError(f"[{app}] App card is missing its data-version attribute.")

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
            raise RuntimeError(f"[{app}] App card is missing its version badge.")

        link_pattern = re.compile(
            rf'(<a\b[^>]*\bhref="){re.escape(app)}/[^"]*/index\.html(")',
            flags=re.IGNORECASE
        )
        card_content, link_matches = link_pattern.subn(
            lambda match: f"{match.group(1)}{href}{match.group(2)}",
            card_content
        )
        if not link_matches:
            raise RuntimeError(f"[{app}] No app launch links found in the template.")

        release_url = html.escape(
            f"https://github.com/{GITHUB_ORG}/{app}/releases/tag/v{version}#:~:text=Assets",
            quote=True
        )
        get_link_pattern = re.compile(
            r'(<a\b(?=[^>]*\bclass="[^"]*\bbutton-get\b[^"]*")[^>]*\bhref=")[^"]*(")',
            flags=re.IGNORECASE | re.DOTALL
        )
        card_content, get_link_matches = get_link_pattern.subn(
            lambda match: f"{match.group(1)}{release_url}{match.group(2)}",
            card_content
        )
        if get_link_matches != 1:
            raise RuntimeError(
                f"[{app}] Expected one Get link in the template, found {get_link_matches}."
            )

        updated_card = f"{opening_tag}{card_content}</article>"
        content = (
            content[:card_match.start()]
            + updated_card
            + content[card_match.end():]
        )

    index_file.write_text(content)
    print(f"Generated {index_file} from {INDEX_TEMPLATE}.")

def copy_brand_assets():
    source_dir = Path(__file__).with_name("media")
    destination_dir = WEB_ROOT / "media"
    destination_dir.mkdir(parents=True, exist_ok=True)

    for filename in ("craftyapps_logo.svg", "craftyapps_logo_dark.svg"):
        shutil.copy2(source_dir / filename, destination_dir / filename)

def main():
    WEB_ROOT.mkdir(parents=True, exist_ok=True)
    copy_brand_assets()
    installed_versions = {}

    for app in APPS:
        installed_versions[app] = update_app(app)

    update_index_html(installed_versions)

if __name__ == "__main__":
    main()
