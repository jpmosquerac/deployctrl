# ─────────────────────────────────────────────────────────────────────────────
# S3 Bucket — DeployCtrl Terraform Module
# Parameters are driven by the s3_bucket.json template definition.
# ─────────────────────────────────────────────────────────────────────────────

# ── Variables ─────────────────────────────────────────────────────────────────

variable "bucket_name" {
  description = "Globally unique S3 bucket name"
  type        = string
}

variable "storage_class" {
  description = "Default storage class for objects (STANDARD | INTELLIGENT_TIERING | STANDARD_IA | GLACIER_IR | GLACIER)"
  type        = string
  default     = "STANDARD"

  validation {
    condition     = contains(["STANDARD", "INTELLIGENT_TIERING", "STANDARD_IA", "GLACIER_IR", "GLACIER"], var.storage_class)
    error_message = "storage_class must be one of: STANDARD, INTELLIGENT_TIERING, STANDARD_IA, GLACIER_IR, GLACIER."
  }
}

variable "versioning" {
  description = "Versioning state: Enabled or Suspended"
  type        = string
  default     = "Enabled"

  validation {
    condition     = contains(["Enabled", "Suspended"], var.versioning)
    error_message = "versioning must be Enabled or Suspended."
  }
}

variable "encryption" {
  description = "Server-side encryption algorithm: AES256 (SSE-S3) or aws:kms (SSE-KMS)"
  type        = string
  default     = "AES256"

  validation {
    condition     = contains(["AES256", "aws:kms"], var.encryption)
    error_message = "encryption must be AES256 or aws:kms."
  }
}

variable "kms_key_id" {
  description = "KMS key ARN to use when encryption = aws:kms. Leave empty to use the AWS-managed key."
  type        = string
  default     = ""
}

variable "access_control" {
  description = "Access control preset: private or public-read"
  type        = string
  default     = "private"

  validation {
    condition     = contains(["private", "public-read"], var.access_control)
    error_message = "access_control must be private or public-read."
  }
}

variable "lifecycle_days" {
  description = "Delete objects after N days. Set to 0 to disable the lifecycle rule."
  type        = number
  default     = 0

  validation {
    condition     = var.lifecycle_days >= 0
    error_message = "lifecycle_days must be 0 or greater."
  }
}

# ── Locals ────────────────────────────────────────────────────────────────────

locals {
  is_public          = var.access_control == "public-read"
  has_lifecycle      = var.lifecycle_days > 0
  kms_key_id        = var.kms_key_id != "" ? var.kms_key_id : null
}

# ── Bucket ────────────────────────────────────────────────────────────────────

resource "aws_s3_bucket" "main" {
  bucket = var.bucket_name

  tags = {
    Name        = var.bucket_name
    ManagedBy   = "DeployCtrl"
    Environment = var.name_prefix
  }
}

# ── Versioning ────────────────────────────────────────────────────────────────

resource "aws_s3_bucket_versioning" "main" {
  bucket = aws_s3_bucket.main.id

  versioning_configuration {
    status = var.versioning
  }
}

# ── Encryption ────────────────────────────────────────────────────────────────

resource "aws_s3_bucket_server_side_encryption_configuration" "main" {
  bucket = aws_s3_bucket.main.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.encryption
      kms_master_key_id = local.kms_key_id
    }
    bucket_key_enabled = var.encryption == "aws:kms"
  }
}

# ── Public access block ───────────────────────────────────────────────────────

resource "aws_s3_bucket_public_access_block" "main" {
  bucket = aws_s3_bucket.main.id

  block_public_acls       = !local.is_public
  block_public_policy     = !local.is_public
  ignore_public_acls      = !local.is_public
  restrict_public_buckets = !local.is_public
}

# ── Ownership controls (required before setting ACL) ─────────────────────────

resource "aws_s3_bucket_ownership_controls" "main" {
  bucket = aws_s3_bucket.main.id

  rule {
    object_ownership = local.is_public ? "BucketOwnerPreferred" : "BucketOwnerEnforced"
  }

  depends_on = [aws_s3_bucket_public_access_block.main]
}

# ── ACL (only when public-read) ───────────────────────────────────────────────

resource "aws_s3_bucket_acl" "main" {
  count = local.is_public ? 1 : 0

  bucket = aws_s3_bucket.main.id
  acl    = "public-read"

  depends_on = [aws_s3_bucket_ownership_controls.main]
}

# ── Lifecycle rule ────────────────────────────────────────────────────────────

resource "aws_s3_bucket_lifecycle_configuration" "main" {
  count = local.has_lifecycle ? 1 : 0

  bucket = aws_s3_bucket.main.id

  rule {
    id     = "auto-expire"
    status = "Enabled"

    expiration {
      days = var.lifecycle_days
    }

    noncurrent_version_expiration {
      noncurrent_days = var.lifecycle_days
    }
  }
}

# ── Intelligent Tiering configuration ─────────────────────────────────────────

resource "aws_s3_bucket_intelligent_tiering_configuration" "main" {
  count = var.storage_class == "INTELLIGENT_TIERING" ? 1 : 0

  bucket = aws_s3_bucket.main.id
  name   = "EntireBucket"

  tiering {
    access_tier = "DEEP_ARCHIVE_ACCESS"
    days        = 180
  }

  tiering {
    access_tier = "ARCHIVE_ACCESS"
    days        = 90
  }
}

# ── Outputs ───────────────────────────────────────────────────────────────────

output "bucket_id" {
  description = "S3 bucket name"
  value       = aws_s3_bucket.main.id
}

output "bucket_arn" {
  description = "S3 bucket ARN"
  value       = aws_s3_bucket.main.arn
}

output "bucket_regional_domain" {
  description = "Regional domain name for the bucket"
  value       = aws_s3_bucket.main.bucket_regional_domain_name
}

output "versioning_status" {
  description = "Current versioning state"
  value       = var.versioning
}
