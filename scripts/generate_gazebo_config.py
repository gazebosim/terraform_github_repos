#!/usr/bin/env python3
"""
Fetch Gazebo repositories from gazebodistro collection files and generate
a YAML configuration with their branches and branch protection rules.
"""

import base64
import fnmatch
import json
import subprocess
import sys
import time
import yaml
from pathlib import Path
from typing import Dict, List, Set, Tuple

GAZEBODISTRO_REPO = "gazebo-tooling/gazebodistro"
GAZEBODISTRO_BRANCH = "master"
GITHUB_ORG = "gazebosim"

# Source of truth for which collections are active. Only collection-*.yaml
# files matching an active collection name are parsed.
RELEASE_TOOLS_REPO = "gazebo-tooling/release-tools"
GZ_COLLECTIONS_PATH = "jenkins-scripts/dsl/gz-collections.yaml"


def _translate_status_checks(rule: Dict):
    """GraphQL rule -> config for required_status_checks; None if not required."""
    if not rule.get("requiresStatusChecks"):
        return None
    return {
        "strict": rule.get("requiresStrictStatusChecks", False),
        "contexts": rule.get("contexts", []),
    }


# Branch-protection fields to keep in the generated config, mapped to their
# GraphQL-rule -> config translator. The keys are the allowlist: anything not
# listed here is discarded so Terraform leaves it unchanged (see lifecycle
# ignore_changes in branch_protection.tf). To manage another field, add a
# translator entry here AND remove that field from the ignore_changes list.
PROTECTION_FIELD_TRANSLATORS = {
    "required_status_checks": _translate_status_checks,
}


# Substrings identifying a failure that is worth retrying. Anything else
# (404, auth error, bad query) is a real answer and must not be retried.
TRANSIENT_ERROR_MARKERS = (
    "i/o timeout",
    "error connecting",
    "connection reset",
    "connection refused",
    "TLS handshake timeout",
    "unexpected EOF",
    "502 Bad Gateway",
    "503 Service Unavailable",
    "504 Gateway Timeout",
)
MAX_ATTEMPTS = 5


