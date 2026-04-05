# ─────────────────────────────────────────────────────────────────────────────
# EC2 Instance — DeployCtrl Terraform Module
# Parameters are driven by the ec2_instance.json template definition.
# ─────────────────────────────────────────────────────────────────────────────

# ── Variables ─────────────────────────────────────────────────────────────────

variable "instance_type" {
  description = "EC2 instance type (e.g. t3.small, t3.medium)"
  type        = string
  default     = "t3.small"

  validation {
    condition     = contains(["t2.micro", "t3.small", "t3.medium", "t3.large", "t3.xlarge"], var.instance_type)
    error_message = "instance_type must be one of: t2.micro, t3.small, t3.medium, t3.large, t3.xlarge."
  }
}

variable "disk_type" {
  description = "EBS root volume type (gp3, gp2, io1)"
  type        = string
  default     = "gp3"

  validation {
    condition     = contains(["gp2", "gp3", "io1"], var.disk_type)
    error_message = "disk_type must be one of: gp2, gp3, io1."
  }
}

variable "disk_size_gb" {
  description = "EBS root volume size in GB"
  type        = number
  default     = 20

  validation {
    condition     = contains([20, 50, 100, 200], var.disk_size_gb)
    error_message = "disk_size_gb must be one of: 20, 50, 100, 200."
  }
}

variable "os" {
  description = "Operating system: amazon-linux-2 | ubuntu-22.04 | windows-2022"
  type        = string
  default     = "amazon-linux-2"

  validation {
    condition     = contains(["amazon-linux-2", "ubuntu-22.04", "windows-2022"], var.os)
    error_message = "os must be one of: amazon-linux-2, ubuntu-22.04, windows-2022."
  }
}

variable "inbound_ports" {
  description = "List of TCP ports to allow inbound (e.g. [\"22\", \"80\", \"443\"])"
  type        = list(string)
  default     = ["22", "80", "443"]
}

variable "outbound_ports" {
  description = "List of ports to allow outbound. Use [\"all\"] for unrestricted egress."
  type        = list(string)
  default     = ["all"]
}

variable "protocol" {
  description = "IP protocol for security group rules: tcp | udp | all"
  type        = string
  default     = "tcp"

  validation {
    condition     = contains(["tcp", "udp", "all"], var.protocol)
    error_message = "protocol must be one of: tcp, udp, all."
  }
}

# ── AMI lookup ────────────────────────────────────────────────────────────────

locals {
  ami_map = {
    "amazon-linux-2" = {
      filter = "amzn2-ami-hvm-*-x86_64-gp2"
      owners = ["amazon"]
    }
    "ubuntu-22.04" = {
      filter = "ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"
      owners = ["099720109477"] # Canonical
    }
    "windows-2022" = {
      filter = "Windows_Server-2022-English-Full-Base-*"
      owners = ["amazon"]
    }
  }

  selected_ami = local.ami_map[var.os]

  # Normalise protocol: "all" → "-1" for AWS API
  sg_protocol = var.protocol == "all" ? "-1" : var.protocol
}

data "aws_ami" "selected" {
  most_recent = true
  owners      = local.selected_ami.owners

  filter {
    name   = "name"
    values = [local.selected_ami.filter]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# ── Networking ────────────────────────────────────────────────────────────────

data "aws_vpc" "default" {
  default = true
}

# ── Security Group ────────────────────────────────────────────────────────────

resource "aws_security_group" "instance" {
  name        = "${var.name_prefix}-ec2-sg"
  description = "Managed by DeployCtrl — EC2 instance security group"
  vpc_id      = data.aws_vpc.default.id

  # Inbound rules — one rule per port in var.inbound_ports
  dynamic "ingress" {
    for_each = var.inbound_ports
    content {
      description = "Inbound ${ingress.value}"
      from_port   = local.sg_protocol == "-1" ? 0 : (ingress.value == "all" ? 0 : tonumber(ingress.value))
      to_port     = local.sg_protocol == "-1" ? 0 : (ingress.value == "all" ? 65535 : tonumber(ingress.value))
      protocol    = local.sg_protocol
      cidr_blocks = ["0.0.0.0/0"]
    }
  }

  # Outbound rules — one rule per port in var.outbound_ports
  dynamic "egress" {
    for_each = var.outbound_ports
    content {
      description = "Outbound ${egress.value}"
      from_port   = egress.value == "all" ? 0 : tonumber(egress.value)
      to_port     = egress.value == "all" ? 0 : tonumber(egress.value)
      protocol    = egress.value == "all" ? "-1" : local.sg_protocol
      cidr_blocks = ["0.0.0.0/0"]
    }
  }

  tags = {
    Name        = "${var.name_prefix}-ec2-sg"
    ManagedBy   = "DeployCtrl"
  }
}

# ── EC2 Instance ──────────────────────────────────────────────────────────────

resource "aws_instance" "main" {
  ami                    = data.aws_ami.selected.id
  instance_type          = var.instance_type
  vpc_security_group_ids = [aws_security_group.instance.id]

  root_block_device {
    volume_type           = var.disk_type
    volume_size           = var.disk_size_gb
    delete_on_termination = true
    encrypted             = true
  }

  tags = {
    Name      = "${var.name_prefix}-ec2"
    OS        = var.os
    ManagedBy = "DeployCtrl"
  }
}

# ── Outputs ───────────────────────────────────────────────────────────────────

output "instance_id" {
  description = "EC2 instance ID"
  value       = aws_instance.main.id
}

output "public_ip" {
  description = "Public IP address (empty if no public IP assigned)"
  value       = aws_instance.main.public_ip
}

output "private_ip" {
  description = "Private IP address"
  value       = aws_instance.main.private_ip
}

output "ami_id" {
  description = "AMI ID used for the instance"
  value       = data.aws_ami.selected.id
}

output "security_group_id" {
  description = "Security group ID"
  value       = aws_security_group.instance.id
}
