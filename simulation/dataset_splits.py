"""Frozen split assignment by world ancestry, never by episode or simulator.

New derived worlds must use their ancestor's family ID (or register an alias).
Unknown ancestry cannot be inferred from a random seed: the caller supplies it.
"""
import hashlib
import json
from pathlib import Path

DEFAULT_REGISTRY = Path(__file__).resolve().parents[1] / "configs" / "splits-v1.json"
DEFAULT_REGISTRY_SHA256 = "40122d723abd04b39961542a692a37a07231678c5adeed610f34186508dd551f"
VALID_SPLITS = {"train", "validation", "test"}


def registry_digest(registry):
    return hashlib.sha256(json.dumps(registry, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load_registry(path=None, expected_sha256=None):
    path = Path(path) if path is not None else DEFAULT_REGISTRY
    expected = expected_sha256
    if path.resolve() == DEFAULT_REGISTRY.resolve():
        expected = expected or DEFAULT_REGISTRY_SHA256
    if not expected:
        raise ValueError("Custom split registries require an explicitly pinned expected_sha256")
    registry = json.loads(path.read_text(encoding="utf-8"))
    if registry_digest(registry) != expected:
        raise ValueError("Split registry digest mismatch: create and pin a new version instead of editing a frozen split")
    validate_registry(registry)
    return registry


def canonical_family(world_family_id, registry):
    if not isinstance(world_family_id, str) or not world_family_id.strip():
        raise ValueError("An explicit nonempty ancestry world_family_id is required")
    family = world_family_id.strip()
    seen = set()
    aliases = registry["family_aliases"]
    while family in aliases:
        if family in seen:
            raise ValueError("Cyclic world family aliases")
        seen.add(family)
        family = aliases[family]
        if not isinstance(family, str) or not family:
            raise ValueError("Invalid ancestry alias")
    return family


def validate_registry(registry):
    required = ("version", "hash_algorithm", "salt", "bucket_count", "train_end",
                "validation_end", "family_aliases", "explicit_assignments")
    if any(key not in registry for key in required):
        raise ValueError("Incomplete split registry")
    if registry["hash_algorithm"] != "sha256" or not registry["version"] or not registry["salt"]:
        raise ValueError("Invalid split hash policy")
    if not 0 < registry["train_end"] < registry["validation_end"] < registry["bucket_count"]:
        raise ValueError("Invalid split boundaries")
    for family in registry["family_aliases"]:
        canonical_family(family, registry)
    for family, split in registry["explicit_assignments"].items():
        if split not in VALID_SPLITS:
            raise ValueError("Unknown split")
        if canonical_family(family, registry) != family:
            raise ValueError("Explicit assignments must name ancestry roots, not variants")


def assign_split(world_family_id, registry=None):
    registry = load_registry() if registry is None else registry
    validate_registry(registry)
    digest = registry_digest(registry)
    # Never allow an in-memory override to silently mutate the frozen v1 policy.
    if registry["version"] == "world-family-splits-v1" and digest != DEFAULT_REGISTRY_SHA256:
        raise ValueError("Frozen v1 registry changed without a new version")
    family = canonical_family(world_family_id, registry)
    split = registry["explicit_assignments"].get(family)
    if split is None:
        identity = json.dumps([registry["salt"], family], separators=(",", ":")).encode()
        bucket = int.from_bytes(hashlib.sha256(identity).digest()[:8], "big") % registry["bucket_count"]
        split = ("train" if bucket < registry["train_end"] else
                 "validation" if bucket < registry["validation_end"] else "test")
    return {"world_family_id": family, "split": split,
            "split_registry_version": registry["version"],
            "split_registry_sha256": digest,
            "split_assignment_policy": "ancestry_family"}


def validate_assignments(assignments, registry=None):
    """Reject inconsistent, stale or tampered episode split metadata before pooling."""
    registry = load_registry() if registry is None else registry
    errors = []
    for index, assignment in enumerate(assignments):
        try:
            expected = assign_split(assignment["world_family_id"], registry)
            mismatches = [key for key, value in expected.items() if assignment.get(key) != value]
            if mismatches:
                errors.append({"index": index, "reason": "split metadata mismatch", "fields": mismatches})
        except (ValueError, KeyError, TypeError) as exc:
            errors.append({"index": index, "reason": str(exc)})
    return {"valid": not errors, "errors": errors}

