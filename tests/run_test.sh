#!/bin/bash
set -e

if [ -f /tmp/power_hog_test.db ]; then
    sudo rm /tmp/power_hog_test.db
fi

if [ -f /tmp/power_hog_test_output ]; then
    sudo rm /tmp/power_hog_test_output
fi

sudo ../power_logger.py -t -f powermetrics_test_output.plist -o /tmp/power_hog_test_output

./tester.py
