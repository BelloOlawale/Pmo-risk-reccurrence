#!/bin/bash

issues=$(cat Issues/0*.md 2>/dev/null || echo "No issues found")
commits=$(git log -n 5 --format="%H%n%ad%n%B---" --date=short 2>/dev/null || echo "No commits found")
prompt=$(cat ralph/prompt.md)
progress=$(cat progress.txt 2>/dev/null || echo "No progress file")

echo "Previous commits: $commits

Progress: $progress

Issues: $issues

$prompt" | pi -p