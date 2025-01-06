#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'
NC='\033[0m' # No Color
CONFIG_FILE="/etc/hog_settings.ini"

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
hog_running_output=$(launchctl list | grep io.green-coding.hogger || echo "")

if [[ ! -z "$hog_running_output" ]]; then
    launchctl bootout system /Library/LaunchDaemons/io.green-coding.hogger.plist
    rm -f /tmp/latest_release.zip
fi

###
# Downloads and moves the code
###

ZIP_LOCATION=$(curl -s https://api.github.com/repos/green-coding-solutions/hog/releases/latest | grep -o 'https://[^"]*/hog_power_logger.zip')
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

update_config() {
    local key="$1"
    local value="$2"
    local file="$3"
    if grep -q "^${key} =" "$file"; then
        sed -i "s|^${key} =.*|${key} = ${value}|" "$file"
    else
        echo "${key} = ${value}" >> "$file"
    fi
}

cat settings.ini > "$CONFIG_FILE"

if [[ -t 0 ]]; then
    read -p "In order for the app to work with all features, please allow us to upload some data. [Y/n]: " upload_data
    upload_data=${upload_data:-Y}
    upload_data=$(echo "$upload_data" | tr '[:upper:]' '[:lower:]')

    if [[ $upload_data == "y" || $upload_data == "yes" ]]; then
        sed -i "s|^upload_data =.*|upload_data = true|" "$CONFIG_FILE"
    else
        sed -i "s|^upload_data =.*|upload_data = false|" "$CONFIG_FILE"
    fi
fi

echo "Installation complete. Configuration updated at $CONFIG_FILE."


###
# Setting up the background demon
###

mv -f /usr/local/bin/hog/io.green-coding.hogger.plist /Library/LaunchDaemons/io.green-coding.hogger.plist

sed -i '' "s|PATH_PLEASE_CHANGE|/usr/local/bin/hog|g" /Library/LaunchDaemons/io.green-coding.hogger.plist

chown root:wheel /Library/LaunchDaemons/io.green-coding.hogger.plist
chmod 644 /Library/LaunchDaemons/io.green-coding.hogger.plist

launchctl bootstrap system /Library/LaunchDaemons/io.green-coding.hogger.plist

echo -e "${GREEN}Successfully installed the Power Hog Demon!${NC}"
