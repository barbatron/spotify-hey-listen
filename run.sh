#!/bin/bash

# Ensure Poetry is installed and activate the virtual environment
if ! command -v poetry &> /dev/null; then
    echo "Poetry could not be found. Please install it first."
    echo "Visit https://python-poetry.org/docs/#installation for instructions."
    exit 1
fi

# Install dependencies if needed
poetry install

# Run the application
poetry run python -m heylisten.main
