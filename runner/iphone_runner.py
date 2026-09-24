#!/var/jb/usr/bin/python3
import argparse
import html
import http.server
import json
import os
import plistlib
import re
import signal
import shutil
import subprocess
import time
import uuid
import urllib.request
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, unquote


ROOT = Path("/var/jb/var/mobile/SwiftRunner")
JOBS = ROOT / "jobs"
LAUNCHER_DIR = ROOT / "launcher"
SDK = Path("/var/jb/usr/share/SDKs/iPhoneOS.sdk")
SWIFTC = Path("/var/jb/usr/lib/llvm-14/bin/swiftc")
LDID = Path("/var/jb/usr/bin/ldid")
UICACHE_CANDIDATES = [
    Path("/cores/binpack/usr/bin/uicache"),
    Path("/var/jb/usr/bin/uicache"),
]


DEFAULT_ENTITLEMENTS = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>platform-application</key>
  <true/>
  <key>com.apple.private.security.no-container</key>
  <true/>
  <key>com.apple.private.skip-library-validation</key>
  <true/>
  <key>com.apple.springboard.launchapplications</key>
  <true/>
  <key>com.apple.frontboard.launchapplications</key>
  <true/>
</dict>
</plist>
"""


LAUNCHER_SWIFT = r'''
import Foundation

let bundleID = CommandLine.arguments.count > 1 ? CommandLine.arguments[1] : ""
if bundleID.isEmpty {
    print("missing bundle id")
    exit(2)
}

let defaultSel = NSSelectorFromString("defaultWorkspace")
let openSel = NSSelectorFromString("openApplicationWithBundleID:")

guard let rawClass = NSClassFromString("LSApplicationWorkspace") else {
    print("no LSApplicationWorkspace")
    exit(3)
}

let classObject = rawClass as AnyObject
guard classObject.responds(to: defaultSel), let unmanagedWorkspace = classObject.perform(defaultSel) else {
    print("no defaultWorkspace")
    exit(4)
}

let workspace = unmanagedWorkspace.takeUnretainedValue() as AnyObject
guard workspace.responds(to: openSel) else {
    print("no openApplicationWithBundleID")
    exit(5)
}

let result = workspace.perform(openSel, with: bundleID)
print("open requested \(bundleID) \(result != nil)")
exit(result != nil ? 0 : 6)
'''


def run(cmd, cwd=None, timeout=240):
    started = time.time()
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    return {
        "cmd": [str(x) for x in cmd],
        "code": proc.returncode,
        "seconds": round(time.time() - started, 3),
        "output": proc.stdout[-12000:],
    }


def find_executable(name):
    for directory in os.environ.get("PATH", "").split(":"):
        candidate = Path(directory) / name
        if candidate.exists():
            return candidate
    for directory in ["/bin", "/usr/bin", "/usr/sbin", "/sbin", "/var/jb/usr/bin", "/var/jb/usr/sbin"]:
        candidate = Path(directory) / name
        if candidate.exists():
            return candidate
    return None


def terminate_app_processes(executable):
    ps = find_executable("ps")
    if not ps:
        return
    try:
        proc = subprocess.run(
            [ps, "-axo", "pid,command"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        return
    for line in proc.stdout.splitlines():
        if executable not in line or "iphone_runner.py" in line:
            continue
        parts = line.strip().split(None, 1)
        if not parts or not parts[0].isdigit():
            continue
        try:
            os.kill(int(parts[0]), signal.SIGTERM)
        except OSError:
            pass


def require_file(path):
    if not Path(path).exists():
        raise RuntimeError(f"missing required file: {path}")


def uicache_path():
    for path in UICACHE_CANDIDATES:
        if path.exists():
            return path
    raise RuntimeError("uicache not found")


def parse_plist(path):
    with open(path, "rb") as f:
        return plistlib.load(f)


def ensure_launcher():
    LAUNCHER_DIR.mkdir(parents=True, exist_ok=True)
    source = LAUNCHER_DIR / "launcher.swift"
    binary = LAUNCHER_DIR / "open_app"
    entitlements = LAUNCHER_DIR / "entitlements.plist"

    source.write_text(LAUNCHER_SWIFT, encoding="utf-8")
    entitlements.write_text(DEFAULT_ENTITLEMENTS, encoding="utf-8")

    if binary.exists():
        return binary

    compile_result = run([
        SWIFTC,
        "-sdk", SDK,
        "-target", "arm64-apple-ios16.0",
        "-framework", "MobileCoreServices",
        "-framework", "CoreServices",
        source,
        "-o", binary,
    ], timeout=300)
    if compile_result["code"] != 0:
        raise RuntimeError("launcher compile failed: " + compile_result["output"])

    sign_result = run([LDID, f"-S{entitlements}", binary])
    if sign_result["code"] != 0:
        raise RuntimeError("launcher sign failed: " + sign_result["output"])

    return binary


def parse_github_url(git_url):
    match = re.match(r"^https://github\.com/([^/]+)/([^/#?]+?)(?:\.git)?/?(?:[?#].*)?$", git_url)
    if not match:
        return None
    return match.group(1), match.group(2)


def download_github_archive(git_url, ref, dest):
    parsed = parse_github_url(git_url)
    if not parsed:
        raise RuntimeError("not a supported GitHub URL")

    owner, repo = parsed
    refs = [ref] if ref else ["main", "master"]
    last_error = None

    for candidate in refs:
        archive_url = f"https://codeload.github.com/{owner}/{repo}/zip/refs/heads/{candidate}"
        archive_path = dest.parent / f"{repo}-{candidate}.zip"
        try:
            urllib.request.urlretrieve(archive_url, archive_path)
            with zipfile.ZipFile(archive_path) as zf:
                zf.extractall(dest.parent)
                roots = {name.split("/", 1)[0] for name in zf.namelist() if "/" in name}
            if not roots:
                raise RuntimeError("archive did not contain a root directory")
            extracted = dest.parent / sorted(roots)[0]
            if dest.exists():
                shutil.rmtree(dest)
            extracted.rename(dest)
            return {
                "cmd": ["github-archive", archive_url],
                "code": 0,
                "seconds": None,
                "output": f"Downloaded GitHub archive for {owner}/{repo}@{candidate}",
            }
        except Exception as exc:
            last_error = exc

    raise RuntimeError(f"GitHub archive download failed: {last_error}")


def fetch_source(git_url, ref, src_root):
    clone = run(["git", "clone", "--depth", "1", git_url, src_root], timeout=300)
    if clone["code"] == 0:
        steps = [clone]
        if ref:
            steps.append(run(["git", "fetch", "--depth", "1", "origin", ref], cwd=src_root, timeout=300))
            steps.append(run(["git", "checkout", "FETCH_HEAD"], cwd=src_root, timeout=120))
            if steps[-1]["code"] != 0:
                raise RuntimeError("git checkout failed: " + steps[-1]["output"])
        return steps

    if parse_github_url(git_url):
        archive = download_github_archive(git_url, ref, src_root)
        archive["output"] = "git clone failed, used GitHub zip fallback.\n\n" + clone["output"] + "\n\n" + archive["output"]
        return [clone, archive]

    raise RuntimeError("git clone failed: " + clone["output"])


def screenshot(job_dir):
    out = job_dir / "screenshot.png"
    for _ in range(60):
        if out.exists() and out.stat().st_size > 0:
            return out, None
        time.sleep(0.5)
    return None, "app did not produce screenshot.png"


def instrument_swift_for_screenshot(source, destination, screenshot_path, delay_seconds, debug_path):
    text = Path(source).read_text(encoding="utf-8")
    marker = "UIApplicationMain("
    if marker not in text:
        raise RuntimeError(
            "screenshot capture requires a UIKit entry file that calls UIApplicationMain(...)"
        )

    hook = f"""

