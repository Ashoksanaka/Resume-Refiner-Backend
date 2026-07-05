# LaTeX Compilation Microservice Dockerfile
FROM python:3.11-slim

# Install comprehensive TeX Live packages for resume generation
# This includes all commonly used packages without the full distribution
# Packages included:
# - Base LaTeX and recommended/extra packages (covers most resume needs)
# - Font packages (for fontawesome5, custom fonts, etc.)
# - Graphics packages (for images, diagrams)
# - Publishing packages (for advanced formatting)
# - Language support (for international characters)
RUN apt-get update && apt-get install -y --no-install-recommends \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-fonts-extra \
    texlive-font-utils \
    texlive-pictures \
    texlive-publishers \
    texlive-bibtex-extra \
    texlive-lang-english \
    texlive-lang-european \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

WORKDIR /app

# Create a non-root user
RUN addgroup --system latex && adduser --system --ingroup latex latex

# Create directories and set permissions
RUN mkdir -p /app/output /app/templates && chown -R latex:latex /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=latex:latex main.py validator.py ats_preamble.py .

# Copy templates directory
COPY --chown=latex:latex templates/ /app/templates/

# Set environment
ENV OUTPUT_DIR=/app/output
ENV TEMPLATES_DIR=/app/templates

# Switch to non-root user
USER latex

EXPOSE 8002

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
