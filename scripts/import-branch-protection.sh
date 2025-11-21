#!/bin/bash
# Import existing branch protection rules into Terraform state

set -e

if [ "$#" -ne 1 ]; then
    echo "Usage: $0 <config-file.yaml>"
    echo ""
    echo "This script imports existing branch protection rules into Terraform state."
    echo "Run 'terraform init' before using this script."
    exit 1
fi

CONFIG_FILE="$1"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file '$CONFIG_FILE' not found"
    exit 1
fi

echo "=== Branch Protection Import Tool ==="
echo ""
echo "This script will import existing branch protection rules into Terraform state."
echo "Make sure you have:"
echo "  1. Run 'terraform init'"
echo "  2. Set GITHUB_TOKEN environment variable"
echo ""
read -p "Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 0
fi

# Extract repository names and branches from YAML config
python3 -c "
import yaml
import sys

with open('$CONFIG_FILE', 'r') as f:
    config = yaml.safe_load(f)
    
for repo in config.get('repositories', []):
    repo_name = repo['name']
    for branch_config in repo.get('branches', []):
        branch = branch_config['branch']
        # Terraform resource key format: repo:branch
        terraform_key = f'{repo_name}:{branch}'
        # GitHub import format: repo:branch
        github_id = f'{repo_name}:{branch}'
        print(f'{terraform_key}|{github_id}')
" | while IFS='|' read -r terraform_key github_id; do
    if [ -n "$terraform_key" ]; then
        echo ""
        echo "Importing branch protection: $terraform_key"
        terraform import "github_branch_protection.protection[\"$terraform_key\"]" "$github_id" || echo "  Warning: Failed to import $terraform_key (may not exist or already imported)"
    fi
done

echo ""
echo "Import complete! Run 'terraform plan' to verify."
echo "If some imports failed, those branches may not have protection rules yet."
