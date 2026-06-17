#!/bin/bash
# Start RSSHub locally via Docker for development
# Prerequisite: Docker Desktop installed
# Then run: python3 main.py (RSSHub sources will be available at localhost:1200)

echo "Starting RSSHub on http://localhost:1200 ..."
docker run -d --name rsshub -p 1200:1200 diygod/rsshub 2>/dev/null || \
  docker start rsshub 2>/dev/null || \
  echo "Docker not available. RSSHub sources will be skipped."
