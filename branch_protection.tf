resource "github_branch_protection" "protection" {
  for_each = local.branch_protections

  # Use data source (for existing repos) instead of resource
  repository_id = data.github_repository.repos[each.value.repository_name].node_id
  pattern       = each.value.pattern

  enforce_admins                  = lookup(each.value, "enforce_admins", false)
  require_signed_commits          = lookup(each.value, "require_signed_commits", false)
  required_linear_history         = lookup(each.value, "required_linear_history", false)
  require_conversation_resolution = lookup(each.value, "require_conversation_resolution", false)

  dynamic "required_status_checks" {
    for_each = lookup(each.value, "required_status_checks", null) != null ? [each.value.required_status_checks] : []
    content {
      strict   = lookup(required_status_checks.value, "strict", false)
      contexts = lookup(required_status_checks.value, "contexts", [])
    }
  }

  dynamic "required_pull_request_reviews" {
    for_each = lookup(each.value, "required_pull_request_reviews", null) != null ? [each.value.required_pull_request_reviews] : []
    content {
      dismiss_stale_reviews           = lookup(required_pull_request_reviews.value, "dismiss_stale_reviews", false)
      require_code_owner_reviews      = lookup(required_pull_request_reviews.value, "require_code_owner_reviews", false)
      required_approving_review_count = lookup(required_pull_request_reviews.value, "required_approving_review_count", 1)
      require_last_push_approval      = lookup(required_pull_request_reviews.value, "require_last_push_approval", false)
      restrict_dismissals             = lookup(required_pull_request_reviews.value, "restrict_dismissals", false)
      dismissal_restrictions          = lookup(required_pull_request_reviews.value, "dismissal_restrictions", [])
    }
  }

  dynamic "restrict_pushes" {
    for_each = lookup(each.value, "restrict_pushes", null) != null ? [each.value.restrict_pushes] : []
    content {
      blocks_creations = lookup(restrict_pushes.value, "blocks_creations", false)
      push_allowances  = lookup(restrict_pushes.value, "push_allowances", [])
    }
  }

  force_push_bypassers = lookup(each.value, "force_push_bypassers", [])

  lifecycle {
    # Manage only required_status_checks; leave every other protection setting
    # as it currently exists on GitHub. Terraform's ignore_changes only accepts
    # a literal list, so this is hand-maintained. It must stay the complement of
    # the fields emitted by rule_to_config() in scripts/generate_gazebo_config.py:
    # every field that function does NOT emit belongs here.
    ignore_changes = [
      enforce_admins,
      require_signed_commits,
      required_linear_history,
      require_conversation_resolution,
      required_pull_request_reviews,
      restrict_pushes,
      force_push_bypassers,
    ]
  }
}