def _is_transient(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(marker.lower() in lowered for marker in TRANSIENT_ERROR_MARKERS)


def run_gh(cmd: List[str], max_attempts: int = MAX_ATTEMPTS):
    """Run a gh command, retrying transient network failures with backoff.

    A full generation run makes hundreds of API calls, so an occasional
    timeout is expected; without retries a single blip aborts everything.
    Returns the CompletedProcess and lets the caller decide how to treat a
    non-zero exit that survived every attempt.
    """
    for attempt in range(1, max_attempts + 1):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0 or not _is_transient(result.stderr):
            return result
        if attempt < max_attempts:
            delay = 2 ** (attempt - 1)
            first_line = result.stderr.strip().splitlines()[0]
            print(f"    transient failure ({attempt}/{max_attempts}), "
                  f"retrying in {delay}s: {first_line}")
            time.sleep(delay)
    return result


def run_command(cmd: List[str], check=True) -> str:
    """Run a shell command and return its output."""
    result = run_gh(cmd)
    if result.returncode != 0:
        print(f"Error running command {' '.join(cmd)}: {result.stderr}",
              file=sys.stderr)
        if check:
            raise subprocess.CalledProcessError(
                result.returncode, cmd, result.stdout, result.stderr
            )
        return ""
    return result.stdout.strip()


def fetch_collection_files() -> List[str]:
    """Fetch list of active collection-*.yaml files from gazebodistro.

    Restricts the discovered collection files to the active collections defined
    in release-tools' gz-collections.yaml. A collection named ``<name>`` maps to
    the gazebodistro file ``collection-<name>.yaml``.
    """
    print("Fetching collection files from gazebodistro...")

    # List files in the root directory
    output = run_command([
        "gh", "api",
        f"repos/{GAZEBODISTRO_REPO}/contents",
        "-q", ".[].name"
    ])

    files = output.split('\n')
    discovered = [f for f in files if f.startswith('collection-') and f.endswith('.yaml')]

    # Keep only the collection files that correspond to an active collection.
    active_names = fetch_active_collection_names()
    active_files = {f"collection-{name}.yaml" for name in active_names}
    collection_files = sorted(f for f in discovered if f in active_files)

    # Warn (and skip) for any active collection without a gazebodistro file.
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
    """Fetch content of a file from gazebodistro."""
    output = run_command([
        "gh", "api",
        f"repos/{GAZEBODISTRO_REPO}/contents/{filename}",
        "-q", ".content"
    ])

    # Decode base64 content
    return base64.b64decode(output).decode('utf-8')


def fetch_active_collection_names() -> Set[str]:
    """Fetch the set of active collection names from release-tools'
    gz-collections.yaml.

    The remote file is the single source of truth for which collections are
    active. Any failure to fetch or parse it aborts the run (fail loud) rather
    than silently falling back to processing every collection.
    """
    print("Fetching active collections from release-tools...")

    # check=True so a failed fetch raises and aborts the run.
    output = run_command([
        "gh", "api",
        f"repos/{RELEASE_TOOLS_REPO}/contents/{GZ_COLLECTIONS_PATH}",
        "-q", ".content"
    ])

    content = base64.b64decode(output).decode('utf-8')
    data = yaml.safe_load(content)

    if not data or 'collections' not in data or not data['collections']:
        raise RuntimeError(
            f"No 'collections' found in {RELEASE_TOOLS_REPO}/{GZ_COLLECTIONS_PATH}"
        )

    names = {c['name'] for c in data['collections'] if c.get('name')}
    if not names:
        raise RuntimeError(
            f"No named collections in {RELEASE_TOOLS_REPO}/{GZ_COLLECTIONS_PATH}"
        )

    print(f"Active collections ({len(names)}): {', '.join(sorted(names))}")
    return names


def parse_repositories_with_branches(yaml_content: str) -> Dict[str, List[str]]:
    """Parse repository names and their branches from collection YAML file."""
    data = yaml.safe_load(yaml_content)
    repos = {}
    
    if 'repositories' in data:
        for repo_name, repo_data in data['repositories'].items():
            # Only include gz- and sdformat repositories
            if repo_name.startswith('gz-') or repo_name == 'sdformat':
                branches = []
                if repo_data and 'version' in repo_data:
                    # version can be a string or a dict with branch info
                    version = repo_data['version']
                    if isinstance(version, str):
                        branches.append(version)
                    elif isinstance(version, dict):
                        # Extract branch names from version dict
                        for key in version.keys():
                            branches.append(key)
                
                # Default to 'main' if no branches found
                if not branches:
                    branches.append('main')
                
                repos[repo_name] = branches
    
    return repos


def get_all_repositories_with_branches() -> Dict[str, Set[str]]:
    """Get all unique repository names with their branches from all collection files."""
    all_repos = {}
    collection_files = fetch_collection_files()
    
    for filename in collection_files:
        print(f"Parsing {filename}...")
        content = fetch_file_content(filename)
        repos = parse_repositories_with_branches(content)
        
        for repo_name, branches in repos.items():
            if repo_name not in all_repos:
                all_repos[repo_name] = set()
            all_repos[repo_name].update(branches)
        
        print(f"  Found {len(repos)} repositories")
    
    print(f"\nTotal unique repositories: {len(all_repos)}")
    return all_repos


def check_repo_exists(repo_name: str) -> bool:
    """Check if a repository exists in the GitHub organization.

    Only a genuine 404 counts as "does not exist". Any other failure
    (timeout, 5xx, connection reset) aborts the run: treating it as a
    missing repository would silently drop every protection rule for that
    repo from the generated config, making the output non-deterministic.
    """
    result = run_gh(
        ["gh", "api", f"repos/{GITHUB_ORG}/{repo_name}", "-q", ".name"]
    )
    if result.returncode == 0:
        return True

    if "404" in result.stderr or "Not Found" in result.stderr:
        return False

    raise RuntimeError(
        f"Failed to check whether {GITHUB_ORG}/{repo_name} exists: "
        f"{result.stderr.strip()}"
    )


def fetch_branch_protection_rules(repo_name: str) -> List[Dict]:
    """Fetch all branch-protection *rules* for a repository via GraphQL.

    GitHub stores branch protection as pattern rules (e.g. ``gz-common[7-9]``)
    that can match many branches; it is not one rule per concrete branch.
    Terraform's ``github_branch_protection`` matches rules by their exact
    pattern string, so the generated config must use the real rule patterns.
    (The REST ``/branches/<branch>/protection`` endpoint only returns the
    *effective* protection for a concrete branch, whose name usually does not
    equal the governing rule pattern -- which is why importing by branch name
    failed.)
    """
    query = """
    query($owner:String!,$name:String!){
      repository(owner:$owner,name:$name){
        branchProtectionRules(first:100){
          nodes{
            pattern
            requiresStatusChecks
            requiresStrictStatusChecks
            requiredStatusChecks{ context }
          }
        }
      }
    }
    """
    # Any failure aborts the run. Returning an empty rule list on a transient
    # error would make the repository look unprotected and silently drop all
    # of its rules from the generated config.
    output = run_command([
        "gh", "api", "graphql",
        "-f", f"query={query}",
        "-F", f"owner={GITHUB_ORG}",
        "-F", f"name={repo_name}",
    ])

    try:
        data = json.loads(output)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"Unparseable branch-protection response for {repo_name}: {e}"
        ) from e

    if data.get("errors"):
        raise RuntimeError(
            f"GraphQL errors fetching branch protection for {repo_name}: "
            f"{data['errors']}"
        )

    repo = (data.get("data") or {}).get("repository")
    if repo is None:
        raise RuntimeError(
            f"GraphQL returned no repository object for "
            f"{GITHUB_ORG}/{repo_name} (expected it to exist)"
        )

    nodes = (repo.get("branchProtectionRules") or {}).get("nodes") or []

    rules = []
    for node in nodes:
        rules.append({
            "pattern": node["pattern"],
            "requiresStatusChecks": node.get("requiresStatusChecks", False),
            "requiresStrictStatusChecks": node.get("requiresStrictStatusChecks", False),
            "contexts": [c["context"] for c in (node.get("requiredStatusChecks") or [])],
        })
    return rules


