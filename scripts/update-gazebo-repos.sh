#!/bin/bash
# Generate Gazebo repository configurations locally

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

echo "Installing Python dependencies..."
python3 -m venv .venv
source .venv/bin/activate
pip install -q -r requirements.txt

echo ""
echo "Generating Gazebo repository configurations..."
python scripts/generate_gazebo_config.py

echo ""
echo "Done! The configuration has been saved to gazebo-repos-config.yaml"
echo ""
echo "Review the changes:"
echo "  git diff gazebo-repos-config.yaml"
echo ""
echo "To apply the configuration:"
echo "  terraform plan"
echo "  terraform apply"
