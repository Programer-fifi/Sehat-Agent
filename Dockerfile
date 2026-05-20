FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all agent code
COPY agents/ ./agents/

# Copy start script
COPY start.sh .
RUN chmod +x start.sh

# Expose port 7860 (HuggingFace default)
EXPOSE 7860

# Set environment variables
ENV PORT=7860
ENV PYTHONUNBUFFERED=1

CMD ["bash", "start.sh"]
