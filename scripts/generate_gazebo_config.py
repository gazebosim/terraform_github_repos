#!/usr/bin/env python3
"""
Fetch Gazebo repositories from gazebodistro collection files and generate
a YAML configuration with their branches and branch protection rules.

Branch protection rules are fetched via the GitHub GraphQL API so that
wildcard patterns (e.g. ``gz-common[7-9]``) are preserved verbatim.  The
REST endpoint ``/branches/{branch}/protection`` resolves wildcards and loses
the original pattern, which breaks ``terraform import``.

To manage an additional protection field:
  1. Add its GraphQL field to the query in ``get_repo_protection_rules``.
  2. Handle it in ``rule_to_config``.
  3. Remove it from the ``ignore_changes`` list in ``branch_protection.tf``
     (those two lists must stay complementary).
"""

import base64
import fnmatch
import json
import subprocess
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Set

GAZEBODISTRO_REPO = "gazebo-tooling/gazebodistro"
GAZEBODISTRO_BRANCH = "master"
GITHUB_ORG = "gazebosim"

# Source of truth for which collections are active.
RELEASE_TOOLS_REPO = "gazebo-tooling/release-tools"
GZ_COLLECTIONS_PATH = "jenkins-scripts/dsl/gz-collections.yaml"


def run_command(cmd: List[str], check=True) -> str:
    """Run a shell command and return its stdout."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=check)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running command {' '.join(cmd)}: {e.stderr}", file=sys.stderr)
        if check:
            raise
        return ""


# ---------------------------------------------------------------------------
# Collection / repo discovery
# ---------------------------------------------------------------------------

def fetch_active_collection_names() -> Set[str]:
    """Return the set of active collection names from release-tools."""
    print("Fetching active collections from release-tools...")
    output = run_command([
        "gh", "api",
        f"repos/{RELEASE_TOOLS_REPO}/contents/{GZ_COLLECTIONS_PATH}",
        "-q", ".content"
    ])
    content = base64.b64decode(output).decode("utf-8")
    data = yaml.safe_load(content)
    if not data or "collections" not in data or not data["collections"]:
        raise RuntimeError(
            f"No 'collections' found in {RELEASE_TOOLS_REPO}/{GZ_COLLECTIONS_PATH}"
        )
    names = {c["name"] for c in data["collections"] if c.get("name")}
    if not names:
        raise RuntimeError(
            f"No named collections in {RELEASE_TOOLS_REPO}/{GZ_COLLECTIONS_PATH}"
        )
    print(f"Active collections ({len(names)}): {', '.join(sorted(names))}")
    return names


def fetch_collection_files() -> List[str]:
    """Return sorted list of active collection-*.yaml filenames from gazebodistro."""
    print("Fetching collection files from gazebodistro...")
    output = run_command([
        "gh", "api", f"repos/{GAZEBODISTRO_REPO}/contents", "-q", ".[].name"
    ])
    files = output.split("\n")
    discovered = [f for f in files if f.startswith("collection-") and f.endswith(".yaml")]
    active_names = fetch_active_collection_names()
    active_files = {f"collection-{name}.yaml" for name in active_names}
    collection_files = sorted(f for f in discovered if f in active_files)
    missing = sorted(name for name in active_names
                     if f"collection-{name}.yaml" not in discovered)
    for name in missing:
        print(f"  WARNING: active collection '{name}' has no "
              f"collection-{name}.yaml in {GAZEBODISTRO_REPO}, skipping")
    print(f"Found {len(collection_files)} active collection files "
          f"(filtered from {len(discovered)} discovered): "
          f"{', '.join(collection_files)}")
    return collection_files


def fetch_file_content(filename: str) -> str:
    """Fetch and base64-decode a file from gazebodistro."""
    output = run_command([
        "gh", "api",
        f"repos/{GAZEBODISTRO_REPO}/contents/{filename}",
        "-q", ".content"
    ])
    return base64.b64decode(output).decode("utf-8")


def parse_repositories_with_branches(yaml_content: str) -> Dict[str, List[str]]:
    """Parse gz-* / sdformat repository names and their branch versions."""
    data = yaml.safe_load(yaml_content)
    repos: Dict[str, List[str]] = {}
    for repo_name, repo_data in data.get("repositories", {}).items():
        if not (repo_name.startswith("gz-") or repo_name == "sdformat"):
            continue
        branches: List[str] = []
        if repo_data and "version" in repo_data:
            version = repo_data["version"]
            if isinstance(version, str):
                branches.append(version)
            elif isinstance(version, dict):
                branches.extend(version.keys())
        if not branches:
            branches.append("main")
        repos[repo_name] = branches
    return repos


def get_all_repositories_with_branches() -> Dict[str, Set[str]]:
    """Aggregate active branches per repo across all active collection files."""
    all_repos: Dict[str, Set[str]] = {}
    for filename in fetch_collection_files():
        print(f"Parsing {filename}...")
        content = fetch_file_content(filename)
        repos = parse_repositories_with_branches(content)
        for repo_name, branches in repos.items():
            all_repos.setdefault(repo_name, set()).update(branches)
        print(f"  Found {len(repos)} repositories")
    print(f"\nTotal unique repositories: {len(all_repos)}")
    return all_repos


# ---------------------------------------------------------------------------
# Branch protection via GraphQL
# ---------------------------------------------------------------------------

_GRAPHQL_QUERY = """
{
  repository(owner: "%s", name: "%s") {
    branchProtectionRules(first: 50) {
      nodes {
        pattern
        requiresStatusChecks
        requiresStrictStatusChecks
        requiredStatusCheckContexts
      }
    }
  }
}
"""


def get_repo_protection_rules(repo_name: str) -> List[Dict]:
    """Return all branch protection rules for a repo via GraphQL.

    Each element is the raw GraphQL node dict with keys: pattern,
    requiresStatusChecks, requiresStrictStatusChecks,
    requiredStatusCheckContexts.
    """
    query = _GRAPHQL_QUERY % (GITHUB_ORG, repo_name)
    output = run_command(["gh", "api", "graphql", "-f", f"query={query}"], check=False)
    if not output:
        return []
    try:
        data = json.loads(output)
        return (
            data.get("data", {})
                .get("repository", {})
                .get("branchProtectionRules", {})
                .get("nodes", [])
        )
    except (json.JSONDecodeError, KeyError):
        print(f"  Failed to parse GraphQL response for {repo_name}")
        return []


def rule_to_config(rule: Dict) -> Dict:
    """Convert a GraphQL rule node to the config dict stored in the YAML.

    Returns an empty dict if the rule has no fields we manage (currently
    only required_status_checks).  The branch/pattern key is NOT included
    here; it is added by the caller.
    """
    if not rule.get("requiresStatusChecks"):
        return {}
    contexts = rule.get("requiredStatusCheckContexts") or []
    if not contexts:
        return {}
    return {
        "required_status_checks": {
            "strict": bool(rule.get("requiresStrictStatusChecks", False)),
            "contexts": contexts,
        }
    }


def branch_matches_pattern(branch: str, pattern: str) -> bool:
    """Return True if *branch* matches a GitHub branch-protection *pattern*.

    GitHub uses fnmatch-style globs (``*``, ``?``, ``[a-z]``).
    """
    return fnmatch.fnmatch(branch, pattern)


# ---------------------------------------------------------------------------
# Repo existence check
# ---------------------------------------------------------------------------

def check_repo_exists(repo_name: str) -> bool:
    result = run_command([
        "gh", "api", f"repos/{GITHUB_ORG}/{repo_name}", "-q", ".name"
    ], check=False)
    return bool(result)


# ---------------------------------------------------------------------------
# YAML generation
# ---------------------------------------------------------------------------

def generate_yaml_config(repos_config: Dict[str, List[Dict]]) -> str:
    config = {
        "github_organization": GITHUB_ORG,
        "repositories": [],
    }
    for repo_name in sorted(repos_config.keys()):
        branches = repos_config[repo_name]
        if not branches:
            continue
        config["repositories"].append({
            "name": repo_name,
            "branches": sorted(branches, key=lambda b: b["branch"]),
        })
    return yaml.dump(config, default_flow_style=False, sort_keys=False)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=== Gazebo Repository Protection Rules Generator ===\n")

    repos_with_branches = get_all_repositories_with_branches()

    print("\n=== Fetching branch protection rules (GraphQL) ===\n")

    repos_config: Dict[str, List[Dict]] = {}
    total_rules_checked = 0
    included_rules = 0

    for repo_name in sorted(repos_with_branches.keys()):
        if not check_repo_exists(repo_name):
            print(f"Repository {repo_name} does not exist, skipping...")
            continue

        active_branches = repos_with_branches[repo_name]
        print(f"Processing {repo_name} "
              f"(active branches: {', '.join(sorted(active_branches))})...")

        rules = get_repo_protection_rules(repo_name)
        total_rules_checked += len(rules)

        repo_entries: List[Dict] = []
        for rule in rules:
            pattern = rule.get("pattern", "")
            # Only manage rules that cover at least one active collection branch.
            if not any(branch_matches_pattern(b, pattern) for b in active_branches):
                print(f"  Skipping pattern '{pattern}' (no active branch matches)")
                continue
            config = rule_to_config(rule)
            if not config:
                print(f"  Skipping pattern '{pattern}' (no managed fields)")
                continue
            print(f"  Including pattern '{pattern}'")
            repo_entries.append({"branch": pattern, **config})
            included_rules += 1

        if repo_entries:
            repos_config[repo_name] = repo_entries

    print("\n=== Generating YAML configuration ===\n")
    yaml_content = generate_yaml_config(repos_config)
    output_file = Path("gazebo-repos-config.yaml")
    output_file.write_text(yaml_content)

    print(f"Generated {output_file}")
    print(f"Processed {len(repos_config)} repositories")
    print(f"Checked {total_rules_checked} protection rules")
    print(f"Included {included_rules} rules covering active branches")
    print("\nNext steps:")
    print("  git diff gazebo-repos-config.yaml   # review changes")
    print("  ./scripts/import-branch-protection.sh gazebo-repos-config.yaml")
    print("  terraform plan")


if __name__ == "__main__":
    main()
