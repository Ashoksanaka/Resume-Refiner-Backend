# LaTeX Compilation Microservice Dockerfile
FROM python:3.11-slim

# Install TeX Live and PDF tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-fonts-recommended \
    texlive-latex-extra \
    texlive-fonts-extra \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create a non-root user
RUN addgroup --system latex && adduser --system --ingroup latex latex

# Create directories and set permissions
RUN mkdir -p /app/output /app/templates && chown -R latex:latex /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=latex:latex main.py .

# Copy templates directory
COPY --chown=latex:latex templates/ /app/templates/

# Set environment
ENV OUTPUT_DIR=/app/output
ENV TEMPLATES_DIR=/app/templates

# Switch to non-root user
USER latex

EXPOSE 8002

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
