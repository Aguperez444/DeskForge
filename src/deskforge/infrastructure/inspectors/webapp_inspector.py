"""Inspector for Web Apps / PWAs: fetches title, description, favicon, and detects compatible browsers."""

from __future__ import annotations

import hashlib
from html.parser import HTMLParser
from pathlib import Path
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request

from deskforge.domain.models import AppType, DetectionResult
from deskforge.infrastructure.inspectors.base import BaseInspector

SUPPORTED_BROWSERS: tuple[tuple[str, str], ...] = (
    ("chromium", "Chromium"),
    ("google-chrome", "Google Chrome"),
    ("google-chrome-stable", "Google Chrome"),
    ("brave-browser", "Brave"),
    ("brave", "Brave"),
    ("vivaldi-stable", "Vivaldi"),
    ("vivaldi", "Vivaldi"),
    ("microsoft-edge", "Microsoft Edge"),
    ("firefox", "Firefox"),
)


def detect_installed_browsers() -> list[tuple[str, str]]:
    """Return list of (binary_name_or_path, display_label) for installed browsers."""
    found: list[tuple[str, str]] = []
    seen_labels: set[str] = set()
    for binary, label in SUPPORTED_BROWSERS:
        if label in seen_labels:
            continue
        if shutil.which(binary):
            seen_labels.add(label)
            found.append((binary, label))
    return found


class _HeadMetadataParser(HTMLParser):
    """Lightweight HTML <head> parser to extract title, description, and icon links."""

    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.title_parts: list[str] = []
        self.description: str = ""
        self.icon_urls: list[tuple[int, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        attr_map = {k.lower(): (v or "") for k, v in attrs}
        if tag_l == "title":
            self.in_title = True
        elif tag_l == "meta":
            name = attr_map.get("name", "").lower()
            prop = attr_map.get("property", "").lower()
            if name == "description" or prop == "og:description":
                if not self.description and attr_map.get("content"):
                    self.description = attr_map["content"].strip()
        elif tag_l == "link":
            rel = attr_map.get("rel", "").lower()
            href = attr_map.get("href", "").strip()
            if not href:
                return
            if "apple-touch-icon" in rel:
                self.icon_urls.append((90, href))
            elif "icon" in rel:
                sizes = attr_map.get("sizes", "")
                score = 70 if "192" in sizes or "180" in sizes or "128" in sizes else 50
                if href.lower().endswith(".png"):
                    score += 15
                elif href.lower().endswith(".svg"):
                    score += 10
                self.icon_urls.append((score, href))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self.title_parts).split()).strip()


class WebAppInspector(BaseInspector):
    """Inspects http(s) URLs to build standalone frameless WebApp launchers."""

    USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) DeskForge/2.0"

    def can_handle(self, target: str) -> bool:
        t = target.strip().lower()
        return t.startswith("https://") or t.startswith("http://")

    def inspect(self, target: str, fetch_remote: bool = True) -> DetectionResult:
        url = target.strip()
        parsed_url = urllib.parse.urlparse(url)
        host = (parsed_url.netloc or "webapp").removeprefix("www.")
        host_title = host.split(".")[0].capitalize() if host else "WebApp"

        suggested_name = host_title
        comment = f"Aplicación web ({host})"
        icon_candidates: list[str] = []
        warnings: list[str] = []

        browsers = detect_installed_browsers()
        default_browser = browsers[0][0] if browsers else "chromium"
        if not browsers:
            warnings.append("No se detectó Chromium/Chrome/Brave/Firefox en PATH. Configurá el navegador manualmente.")

        if fetch_remote:
            html_title, html_desc, icon_links = self._fetch_page_metadata(url)
            if html_title:
                # Trim overly verbose site subtitles
                suggested_name = re.split(r"\s+[|\-—·]\s+", html_title)[0].strip()[:50] or host_title
            if html_desc:
                comment = html_desc[:140]
            icon_candidates = self._download_icons(url, icon_links)

        if self._paths.default_app_icon.exists():
            icon_candidates.append(str(self._paths.default_app_icon))

        wm_slug = re.sub(r"[^a-zA-Z0-9]+", "-", suggested_name.lower()).strip("-") or "webapp"

        return DetectionResult(
            target=url,
            app_type=AppType.WEBAPP,
            suggested_name=suggested_name,
            comment=comment,
            categories=["Network"],
            icon_candidates=icon_candidates,
            selected_icon=icon_candidates[0] if icon_candidates else "",
            startup_wm_class=f"deskforge-{wm_slug}",
            webapp_browser=default_browser,
            warnings=warnings,
            metadata={"host": host},
        )

    def _fetch_page_metadata(self, url: str) -> tuple[str, str, list[tuple[int, str]]]:
        req = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read(256 * 1024)
            html = raw.decode("utf-8", errors="replace")
            parser = _HeadMetadataParser()
            parser.feed(html)
            return parser.title, parser.description, parser.icon_urls
        except (urllib.error.URLError, OSError, ValueError):
            return "", "", []

    def _download_icons(self, base_url: str, links: list[tuple[int, str]]) -> list[str]:
        candidates = sorted(links, key=lambda x: x[0], reverse=True)
        candidates.append((10, "/favicon.ico"))

        url_hash = hashlib.sha1(base_url.encode()).hexdigest()[:12]
        out_dir = self._paths.cache_dir / "extracted" / f"web_{url_hash}"
        out_dir.mkdir(parents=True, exist_ok=True)

        saved: list[str] = []
        seen_urls: set[str] = set()
        for idx, (_score, href) in enumerate(candidates):
            full_url = urllib.parse.urljoin(base_url, href)
            if full_url in seen_urls or not full_url.startswith(("http://", "https://")):
                continue
            seen_urls.add(full_url)

            req = urllib.request.Request(full_url, headers={"User-Agent": self.USER_AGENT})
            try:
                with urllib.request.urlopen(req, timeout=4) as resp:
                    data = resp.read(1024 * 1024)
                    ctype = (resp.headers.get("Content-Type") or "").lower()
                if len(data) < 64:
                    continue
                ext = ".png"
                if "svg" in ctype or full_url.lower().endswith(".svg"):
                    ext = ".svg"
                elif "icon" in ctype or full_url.lower().endswith(".ico"):
                    ext = ".ico"
                out_file = out_dir / f"favicon_{idx}{ext}"
                out_file.write_bytes(data)
                saved.append(str(out_file))
                if len(saved) >= 3:
                    break
            except (urllib.error.URLError, OSError, ValueError):
                continue
        return saved
