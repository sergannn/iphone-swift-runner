#!/bin/sh
set -eu

DEST=/var/jb/var/mobile/SwiftRunner
mkdir -p "$DEST"
cp -R runner "$DEST/"
cp -R examples "$DEST/"
cp -R launchd "$DEST/"
cp README.md "$DEST/"

if [ -d "$DEST/runner" ]; then
  cp "$DEST/runner/iphone_runner.py" "$DEST/iphone_runner.py"
  chmod +x "$DEST/iphone_runner.py"
fi

echo "Installed to $DEST"

if [ -d /var/jb/Library/LaunchDaemons ]; then
  cp launchd/com.local.iphone-swift-runner.plist /var/jb/Library/LaunchDaemons/
  chmod 644 /var/jb/Library/LaunchDaemons/com.local.iphone-swift-runner.plist
  echo "LaunchDaemon installed."
  echo "Try loading with:"
  echo "launchctl bootstrap system /var/jb/Library/LaunchDaemons/com.local.iphone-swift-runner.plist"
fi

echo "Manual start:"
echo "/var/jb/usr/bin/python3 $DEST/iphone_runner.py --host 0.0.0.0 --port 8090"
