# iPhone Swift Runner

Tiny rootless-jailbreak service for an iPhone that can receive a Git URL from a
web form or command line, clone a Swift UIKit app, build it directly on the
iPhone, install it as an `.app`, launch it through iOS LaunchServices, and
return a result page / JSON response.

This project is experimental and intentionally executes Swift projects from Git.

## Tested Shape

- iPhone 8 / iPhone10,4
- iOS 16.7.x
- palera1n rootless
- Procursus bootstrap
- Swift 5.7.2 installed on the iPhone
- `ldid`, `python3`, `uicache`, `uiopen`, and `git` available on the iPhone

The service expects a simple source repository layout:

```text
AppDelegate.swift
Info.plist
entitlements.plist        # optional
```

See `examples/CodexScreen`.

## Install On iPhone

Copy this repository to the iPhone, then run:

```sh
cd /path/to/iphone-swift-runner
sh scripts/install_on_iphone.sh
```

Start the service manually:

```sh
/var/jb/usr/bin/python3 /var/jb/var/mobile/SwiftRunner/iphone_runner.py --host 0.0.0.0 --port 8090
```

Open in a browser:

```text
http://10.77.0.3:8090/
```

Or from another machine:

```sh
curl -sS -X POST http://10.77.0.3:8090/run \
  -H 'Content-Type: application/json' \
  -d '{"git_url":"https://github.com/USER/REPO.git"}'
```

With ref and subdirectory:

```sh
curl -sS -X POST http://10.77.0.3:8090/run \
  -H 'Content-Type: application/json' \
  -d '{"git_url":"https://github.com/USER/REPO.git","ref":"main","subdir":"examples/CodexScreen","wait_seconds":3}'
```

## One Command From Terminal

After the service is running on the iPhone:

```sh
sh scripts/run_remote.sh http://10.77.0.3:8090 https://github.com/USER/REPO.git main examples/CodexScreen
```

## Internet Access Through Nginx

Example reverse proxy on a public server:

```nginx
location ^~ /swift-runner/ {
    proxy_pass http://10.77.0.3:8090/;
    proxy_http_version 1.1;
    proxy_read_timeout 900s;
    proxy_send_timeout 900s;
}
```

Then open:

```text
https://your-domain.example/swift-runner/
```

## What The Runner Does

1. Creates a job directory on the iPhone.
2. Clones the Git repository.
3. Checks out the requested ref if provided.
4. Builds `AppDelegate.swift` using the iPhone SDK and Swift compiler.
5. Signs the binary with `ldid`.
6. Installs the app to `/var/jb/Applications/<Name>.app`.
7. Registers it with `uicache`.
8. Launches it through a small Swift launcher that calls iOS LaunchServices.
9. Tries to capture a screenshot if a screenshot tool exists.

On the current tested phone, no `screencapture` command was present, so the
runner reports `screenshot: null` until a capture backend is installed or added.