final class RunnerScreenshot {{
    private static func debug(_ message: String) {{
        let line = message + "\\n"
        let url = URL(fileURLWithPath: "{debug_path}")
        if let data = line.data(using: .utf8) {{
            if FileManager.default.fileExists(atPath: url.path),
               let handle = try? FileHandle(forWritingTo: url) {{
                try? handle.seekToEnd()
                try? handle.write(contentsOf: data)
                try? handle.close()
            }} else {{
                try? data.write(to: url, options: .atomic)
            }}
        }}
    }}

    static func install(path: String, delay: TimeInterval) {{
        debug("install")
        NotificationCenter.default.addObserver(
            forName: UIApplication.didBecomeActiveNotification,
            object: nil,
            queue: .main
        ) {{ _ in
            debug("didBecomeActive")
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) {{
                capture(path: path)
            }}
        }}
    }}

    private static func capture(path: String) {{
        debug("capture-start")
        let windowFromScene = UIApplication.shared.connectedScenes
            .compactMap {{ $0 as? UIWindowScene }}
            .flatMap {{ $0.windows }}
            .first {{ $0.isKeyWindow }}
        let fallbackWindow = UIApplication.shared.windows.first {{ $0.isKeyWindow }}

        guard let window = windowFromScene ?? fallbackWindow else {{
            debug("no-window")
            return
        }}

        let format = UIGraphicsImageRendererFormat.default()
        format.scale = UIScreen.main.scale
        let renderer = UIGraphicsImageRenderer(bounds: window.bounds, format: format)
        let image = renderer.image {{ _ in
            window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
        }}

        if let data = image.pngData() {{
            try? data.write(to: URL(fileURLWithPath: path), options: .atomic)
            debug("wrote-png \\(data.count)")
        }} else {{
            debug("pngData-nil")
        }}
    }}
}}

