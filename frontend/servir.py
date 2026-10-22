"""Sirve el frontend, reenvia /api al backend y los mosaicos de OSM (/tiles) con cache,
para exponer UN solo puerto (por ejemplo desde el panel Puertos de VS Code).

    py servir.py            # pagina en http://localhost:5173, backend esperado en :8000

Pensado para pasar por un tunel: conexiones persistentes (HTTP/1.1), una sola escritura por
respuesta y gzip en lo que es texto. Con HTTP/1.0 cada archivo abria una conexion nueva y
en Windows costaba ~200 ms por respuesta, y el tunel llegaba a dar 504.
"""

import gzip
import http.server
import mimetypes
import os
import re
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

PUERTO = int(sys.argv[1]) if len(sys.argv) > 1 else 5173
BACKEND = os.environ.get("OJO_BACKEND", "http://127.0.0.1:8000")
AQUI = os.path.dirname(os.path.abspath(__file__))
TILES = "https://tile.openstreetmap.org"
CACHE = os.path.join(AQUI, ".tiles")
UA = "OjoDeTlaloc/0.1 (NASA Space Apps 2026 demo; frontend local)"
RE_TILE = re.compile(r"^/tiles/(\d{1,2})/(\d+)/(\d+)\.png$")
SALTAR = {"connection", "keep-alive", "transfer-encoding", "content-length", "server", "date"}
COMPRIMIBLES = ("text/", "application/json", "application/javascript", "image/svg")
ESTABLES = (".woff2", ".png", ".ico") + ("leaflet.min.js", "leaflet.min.css")  # cambian casi nunca

_gz = {}  # (ruta, mtime) -> bytes ya comprimidos


def _comprimible(tipo):
    return tipo.startswith(COMPRIMIBLES)


class Manejador(http.server.SimpleHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    wbufsize = 1 << 16          # encabezados y cuerpo salen juntos, sin esperar al ACK retardado

    def setup(self):
        super().setup()
        self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def log_message(self, fmt, *args):
        pass

    # ---- utilidades ------------------------------------------------------

    def _acepta_gzip(self):
        return "gzip" in (self.headers.get("Accept-Encoding") or "")

    def _responde(self, estado, tipo, datos, extra=(), comprimir=True):
        cab = list(extra)
        if comprimir and len(datos) > 600 and _comprimible(tipo) and self._acepta_gzip():
            datos = gzip.compress(datos, 5)
            cab.append(("Content-Encoding", "gzip"))
        self.send_response(estado)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Vary", "Accept-Encoding")
        for k, v in cab:
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(datos)

    def _es_api(self):
        return self.path.startswith(("/api/", "/salud", "/docs", "/openapi.json"))

    # ---- backend ---------------------------------------------------------

    def _reenvia(self):
        largo = int(self.headers.get("Content-Length") or 0)
        cuerpo = self.rfile.read(largo) if largo else None
        req = urllib.request.Request(BACKEND + self.path, data=cuerpo, method=self.command)
        if self.headers.get("Content-Type"):
            req.add_header("Content-Type", self.headers["Content-Type"])
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                estado, cab, datos = r.status, r.headers, r.read()
        except urllib.error.HTTPError as e:
            estado, cab, datos = e.code, e.headers, e.read()
        except (urllib.error.URLError, OSError) as e:
            self._responde(502, "application/json",
                           ('{"detail": "el backend no responde en %s: %s"}' % (BACKEND, e)).encode())
            return
        extra = [(k, v) for k, v in cab.items()
                 if k.lower() not in SALTAR | {"content-type", "vary", "content-encoding"}]
        self._responde(estado, cab.get("Content-Type", "application/json"), datos, extra)

    # ---- mosaicos --------------------------------------------------------

    def _tile(self, m):
        z, x, y = m.groups()
        ruta = os.path.join(CACHE, z, x, y + ".png")
        if not os.path.exists(ruta):
            req = urllib.request.Request("%s/%s/%s/%s.png" % (TILES, z, x, y), headers={"User-Agent": UA})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    datos = r.read()
            except (urllib.error.URLError, OSError):
                self._responde(502, "text/plain", b"sin acceso al mosaico")
                return
            os.makedirs(os.path.dirname(ruta), exist_ok=True)
            with open(ruta, "wb") as f:
                f.write(datos)
        with open(ruta, "rb") as f:
            datos = f.read()
        self._responde(200, "image/png", datos, [("Cache-Control", "public, max-age=86400")], comprimir=False)

    # ---- archivos del frontend ------------------------------------------

    def _estatico(self):
        ruta = self.translate_path(urllib.parse.urlsplit(self.path).path)
        if os.path.isdir(ruta):
            ruta = os.path.join(ruta, "index.html")
        if not os.path.isfile(ruta) or os.path.basename(ruta).startswith("."):
            self._responde(404, "text/plain; charset=utf-8", b"no existe")
            return
        tipo = mimetypes.guess_type(ruta)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo == "application/javascript":
            tipo += "; charset=utf-8"
        with open(ruta, "rb") as f:
            datos = f.read()
        estable = ruta.endswith(ESTABLES)
        cache = "public, max-age=86400" if estable else "no-cache"
        if _comprimible(tipo) and len(datos) > 600 and self._acepta_gzip():
            clave = (ruta, os.path.getmtime(ruta))
            if clave not in _gz:
                _gz[clave] = gzip.compress(datos, 6)
            self._responde(200, tipo, _gz[clave], [("Cache-Control", cache), ("Content-Encoding", "gzip")],
                           comprimir=False)
        else:
            self._responde(200, tipo, datos, [("Cache-Control", cache)], comprimir=False)

    # ---- metodos ---------------------------------------------------------

    def do_GET(self):
        m = RE_TILE.match(self.path)
        if m:
            self._tile(m)
        elif self._es_api():
            self._reenvia()
        else:
            self._estatico()

    do_HEAD = do_GET

    def do_POST(self):
        self._reenvia()


class Servidor(http.server.ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64


class ServidorDual(Servidor):
    """Escucha en IPv4 e IPv6. Windows resuelve 'localhost' a ::1 primero; si nadie escucha
    ahi, cada conexion (y las del tunel de VS Code) pierde de 0.2 a 2 s antes de caer a IPv4."""
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


if __name__ == "__main__":
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("font/woff2", ".woff2")
    try:
        srv = ServidorDual(("::", PUERTO), Manejador)
    except OSError:                      # sin IPv6 en este equipo
        srv = Servidor(("0.0.0.0", PUERTO), Manejador)
    print("Frontend en http://localhost:%d  ->  backend %s" % (PUERTO, BACKEND))
    srv.serve_forever()
