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

ZIP_LOCATION=$(curl -s https://api.github.com/repos/green-coding-berlin/hog/releases/latest | grep '/hog_power_logger.zip' | cut -d\" -f4)
curl -fLo /tmp/latest_release.zip $ZIP_LOCATION

mkdir -p /usr/local/bin/hog

unzip /tmp/latest_release.zip -d /usr/local/bin/hog/
rm /tmp/latest_release.zip

chmod 755 /usr/local/bin/hog
chmod -R 755 /usr/local/bin/hog/
chmod +x /usr/local/bin/hog/power_logger.py

mv /usr/local/bin/hog/berlin.green-coding.hog.plist /Library/LaunchDaemons/berlin.green-coding.hog.plist

sed -i '' "s|PATH_PLEASE_CHANGE|/usr/local/bin/hog/|g" /Library/LaunchDaemons/berlin.green-coding.hog.plist

chown root:wheel /Library/LaunchDaemons/berlin.green-coding.hog.plist
chmod 644 /Library/LaunchDaemons/berlin.green-coding.hog.plist

launchctl load /Library/LaunchDaemons/berlin.green-coding.hog.plist

echo -e "${GREEN}Successfully installed the Power Hog Demon!${NC}"