RunnerScreenshot.install(path: "{screenshot_path}", delay: {delay_seconds})

"""
    text = text.replace(marker, hook + marker, 1)
    Path(destination).write_text(text, encoding="utf-8")
    return destination


def build_and_run(payload):
    require_file(SWIFTC)
    require_file(LDID)
    require_file(SDK)

    git_url = payload.get("git_url")
    if not git_url:
        raise RuntimeError("git_url is required")

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS / job_id
    src_root = job_dir / "src"
    job_dir.mkdir(parents=True, exist_ok=True)

    steps = []
    ref = payload.get("ref")
    steps.extend(fetch_source(git_url, ref, src_root))

    app_src = src_root / payload.get("subdir", ".")
    swift_file = app_src / payload.get("swift_file", "AppDelegate.swift")
    info_plist = app_src / payload.get("info_plist", "Info.plist")
    entitlements = app_src / payload.get("entitlements", "entitlements.plist")

    require_file(swift_file)
    require_file(info_plist)

    info = parse_plist(info_plist)
    executable = info.get("CFBundleExecutable", "RunnerApp")
    bundle_id = info.get("CFBundleIdentifier")
    display_name = info.get("CFBundleDisplayName", executable)
    if not bundle_id:
        raise RuntimeError("Info.plist must include CFBundleIdentifier")

    build_app = job_dir / f"{executable}.app"
    install_app = Path("/var/jb/Applications") / f"{executable}.app"
    if build_app.exists():
        shutil.rmtree(build_app)
    build_app.mkdir(parents=True)
    shutil.copy2(info_plist, build_app / "Info.plist")

    if not entitlements.exists():
        entitlements = job_dir / "default-entitlements.plist"
        entitlements.write_text(DEFAULT_ENTITLEMENTS, encoding="utf-8")

    binary = build_app / executable
    screenshot_delay = float(payload.get("wait_seconds", 2))
    instrumented_swift = job_dir / "InstrumentedAppDelegate.swift"
    instrument_swift_for_screenshot(
        swift_file,
        instrumented_swift,
        job_dir / "screenshot.png",
        max(0.5, min(screenshot_delay, 30)),
        job_dir / "screenshot-debug.log",
    )

    compile_cmd = [
        SWIFTC,
        "-sdk", SDK,
        "-target", "arm64-apple-ios16.0",
        "-framework", "UIKit",
        instrumented_swift,
        "-o", binary,
    ]
    for framework in payload.get("frameworks", []):
        compile_cmd[5:5] = ["-framework", framework]

    steps.append(run(compile_cmd, cwd=app_src, timeout=600))
    if steps[-1]["code"] != 0:
        raise RuntimeError("swift build failed: " + steps[-1]["output"])

    steps.append(run([LDID, f"-S{entitlements}", binary]))
    if steps[-1]["code"] != 0:
        raise RuntimeError("ldid failed: " + steps[-1]["output"])

    if install_app.exists():
        shutil.rmtree(install_app)
    shutil.copytree(build_app, install_app)
    os.chown(install_app, 0, 0)
    for path in install_app.rglob("*"):
        try:
            os.chown(path, 0, 0)
        except PermissionError:
            pass

    steps.append(run([uicache_path(), "-p", install_app], timeout=60))
    if steps[-1]["code"] != 0:
        raise RuntimeError("uicache failed: " + steps[-1]["output"])

    # Ensure LaunchServices starts the freshly built instrumented binary.
    terminate_app_processes(executable)
    time.sleep(1)

    launcher = ensure_launcher()
    steps.append(run([launcher, bundle_id], timeout=30))
    launch_ok = steps[-1]["code"] == 0

    wait_seconds = screenshot_delay
    if wait_seconds > 0:
        time.sleep(min(wait_seconds, 30))

    screenshot_path, screenshot_error = screenshot(job_dir)
    if not screenshot_path:
        raise RuntimeError("screenshot failed: " + (screenshot_error or "unknown error"))

    return {
        "ok": True,
        "job_id": job_id,
        "app": {
            "display_name": display_name,
            "bundle_id": bundle_id,
            "executable": executable,
            "installed_path": str(install_app),
        },
        "launch_ok": launch_ok,
        "screenshot": f"/artifacts/{job_id}/screenshot.png" if screenshot_path else None,
        "screenshot_error": screenshot_error,
        "steps": steps,
    }


def page(title, body):
    html_body = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light dark;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: Canvas;
      color: CanvasText;
    }}
    body {{
      margin: 0;
      padding: 28px;
      max-width: 920px;
    }}
    h1 {{
      font-size: 28px;
      margin: 0 0 20px;
    }}
    form {{
      display: grid;
      gap: 14px;
      max-width: 720px;
    }}
    label {{
      display: grid;
      gap: 6px;
      font-weight: 600;
    }}
    input {{
      font: inherit;
      padding: 10px 12px;
      border: 1px solid color-mix(in srgb, CanvasText 25%, transparent);
      border-radius: 6px;
      background: Canvas;
      color: CanvasText;
    }}
    button {{
      width: fit-content;
      font: inherit;
      font-weight: 700;
      padding: 10px 16px;
      border: 0;
      border-radius: 6px;
      color: white;
      background: #1267d8;
    }}
    pre {{
      overflow: auto;
      padding: 14px;
      border-radius: 6px;
      background: color-mix(in srgb, CanvasText 8%, transparent);
    }}
    img {{
      max-width: min(100%, 420px);
      height: auto;
      border: 1px solid color-mix(in srgb, CanvasText 15%, transparent);
      border-radius: 6px;
    }}
    .muted {{
      color: color-mix(in srgb, CanvasText 65%, transparent);
    }}
  </style>
</head>
<body>
{body}
</body>
</html>"""
    return html_body.encode("utf-8")


