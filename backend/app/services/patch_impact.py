from pathlib import PurePosixPath
from typing import Any


OBJECT_FOLDERS = {
    "Documents": "Document",
    "Catalogs": "Catalog",
    "CommonModules": "CommonModule",
    "Reports": "Report",
    "DataProcessors": "DataProcessor",
    "InformationRegisters": "InformationRegister",
    "AccumulationRegisters": "AccumulationRegister",
}


def analyze_patch_impact(files: list[dict[str, Any]]) -> list[dict[str, str]]:
    impacts: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in files:
        path = PurePosixPath(str(item.get("path", "")))
        parts = path.parts
        if len(parts) < 2:
            continue
        folder = OBJECT_FOLDERS.get(parts[0])
        if folder:
            object_name = parts[1][:-4] if parts[1].endswith(".bsl") else parts[1]
            object_fqn = f"{folder}.{object_name}"
            relation = "object_module"
            if len(parts) > 2 and parts[2] in {"Forms", "Commands"}:
                relation = parts[2].lower()
            key = (object_fqn, relation)
            if key not in seen:
                impacts.append(
                    {
                        "objectFqn": object_fqn,
                        "relation": relation,
                        "risk": "candidate",
                        "source": "changed_path",
                    }
                )
                seen.add(key)
        elif parts[0] == "Ext":
            key = ("ConfigurationExtension", "extension")
            if key not in seen:
                impacts.append(
                    {
                        "objectFqn": "ConfigurationExtension",
                        "relation": "extension",
                        "risk": "candidate",
                        "source": "changed_path",
                    }
                )
                seen.add(key)
    return impacts


def enrich_patch_impact(
    impacts: list[dict[str, str]], evidence: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Attach caller-provided read-only evidence to matching candidates only."""
    evidence_by_key = {
        (str(item.get("objectFqn")), str(item.get("relation"))): item for item in evidence
    }
    enriched: list[dict[str, Any]] = []
    for impact in impacts:
        item: dict[str, Any] = dict(impact)
        source = evidence_by_key.get((impact["objectFqn"], impact["relation"]))
        if source is not None:
            item["risk"] = "evidenced"
            item["source"] = str(source["sourceTool"])
            item["evidence"] = list(source["evidence"])
        enriched.append(item)
    return enriched
