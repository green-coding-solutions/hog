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

# Checks if the hog is already running
hog_running_output=$(launchctl list | grep berlin.green-coding.hog || echo "")

if [[ ! -z "$hog_running_output" ]]; then
    launchctl unload /Library/LaunchDaemons/berlin.green-coding.hog.plist
    rm -f /tmp/latest_release.zip
fi

###
# Downloads and moves the code
###

ZIP_LOCATION=$(curl -s https://api.github.com/repos/green-coding-berlin/hog/releases/latest | grep -o 'https://[^"]*/hog_power_logger.zip')
curl -fLo /tmp/latest_release.zip $ZIP_LOCATION

mkdir -p /usr/local/bin/hog

unzip -o -u /tmp/latest_release.zip -d /usr/local/bin/hog/
rm /tmp/latest_release.zip

chmod 755 /usr/local/bin/hog
chmod -R 755 /usr/local/bin/hog/
chmod +x /usr/local/bin/hog/power_logger.py

###
# Writing the config file
###

if [[ -t 0 ]]; then  # Check if input is from a terminal
    read -p "In order for the app to work with all features please allow us to upload some data. [Y/n]: " upload_data
    upload_data=${upload_data:-Y}
    upload_data=$(echo "$upload_data" | tr '[:upper:]' '[:lower:]')

    if [[ $upload_data == "y" || $upload_data == "yes" ]]; then
        upload_flag="true"
    else
        upload_flag="false"
    fi
else
    upload_flag="true"
fi

cat > /etc/hog_settings.ini << EOF
[DEFAULT]
api_url = https://api.green-coding.berlin/v1/hog/add
web_url = https://metrics.green-coding.berlin/hog-details.html?machine_uuid=
upload_delta = 300
powermetrics = 5000
upload_data = $upload_flag
resolve_coalitions=com.googlecode.iterm2,com.apple.Terminal,com.vix.cron
EOF

echo "Configuration written to /etc/hog_settings.ini"

###
# Setting up the background demon
###

mv -f /usr/local/bin/hog/berlin.green-coding.hog.plist /Library/LaunchDaemons/berlin.green-coding.hog.plist

sed -i '' "s|PATH_PLEASE_CHANGE|/usr/local/bin/hog|g" /Library/LaunchDaemons/berlin.green-coding.hog.plist

chown root:wheel /Library/LaunchDaemons/berlin.green-coding.hog.plist
chmod 644 /Library/LaunchDaemons/berlin.green-coding.hog.plist

launchctl load /Library/LaunchDaemons/berlin.green-coding.hog.plist

echo -e "${GREEN}Successfully installed the Power Hog Demon!${NC}"
