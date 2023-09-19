#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
NC='\033[0m' # No Color


# Define download URLs
FILE_URL="https://raw.githubusercontent.com/green-coding-berlin/hog/main/power_logger.py"
PLIST_URL="https://raw.githubusercontent.com/green-coding-berlin/hog/main/berlin.green-coding.hog.plist"

# Download and place the power_logger.py script into the standard directory for user executables
mkdir -p /usr/local/bin/
chmod 755 /usr/local/bin/
curl -o /usr/local/bin/power_logger.py $FILE_URL
chmod +x /usr/local/bin/power_logger.py

# Download and place the .plist file into /Library/LaunchDaemons/
sudo curl -o /Library/LaunchDaemons/berlin.green-coding.hog.plist $PLIST_URL
sed -i.bak "s|PATH_PLASE_CHANGE|/usr/local/bin/|g" /Library/LaunchDaemons/berlin.green-coding.hog.plist
chown root:wheel /Library/LaunchDaemons/berlin.green-coding.hog.plist
chmod 644 /Library/LaunchDaemons/berlin.green-coding.hog.plist

launchctl load /Library/LaunchDaemons/berlin.green-coding.hog.plist

echo -e "${GREEN}Successfully installed the Power Hog Demon!${NC}"
