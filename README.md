# GitHub Repository Management with Terraform

This Terraform project manages GitHub repositories and their branch protection rules using the GitHub provider.

## Features

- Create and manage GitHub repositories
- Configure branch protection rules
- Customize repository settings (issues, projects, wiki, etc.)
- Configure merge strategies and auto-merge options
- Set up vulnerability alerts and topics

## Prerequisites

- [Terraform](https://www.terraform.io/downloads.html) >= 1.0
- GitHub account with appropriate permissions
- GitHub Personal Access Token with `repo` and `admin:org` scopes

## Important: Managing Existing vs New Repositories

**By default, this configuration manages EXISTING repositories** (read-only reference). It only manages:
- ✅ Branch protection rules
- ✅ Reading repository information

**It does NOT:**
- ❌ Create new repositories
- ❌ Modify repository settings (description, visibility, etc.)
- ❌ Delete repositories

### For Existing Repositories (Default - Recommended)

The current setup uses `data.github_repository` which:
- References existing repositories without managing them
- Only manages branch protection rules
- Safe for production use - won't accidentally modify/delete repos

### For Full Repository Management (Advanced)

If you want Terraform to fully manage repositories:
1. Uncomment the `github_repository` resource in `main.tf`
2. Import existing repositories: `./scripts/import-repositories.sh gazebo-repos-config.yaml`
3. Update `branch_protection.tf` and `outputs.tf` to use `github_repository.repos` instead of `data.github_repository.repos`
4. Terraform will then manage all repository settings

**⚠️ Warning**: Full management means Terraform could modify or delete repositories if misconfigured!

## Setup

1. **Create a GitHub Personal Access Token**

   **Option A: Fine-Grained Personal Access Token (Recommended)**
   
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
       - Repository permissions → **Metadata**: Read-only (automatically included)
   - Generate and copy the token (format: `github_pat_...`)

   **Option B: Classic Personal Access Token**
   
   - Go to GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
   - Generate new token with:
     - `repo` scope (required for branch protection)
     - `admin:org` scope (if managing org repositories)
   - Save the token securely (format: `ghp_...`)

2. **Set environment variable**
   ```bash
   export GITHUB_TOKEN="your_github_token"
   ```

3. **Generate or create a configuration file**

   For Gazebo repositories:
   ```bash
   ./scripts/update-gazebo-repos.sh
   ```

   Or manually create `gazebo-repos-config.yaml`:
   ```yaml
   github_organization: gazebosim
   repositories:
     - name: my-repo
       description: My repository
       visibility: public
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

1. **Initialize Terraform**
   ```bash
   terraform init
   ```

2. **Review the plan**
   ```bash
   terraform plan
   ```

3. **Apply the configuration**
   ```bash
   terraform apply
   ```

4. **Destroy resources (when needed)**
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
    description: Gazebo gz-common # Repository description
    visibility: public            # public or private
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
    description: Gazebo gz-sim
    visibility: public
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

## Variables

| Name | Description | Type | Required | Default |
|------|-------------|------|----------|------|
| `config_file_path` | Path to YAML configuration file | string | No | `gazebo-repos-config.yaml` |
| `github_organization` | GitHub org (overrides config file) | string | No | From config file |

## Outputs

| Name | Description |
|------|-------------|
| `repository_ids` | Map of repository names to their IDs |
| `repository_full_names` | Map of repository names to their full names |
| `repository_urls` | Map of repository names to their HTML URLs |
| `repository_ssh_clone_urls` | Map of repository names to their SSH clone URLs |
| `repository_http_clone_urls` | Map of repository names to their HTTP clone URLs |

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

### GitHub Actions Workflow

The repository includes a workflow (`.github/workflows/update-gazebo-config.yml`) that:
- Runs daily at 2 AM UTC (configurable via cron schedule)
- Can be triggered manually via workflow_dispatch
- Automatically creates a pull request when changes are detected
- Labels PRs as `automated` and `configuration`

This ensures your Terraform configuration stays synchronized with the gazebodistro collection files and current protection rules.

## License

MIT
