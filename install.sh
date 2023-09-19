#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
NC='\033[0m' # No Color

# Function to check and install Xcode Command Line Tools
install_xcode_clt() {
    if xcode-select --print-path &>/dev/null; then
        echo "Xcode Command Line Tools are already installed!"
        return
    fi

    xcode-select --install &>/dev/null

    echo "Installing Xcode Command Line Tools..."

    while true; do
        if xcode-select --print-path &>/dev/null; then
            echo "Installation completed!"
            return
        fi

        if ! pgrep "Install Command Line Developer Tools" &>/dev/null; then
            echo "Installation was canceled or failed!"
            exit 1
        fi

        sleep 5
    done
}

# Call the function to ensure Xcode Command Line Tools are installed
install_xcode_clt

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
