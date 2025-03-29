# Stage 1: Builder and development environment
FROM python:3.13-alpine AS builder

# Install build dependencies
RUN apk add --no-cache gcc musl-dev

# Install poetry
RUN pip install --no-cache-dir poetry

# Set working directory
WORKDIR /app

# Copy only dependency definition files first to leverage Docker cache
COPY pyproject.toml poetry.lock* ./

# Configure poetry to not create a virtual environment
RUN poetry config virtualenvs.create false

# Install dependencies (including dev dependencies for linting and testing)
RUN poetry install --no-interaction --no-root

# Copy the rest of the application
COPY . .

# Stage for linting and testing
FROM builder AS lint
RUN ./ci/lint
RUN ./ci/test

# Stage 2: Production environment
FROM python:3.13-alpine AS production

# Set working directory
WORKDIR /app

# Install runtime dependencies only
RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock* ./
RUN poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-root

# Copy the application code
COPY --from=builder /app/heylisten ./heylisten
COPY --from=builder /app/templates ./templates
COPY --from=builder /app/README.md ./README.md
COPY --from=builder /app/run.sh ./

# Make run.sh executable
RUN chmod +x run.sh

# Create volume for persistent data
VOLUME ["/app/data"]

# Set environment variables
ENV DATA_DIR="/app/data"
ENV WEB_HOST=0.0.0.0
ENV WEB_PORT=8000

# Expose the web port
EXPOSE 8000

# Run the application
CMD ["python", "-m", "heylisten.main"]
