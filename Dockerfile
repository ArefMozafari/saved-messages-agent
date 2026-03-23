FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock* ./

# Install dependencies
RUN uv sync --no-dev --frozen

# Copy source
COPY . .

CMD ["uv", "run", "python", "run.py"]
