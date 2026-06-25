#!/usr/bin/env python3
"""
Fetch Gazebo repositories from gazebodistro collection files and generate
a YAML configuration with their branches and branch protection rules.
"""

import base64
import json
import subprocess
import sys
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


def _translate_status_checks(protection: Dict):
    """API -> config for required_status_checks; None if not set."""
    status_checks = protection.get("required_status_checks")
    if not status_checks:
        return None
    return {
        "strict": status_checks.get("strict", False),
        "contexts": status_checks.get("contexts", []),
    }


# Branch-protection fields to keep in the generated config, mapped to their
# GitHub-API -> config translator. The keys are the allowlist: anything not
# listed here is discarded so Terraform leaves it unchanged (see lifecycle
# ignore_changes in branch_protection.tf). To manage another field, add a
# translator entry here AND remove that field from the ignore_changes list.
PROTECTION_FIELD_TRANSLATORS = {
    "required_status_checks": _translate_status_checks,
}


def run_command(cmd: List[str], check=True) -> str:
    """Run a shell command and return its output."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running command {' '.join(cmd)}: {e.stderr}", file=sys.stderr)
        if check:
            raise
        return ""


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
    """Check if a repository exists in the GitHub organization."""
    result = run_command([
        "gh", "api",
        f"repos/{GITHUB_ORG}/{repo_name}",
        "-q", ".name"
    ], check=False)
    return bool(result)


def check_branch_exists(repo_name: str, branch: str) -> bool:
    """Check if a branch exists in a repository."""
    result = run_command([
        "gh", "api",
        f"repos/{GITHUB_ORG}/{repo_name}/branches/{branch}",
        "-q", ".name"
    ], check=False)
    return bool(result)


def get_branch_protection(repo_name: str, branch: str) -> Dict:
    """Fetch branch protection rules for a repository branch."""
    print(f"  Fetching protection rules for {repo_name}:{branch}...")
    
    output = run_command([
        "gh", "api",
        f"repos/{GITHUB_ORG}/{repo_name}/branches/{branch}/protection"
    ], check=False)
    
    if not output:
        print(f"    No protection rules found")
        return {}
    
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        print(f"    Failed to parse protection rules")
        return {}


def protection_to_config(protection: Dict, branch: str) -> Dict:
    """Convert GitHub API protection response to configuration dict.

    Only the fields registered in PROTECTION_FIELD_TRANSLATORS are kept; every
    other protection setting fetched from GitHub is discarded so Terraform
    leaves it unchanged.
    """
    if not protection:
        return {}

    config = {"branch": branch}
    for field, translate in PROTECTION_FIELD_TRANSLATORS.items():
        value = translate(protection)
        if value is not None:
            config[field] = value

    # Nothing interesting on this branch -> don't manage it.
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
        
        # Add branch protection configurations
        for branch_config in repos_config[repo_name]:
            if branch_config:  # Only add if there's actual protection config
                repo_data["branches"].append(branch_config)
        
        config["repositories"].append(repo_data)
    
    return yaml.dump(config, default_flow_style=False, sort_keys=False)


def main():
    """Main execution function."""
    print("=== Gazebo Repository Protection Rules Generator ===\n")

    # Get all repositories with their branches from collection files
    repos_with_branches = get_all_repositories_with_branches()
    
    print("\n=== Fetching branch protection rules ===\n")
    
    repos_config = {}
    total_branches = 0
    protected_branches = 0
    
    for repo_name in sorted(repos_with_branches.keys()):
        if not check_repo_exists(repo_name):
            print(f"Repository {repo_name} does not exist, skipping...")
            continue
        
        print(f"Processing {repo_name}...")
        repos_config[repo_name] = []
        
        for branch in sorted(repos_with_branches[repo_name]):
            total_branches += 1
            
            # Check if branch exists
            if not check_branch_exists(repo_name, branch):
                print(f"  Branch {branch} does not exist, skipping...")
                continue
            
            # Fetch protection rules
            protection = get_branch_protection(repo_name, branch)
            branch_config = protection_to_config(protection, branch)
            
            if branch_config:
                repos_config[repo_name].append(branch_config)
                protected_branches += 1
    
    print("\n=== Generating YAML configuration ===\n")
    
    yaml_content = generate_yaml_config(repos_config)
    
    output_file = Path("gazebo-repos-config.yaml")
    output_file.write_text(yaml_content)
    
    print(f"✓ Generated {output_file}")
    print(f"✓ Processed {len(repos_config)} repositories")
    print(f"✓ Checked {total_branches} branches")
    print(f"✓ Found {protected_branches} branches with protection rules")
    
    print("\nConfiguration file generated successfully!")
    print("Next steps:")
    print(f"  1. Review the configuration: cat {output_file}")
    print(f"  2. Apply with Terraform: terraform plan")
    print(f"                           terraform apply")


if __name__ == "__main__":
    main()
