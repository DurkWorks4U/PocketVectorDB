FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories
RUN mkdir -p /app/databases /app/backups

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV STORAGE_DIR=/app/databases

# Expose ports
EXPOSE 5000 5001 5002

# Default command runs all services
# Override with SERVICE environment variable to run single service:
# SERVICE=api -> python app.py --service api
# SERVICE=dashboard -> python app.py --service dashboard
# SERVICE=admin -> python app.py --service admin
CMD ["python", "app.py"]
