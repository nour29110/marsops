#!/bin/bash
# Pre-tool-use hook: block destructive Bash commands.

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // ""')

if echo "$COMMAND" | grep -qE 'rm\s+-rf\s+/'; then
  echo "BLOCKED: 'rm -rf /' is not allowed." >&2
  exit 2
fi

if echo "$COMMAND" | grep -qE 'git\s+push\s+--force'; then
  echo "BLOCKED: 'git push --force' is not allowed. Use --force-with-lease if needed." >&2
  exit 2
fi

exit 0
