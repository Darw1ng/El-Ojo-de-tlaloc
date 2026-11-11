/* Mapa de la historia NISAR con Mapbox GL JS 3.8: imágenes de radar en dos ranuras
   que se funden entre fechas, lagunas de OSM coloreadas por firma de radar, hexágonos
   3D (altura = agua temporal; color = exposición o humedad de la fecha), escuelas/salud/
   emergencia, zona resaltada, etiquetas, base oscura o satelital, comparador con un
   segundo mapa sincronizado y recortado, y lectura de pixeles.bin para la serie HH/HV. */
(function () {
  const ESTILOS = {
    oscuro: 'mapbox://styles/mapbox/dark-v11',
    satelite: 'mapbox://styles/mapbox/satellite-streets-v12'
  };
  const OPACAS = new Set(['rgb', 'hh', 'hv', 'humedad']);
  const VACIO = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQYV2NgAAIAAAUAAarVyFEAAAAASUVORK5CYII=';
  const COLOR_GRUPO = ['match', ['get', 'grupo'], 'escuelas', '#b8860b', 'salud', '#db2777', 'emergencia', '#7c5cff', '#8a939a'];
  const COLOR_FIRMA = ['match', ['get', 'firma'], 'vegetacion sobre agua', '#4ade80', 'mixta', '#22d3ee', 'agua abierta', '#818cf8', '#a3abb1'];
  const COLOR_HEX = {
    agua: ['case', ['>', ['get', 'puntaje_exposicion'], 0], '#e8845a',
      ['interpolate', ['linear'], ['coalesce', ['feature-state', 'p'], 0], 0, '#27343b', 2, '#1d5f72', 10, '#1aa3bd', 30, '#22d3ee']],
    humedad: ['case', ['<', ['coalesce', ['feature-state', 'h'], -1], 0], '#2f363b',
      ['interpolate', ['linear'], ['feature-state', 'h'], 0, '#925e30', 0.35, '#d6b270', 0.6, '#6eaa78', 0.8, '#2896aa', 1, '#1e5ac8']]
  };
  const ALTURA_HEX = {
    agua: ['*', ['sqrt', ['coalesce', ['feature-state', 'p'], 0]], 160],
    humedad: ['*', ['sqrt', ['+', ['get', 'n_escuelas'], ['get', 'n_salud'], ['get', 'n_emergencia']]], 230]
  };
  const FUENTE_TXT = ['DIN Pro Medium', 'Arial Unicode MS Regular'];
  const VACIA = { type: 'FeatureCollection', features: [] };

  const M = {};
  let meta = null;
  let base = 'oscuro';
  let A = null;
  let B = null;
  let interactivo = false;
  let manejadores = {};
  const datos = { hex: null, pois: null, lugares: null, lagunas: null };
  const est = {
    capa: 'rgb', fecha: 0, pois: 'ninguno', zona: null, etiquetas: null, comparar: null,
    corte: 0.5, hexP: null, hexColor: 'humedad', laguna: null, lagunaSel: []
  };
  let hexAnim = 0;
  let pixeles = null;
  let popup = null;
  let resolverDatos;
  M.datosListos = new Promise((r) => { resolverDatos = r; });

  class Proyector {
    constructor(map) {
      this.map = map;
      this.slots = [null, null];
      this.activo = 0;
      this.url = null;
      this.tipo = null;
      this.turno = 0;
      this.opacidad = 1;
    }
    id(k) {
      return 'radar-' + k;
    }
    instalar(antes) {
      for (const k of [0, 1]) {
        if (this.map.getSource(this.id(k))) continue;
        this.map.addSource(this.id(k), { type: 'image', url: this.slots[k] || VACIO, coordinates: meta.imagen.esquinas });
        this.map.addLayer({
          id: this.id(k),
          type: 'raster',
          source: this.id(k),
          paint: {
            'raster-opacity': k === this.activo && this.url ? this.opacidad : 0,
            'raster-fade-duration': 0,
            'raster-resampling': 'linear',
            'raster-opacity-transition': { duration: 0, delay: 0 }
          }
        }, antes);
      }
      this.map.moveLayer(this.id(1 - this.activo), this.id(this.activo));
    }
    cargar(k, url) {
      return new Promise((res) => {
        const id = this.id(k);
        const map = this.map;
        const src = map.getSource(id);
        if (!src) return res(false);
        if (this.slots[k] === url) return res(true);
        let hecho = false;
        const oir = (e) => {
          if (e.sourceId === id && e.sourceDataType === 'metadata') fin(true);
        };
        const fin = (ok) => {
          if (hecho) return;
          hecho = true;
          map.off('sourcedata', oir);
          clearTimeout(t);
          res(ok);
        };
        const t = setTimeout(() => fin(true), 6000);
        map.on('sourcedata', oir);
        this.slots[k] = url;
        src.updateImage({ url });
      });
    }
    fundir(k, valor, duracion) {
      const id = this.id(k);
      if (!this.map.getLayer(id)) return;
      this.map.setPaintProperty(id, 'raster-opacity-transition', { duration: duracion, delay: 0 });
      this.map.setPaintProperty(id, 'raster-opacity', valor);
    }
    async mostrar(url, tipo, duracion) {
      const turno = ++this.turno;
      if (!url) {
        if (this.url) this.fundir(this.activo, 0, duracion);
        this.url = null;
        this.tipo = tipo;
        return;
      }
      if (url === this.url) {
        this.fundir(this.activo, this.opacidad, duracion);
        this.tipo = tipo;
        return;
      }
      let blob;
      try {
        blob = await (tipo === 'frecuencia' ? U.precargarSinNegro(url) : U.precargar(url));
      } catch (e) {
        if (manejadores.error) manejadores.error('imagen', url);
        return;
      }
      if (turno !== this.turno) return;
      const viejo = this.activo;
      const nuevo = !this.url && this.slots[viejo] === blob ? viejo : 1 - viejo;
      await this.cargar(nuevo, blob);
      if (turno !== this.turno || !this.map.getLayer(this.id(nuevo))) return;
      const encima = Boolean(this.url) && OPACAS.has(tipo) && OPACAS.has(this.tipo) && nuevo !== viejo;
      if (nuevo !== viejo) this.map.moveLayer(this.id(viejo), this.id(nuevo));
      this.fundir(nuevo, this.opacidad, duracion);
      if (nuevo !== viejo) {
        if (encima) {
          setTimeout(() => {
            if (this.activo !== viejo) this.fundir(viejo, 0, 0);
          }, duracion + 80);
        } else {
          this.fundir(viejo, 0, duracion);
        }
      }
      this.activo = nuevo;
      this.url = url;
      this.tipo = tipo;
    }
    fijarOpacidad(v) {
      this.opacidad = v;
      if (this.url) this.fundir(this.activo, v, 0);
    }
  }

  const capaRadar = (capa) => (capa === 'lagunas' ? 'rgb' : capa);

  function urlCapa(capa, fecha) {
    const c = capaRadar(capa);
    if (c === 'frecuencia') return meta.imagen.frecuencia ? 'datos/' + meta.imagen.frecuencia : null;
    const lista = meta.imagen.capas[c];
    return lista && lista[fecha] ? 'datos/' + lista[fecha] : null;
  }

  function primeraEtiqueta(map) {
    const capas = map.getStyle().layers || [];
    const s = capas.find((l) => l.type === 'symbol');
    return s ? s.id : undefined;
  }

  function crearMapa(contenedor, conControles) {
    const [w, s, e, n] = meta.bbox;
    const map = new mapboxgl.Map({
      container: contenedor,
      style: ESTILOS[base],
      projection: 'mercator',
      bounds: [[w, s], [e, n]],
      fitBoundsOptions: { padding: 24 },
      maxBounds: [[w - 0.45, s - 0.3], [e + 0.45, n + 0.3]],
      minZoom: 8.5,
      maxZoom: 17,
      maxPitch: 65,
      attributionControl: false,
      logoPosition: 'bottom-right',
      antialias: true,
      fadeDuration: 120,
      cooperativeGestures: false
    });
    map.addControl(new mapboxgl.AttributionControl({
      compact: true,
      customAttribution: 'NISAR: NASA/JPL-Caltech/ISRO · NASA POWER'
    }), 'bottom-right');
    const reg = { map, proyector: new Proyector(map), marcas: [], nav: null, conControles };
    reg.listo = new Promise((res, rej) => {
      map.once('load', () => res());
      map.once('error', (ev) => {
        if (!map.loaded()) rej(ev && ev.error ? ev.error : new Error('mapbox'));
      });
    });
    map.on('error', (ev) => {
      const st = ev && ev.error && ev.error.status;
      if (manejadores.error) manejadores.error(st === 401 || st === 403 ? 'token' : 'mapa', ev && ev.error);
    });
    map.on('style.load', () => instalar(reg));
    fijarInteraccion(reg, interactivo);
    return reg;
  }

  const OCULTAS = /road-label|road-number|road-exit|shield|path-pedestrian|golf|ferry|aerialway|poi-label|transit|building-number|block-number/;
  const PROPIAS = /^(radar|zona|lagunas|hex|pois)/;

  function campoIdioma(campo, idioma) {
    const txt = JSON.stringify(campo);
    const destino = idioma === 'es' ? 'name_es' : 'name_en';
    return JSON.parse(txt.replace(/"name_(en|es)"/g, '"' + destino + '"'));
  }

  function estilizarEtiquetas(map) {
    const capas = map.getStyle().layers || [];
    for (const l of capas) {
      if (l.type !== 'symbol' || PROPIAS.test(l.id)) continue;
      if (OCULTAS.test(l.id)) {
        map.setLayoutProperty(l.id, 'visibility', 'none');
        continue;
      }
      if (/subdivision|neighbo/.test(l.id)) map.setLayerZoomRange(l.id, 13.2, 24);
      const campo = map.getLayoutProperty(l.id, 'text-field');
      if (campo) map.setLayoutProperty(l.id, 'text-field', campoIdioma(campo, U.idioma()));
      map.setPaintProperty(l.id, 'text-color', '#eef0f1');
      map.setPaintProperty(l.id, 'text-halo-color', 'rgba(12, 14, 16, 0.92)');
      map.setPaintProperty(l.id, 'text-halo-width', 1.4);
      map.setPaintProperty(l.id, 'text-halo-blur', 0.3);
    }
  }

  function capasSimbolo(map) {
    try {
      const st = map.getStyle();
      return st && st.layers ? st.layers.filter((l) => l.type === 'symbol' && !PROPIAS.test(l.id)) : [];
    } catch (e) {
      return [];
    }
  }

  function ocultarLocalidades(map, ocultar) {
    for (const l of capasSimbolo(map)) {
      if (/settlement-(major|minor|subdivision)|airport-label/.test(l.id)) map.setLayoutProperty(l.id, 'visibility', ocultar ? 'none' : 'visible');
    }
  }

  function instalar(reg) {
    const map = reg.map;
    const antes = primeraEtiqueta(map);
    try {
      estilizarEtiquetas(map);
      ocultarLocalidades(map, Boolean(est.etiquetas));
    } catch (e) {
      if (manejadores.error) manejadores.error('estilo', e);
    }
    reg.proyector.instalar(antes);
    if (reg === A) {
      instalarVectoriales(map, antes);
      aplicarPois();
      aplicarZona();
      aplicarLagunas();
      hexVisible(est.capa === 'hex', true);
      if (est.capa === 'hex') alturasHex(est.fecha, 0);
    }
  }

  function instalarVectoriales(map, antes) {
    if (!map.getSource('zona')) map.addSource('zona', { type: 'geojson', data: VACIA });
    if (!map.getSource('lagunas')) map.addSource('lagunas', { type: 'geojson', data: datos.lagunas || VACIA, generateId: true });
    if (!map.getSource('hex')) map.addSource('hex', { type: 'geojson', data: datos.hex || VACIA, promoteId: 'id' });
    if (!map.getSource('pois')) map.addSource('pois', { type: 'geojson', data: datos.pois || VACIA, generateId: true });
    const expuesto = ['<=', ['coalesce', ['get', 'dist_agua_temporal_m'], 999999], (meta.exposicion && meta.exposicion.radio_m) || 200];
    M.expuesto = expuesto;
    const sel = ['boolean', ['feature-state', 'sel'], false];
    const capas = [
      {
        id: 'zona-halo', type: 'line', source: 'zona',
        paint: { 'line-color': '#22d3ee', 'line-width': 10, 'line-blur': 8, 'line-opacity': 0.35 }
      },
      {
        id: 'zona-borde', type: 'line', source: 'zona',
        paint: { 'line-color': '#f4f6f7', 'line-width': 1.5, 'line-opacity': 0.95 }
      },
      {
        id: 'lagunas-relleno', type: 'fill', source: 'lagunas',
        layout: { visibility: 'none' },
        paint: { 'fill-color': COLOR_FIRMA, 'fill-opacity': ['case', sel, 0.34, 0.16] }
      },
      {
        id: 'lagunas-halo', type: 'line', source: 'lagunas',
        layout: { visibility: 'none' },
        paint: { 'line-color': '#ffffff', 'line-width': ['case', sel, 7, 0], 'line-blur': 5, 'line-opacity': 0.35 }
      },
      {
        id: 'lagunas-casco', type: 'line', source: 'lagunas',
        layout: { visibility: 'none' },
        paint: {
          'line-color': '#0b0d0f', 'line-opacity': 0.85,
          'line-width': ['interpolate', ['linear'], ['zoom'], 11, ['case', sel, 4, 3], 15, ['case', sel, 5.5, 4.5]]
        }
      },
      {
        id: 'lagunas-borde', type: 'line', source: 'lagunas',
        layout: { visibility: 'none' },
        paint: {
          'line-color': ['case', sel, '#ffffff', COLOR_FIRMA],
          'line-width': ['interpolate', ['linear'], ['zoom'], 11, ['case', sel, 2, 1.1], 15, ['case', sel, 3, 2]]
        }
      },
      {
        id: 'hex', type: 'fill-extrusion', source: 'hex', filter: ['has', 'agua_pct'],
        layout: { visibility: 'none' },
        paint: {
          'fill-extrusion-height': ALTURA_HEX[est.hexColor],
          'fill-extrusion-base': 0,
          'fill-extrusion-color': COLOR_HEX[est.hexColor],
          'fill-extrusion-opacity': 0.9,
          'fill-extrusion-vertical-gradient': true
        }
      },
      {
        id: 'hex-borde', type: 'line', source: 'hex', filter: ['has', 'agua_pct'],
        layout: { visibility: 'none' },
        paint: { 'line-color': '#0f1214', 'line-width': 0.8, 'line-opacity': 0.8 }
      },
      {
        id: 'pois-halo', type: 'circle', source: 'pois', filter: expuesto,
        layout: { visibility: 'none' },
        paint: {
          'circle-color': '#ffffff', 'circle-opacity': 0.14, 'circle-blur': 0.4,
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 14, 15, 26]
        }
      },
      {
        id: 'pois', type: 'circle', source: 'pois',
        layout: { visibility: 'none' },
        paint: {
          'circle-color': COLOR_GRUPO,
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, ['case', expuesto, 6, 2.6], 15, ['case', expuesto, 11, 6.5]],
          'circle-stroke-color': ['case', expuesto, '#ffffff', '#0b0d0f'],
          'circle-stroke-width': ['case', expuesto, 2, 1],
          'circle-opacity': ['case', expuesto, 1, 0.88],
          'circle-stroke-opacity': ['case', expuesto, 1, 0.88]
        }
      },
      {
        id: 'pois-nombre', type: 'symbol', source: 'pois', filter: expuesto,
        layout: {
          visibility: 'none',
          'text-field': ['coalesce', ['get', 'nombre'], ''],
          'text-font': FUENTE_TXT,
          'text-size': 12.5,
          'text-anchor': 'top',
          'text-offset': [0, 1.1],
          'text-max-width': 12,
          'text-optional': true
        },
        paint: { 'text-color': '#f4f6f7', 'text-halo-color': '#0f1214', 'text-halo-width': 1.6 }
      }
    ];
    for (const c of capas) {
      if (!map.getLayer(c.id)) map.addLayer(c, c.type === 'symbol' ? undefined : antes);
    }
  }

  function fijarInteraccion(reg, si) {
    const map = reg.map;
    for (const h of ['scrollZoom', 'boxZoom', 'dragRotate', 'dragPan', 'keyboard', 'doubleClickZoom', 'touchZoomRotate', 'touchPitch']) {
      if (map[h]) si ? map[h].enable() : map[h].disable();
    }
    if (reg.conControles) {
      if (si && !reg.nav) {
        reg.nav = new mapboxgl.NavigationControl({ visualizePitch: true });
        map.addControl(reg.nav, 'top-right');
      } else if (!si && reg.nav) {
        map.removeControl(reg.nav);
        reg.nav = null;
      }
    }
  }

  function sincronizar() {
    let ocupado = false;
    const copiar = (de, a) => () => {
      if (ocupado || !est.comparar) return;
      ocupado = true;
      a.jumpTo({ center: de.getCenter(), zoom: de.getZoom(), bearing: de.getBearing(), pitch: de.getPitch(), padding: de.getPadding() });
      ocupado = false;
    };
    A.map.on('move', copiar(A.map, B.map));
    B.map.on('move', copiar(B.map, A.map));
  }

  function porcentajeTemporal(p, i) {
    if (!p.agua_pct) return 0;
    const perm = p.tierra_ha ? (p.permanente_ha || 0) / p.tierra_ha * 100 : 0;
    return Math.max(0, (p.agua_pct[i] || 0) - perm);
  }
  M.porcentajeTemporal = porcentajeTemporal;

  function alturasHex(fecha, duracion) {
    if (!datos.hex || !A || !A.map.getSource('hex')) return;
    const feats = datos.hex.features;
    for (const f of feats) {
      const h = f.properties.humedad_idx;
      A.map.setFeatureState({ source: 'hex', id: f.properties.id }, { h: h && h[fecha] != null ? h[fecha] : -1 });
    }
    const destino = feats.map((f) => porcentajeTemporal(f.properties, fecha));
    const origen = est.hexP && est.hexP.length === destino.length ? est.hexP : destino.map(() => 0);
    cancelAnimationFrame(hexAnim);
    const t0 = performance.now();
    const paso = (t) => {
      const k = duracion > 0 ? Math.min(1, (t - t0) / duracion) : 1;
      const e = 1 - Math.pow(1 - k, 3);
      est.hexP = origen.map((o, i) => o + (destino[i] - o) * e);
      for (let i = 0; i < feats.length; i++) {
        A.map.setFeatureState({ source: 'hex', id: feats[i].properties.id }, { p: est.hexP[i] });
      }
      if (k < 1) hexAnim = requestAnimationFrame(paso);
    };
    hexAnim = requestAnimationFrame(paso);
  }

  function hexVisible(si, inmediato) {
    if (!A || !A.map.getLayer('hex')) return;
    const map = A.map;
    const vis = si ? 'visible' : 'none';
    map.setPaintProperty('hex', 'fill-extrusion-color', COLOR_HEX[est.hexColor]);
    map.setPaintProperty('hex', 'fill-extrusion-height', ALTURA_HEX[est.hexColor]);
    if (map.getLayoutProperty('hex', 'visibility') !== vis) {
      map.setLayoutProperty('hex', 'visibility', vis);
      map.setLayoutProperty('hex-borde', 'visibility', vis);
      if (si && !inmediato) est.hexP = null;
    }
  }

  function aplicarPois() {
    if (!A || !A.map.getLayer('pois')) return;
    const map = A.map;
    const modo = est.pois;
    const ver = modo === 'todos' || modo === 'expuestos';
    const contexto = modo === 'expuestos' ? 0.42 : 0.88;
    map.setLayoutProperty('pois', 'visibility', ver ? 'visible' : 'none');
    map.setPaintProperty('pois', 'circle-opacity', ['case', M.expuesto, 1, contexto]);
    map.setPaintProperty('pois', 'circle-stroke-opacity', ['case', M.expuesto, 1, contexto]);
    map.setLayoutProperty('pois-halo', 'visibility', ver ? 'visible' : 'none');
    map.setLayoutProperty('pois-nombre', 'visibility', modo === 'expuestos' ? 'visible' : 'none');
  }

  function aplicarZona() {
    if (!A || !A.map.getSource('zona')) return;
    const z = est.zona;
    let data = VACIA;
    if (z && z.caja) {
      const [w, s, e, n] = z.caja;
      const m = 0.0025;
      data = { type: 'FeatureCollection', features: [{ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[[w - m, s - m], [e + m, s - m], [e + m, n + m], [w - m, n + m], [w - m, s - m]]] } }] };
    }
    A.map.getSource('zona').setData(data);
  }

  function aplicarLagunas() {
    if (!A || !A.map.getLayer('lagunas-borde')) return;
    const map = A.map;
    const ver = est.capa === 'lagunas' || Boolean(est.laguna);
    for (const id of ['lagunas-relleno', 'lagunas-halo', 'lagunas-casco', 'lagunas-borde']) map.setLayoutProperty(id, 'visibility', ver ? 'visible' : 'none');
    map.removeFeatureState({ source: 'lagunas' });
    for (const id of est.lagunaSel) map.setFeatureState({ source: 'lagunas', id }, { sel: true });
  }

  function indicesLaguna(nombre) {
    if (!datos.lagunas || !nombre) return [];
    const objetivo = String(nombre).trim().toLowerCase();
    const out = [];
    datos.lagunas.features.forEach((f, i) => {
      const n = f.properties.nombre;
      if (n && n.trim().toLowerCase() === objetivo) out.push(i);
    });
    return out;
  }

  function cajaDe(indices) {
    let w = Infinity;
    let s = Infinity;
    let e = -Infinity;
    let n = -Infinity;
    for (const i of indices) {
      const g = datos.lagunas.features[i].geometry;
      const anillos = g.type === 'Polygon' ? g.coordinates : g.coordinates.flat();
      for (const anillo of anillos) {
        for (const [x, y] of anillo) {
          if (x < w) w = x;
          if (x > e) e = x;
          if (y < s) s = y;
          if (y > n) n = y;
        }
      }
    }
    return Number.isFinite(w) ? [w, s, e, n] : null;
  }

  function ponerEtiquetas(reg, lista) {
    for (const m of reg.marcas) m.remove();
    reg.marcas = [];
    if (!lista) return;
    for (const e of lista) {
      if (!Number.isFinite(e.lon) || !Number.isFinite(e.lat)) continue;
      const cuerpo = U.el('span', { class: 'etq-cuerpo' }, U.el('span', { class: 'etq-punto' }), U.el('span', { class: 'etq-txt', text: U.loc(e.texto) }));
      const nodo = U.el('div', { class: 'etq-mapa' }, cuerpo);
      const mk = new mapboxgl.Marker({ element: nodo, anchor: 'center' }).setLngLat([e.lon, e.lat]).addTo(reg.map);
      reg.marcas.push(mk);
      requestAnimationFrame(() => requestAnimationFrame(() => cuerpo.classList.add('visible')));
    }
    orientarEtiquetas(reg);
    if (!reg.orientando) {
      reg.orientando = true;
      reg.map.on('moveend', () => orientarEtiquetas(reg));
    }
  }

  function orientarEtiquetas(reg) {
    if (!reg.marcas.length) return;
    const ancho = reg.map.getContainer().clientWidth;
    for (const mk of reg.marcas) {
      const el = mk.getElement();
      const txt = el.querySelector('.etq-txt');
      const p = reg.map.project(mk.getLngLat());
      const w = txt ? txt.offsetWidth : 120;
      el.classList.toggle('izq', p.x + 16 + w > ancho - 12 && p.x - 16 - w > 12);
    }
  }

  function rasgosEn(punto) {
    const capas = ['pois', 'lagunas-relleno', 'hex'].filter((id) => A.map.getLayer(id) && A.map.getLayoutProperty(id, 'visibility') === 'visible');
    const feats = capas.length ? A.map.queryRenderedFeatures(punto, { layers: capas }) : [];
    const poi = feats.find((f) => f.layer.id === 'pois');
    const lag = feats.find((f) => f.layer.id === 'lagunas-relleno');
    const hex = feats.find((f) => f.layer.id === 'hex');
    return {
      poi: poi && datos.pois ? datos.pois.features[poi.id] || null : null,
      laguna: lag && datos.lagunas ? { indice: lag.id, rasgo: datos.lagunas.features[lag.id] } : null,
      hex: hex && datos.hex ? datos.hex.features.find((f) => f.properties.id === hex.id) || null : null
    };
  }

  M.iniciar = async (opciones) => {
    meta = opciones.meta;
    base = opciones.base || 'oscuro';
    manejadores = opciones.manejadores || {};
    mapboxgl.accessToken = opciones.token;
    A = crearMapa(opciones.contenedor, true);
    A.map.on('click', (e) => {
      if (!interactivo || !manejadores.clic) return;
      manejadores.clic({ lngLat: e.lngLat, ...rasgosEn(e.point) });
    });
    A.map.on('mousemove', (e) => {
      if (!interactivo || !manejadores.flotar) return;
      const r = rasgosEn(e.point);
      A.map.getCanvas().style.cursor = r.poi || r.laguna ? 'pointer' : 'crosshair';
      manejadores.flotar({ punto: e.point, ...r });
    });
    A.map.on('mouseout', () => manejadores.flotar && manejadores.flotar(null));
    A.map.on('moveend', () => manejadores.movido && manejadores.movido());
    await A.listo;
    return A.map;
  };

  M.cargarDatos = async (metaInicial) => {
    if (!meta && metaInicial) meta = metaInicial;
    const leer = (n) => fetch('datos/' + n).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    const archivoLagunas = (meta.lagunas && meta.lagunas.archivo) || 'lagunas.geojson';
    const [hex, pois, lugares, lagunas] = await Promise.all([
      leer('hex.geojson'), leer('pois.geojson'), leer('lugares.geojson'), meta.lagunas ? leer(archivoLagunas) : Promise.resolve(null)
    ]);
    Object.assign(datos, { hex, pois, lugares, lagunas });
    if (A) {
      if (A.map.getSource('hex') && hex) A.map.getSource('hex').setData(hex);
      if (A.map.getSource('pois') && pois) A.map.getSource('pois').setData(pois);
      if (A.map.getSource('lagunas') && lagunas) A.map.getSource('lagunas').setData(lagunas);
    }
    if (est.laguna) est.lagunaSel = indicesLaguna(est.laguna);
    resolverDatos(datos);
    if (A) A.map.once('idle', aplicarLagunas);
    if (est.capa === 'hex') alturasHex(est.fecha, 0);
    return datos;
  };
  M.datos = () => datos;
  M.mapa = () => (A ? A.map : null);
  M.url = urlCapa;
  M.capaRadar = capaRadar;

  M.vista = (capa, fecha, opciones = {}) => {
    if (!A) return Promise.resolve();
    est.capa = capa;
    est.fecha = fecha;
    const d = opciones.duracion != null ? opciones.duracion : (U.reducido() ? 0 : 650);
    const promesa = A.proyector.mostrar(urlCapa(capa, fecha), capaRadar(capa), d);
    hexVisible(capa === 'hex');
    if (capa === 'hex') alturasHex(fecha, U.reducido() ? 0 : 700);
    aplicarLagunas();
    return promesa;
  };

  M.precargar = (capa, fecha) => {
    const u = meta ? urlCapa(capa, fecha) : null;
    if (u) (capaRadar(capa) === 'frecuencia' ? U.precargarSinNegro(u) : U.precargar(u)).catch(() => null);
  };

  M.opacidad = (v) => {
    if (A) A.proyector.fijarOpacidad(v);
    if (B) B.proyector.fijarOpacidad(v);
  };

  M.base = (b) => {
    if (!ESTILOS[b] || b === base) return;
    base = b;
    for (const reg of [A, B]) if (reg) reg.map.setStyle(ESTILOS[b], { diff: false });
  };
  M.baseActual = () => base;

  M.colorHex = (modo) => {
    est.hexColor = COLOR_HEX[modo] ? modo : 'humedad';
    if (A && A.map.getLayer('hex')) {
      A.map.setPaintProperty('hex', 'fill-extrusion-color', COLOR_HEX[est.hexColor]);
      A.map.setPaintProperty('hex', 'fill-extrusion-height', ALTURA_HEX[est.hexColor]);
    }
    return est.hexColor;
  };
  M.colorHexActual = () => est.hexColor;

  M.pois = (modo) => {
    est.pois = modo || 'ninguno';
    aplicarPois();
  };

  M.zona = (z) => {
    est.zona = z || null;
    aplicarZona();
  };

  M.laguna = (nombre) => {
    est.laguna = nombre || null;
    est.lagunaSel = indicesLaguna(est.laguna);
    aplicarLagunas();
    return est.lagunaSel.length ? cajaDe(est.lagunaSel) : null;
  };
  M.seleccionarLaguna = (indice) => {
    est.lagunaSel = indice == null ? indicesLaguna(est.laguna) : [indice];
    aplicarLagunas();
  };

  M.serieLaguna = (nombre) => {
    const idx = indicesLaguna(nombre);
    if (!idx.length) return null;
    return M.agregarLagunas(idx.map((i) => datos.lagunas.features[i]));
  };
  M.agregarLagunas = (rasgos) => {
    const n = meta.fechas.length;
    let area = 0;
    const lin = (db) => Math.pow(10, db / 10);
    const hh = new Array(n).fill(0);
    const hv = new Array(n).fill(0);
    const ab = new Array(n).fill(0);
    const firmas = {};
    for (const f of rasgos) {
      const p = f.properties;
      const a = p.area_ha || 0;
      area += a;
      firmas[p.firma] = (firmas[p.firma] || 0) + a;
      for (let t = 0; t < n; t++) {
        hh[t] += lin(p.hh_db[t]) * a;
        hv[t] += lin(p.hv_db[t]) * a;
        ab[t] += (p.agua_abierta_pct ? p.agua_abierta_pct[t] : 0) * a;
      }
    }
    if (!area) return null;
    const db = (v) => 10 * Math.log10(v / area);
    const p0 = rasgos[0].properties;
    return {
      nombre: p0.nombre,
      tipo: p0.tipo,
      subtipo: p0.subtipo,
      firma: Object.entries(firmas).sort((a, b) => b[1] - a[1])[0][0],
      area_ha: area,
      poligonos: rasgos.length,
      hh: hh.map(db),
      hv: hv.map(db),
      agua_abierta_pct: ab.map((v) => v / area)
    };
  };

  M.etiquetas = (lista) => {
    est.etiquetas = lista && lista.length ? lista : null;
    if (A) {
      ponerEtiquetas(A, est.etiquetas);
      ocultarLocalidades(A.map, Boolean(est.etiquetas));
    }
    if (B) {
      ponerEtiquetas(B, est.comparar ? est.etiquetas : null);
      ocultarLocalidades(B.map, Boolean(est.etiquetas));
    }
  };

  M.camara = (cam, opciones = {}) => {
    if (!A || !cam) return;
    const pad = opciones.padding || { top: 0, bottom: 0, left: 0, right: 0 };
    const o = { center: cam.center, zoom: cam.zoom, pitch: cam.pitch || 0, bearing: cam.bearing || 0, padding: pad };
    if (opciones.inmediato || U.reducido()) A.map.jumpTo(o);
    else A.map.flyTo({ ...o, duration: opciones.duracion || 2600, curve: 1.25, essential: false });
  };

  M.encuadre = (pad, extra = 28, caja = null, maxZoom = 16) => {
    if (!A) return null;
    const map = A.map;
    const cont = map.getContainer();
    const W = Math.max(120, cont.clientWidth - pad.left - pad.right - extra * 2);
    const H = Math.max(120, cont.clientHeight - pad.top - pad.bottom - extra * 2);
    const [w, s, e, n] = caja || meta.bbox;
    const a = mapboxgl.MercatorCoordinate.fromLngLat([w, n]);
    const b = mapboxgl.MercatorCoordinate.fromLngLat([e, s]);
    const dx = Math.max(b.x - a.x, 1e-9);
    const dy = Math.max(b.y - a.y, 1e-9);
    const zoom = Math.min(maxZoom, Math.log2(Math.min(W / (dx * 512), H / (dy * 512))));
    const c = new mapboxgl.MercatorCoordinate((a.x + b.x) / 2, (a.y + b.y) / 2).toLngLat();
    return { center: [c.lng, c.lat], zoom, pitch: 0, bearing: 0 };
  };

  M.relleno = (pad, duracion) => {
    if (!A) return;
    if (U.reducido() || !duracion) A.map.setPadding(pad);
    else A.map.easeTo({ padding: pad, duration: duracion });
  };

  M.camaraActual = () => {
    if (!A) return null;
    const m = A.map;
    const c = m.getCenter();
    return { center: [c.lng, c.lat], zoom: m.getZoom(), bearing: m.getBearing(), pitch: m.getPitch() };
  };

  M.interactivo = (si) => {
    interactivo = si;
    for (const reg of [A, B]) {
      if (!reg) continue;
      fijarInteraccion(reg, si);
      reg.map.getCanvas().setAttribute('tabindex', si ? '0' : '-1');
    }
    if (!si) {
      M.cerrarPopup();
      if (A) A.map.getCanvas().style.cursor = '';
    } else if (A) {
      A.map.getCanvas().style.cursor = 'crosshair';
    }
  };

  M.comparar = async (cfg) => {
    if (!A) return;
    est.comparar = cfg || null;
    const contB = document.getElementById('mapa-b');
    const cortina = document.getElementById('cortina');
    const asa = document.getElementById('cortina-asa');
    if (!cfg) {
      contB.hidden = true;
      cortina.hidden = true;
      asa.hidden = true;
      if (B) ponerEtiquetas(B, null);
      return;
    }
    contB.hidden = false;
    cortina.hidden = false;
    asa.hidden = false;
    M.corte(est.corte);
    if (!B) {
      B = crearMapa('mapa-b', false);
      sincronizar();
      try {
        await B.listo;
      } catch (e) {
        if (manejadores.error) manejadores.error('mapa', e);
        return;
      }
    } else {
      B.map.resize();
    }
    B.map.getCanvas().setAttribute('tabindex', interactivo ? '0' : '-1');
    if (!est.comparar) return;
    const m = A.map;
    B.map.jumpTo({ center: m.getCenter(), zoom: m.getZoom(), bearing: m.getBearing(), pitch: m.getPitch(), padding: m.getPadding() });
    B.proyector.fijarOpacidad(A.proyector.opacidad);
    B.proyector.mostrar(urlCapa(est.comparar.capa, est.comparar.j), capaRadar(est.comparar.capa), 0);
    ponerEtiquetas(B, est.etiquetas);
  };

  M.compararFechaB = (capa, j) => {
    if (!est.comparar) return;
    est.comparar = { ...est.comparar, capa, j };
    if (B) B.proyector.mostrar(urlCapa(capa, j), capaRadar(capa), U.reducido() ? 0 : 400);
  };

  M.corte = (f) => {
    est.corte = U.limitar(f, 0.04, 0.96);
    const x = Math.round(est.corte * window.innerWidth);
    document.documentElement.style.setProperty('--corte', x + 'px');
    const asa = document.getElementById('cortina-asa');
    if (asa) {
      asa.setAttribute('aria-valuenow', String(Math.round(est.corte * 100)));
      asa.setAttribute('aria-valuetext', Math.round(est.corte * 100) + ' %');
    }
    return est.corte;
  };
  M.corteActual = () => est.corte;

  M.cargarPixeles = () => {
    if (!pixeles) {
      pixeles = fetch('datos/' + meta.pixeles.archivo)
        .then((r) => {
          if (!r.ok) throw new Error('pixeles ' + r.status);
          return r.arrayBuffer();
        })
        .then((b) => new Uint8Array(b));
      pixeles.catch(() => { pixeles = null; });
    }
    return pixeles;
  };

  M.serieEn = async (lng, lat) => {
    const bytes = await M.cargarPixeles();
    const P = meta.pixeles;
    const n = meta.fechas.length;
    const W = P.ancho;
    const H = P.alto;
    const plano = W * H;
    if (bytes.length < (2 * n + 1) * plano) return null;
    const R = 6378137;
    const x = R * lng * Math.PI / 180;
    const y = R * Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
    const [x0, y0, x1, y1] = P.limites_3857;
    const anchoT = meta.imagen.ancho || W * P.paso;
    const altoT = meta.imagen.alto || H * P.paso;
    const col = Math.round(((x - x0) / (x1 - x0) * anchoT - 0.5) / P.paso);
    const fil = Math.round(((y1 - y) / (y1 - y0) * altoT - 0.5) / P.paso);
    if (col < 0 || fil < 0 || col >= W || fil >= H) return { fuera: true, lng, lat };
    const idx = fil * W + col;
    const [lo, hi] = P.cuantiza_db;
    const db = (v) => (v ? lo + (v - 1) / 254 * (hi - lo) : null);
    const hh = [];
    const hv = [];
    for (let t = 0; t < n; t++) {
      hh.push(db(bytes[t * plano + idx]));
      hv.push(db(bytes[(n + t) * plano + idx]));
    }
    const mascara = bytes[2 * n * plano + idx];
    const u = meta.umbrales || {};
    const agua = hh.map((v, t) => v != null && hv[t] != null && v < u.hh_db && hv[t] < u.hv_db);
    return { lng, lat, hh, hv, mascara, agua, fuera: hh.every((v) => v == null) };
  };

  M.lugarCercano = (lng, lat, maxKm = 2.5) => {
    if (!datos.lugares) return null;
    const kx = 111.32 * Math.cos(lat * Math.PI / 180);
    let mejor = null;
    let dmin = Infinity;
    for (const f of datos.lugares.features) {
      if (f.properties.clase !== 'lugar') continue;
      const [x, y] = f.geometry.coordinates;
      const d = Math.hypot((x - lng) * kx, (y - lat) * 110.57);
      if (d < dmin) {
        dmin = d;
        mejor = f.properties.nombre;
      }
    }
    return dmin <= maxKm ? mejor : null;
  };

  M.popup = (lngLat, nodo) => {
    if (!A) return null;
    if (!popup) {
      popup = new mapboxgl.Popup({ className: 'pp', maxWidth: 'none', closeButton: true, closeOnClick: false, focusAfterOpen: false, offset: 12 });
      popup.on('close', () => manejadores.popupCerrado && manejadores.popupCerrado());
    }
    popup.setLngLat(lngLat).setDOMContent(nodo);
    if (!popup.isOpen()) popup.addTo(A.map);
    return popup;
  };
  M.contenidoPopup = (nodo) => {
    if (popup && popup.isOpen()) popup.setDOMContent(nodo);
  };
  M.cerrarPopup = () => {
    if (popup && popup.isOpen()) popup.remove();
  };
  M.popupAbierto = () => Boolean(popup && popup.isOpen());

  M.idioma = () => {
    for (const reg of [A, B]) {
      if (!reg) continue;
      for (const l of capasSimbolo(reg.map)) {
        const campo = reg.map.getLayoutProperty(l.id, 'text-field');
        if (campo) reg.map.setLayoutProperty(l.id, 'text-field', campoIdioma(campo, U.idioma()));
      }
    }
  };

  M.redimensionar = () => {
    for (const reg of [A, B]) if (reg) reg.map.resize();
    M.corte(est.corte);
  };

  window.Mapa = M;
})();
