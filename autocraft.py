#!/usr/bin/env python3
import html
import json
import os
import re
import urllib.request
import zipfile
from pathlib import Path

# --- Configuration ---
WEB_ROOT = Path("/tmp/artcraft")
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

    # Check if we already have this version extracted
    if version_file.exists() and version_file.read_text().strip() == tag_name:
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

    app_names = set(re.findall(r'<a\s+href="([^/"]+)/index\.html"', content))
    for app in app_names:
        app_dir = WEB_ROOT / app
        version_file = app_dir / ".version"
        version = versions.get(app)
        if not version and version_file.exists():
            version = version_file.read_text().strip()

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
            print(f"[{app}] Expected one installed index.html, found {len(candidates)}; leaving template link unchanged.")
            continue

        href = html.escape(candidates[0].relative_to(WEB_ROOT).as_posix(), quote=True)
        link_pattern = re.compile(
            rf'(<a\s+href="){re.escape(app)}/index\.html(")([^>]*)>(.*?)</a>',
            flags=re.IGNORECASE | re.DOTALL
        )

        def update_link(match):
            attributes = match.group(3)
            card_content = match.group(4)
            if version:
                version_attributes = (
                    f' data-app="{html.escape(app, quote=True)}"'
                    f' data-version="{html.escape(version, quote=True)}"'
                )
                attributes = re.sub(
                    r'\sdata-(?:app|version)="[^"]*"',
                    '',
                    attributes,
                    flags=re.IGNORECASE
                )
                attributes += version_attributes
                version_badge = (
                    f'<span class="app-version">v{html.escape(version)}</span>'
                )
                badge_pattern = re.compile(
                    r'<span\s+class="app-version">.*?</span>',
                    flags=re.IGNORECASE | re.DOTALL
                )
                if badge_pattern.search(card_content):
                    card_content = badge_pattern.sub(version_badge, card_content)
                else:
                    app_name_pattern = re.compile(
                        r'(^[ \t]*)(<span\s+class="app-name">.*?</span>)',
                        flags=re.IGNORECASE | re.DOTALL | re.MULTILINE
                    )
                    card_content, matches = app_name_pattern.subn(
                        lambda name_match: (
                            f'{name_match.group(1)}{name_match.group(2)}\n'
                            f'{name_match.group(1)}{version_badge}'
                        ),
                        card_content,
                        count=1
                    )
                    if not matches:
                        print(f"[{app}] No app name found in its index card.")
            return f'{match.group(1)}{href}{match.group(2)}{attributes}>{card_content}</a>'

        content = link_pattern.sub(update_link, content)

    index_file.write_text(content)
    print(f"Generated {index_file} from {INDEX_TEMPLATE}.")

def main():
    WEB_ROOT.mkdir(parents=True, exist_ok=True)
    installed_versions = {}

    for app in APPS:
        installed_versions[app] = update_app(app)

    update_index_html(installed_versions)

if __name__ == "__main__":
    main()
