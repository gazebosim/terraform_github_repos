output "repository_ids" {
  description = "Map of repository names to their IDs"
  value       = { for k, v in data.github_repository.repos : k => v.repo_id }
}

output "repository_full_names" {
  description = "Map of repository names to their full names"
  value       = { for k, v in data.github_repository.repos : k => v.full_name }
}

output "repository_urls" {
  description = "Map of repository names to their HTML URLs"
  value       = { for k, v in data.github_repository.repos : k => v.html_url }
}

output "repository_ssh_clone_urls" {
  description = "Map of repository names to their SSH clone URLs"
  value       = { for k, v in data.github_repository.repos : k => v.ssh_clone_url }
}

output "repository_http_clone_urls" {
  description = "Map of repository names to their HTTP clone URLs"
  value       = { for k, v in data.github_repository.repos : k => v.http_clone_url }
}

output "protected_branches" {
  description = "Map of protected branches by repository"
  value = {
    for k, v in local.branch_protections :
    k => {
      repository = v.repository_name
      branch     = v.pattern
    }
  }
}
