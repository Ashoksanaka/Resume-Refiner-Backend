# AI Agent Microservice Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Create a non-root user
RUN addgroup --system agent && adduser --system --ingroup agent agent

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application and set permissions
COPY --chown=agent:agent . .

# Switch to non-root user
USER agent

EXPOSE 8001

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]