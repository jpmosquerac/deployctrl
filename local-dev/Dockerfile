FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# System deps: build tools, git (for cloning repos), curl+unzip for terraform
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential git curl unzip \
    && TERRAFORM_VERSION=1.10.5 \
    && curl -fsSL "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_amd64.zip" \
         -o /tmp/terraform.zip \
    && unzip -q /tmp/terraform.zip -d /usr/local/bin/ \
    && rm /tmp/terraform.zip \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --noinput

EXPOSE 8000

CMD ["gunicorn", "deployctrl.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "2"]
