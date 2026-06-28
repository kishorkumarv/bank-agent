# Use a lightweight Python image
FROM python:3.11-slim

# Install uv binary directly
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set the working directory
WORKDIR /app

# Enable bytecode compilation for faster startup
ENV UV_COMPILE_BYTECODE=1
# Ensure output is sent directly to logs
ENV PYTHONUNBUFFERED=1

# Copy project files
COPY pyproject.toml uv.lock main.py .python-version ./
COPY bank_agent ./bank_agent/

# Install dependencies into the system environment
# --system tells uv to install without a virtualenv (ideal for containers)
#RUN uv pip install --system --requirement pyproject.toml
RUN uv sync --frozen --no-dev 

ENV PATH="/app/.venv/bin:$PATH"

# Expose the ADK port
EXPOSE 8080

# Run your agent
CMD ["uvicorn","main:app", "--host", "0.0.0.0", "--port", "8080"]