# PocketVectorDB Deployment Guide

Complete guide to deploying PocketVectorDB to production.

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Local Development](#local-development)
3. [Docker Deployment](#docker-deployment)
4. [Heroku Deployment](#heroku-deployment)
5. [AWS Deployment](#aws-deployment)
6. [Configuration](#configuration)
7. [Monitoring](#monitoring)
8. [Scaling](#scaling)

---

## Prerequisites

### System Requirements
- Python 3.8+
- 2GB RAM minimum
- 10GB disk space (for databases)
- Modern Linux/macOS/Windows

### External Services (Optional but Recommended)
- **Stripe** for payment processing (API keys at stripe.com)
- **AWS S3** for backups (IAM credentials)
- **SendGrid** or similar for email (SMTP credentials)
- **Sentry** for error tracking (DSN)

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/pocketvectordb.git
cd pocketvectordb

# Install dependencies
pip install -r requirements.txt

# Verify installation
python app.py --no-verify-deps --help
```

---

## Local Development

### Running All Services

```bash
# Start all services (API, Dashboard, Admin)
python app.py

# Output:
# API:       http://localhost:5000/health
# Dashboard: http://localhost:5001/login
# Admin:     http://localhost:5002/admin
```

### Running Single Service

Useful for development on specific service:

```bash
# Start only API server
python app.py --service api --api-port 8000

# Start only dashboard
python app.py --service dashboard --dashboard-port 8001

# Start only admin panel
python app.py --service admin --admin-port 8002
```

### Configuration

Create `.env` file in project root:

```bash
# Debug mode
DEBUG=true

# Ports
API_PORT=5000
DASHBOARD_PORT=5001
ADMIN_PORT=5002

# Storage
STORAGE_DIR=./databases

# Stripe (optional)
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_test_...

# Email (optional)
SMTP_HOST=smtp.gmail.com
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=noreply@pocketvectordb.com

# Session security
DASHBOARD_SECRET_KEY=your-secure-random-key
```

Load environment variables:
```bash
export $(cat .env | xargs)
```

---

## Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy application
COPY . .

# Create storage directory
RUN mkdir -p /app/databases

# Expose ports
EXPOSE 5000 5001 5002

# Start based on service argument
ENV SERVICE=all
CMD if [ "$SERVICE" = "all" ]; then \
      python app.py; \
    else \
      python app.py --service $SERVICE; \
    fi
```

### Docker Compose

```yaml
version: '3.8'

services:
  api:
    build: .
    ports:
      - "5000:5000"
    environment:
      SERVICE: api
      STRIPE_SECRET_KEY: ${STRIPE_SECRET_KEY}
      STORAGE_DIR: /data/databases
    volumes:
      - pocketvectordb_data:/data/databases
    restart: always

  dashboard:
    build: .
    ports:
      - "5001:5001"
    environment:
      SERVICE: dashboard
      STORAGE_DIR: /data/databases
    volumes:
      - pocketvectordb_data:/data/databases
    depends_on:
      - api
    restart: always

  admin:
    build: .
    ports:
      - "5002:5002"
    environment:
      SERVICE: admin
    depends_on:
      - api
    restart: always

volumes:
  pocketvectordb_data:
```

### Running with Docker Compose

```bash
# Build and start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

---

## Heroku Deployment

### Setup

```bash
# Install Heroku CLI
# https://devcenter.heroku.com/articles/heroku-cli

# Login
heroku login

# Create app
heroku create your-app-name

# Set buildpack
heroku buildpacks:set heroku/python
```

### Procfile

```
web: python app.py --api-port $PORT
dashboard: python app.py --service dashboard --dashboard-port $PORT
admin: python app.py --service admin --admin-port $PORT
```

### Environment Variables

```bash
# Set configuration
heroku config:set STRIPE_SECRET_KEY=sk_live_...
heroku config:set STRIPE_WEBHOOK_SECRET=whsec_...
heroku config:set STORAGE_DIR=/app/databases
```

### Deploy

```bash
# Push to Heroku
git push heroku main

# View logs
heroku logs -t

# Restart dynos
heroku restart

# Scale dynos
heroku ps:scale web=2 dashboard=1 admin=1
```

---

## AWS Deployment

### EC2 Deployment

```bash
# Launch EC2 instance
# - AMI: Ubuntu 22.04 LTS
# - Instance type: t3.medium (2GB RAM)
# - Storage: 20GB GP3

# SSH into instance
ssh -i your-key.pem ubuntu@your-instance-ip

# Install Python and dependencies
sudo apt update && sudo apt install python3.11 python3-pip -y

# Clone repository
git clone https://github.com/yourusername/pocketvectordb.git
cd pocketvectordb

# Install requirements
pip3 install -r requirements.txt

# Create systemd service
sudo cat > /etc/systemd/system/pocketvectordb.service << 'EOF'
[Unit]
Description=PocketVectorDB
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/pocketvectordb
ExecStart=/usr/bin/python3 app.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Start service
sudo systemctl enable pocketvectordb
sudo systemctl start pocketvectordb

# View logs
sudo journalctl -u pocketvectordb -f
```

### S3 Backups

```python
# In your backup code
import boto3

s3 = boto3.client(
    's3',
    aws_access_key_id=os.environ['AWS_ACCESS_KEY'],
    aws_secret_access_key=os.environ['AWS_SECRET_KEY'],
)

# Upload database backup
s3.upload_file(
    'databases/backup.tar.gz',
    'pocketvectordb-backups',
    f'backups/{date}.tar.gz'
)
```

### CloudFront CDN

For serving dashboards with low latency, configure CloudFront:

```bash
# Create distribution pointing to your Heroku/EC2 app
# Enable caching for /api/* routes
# Disable caching for /api/auth/* and /api/dashboard/*
```

---

## Configuration

### Environment Variables

**Required:**
- `STORAGE_DIR` - Vector database storage directory
- `STRIPE_SECRET_KEY` - Stripe API key (for payments)

**Optional:**
- `DEBUG` - Enable debug mode (true/false)
- `API_PORT` - API server port (default: 5000)
- `DASHBOARD_PORT` - Dashboard port (default: 5001)
- `ADMIN_PORT` - Admin panel port (default: 5002)
- `SMTP_HOST` - SMTP server hostname
- `SMTP_USER` - SMTP username
- `SMTP_PASSWORD` - SMTP password
- `SMTP_FROM` - Sender email address
- `STRIPE_WEBHOOK_SECRET` - Stripe webhook secret

### Database Configuration

By default, SQLite databases are used for maximum portability:

- `dashboard.db` - User accounts, sessions, API keys
- `billing.db` - Subscriptions, invoices, usage
- `databases/*/vectordb.sqlite3` - Vector embeddings

To migrate to PostgreSQL:

```python
# Modify database connection in each module:
# FROM: sqlite3.connect(path)
# TO: psycopg2.connect(database_url)
```

---

## Monitoring

### Health Checks

```bash
# API health
curl http://localhost:5000/health

# Dashboard availability
curl http://localhost:5001/login

# Admin access
curl http://localhost:5002/admin
```

### Key Metrics to Monitor

1. **API Performance**
   - Query latency (target: <100ms)
   - API calls per second
   - Error rate (target: <1%)

2. **User Growth**
   - Active users
   - New signups
   - Churn rate (target: <5%/month)

3. **Revenue Metrics**
   - MRR (Monthly Recurring Revenue)
   - Conversion rate (free → paid)
   - Average revenue per user

4. **Infrastructure**
   - CPU usage (target: <70%)
   - Memory usage (target: <80%)
   - Disk usage
   - Database size

### Logging

All services log to stdout/stderr. Capture with:

```bash
# File logging
python app.py 2>&1 | tee app.log

# With log rotation
pip install python-logging-loki
```

### Error Tracking (Sentry)

```python
import sentry_sdk

sentry_sdk.init(
    dsn="https://key@sentry.io/project",
    traces_sample_rate=0.1,
    environment="production"
)
```

---

## Scaling

### Horizontal Scaling (Multiple Instances)

For high traffic, run multiple API server instances behind a load balancer:

```bash
# Nginx configuration
upstream pocketvectordb {
    server localhost:5000;
    server localhost:5001;  # Second instance
    server localhost:5002;  # Third instance
}

server {
    listen 80;
    server_name api.pocketvectordb.com;

    location / {
        proxy_pass http://pocketvectordb;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Caching Strategy

1. **Query Results** - Cache frequent queries (Redis)
2. **Metadata** - Cache user tier limits
3. **API Responses** - Cache dashboard data (5 min TTL)

### Database Optimization

1. **Index Metadata Fields** - For faster filtering
2. **Archive Old Data** - Move 1-year+ old invoices to separate table
3. **Connection Pooling** - Reuse database connections

```python
# SQLite with connection pooling
from queue import Queue

class DatabasePool:
    def __init__(self, path, max_connections=5):
        self.path = path
        self.pool = Queue(maxsize=max_connections)
        for _ in range(max_connections):
            self.pool.put(sqlite3.connect(path))

    def get_connection(self):
        return self.pool.get()

    def release_connection(self, conn):
        self.pool.put(conn)
```

---

## Troubleshooting

### Common Issues

**API server fails to start**
```bash
# Check port is available
lsof -i :5000
# Kill process if needed
kill -9 <PID>
```

**Dashboard login fails**
```bash
# Check database exists
ls -la dashboard.db
# Reset database
rm dashboard.db
python app.py  # Recreates it
```

**Slow queries**
```bash
# Check database indexes
sqlite3 databases/vectordb.sqlite3
> .indices

# Add missing indexes if needed
```

**Out of memory**
```bash
# Check memory usage
free -h

# Reduce batch size for large imports
# In pocketvectordb.py, adjust batch_size parameter
```

---

## Production Checklist

- [ ] All environment variables configured
- [ ] SSL certificates installed (HTTPS)
- [ ] Backups automated (daily to S3)
- [ ] Monitoring alerts setup
- [ ] Error tracking (Sentry) configured
- [ ] Email notifications working
- [ ] Stripe webhooks verified
- [ ] Database connection pooling enabled
- [ ] Load balancer configured
- [ ] CDN caching rules set
- [ ] Rate limiting verified
- [ ] API key rotation policy
- [ ] Uptime monitoring active (StatusPage)
- [ ] Runbook documentation complete
- [ ] On-call rotation setup

---

## Support

For deployment issues:
- Check logs: `docker-compose logs -f`
- Verify configuration: `echo $STRIPE_SECRET_KEY`
- Test connectivity: `curl -v http://localhost:5000/health`

For assistance: support@pocketvectordb.com
