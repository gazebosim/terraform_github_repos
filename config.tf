locals {
  # Load the YAML configuration file
  config_file = fileexists(var.config_file_path) ? file(var.config_file_path) : "{}"
  config      = yamldecode(local.config_file)

  # Extract repository names (only used for data source lookup)
  repositories = {
    for repo in lookup(local.config, "repositories", []) :
    repo.name => {}
  }

  # Transform branch protection rules from YAML into flat map
  # Key format: "repo_name:branch_name"
  branch_protections = merge([
    for repo in lookup(local.config, "repositories", []) : {
      for branch in lookup(repo, "branches", []) :
      "${repo.name}:${branch.branch}" => merge(
        {
          repository_name = repo.name
          pattern         = branch.branch
        },
        branch
      )
    }
  ]...)
}
