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

   For Gazebo repositories, this will generate the `gazebo-repos-config.yaml` for all the collections in gazebodistro.
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
           enforce_admins: false
           required_linear_history: true
           required_status_checks:
             strict: true
             contexts:
               - ci/test
               - ci/lint
           required_pull_request_reviews:
             dismiss_stale_reviews: true
             required_approving_review_count: 1
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
        enforce_admins: false
        require_signed_commits: false
        required_linear_history: false
        require_conversation_resolution: false
        
        required_status_checks:   # Optional
          strict: true
          contexts:
            - DCO
            - CI-test
        
        required_pull_request_reviews:  # Optional
          dismiss_stale_reviews: false
          require_code_owner_reviews: false
          required_approving_review_count: 1
          require_last_push_approval: false
```

### Multiple Branches

You can protect multiple branches per repository:

```yaml
repositories:
  - name: gz-sim
    branches:
      - branch: main
        enforce_admins: false
        # ... protection rules ...
      - branch: gz-sim7
        enforce_admins: true
        # ... different protection rules ...
      - branch: gz-sim8
        enforce_admins: true
        # ... different protection rules ...
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
    description: Gazebo gz-common
    visibility: public
    branches:
      - branch: main
        enforce_admins: false
        required_status_checks:
          strict: true
          contexts:
            - DCO
            - gz_common-ci-pr_any-homebrew-amd64
```

### Automatic Updates

The Python script automatically:
1. Fetches all `collection-*.yaml` files from gazebodistro
2. Extracts all `gz-*` and `sdformat` repositories with their branch versions
3. Retrieves current branch protection rules from each repository branch
4. Generates `gazebo-repos-config.yaml` with the complete configuration

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

## License

MIT
