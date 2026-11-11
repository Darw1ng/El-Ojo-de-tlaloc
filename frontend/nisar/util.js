/* Utilidades de la historia NISAR: idioma y textos con respaldo en español, formatos
   de fecha y número por idioma, estado en el hash de la URL, localStorage protegido,
   constructores de nodos DOM/SVG y caché de imágenes como blobs (una sola descarga
   por archivo, que luego Mapbox toma por URL de objeto). */
(function () {
  const U = {};
  const textos = { es: {}, en: {} };
  let idioma = 'es';

  U.idioma = () => idioma;
  U.fijarIdioma = (l) => {
    idioma = l === 'en' ? 'en' : 'es';
    document.documentElement.lang = idioma;
  };
  U.agregarTextos = (fuente) => {
    if (!fuente || typeof fuente !== 'object') return;
    for (const l of ['es', 'en']) if (fuente[l]) Object.assign(textos[l], fuente[l]);
  };
  U.t = (clave, vars) => {
    let s = textos[idioma][clave];
    if (s == null) s = textos.es[clave];
    if (s == null) return clave;
    if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] != null ? vars[k] : m));
    return s;
  };
  U.loc = (v) => {
    if (v == null) return '';
    if (typeof v === 'object') return v[idioma] != null ? v[idioma] : (v.es != null ? v.es : (v.en || ''));
    return String(v);
  };

  const locale = () => (idioma === 'en' ? 'en-US' : 'es-MX');
  const formatos = new Map();
  const formato = (clave, crear) => {
    const k = locale() + '|' + clave;
    if (!formatos.has(k)) formatos.set(k, crear());
    return formatos.get(k);
  };
  const ESTILOS_FECHA = {
    larga: { day: 'numeric', month: 'short', year: 'numeric' },
    corta: { day: 'numeric', month: 'short' },
    completa: { day: 'numeric', month: 'long', year: 'numeric' },
    mes: { month: 'short' }
  };
  const aFecha = (iso) => new Date(iso + 'T12:00:00Z');
  U.fecha = (iso, estilo = 'larga') =>
    formato('f' + estilo, () => new Intl.DateTimeFormat(locale(), { ...ESTILOS_FECHA[estilo], timeZone: 'UTC' }))
      .format(aFecha(iso)).replace(/\./g, '');
  U.num = (v, dec = 0) =>
    formato('n' + dec, () => new Intl.NumberFormat(locale(), { minimumFractionDigits: dec, maximumFractionDigits: dec }))
      .format(v);
  U.firmado = (v, dec = 1) => (v < 0 ? '−' : v > 0 ? '+' : '') + U.num(Math.abs(v), dec);
  U.decimales = (v) => {
    const s = String(v);
    return s.includes('.') ? s.split('.')[1].length : 0;
  };
  U.dias = (a, b) => Math.round((aFecha(b) - aFecha(a)) / 864e5);
  U.sumarDias = (iso, d) => new Date(aFecha(iso).getTime() + d * 864e5).toISOString().slice(0, 10);
  U.limitar = (v, a, b) => Math.max(a, Math.min(b, v));
  U.esperar = (ms) => new Promise((r) => setTimeout(r, ms));
  const consultaMovimiento = window.matchMedia('(prefers-reduced-motion: reduce)');
  U.reducido = () => consultaMovimiento.matches;
  U.estrecho = () => window.matchMedia('(max-width: 760px)').matches;

  U.leer = (k) => {
    try { return window.localStorage.getItem(k); } catch (e) { return null; }
  };
  U.guardar = (k, v) => {
    try { window.localStorage.setItem(k, v); } catch (e) { return false; }
    return true;
  };

  U.hash = {
    leer() {
      return new URLSearchParams(window.location.hash.replace(/^#/, ''));
    },
    escribir(obj) {
      const p = new URLSearchParams();
      for (const [k, v] of Object.entries(obj)) {
        if (v != null && v !== '' && v !== false) p.set(k, v);
      }
      const h = p.toString().replace(/%2C/g, ',');
      const base = window.location.pathname + window.location.search;
      const nueva = base + (h ? '#' + h : '');
      if (nueva !== base + window.location.hash) window.history.replaceState(null, '', nueva);
    }
  };

  U.el = (tag, attrs, ...hijos) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') n.className = v;
      else if (k === 'text') n.textContent = v;
      else if (k === 'html') n.innerHTML = v;
      else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
      else if (k === 'style' && typeof v === 'object') Object.assign(n.style, v);
      else n.setAttribute(k, v === true ? '' : v);
    }
    for (const h of hijos.flat(3)) {
      if (h == null || h === false) continue;
      n.append(h.nodeType ? h : document.createTextNode(String(h)));
    }
    return n;
  };
  const NS = 'http://www.w3.org/2000/svg';
  U.svg = (tag, attrs, ...hijos) => {
    const n = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'text') n.textContent = v;
      else n.setAttribute(k, v);
    }
    for (const h of hijos.flat(3)) if (h) n.append(h);
    return n;
  };

  const blobs = new Map();
  U.precargar = (url) => {
    if (!blobs.has(url)) {
      const p = fetch(url)
        .then((r) => {
          if (!r.ok) throw new Error(url + ' ' + r.status);
          return r.blob();
        })
        .then((b) => URL.createObjectURL(b));
      p.catch(() => blobs.delete(url));
      blobs.set(url, p);
    }
    return blobs.get(url);
  };

  const limpias = new Map();
  U.precargarSinNegro = (url) => {
    if (!limpias.has(url)) {
      const p = fetch(url)
        .then((r) => {
          if (!r.ok) throw new Error(url + ' ' + r.status);
          return r.blob();
        })
        .then((b) => createImageBitmap(b))
        .then((bmp) => {
          const c = document.createElement('canvas');
          c.width = bmp.width;
          c.height = bmp.height;
          const g = c.getContext('2d', { willReadFrequently: true });
          g.drawImage(bmp, 0, 0);
          const img = g.getImageData(0, 0, c.width, c.height);
          const d = img.data;
          for (let i = 0; i < d.length; i += 4) {
            if (d[i] < 6 && d[i + 1] < 6 && d[i + 2] < 6) d[i + 3] = 0;
          }
          g.putImageData(img, 0, 0);
          return new Promise((res, rej) => c.toBlob((bl) => (bl ? res(URL.createObjectURL(bl)) : rej(new Error('toBlob'))), 'image/png'));
        });
      p.catch(() => limpias.delete(url));
      limpias.set(url, p);
    }
    return limpias.get(url);
  };

  window.U = U;
})();
