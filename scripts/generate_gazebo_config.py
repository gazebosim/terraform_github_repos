#!/usr/bin/env python3
"""
Fetch Gazebo repositories from gazebodistro collection files and generate
a YAML configuration with their branches and branch protection rules.
"""

import json
import subprocess
import sys
import yaml
from pathlib import Path
from typing import Dict, List, Set, Tuple

GAZEBODISTRO_REPO = "gazebo-tooling/gazebodistro"
GAZEBODISTRO_BRANCH = "master"
GITHUB_ORG = "gazebosim"


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
    """Fetch list of collection-*.yaml files from gazebodistro."""
    print("Fetching collection files from gazebodistro...")
    
    # List files in the root directory
    output = run_command([
        "gh", "api",
        f"repos/{GAZEBODISTRO_REPO}/contents",
        "-q", ".[].name"
    ])
    
    files = output.split('\n')
    collection_files = [f for f in files if f.startswith('collection-') and f.endswith('.yaml')]
    
    print(f"Found {len(collection_files)} collection files: {', '.join(collection_files)}")
    return collection_files


def fetch_file_content(filename: str) -> str:
    """Fetch content of a file from gazebodistro."""
    output = run_command([
        "gh", "api",
        f"repos/{GAZEBODISTRO_REPO}/contents/{filename}",
        "-q", ".content"
    ])
    
    # Decode base64 content
    import base64
    return base64.b64decode(output).decode('utf-8')


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
    """Convert GitHub API protection response to configuration dict."""
    if not protection:
        return {}
    
    config = {
        "branch": branch,
        "enforce_admins": protection.get("enforce_admins", {}).get("enabled", False),
        "require_signed_commits": protection.get("required_signatures", {}).get("enabled", False),
        "required_linear_history": protection.get("required_linear_history", {}).get("enabled", False),
        "require_conversation_resolution": protection.get("required_conversation_resolution", {}).get("enabled", False),
    }
    
    # Required status checks
    if "required_status_checks" in protection and protection["required_status_checks"]:
        status_checks = protection["required_status_checks"]
        config["required_status_checks"] = {
            "strict": status_checks.get("strict", False),
            "contexts": status_checks.get("contexts", [])
        }
    
    # Required pull request reviews
    if "required_pull_request_reviews" in protection and protection["required_pull_request_reviews"]:
        reviews = protection["required_pull_request_reviews"]
        config["required_pull_request_reviews"] = {
            "dismiss_stale_reviews": reviews.get("dismiss_stale_reviews", False),
            "require_code_owner_reviews": reviews.get("require_code_owner_reviews", False),
            "required_approving_review_count": reviews.get("required_approving_review_count", 1),
            "require_last_push_approval": reviews.get("require_last_push_approval", False),
        }
    
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
