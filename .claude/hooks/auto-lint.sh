#!/bin/sh
# ABOUTME: Post-edit type-check hook that runs tsc after code changes
# ABOUTME: Uses pnpm exec tsc --noEmit to catch type errors early

set -e

# Parse the input JSON
INPUT_JSON="$1"
FILE_PATH=$(echo "$INPUT_JSON" | jq -r '.file_path // empty')

# Skip if no file path
if [ -z "$FILE_PATH" ]; then
    exit 0
fi

# Only check TypeScript files
case "$FILE_PATH" in
    *.ts|*.tsx) ;;
    *) exit 0 ;;
esac

echo "Running type check after code changes..."

# Run tsc --noEmit for type checking
if pnpm exec tsc --noEmit 2>/dev/null; then
    echo "Type check passed"
else
    echo "WARNING: Type errors found - consider running 'pnpm exec tsc --noEmit' manually"
    # Don't block, just inform
fi

exit 0
