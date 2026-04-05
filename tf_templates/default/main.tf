# ─────────────────────────────────────────────────────────────────────────────
# DeployCtrl — default Terraform configuration
#
# This file is included in every deployment workspace.
# DeployCtrl substitutes {BASE_URL}, {REQ_ID}, and {SECRET} at run time
# before calling `terraform init`.
# ─────────────────────────────────────────────────────────────────────────────

terraform {
  required_version = ">= 1.3.0"

  backend "http" {
    address        = "{BASE_URL}/api/terraform/state/{REQ_ID}/"
    lock_address   = "{BASE_URL}/api/terraform/state/{REQ_ID}/lock/"
    unlock_address = "{BASE_URL}/api/terraform/state/{REQ_ID}/lock/"
    lock_method    = "POST"
    unlock_method  = "DELETE"
    username       = "deployctrl"
    password       = "{SECRET}"
  }

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  description = "AWS region for this deployment"
  type        = string
}

variable "name_prefix" {
  description = "Prefix applied to all resource names and tags"
  type        = string
  default     = "deployctrl"
}