def rule_to_config(rule: Dict) -> Dict:
    """Convert a branch-protection rule to a config entry keyed by its pattern.

    Only the fields registered in PROTECTION_FIELD_TRANSLATORS are kept; a rule
    with none of them is dropped (returns ``{}``). The ``branch`` key holds the
    rule *pattern*, which is also the Terraform import id (``<repo>:<pattern>``).
    """
    config = {"branch": rule["pattern"]}
    for field, translate in PROTECTION_FIELD_TRANSLATORS.items():
        value = translate(rule)
        if value is not None:
            config[field] = value

    # Nothing managed on this rule -> don't track it.
    if len(config) == 1:
        return {}

    return config


def generate_yaml_config(repos_config: Dict) -> str:
    """Generate YAML configuration file content."""
    config = {
        "github_organization": GITHUB_ORG,
        "repositories": []
    }
    
    for repo_name in sorted(repos_config.keys()):
        repo_data = {
            "name": repo_name,
            "branches": []
        }
        
        # Add branch protection configurations (sorted by pattern for stable,
        # diff-friendly output).
        for branch_config in sorted(repos_config[repo_name],
                                    key=lambda c: c["branch"]):
            if branch_config:  # Only add if there's actual protection config
                repo_data["branches"].append(branch_config)
        
        config["repositories"].append(repo_data)
    
    return yaml.dump(config, default_flow_style=False, sort_keys=False)


def main():
    """Main execution function."""
    print("=== Gazebo Repository Protection Rules Generator ===\n")

    # Active (non-EOL) branches per repo, derived from the gazebodistro
    # collection files. Used to keep only the protection rules that actually
    # govern a branch we still care about.
    repos_with_branches = get_all_repositories_with_branches()

    print("\n=== Fetching branch protection rules ===\n")

    repos_config = {}
    total_rules = 0
    managed_rules = 0

    for repo_name in sorted(repos_with_branches.keys()):
        if not check_repo_exists(repo_name):
            print(f"Repository {repo_name} does not exist, skipping...")
            continue

        print(f"Processing {repo_name}...")
        repos_config[repo_name] = []

        active_branches = repos_with_branches[repo_name]
        rules = fetch_branch_protection_rules(repo_name)

        for rule in rules:
            total_rules += 1
            pattern = rule["pattern"]

            # Keep a rule only if its pattern matches at least one active
            # branch. EOL-only patterns (e.g. ign-common[0-2]) are dropped so
            # Terraform never manages protection for retired distros.
            if not any(fnmatch.fnmatchcase(b, pattern) for b in active_branches):
                print(f"  Rule '{pattern}' governs no active branch, skipping...")
                continue

            branch_config = rule_to_config(rule)
            if branch_config:
                repos_config[repo_name].append(branch_config)
                managed_rules += 1
                print(f"  Managing rule '{pattern}'")

    print("\n=== Generating YAML configuration ===\n")

    yaml_content = generate_yaml_config(repos_config)

    output_file = Path("gazebo-repos-config.yaml")
    output_file.write_text(yaml_content)

    print(f"✓ Generated {output_file}")
    print(f"✓ Processed {len(repos_config)} repositories")
    print(f"✓ Inspected {total_rules} branch protection rules")
    print(f"✓ Managing {managed_rules} rules (each matched an active branch)")

    print("\nConfiguration file generated successfully!")
    print("Next steps:")
    print(f"  1. Review the configuration: cat {output_file}")
    print(f"  2. Import + plan with Terraform:")
    print(f"       ./scripts/import-branch-protection.sh {output_file}")
    print(f"       terraform plan")


if __name__ == "__main__":
    main()
