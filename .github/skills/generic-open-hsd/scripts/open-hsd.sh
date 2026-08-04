#!/bin/bash

TICKET_NUMBER="$1"

if [ -z "$TICKET_NUMBER" ]; then
    echo "Error: HSD ticket number required"
    exit 1
fi

HSD_URL="https://hsdes.intel.com/appstore/article-one/#/$TICKET_NUMBER"

# Cross-platform browser opening
if command -v xdg-open &> /dev/null; then
    xdg-open "$HSD_URL"  # Linux
elif command -v open &> /dev/null; then
    open "$HSD_URL"      # macOS
else
    echo "Opening HSD ticket $TICKET_NUMBER..."
    echo "$HSD_URL"
fi