def form_page():
    return page("iPhone Swift Runner", """
  <h1>iPhone Swift Runner</h1>
  <form method="post" action="/run">
    <label>
      Git URL
      <input name="git_url" placeholder="https://github.com/user/repo.git" required>
    </label>
    <label>
      Ref
      <input name="ref" placeholder="main">
    </label>
    <label>
      Subdirectory
      <input name="subdir" value=".">
    </label>
    <label>
      Wait before screenshot, seconds
      <input name="wait_seconds" value="3">
    </label>
    <button type="submit">Build and run</button>
  </form>
  <p class="muted">The request waits while the iPhone clones, builds, installs, launches, and captures if possible.</p>
""")


def result_page(result):
    escaped = html.escape(json.dumps(result, ensure_ascii=False, indent=2))
    screenshot = result.get("screenshot")
    screenshot_html = ""
    if screenshot:
        screenshot_html = f'<h2>Screenshot</h2><p><img src="{html.escape(screenshot)}" alt="screenshot"></p>'
    elif result.get("screenshot_error"):
        screenshot_html = f'<h2>Screenshot</h2><p class="muted">{html.escape(result["screenshot_error"])}</p>'
    return page("Build Result", f"""
  <h1>Build Result</h1>
  {screenshot_html}
  <h2>JSON</h2>
  <pre>{escaped}</pre>
  <p><a href="/">Run another</a></p>
""")


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "iPhoneSwiftRunner/0.1"

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, body, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self.send_html(form_page())
            return

        if self.path == "/health":
            self.send_json({"ok": True, "service": "iPhone Swift Runner"})
            return

        if self.path.startswith("/artifacts/"):
            parts = [unquote(x) for x in self.path.split("/") if x]
            if len(parts) == 3 and parts[2] == "screenshot.png":
                path = JOBS / parts[1] / "screenshot.png"
                if path.exists():
                    body = path.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
            self.send_error(404)
            return

        self.send_error(404)

    def do_POST(self):
        if self.path != "/run":
            self.send_error(404)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length).decode("utf-8")
            content_type = self.headers.get("Content-Type", "")
            wants_html = "application/json" not in content_type
            if "application/json" in content_type:
                payload = json.loads(raw)
            else:
                fields = parse_qs(raw)
                payload = {key: values[-1] for key, values in fields.items() if values}
                payload = {key: value for key, value in payload.items() if value != ""}
            result = build_and_run(payload)
            if wants_html:
                self.send_html(result_page(result))
            else:
                self.send_json(result)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
            if "application/json" in self.headers.get("Content-Type", ""):
                self.send_json(result, status=500)
            else:
                self.send_html(result_page(result), status=500)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    args = parser.parse_args()

    JOBS.mkdir(parents=True, exist_ok=True)
    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"iPhone Swift Runner listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
