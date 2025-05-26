ifneq (,$(wildcard ./.env))
    include .env
    export
endif
.PHONY: run clean install help

run:
	uv run streamlit run src/homepage.py

# Install dependencies (optional)
install:
	uv sync

# Clean cache files (optional)
clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	rm -rf .streamlit/

# Help target
help:
	@echo "Available targets:"
	@echo "  run     - Run the Streamlit application"
	@echo "  install - Install Streamlit"
	@echo "  clean   - Clean cache files"
	@echo "  help    - Show this help message"
