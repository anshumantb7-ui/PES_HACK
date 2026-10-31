"""Tiny static server used by regression.py. Serves dist/ like a real host would."""
import argparse, http.server, os, socketserver

ap = argparse.ArgumentParser()
ap.add_argument("--dir", required=True)
ap.add_argument("--port", type=int, required=True)
ap.add_argument("--redirect-index", action="store_true", help="redirect /index.html to / like Netlify and Cloudflare Pages")
a = ap.parse_args()
os.chdir(a.dir)

class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if a.redirect_index and self.path.split("?")[0].endswith("/index.html"):
            self.send_response(308)
            self.send_header("Location", self.path.replace("index.html", ""))
            self.end_headers()
            return
        return super().do_GET()

    def end_headers(self):
        if self.path.split("?")[0].endswith(("sw.js", "/")):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, *args):
        pass

class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

with Server(("127.0.0.1", a.port), Handler) as server:
    server.serve_forever()
