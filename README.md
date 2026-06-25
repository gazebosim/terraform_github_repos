# GitHub Branch Protection Management with Terraform

This Terraform project manages GitHub repositories and their branch protection rules using the GitHub provider.

## Features

- Configure branch protection rules

## Prerequisites

- [Terraform](https://www.terraform.io/downloads.html) >= 1.0
- GitHub account with appropriate permissions
- GitHub Personal Access Token with `repo` and `admin:org` scopes

## Important: only branch protection modifications

**By default, this configuration manages EXISTING repositories** (read-only reference). It only manages:
- ✅ Branch protection rules
- ✅ Reading repository information

**It does NOT:**
- ❌ Create new repositories
- ❌ Modify repository settings (description, visibility, etc.)
- ❌ Delete repositories

**Only `required_status_checks` is managed.** The generated config keeps just
the `required_status_checks` block per branch. Every other branch-protection
setting (PR reviews, `enforce_admins`, signed commits, linear history, push
restrictions, etc.) is intentionally **left unchanged** on GitHub via
`lifecycle { ignore_changes }` in `branch_protection.tf` — even if you add those
fields to the YAML, Terraform will not touch them.

To manage an additional field, register a translator for it in
`PROTECTION_FIELD_TRANSLATORS` (`scripts/generate_gazebo_config.py`) and remove
it from the `ignore_changes` list in `branch_protection.tf`. Those two are
complements: every field the generator does not emit must be in `ignore_changes`
(Terraform's `ignore_changes` only accepts a literal list, so it is maintained
by hand).

## Setup

1. **Create a GitHub Personal Access Token**

   **Option A: Fine-Grained Personal Access Token**
   
   Fine-grained tokens provide better security with granular permissions:
   
   - Go to GitHub Settings → Developer settings → Personal access tokens → **Fine-grained tokens**
   - Click "Generate new token"
   - Configure:
     - **Token name**: `terraform-github-repos`
     - **Expiration**: Set as needed (90 days, 1 year, etc.)
     - **Repository access**: 
       - Select "Public Repositories (read-only)" for reading gazebodistro
       - OR select "All repositories" if managing org-wide
       - OR select specific repositories you want to manage
     - **Permissions**:
       - Repository permissions → **Administration**: Read and write (for branch protection)
       - Repository permissions → **Contents**: Read-only (for reading configs)
   - Generate and copy the token (format: `github_pat_...`)

2. **Set environment variable**
   ```bash
   export GITHUB_TOKEN="your_github_token"
   ```   

3. **Generate or create a configuration file**

   For Gazebo repositories, this will generate the `gazebo-repos-config.yaml` for the active collections in gazebodistro (those listed in release-tools' `gz-collections.yaml`).
   ```bash
   ./scripts/update-gazebo-repos.sh
   ```   

   Or manually create `gazebo-repos-config.yaml`:
   ```yaml
   github_organization: gazebosim
   repositories:
     - name: my-repo
       branches:
         - branch: main
           required_status_checks:
             strict: true
             contexts:
               - ci/test
               - ci/lint
   ```

## Usage

The workflow will use `gazebo-repos-config.yaml` file as input for the configurations and
terraform for syncing the configurations in that yaml file into the github repositories:

1. **Initialize Terraform**
   ```bash
   terraform init
   ```

2. **Import existing branch protection rules** (first time only)
   ```bash
   ./scripts/import-branch-protection.sh gazebo-repos-config.yaml
   ```

3. **Review the plan** (no changes done in this step)
   ```bash
   terraform plan
   ```

4. **Apply the configuration**
   ```bash
   terraform apply
   ```

5. **To remove branch protection** (if needed)
   ```bash
   terraform destroy
   ```

## Configuration File Structure

### YAML Configuration

The `gazebo-repos-config.yaml` file contains:

```yaml
github_organization: gazebosim  # GitHub org or username

repositories:
  - name: gz-common              # Repository name
    branches:                     # List of branches to protect
      - branch: main              # Branch name/pattern
        required_status_checks:   # The only managed field
          strict: true
          contexts:
            - DCO
            - CI-test
```

### Multiple Branches

You can protect multiple branches per repository:

```yaml
repositories:
  - name: gz-sim
    branches:
      - branch: main
        required_status_checks:
          strict: true
          contexts:
            - DCO
      - branch: gz-sim7
        required_status_checks:
          strict: true
          contexts:
            - gz_sim-ci-pr_any-jammy-amd64
      - branch: gz-sim8
        required_status_checks:
          strict: true
          contexts:
            - gz_sim-ci-pr_any-noble-amd64
```

## Gazebo Repositories Automation

This repository includes automation to manage all Gazebo repositories from the [gazebo-tooling/gazebodistro](https://github.com/gazebo-tooling/gazebodistro) collection files.

### How It Works

1. **Configuration Generation**: A Python script reads collection files from gazebodistro and generates a YAML configuration
2. **Terraform Deployment**: Terraform reads the YAML file and applies repository and branch protection settings

### YAML Configuration Format

The generated `gazebo-repos-config.yaml` contains:
- GitHub organization name
- List of repositories with their branches
- Branch protection rules for each branch

```yaml
github_organization: gazebosim
repositories:
  - name: gz-common
    branches:
      - branch: main
        required_status_checks:
          strict: true
          contexts:
            - DCO
            - gz_common-ci-pr_any-homebrew-amd64
```

### Automatic Updates

The Python script automatically:
1. Fetches the active collections from release-tools' [`gz-collections.yaml`](https://github.com/gazebo-tooling/release-tools/blob/master/jenkins-scripts/dsl/gz-collections.yaml) and parses only the matching `collection-<name>.yaml` files from gazebodistro
2. Extracts all `gz-*` and `sdformat` repositories with their branch versions
3. Retrieves current branch protection rules from each repository branch
4. Filters each branch down to the fields registered in
   `PROTECTION_FIELD_TRANSLATORS` (currently just `required_status_checks`) and
   drops branches that have none of them
5. Generates `gazebo-repos-config.yaml` with the filtered configuration

### Manual Generation

Run the update script locally:

```bash
./scripts/update-gazebo-repos.sh
```

Or run the Python script directly:

```bash
pip install -r requirements.txt
python scripts/generate_gazebo_config.py
```
