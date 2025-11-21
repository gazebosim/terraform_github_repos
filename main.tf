terraform {
  required_version = ">= 1.0"

  required_providers {
    github = {
      source  = "integrations/github"
      version = "~> 6.0"
    }
  }
}

provider "github" {
  # Token should be provided via GITHUB_TOKEN environment variable
  # or using the token parameter
  owner = var.github_organization != "" ? var.github_organization : lookup(local.config, "github_organization", "")
}

# Data source to reference existing repositories (read-only)
# This only reads repository information and does not manage repository settings
data "github_repository" "repos" {
  for_each = local.repositories

  name = each.key
}
