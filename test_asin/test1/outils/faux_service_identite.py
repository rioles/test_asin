"""
Faux service national d'identification, pour essayer l'API à la main.

    ..\\venv\\Scripts\\python.exe outils\\faux_service_identite.py        (écoute sur 127.0.0.1:8081)

GET /identite/{npi} :
  * NPI commençant par 9 → répond au bout de 20 s (comme le 19/11 au matin) ;
  * NPI 0000000000       → 404 (NPI inconnu) ;
  * autres NPI           → 200 {"nom": ..., "prenoms": ...}.
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NOMS = ["DOSSOU", "AGOSSOU", "KPADONOU", "HOUNSOU", "ZINSOU", "SANNI"]


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        npi = self.path.rstrip("/").rsplit("/", 1)[-1]
        if not self.path.startswith("/identite/"):
            self.send_response(404)
            self.end_headers()
            return
        if npi.startswith("9"):
            time.sleep(20)
        if npi == "0000000000":
            self.send_response(404)
            self.end_headers()
            return
        corps = json.dumps({"npi": npi, "nom": NOMS[int(npi[-1]) % len(NOMS)],
                            "prenoms": f"Candidat {npi[-4:]}"}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(corps)
        except ConnectionError:
            pass  # l'application a abandonné au bout de 5 s : normal


class Serveur(ThreadingHTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    print(f"Faux service d'identification sur http://127.0.0.1:{port}/identite/<npi>")
    Serveur(("127.0.0.1", port), Handler).serve_forever()
