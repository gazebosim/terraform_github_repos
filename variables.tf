variable "github_organization" {
  description = "GitHub organization or user account name. Overrides value from config file if set."
  type        = string
  default     = "j-rivero"
}

variable "config_file_path" {
  description = "Path to the YAML configuration file containing repository and branch protection settings"
  type        = string
  default     = "gazebo-repos-config.yaml"
}

# Legacy variables kept for backward compatibility
# These are now loaded from the YAML config file by default
