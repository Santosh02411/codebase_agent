"""Declared dependencies from package manifests (Python, Node, Go, Rust, Java/Maven/Gradle)."""
from __future__ import annotations
import json
import posixpath
import re

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None  # type: ignore

_NAME = re.compile(r"^\s*([A-Za-z0-9_.\-]+)")


def _req_name(line: str) -> str | None:
    line = line.split("#")[0].strip()
    if not line or line.startswith(("-", "git+", "http")):
        return None
    m = _NAME.match(line)
    return m.group(1).lower().replace("_", "-") if m else None


def parse_manifest(path: str, text: str) -> tuple[str, list[str]] | None:
    """-> (ecosystem, [dependency names]) or None if `path` isn't a manifest."""
    name = posixpath.basename(path)
    try:
        if re.fullmatch(r"requirements[\w.\-]*\.txt", name):
            return "python", [n for n in (_req_name(l) for l in text.splitlines()) if n]
        if name == "pyproject.toml" and tomllib:
            d = tomllib.loads(text)
            deps = [_req_name(x) for x in d.get("project", {}).get("dependencies", [])]
            for group in d.get("project", {}).get("optional-dependencies", {}).values():
                deps += [_req_name(x) for x in group]
            deps += [k.lower() for k in d.get("tool", {}).get("poetry", {}).get("dependencies", {}) if k.lower() != "python"]
            return "python", [x for x in deps if x]
        if name == "package.json":
            d = json.loads(text)
            return "node", sorted({*d.get("dependencies", {}), *d.get("devDependencies", {}), *d.get("peerDependencies", {})})
        if name == "go.mod":
            deps = re.findall(r"^\s*(?:require\s+)?([\w.\-]+\.[\w.\-]+/[\w./\-]+)\s+v[\w.\-+]+", text, re.M)
            return "go", sorted(set(deps))
        if name == "Cargo.toml" and tomllib:
            d = tomllib.loads(text)
            deps = set()
            for sec in ("dependencies", "dev-dependencies", "build-dependencies"):
                deps |= set(d.get(sec, {}))
            return "rust", sorted(deps)
        if name == "pom.xml":
            found = re.findall(r"<dependency>.*?<groupId>\s*([^<\s]+)\s*</groupId>.*?<artifactId>\s*([^<\s]+)\s*</artifactId>", text, re.S)
            return "java", sorted({f"{g}:{a}" for g, a in found})
        if name in ("build.gradle", "build.gradle.kts"):
            found = re.findall(r"(?:implementation|api|compile|testImplementation|runtimeOnly|compileOnly|annotationProcessor)\s*\(?\s*['\"]([^'\"]+)['\"]", text)
            return "java", sorted({":".join(x.split(":")[:2]) for x in found})
    except (ValueError, KeyError, AttributeError):
        return None
    return None


def go_module(text: str) -> str:
    m = re.search(r"^module\s+(\S+)", text, re.M)
    return m.group(1) if m else ""
