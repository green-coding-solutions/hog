#!/bin/bash

files_to_zip=(
  "migrations/"
  "io.green-coding.hogger.plist"
  "power_logger.py"
  "libs/"
  "settings.ini"
)

exclude_patterns=()
while IFS= read -r line; do
    exclude_patterns+=("-x" "*$line")
done < <(grep -vE '^\s*#' .gitignore | sed '/^$/d')

zip -r hog_power_logger.zip "${files_to_zip[@]}" "${exclude_patterns[@]}"

echo "Files have been zipped into hog_power_logger.zip"
echo "Now create a new release on github and then delete the zip"
grep 'VERSION =' power_logger.py
