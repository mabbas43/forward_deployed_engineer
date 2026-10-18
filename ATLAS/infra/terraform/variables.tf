variable "env" {
  type    = string
  default = "dev"
}

variable "region" {
  type    = string
  default = "eu-central-1"
  validation {
    # P6: EU data residency is a deploy-time invariant, not a convention.
    condition     = startswith(var.region, "eu-")
    error_message = "ATLAS must be deployed to an EU region (data residency policy)."
  }
}

variable "image" {
  type        = string
  description = "ECR image URI for the atlas container (one image, multiple services)."
}

variable "worker_min" {
  type    = number
  default = 1
}
variable "worker_max" {
  type    = number
  default = 10
}
variable "canary_weight" {
  type        = number
  default     = 10
  description = "% of traffic to the canary target group"
}
