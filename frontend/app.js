/* El Ojo de Tláloc — cliente del contrato de docs/04-api.md.
   Sin build: Leaflet por CDN y JavaScript plano. */
(() => {
'use strict';

// La API se pide al mismo origen: servir.py reenvía /api al backend, así que basta exponer
// un solo puerto. ?api=URL apunta a otro backend a mano (p. ej. con http.server a secas).
const API = (new URLSearchParams(location.search).get('api') || location.origin).replace(/\/$/, '');

/* ------------------------------------------------------------------ util */

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const esNum = (v) => typeof v === 'number' && Number.isFinite(v);
const MESES = ['ene', 'feb', 'mar', 'abr', 'may', 'jun', 'jul', 'ago', 'sep', 'oct', 'nov', 'dic'];
const DIAS = ['D', 'L', 'M', 'M', 'J', 'V', 'S'];

function fechaCorta(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return `${d} ${MESES[m - 1]}`;
}
function diaSemana(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return DIAS[new Date(y, m - 1, d).getDay()];
}
function sumaDias(iso, n) {
  const [y, m, d] = iso.split('-').map(Number);
  const f = new Date(y, m - 1, d + n);
  return `${f.getFullYear()}-${String(f.getMonth() + 1).padStart(2, '0')}-${String(f.getDate()).padStart(2, '0')}`;
}

let pendientes = 0;
function ocupado(delta) {
  pendientes += delta;
  $('#progreso').hidden = pendientes <= 0;
}

class ErrorApi extends Error {
  constructor(status, msg) { super(msg); this.status = status; }
}

async function api(ruta, opciones) {
  ocupado(1);
  try {
    const r = await fetch(API + ruta, opciones);
    if (!r.ok) {
      let detalle = r.statusText;
      try {
        const j = await r.json();
        detalle = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail);
      } catch (_) { /* cuerpo sin JSON */ }
      throw new ErrorApi(r.status, detalle);
    }
    return await r.json();
  } finally {
    ocupado(-1);
  }
}

let temporizadorAviso;
function aviso(texto, ms = 6000) {
  const a = $('#aviso');
  a.textContent = texto;
  a.hidden = false;
  clearTimeout(temporizadorAviso);
  temporizadorAviso = setTimeout(() => { a.hidden = true; }, ms);
}

/* --------------------------------------------------------------- paletas */

// Rampas para fondo oscuro (valores bajos oscuros); la API sólo dice el nombre y el dominio.
const RAMPAS = {
  azules:        ['#162c38', '#1d5a78', '#2f8cb0', '#69b9d0', '#b4e0e5', '#f0f8f4'],
  calidos:       ['#2a3a52', '#3f6f8f', '#c9b45a', '#f09a3e', '#e2503a', '#a3182f'],
  cafes_verdes:  ['#7a4a22', '#b58545', '#d9c27c', '#8fc08a', '#3f9f86', '#14705f'],
  morados:       ['#231a2e', '#512b63', '#8a2f78', '#c9437e', '#ef7b6a', '#fbc79b'],
  naranjas:      ['#2a2216', '#664218', '#a86f1e', '#dd9a2f', '#f1c76a', '#fbeec4'],
  amarillo_rojo: ['#1c242b', '#5b6a35', '#cfae38', '#ee8230', '#d9432f', '#9a1432'],
  verde_rojo:    ['#2a7f5c', '#8dc16a', '#f0cf5a', '#ee7f45', '#b5222f'],
};
const CATEGORIAS = [
  { n: 'bajo', c: '#3f9970' },
  { n: 'moderado', c: '#e0bb40' },
  { n: 'alto', c: '#ee7f35' },
  { n: 'muy alto', c: '#d3303a' },
];

const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
function mezcla(a, b, t) {
  const A = hex(a), B = hex(b);
  return '#' + A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, '0')).join('');
}
function muestrea(rampa, u) {
  const t = Math.min(1, Math.max(0, u)) * (rampa.length - 1);
  const i = Math.min(rampa.length - 2, Math.floor(t));
  return mezcla(rampa[i], rampa[i + 1], t - i);
}
// posición 0..1 de v dentro de un dominio de n cortes; cada tramo pesa igual.
function posicion(v, dominio) {
  const n = dominio.length;
  if (v <= dominio[0]) return 0;
  if (v >= dominio[n - 1]) return 1;
  for (let i = 0; i < n - 1; i++) {
    if (v <= dominio[i + 1]) return (i + (v - dominio[i]) / (dominio[i + 1] - dominio[i])) / (n - 1);
  }
  return 1;
}
function colorEscala(v, escala) {
  const rampa = RAMPAS[escala.paleta] || RAMPAS.azules;
  return muestrea(rampa, posicion(v, escala.dominio));
}

/* ----------------------------------------------------------------- estado */

const VARIABLES = [
  { id: 'lluvia',        nombre: 'Lluvia',            u: 'mm/día',     umbral: 50,  dec: 1 },
  { id: 'tmax',          nombre: 'Temp. máxima',      u: '°C',         umbral: 34,  dec: 1 },
  { id: 'tmin',          nombre: 'Temp. mínima',      u: '°C',         umbral: 24,  dec: 1 },
  { id: 'humedad_suelo', nombre: 'Humedad del suelo', u: 'saturación', umbral: 0.8, dec: 2 },
  { id: 'escurrimiento', nombre: 'Escurrimiento',     u: 'mm/día',     umbral: 15,  dec: 1 },
  { id: 'et0',           nombre: 'Evapotransp. ref.', u: 'mm/día',     umbral: 6,   dec: 1 },
];
const ESTADISTICOS = ['p10', 'p25', 'p50', 'p75', 'p90', 'p99', 'media', 'desv', 'rango'];
const SERIES_CELDA = ['lluvia', 'tmax', 'tmin', 'humedad_suelo'];

const E = {
  area: null,
  escalas: null,
  malla: null,
  nivel: 0,
  run: null,          // { id, resumen }
  dia: 0,
  capa: { modo: 'valor', variable: 'lluvia', stat: 'p50', umbral: 50, ventana: 3, umbralRiesgo: 60 },
  seleccion: null,
  cacheCapas: new Map(),
  cacheCelda: new Map(),
  actual: null,       // capa del día visible
  serieCelda: 'lluvia',
};

const meta = (id) => VARIABLES.find((v) => v.id === id);

/* -------------------------------------------------------------------- mapa */

let mapa, capaHex, poligonos = new Map(), indice = new Map();

function iniciaMapa() {
  mapa = L.map('mapa', { zoomControl: false, zoomSnap: 0.25, attributionControl: false, preferCanvas: true });
  L.control.zoom({ position: 'topleft' }).addTo(mapa);
  // Los mosaicos pasan por servir.py (/tiles): OSM bloquea las peticiones que llegan desde otros
  // orígenes (túneles, dominios) con un 403, y así salen del servidor con su propio User-Agent.
  // Si el servidor no tiene /tiles (p. ej. http.server a secas), cae al mosaico público de OSM.
  const capaTiles = L.tileLayer(location.origin + '/tiles/{z}/{x}/{y}.png', { className: 'tiles', maxZoom: 17 }).addTo(mapa);
  let cayo = false;
  capaTiles.on('tileerror', () => {
    if (cayo) return;
    cayo = true;
    capaTiles.setUrl(E.area.mosaico_sugerido);
  });
  mapa.on('click', () => cierraCelda());
}

function encuadra() {
  if (capaHex) { mapa.fitBounds(capaHex.getBounds(), { padding: [24, 24] }); return; }
  const b = E.area.bbox;
  mapa.fitBounds([[b.lat_min, b.lon_min], [b.lat_max, b.lon_max]], { padding: [24, 24] });
}

function dibujaMalla() {
  if (capaHex) mapa.removeLayer(capaHex);
  poligonos = new Map();
  indice = new Map(E.malla.features.map((f, i) => [f.properties.id, i]));
  const render = L.canvas({ padding: 0.3 });
  capaHex = L.geoJSON(E.malla, {
    renderer: render,
    style: estiloCelda,
    onEachFeature: (f, capa) => {
      poligonos.set(f.properties.id, capa);
      capa.bindTooltip(() => textoTip(f.properties), { sticky: true, className: 'tip', direction: 'top', opacity: 1 });
      capa.on('click', (ev) => { L.DomEvent.stopPropagation(ev); seleccionaCelda(f.properties.id); });
      capa.on('mouseover', () => { if (E.seleccion !== f.properties.id) capa.setStyle({ weight: 2, color: '#e7e9eb' }); });
      capa.on('mouseout', () => capaHex.resetStyle(capa));
    },
  }).addTo(mapa);
}

function valorEn(id) {
  if (!E.actual) return null;
  const i = indice.get(id);
  const v = E.actual.valores[i];
  return esNum(v) ? v : null;
}

function colorCelda(id) {
  const a = E.actual;
  if (!a) return null;
  const i = indice.get(id);
  if (E.capa.modo === 'riesgo') {
    const c = a.categoria?.[i];
    return c >= 0 && CATEGORIAS[c] ? CATEGORIAS[c].c : null;
  }
  const v = a.valores[i];
  if (!esNum(v)) return null;
  return colorEscala(v, escalaVigente());
}

function estiloCelda(f) {
  const id = f.properties.id;
  const color = colorCelda(id);
  const sel = id === E.seleccion;
  if (color) {
    return { fillColor: color, fillOpacity: 0.72, color: sel ? '#ffffff' : 'rgba(20,23,26,.7)', weight: sel ? 3 : 0.8, dashArray: null };
  }
  // sin dominio (mar para humedad/escurrimiento): relleno nulo, nunca un 0 pintado
  return { fillColor: '#000', fillOpacity: 0, color: sel ? '#ffffff' : 'rgba(231,233,235,.25)', weight: sel ? 3 : 0.7, dashArray: sel ? null : '2 4' };
}

function repinta() {
  poligonos.forEach((capa) => capa.setStyle(estiloCelda(capa.feature)));
  if (E.seleccion && poligonos.has(E.seleccion)) poligonos.get(E.seleccion).bringToFront();
}

function textoTip(p) {
  const v = valorEn(p.id);
  const tierra = p.es_tierra ? '' : ' <span class="mar">· mar</span>';
  let cuerpo;
  if (!E.actual) cuerpo = '';
  else if (v === null) cuerpo = '<br><span class="mar">no aplica</span>';
  else cuerpo = `<br>${formato(v)} ${esc(unidadVigente())}` +
    (E.capa.modo === 'riesgo' ? ` · ${esc(E.actual.etiqueta_categoria?.[indice.get(p.id)] ?? '')}` : '');
  return `<b>${esc(p.id)}</b>${tierra}${cuerpo}`;
}

/* --------------------------------------------------------------- capa activa */

function escalaVigente() {
  const a = E.actual?.escala;
  if (E.capa.modo === 'prob') {
    return { dominio: a?.dominio || [0, 0.1, 0.3, 0.6, 0.8, 1], paleta: 'amarillo_rojo', unidad: '%' };
  }
  return a;
}
function unidadVigente() {
  if (E.capa.modo === 'valor') return E.actual?.escala?.unidad || meta(E.capa.variable).u;
  return '%';
}
function formato(v) {
  if (E.capa.modo !== 'valor') return (v * 100).toFixed(v < 0.1 && v > 0 ? 1 : 0);
  return v.toFixed(meta(E.capa.variable).dec);
}

function urlCapa(dia) {
  const { modo, variable, stat, umbral, ventana, umbralRiesgo } = E.capa;
  const id = encodeURIComponent(E.run.id);
  if (modo === 'valor') return `/api/corrida/${id}/capa?variable=${variable}&dia=${dia}&estadistico=${stat}`;
  if (modo === 'prob') return `/api/corrida/${id}/probabilidad?variable=${variable}&dia=${dia}&umbral=${umbral}&ventana_dias=${ventana}`;
  return `/api/corrida/${id}/riesgo?dia=${dia}&ventana_dias=${ventana}&umbral_mm=${umbralRiesgo}`;
}

function capaDia(dia) {
  const url = urlCapa(dia);
  if (!E.cacheCapas.has(url)) {
    const p = api(url).catch((e) => { E.cacheCapas.delete(url); throw e; });
    E.cacheCapas.set(url, p);
  }
  return E.cacheCapas.get(url);
}

async function muestraDia(dia) {
  if (!E.run) return;
  E.dia = dia;
  try {
    const capa = await capaDia(dia);
    if (E.dia !== dia) return;
    E.actual = capa;
    repinta();
    pintaLeyenda();
    marcaBarra();
    if (E.seleccion) { pintaAbanico(); pintaObra(); }
  } catch (e) {
    manejaError(e);
  }
}

async function refrescaCapa() {
  if (!E.run) return;
  E.actual = null;
  const dia = E.dia;
  await muestraDia(dia);
  pintaBarras();
}

function manejaError(e) {
  if (e instanceof ErrorApi && e.status === 404 && /corrida|pronostico/i.test(e.message)) {
    aviso('La corrida expiró en el servidor. Vuelvo a calcularla.');
    corre();
    return;
  }
  aviso(e.message || String(e));
}

/* ----------------------------------------------------------------- leyenda */

function pintaLeyenda() {
  const cont = $('#leyenda');
  const a = E.actual;
  if (!a) { cont.innerHTML = ''; return; }
  if (E.capa.modo === 'riesgo') {
    cont.innerHTML = `
      <div class="ley-tit"><span class="etq">${esc(a.escala?.etiqueta || 'Riesgo')}</span></div>
      <div class="cats">
        ${CATEGORIAS.map((c) => `<div><i style="background:${c.c}"></i>${c.n}</div>`).join('')}
        <div><i class="na"></i>no aplica (mar)</div>
      </div>`;
    return;
  }
  const esc_ = escalaVigente();
  const rampa = RAMPAS[esc_.paleta] || RAMPAS.azules;
  const paradas = rampa.map((c, i) => `${c} ${(i / (rampa.length - 1) * 100).toFixed(1)}%`).join(',');
  const etiqueta = E.capa.modo === 'valor'
    ? (a.escala?.etiqueta || meta(E.capa.variable).nombre)
    : `P(${meta(E.capa.variable).nombre.toLowerCase()} > ${E.capa.umbral})`;
  const fmt = (d) => (E.capa.modo === 'prob' ? Math.round(d * 100) + '%' : String(d));
  cont.innerHTML = `
    <div class="ley-tit"><span class="etq">${esc(etiqueta)}</span><span>${esc(unidadVigente())}</span></div>
    <div class="barra-color" style="background:linear-gradient(90deg,${paradas})"></div>
    <div class="ticks">${esc_.dominio.map((d) => `<span>${fmt(d)}</span>`).join('')}</div>`;
}

/* ---------------------------------------------------------- línea de tiempo */

async function pintaBarras() {
  const cont = $('#barras');
  if (!E.run) return;
  const fechas = E.run.resumen.fechas;
  cont.innerHTML = fechas.map((f, i) => `
    <div class="barra" data-dia="${i}" title="${fechaCorta(f)}">
      <span class="v"></span>
      <div class="col" style="height:2px"></div>
      <div class="d">${diaSemana(f)}<br>${f.slice(8)}</div>
    </div>`).join('');
  cont.querySelectorAll('.barra').forEach((b) => b.addEventListener('click', () => muestraDia(Number(b.dataset.dia))));
  marcaBarra();

  const run = E.run.id;
  const dominio = fechas.map((_, i) => capaDia(i).then(promedio, () => null));
  const medias = await Promise.all(dominio);
  if (!E.run || E.run.id !== run) return;
  E.medias = medias;
  const max = Math.max(...medias.filter(esNum), 1e-9) * 1.08;
  cont.querySelectorAll('.barra').forEach((b, i) => {
    const m = medias[i];
    const col = $('.col', b);
    col.style.height = esNum(m) ? `${Math.max(3, (m / max) * 100 * 0.7)}%` : '2px';
    $('.v', b).textContent = esNum(m) ? formato(m) : '';
  });
}

function promedio(capa) {
  const v = capa.valores.filter(esNum);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

function marcaBarra() {
  document.querySelectorAll('#barras .barra').forEach((b) => b.classList.toggle('on', Number(b.dataset.dia) === E.dia));
  if (!E.run) return;
  const f = E.run.resumen.fechas[E.dia];
  $('#tl-fecha').textContent = f ? `${fechaCorta(f)}` : '—';
  const nombre = E.capa.modo === 'riesgo' ? 'Riesgo' : meta(E.capa.variable).nombre;
  $('#tl-titulo').textContent = `Día ${E.dia + 1} · ${nombre}`;
  const m = E.medias?.[E.dia];
  $('#tl-valor').textContent = esNum(m) ? `media del dominio ${formato(m)} ${unidadVigente()}` : '';
}

let reproduciendo = null;
function alternaPlay() {
  const boton = $('#b-play');
  if (reproduciendo) {
    clearInterval(reproduciendo); reproduciendo = null; boton.classList.remove('on');
    boton.innerHTML = '<svg viewBox="0 0 16 16"><path d="M4 2.5v11l9-5.5z"/></svg>';
    return;
  }
  boton.classList.add('on');
  boton.innerHTML = '<svg viewBox="0 0 16 16"><path d="M3.5 2h3.2v12H3.5zM9.3 2h3.2v12H9.3z"/></svg>';
  reproduciendo = setInterval(() => {
    const n = E.run.resumen.fechas.length;
    muestraDia((E.dia + 1) % n);
  }, 900);
}

/* ------------------------------------------------------------------ corrida */

async function corre() {
  const boton = $('#b-correr');
  boton.disabled = true;
  boton.textContent = 'Calculando…';
  try {
    const nivel = Number($('#f-nivel').value);
    const miembros = Number($('#f-miembros').value);
    const semilla = $('#f-semilla').value === '' ? null : Number($('#f-semilla').value);
    const fecha = $('#f-fecha').value;
    const cuerpo = {
      fecha_inicio: fecha,
      dias: Number($('#f-dias').value),
      miembros, nivel, semilla,
      humedad_inicial: null,
      id_asimilacion: null,
    };

    $('#asim').hidden = true;
    if ($('#f-radar').checked) {
      const asim = await api('/api/asimilar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ fecha: sumaDias(fecha, -1), nivel, miembros, semilla, sintetica: true }),
      });
      cuerpo.id_asimilacion = asim.id_asimilacion;
      muestraAsimilacion(asim.diagnostico);
    }

    if (nivel !== E.nivel || !E.malla) await cargaMalla(nivel);

    const r = await api('/api/pronostico', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(cuerpo),
    });
    if (r.aviso) aviso(r.aviso, 9000);
    E.run = { id: r.id_corrida, resumen: r.resumen };
    E.cacheCapas.clear();
    E.cacheCelda.clear();
    E.medias = null;
    E.dia = Math.min(E.dia, r.resumen.dias - 1);
    $('#expo').innerHTML = '';
    muestraResumen(r.resumen);
    await muestraDia(E.dia);
    pintaBarras();
    if (E.seleccion) { pintaCeldaDatos(); }
  } catch (e) {
    aviso(e.message || String(e), 9000);
  } finally {
    boton.disabled = false;
    boton.textContent = 'Correr ensamble';
  }
}

function muestraResumen(r) {
  const cont = $('#resumen');
  const { p10, p50, p90 } = r.lluvia_total_mm;
  const max = p90 * 1.12;
  cont.hidden = false;
  cont.innerHTML = `
    <span class="etq">Lluvia acumulada · ${r.dias} días</span>
    <div class="gran">${Math.round(p50)}<small>mm · mediana</small></div>
    <div class="rango">
      <i style="left:${(p10 / max) * 100}%;width:${((p90 - p10) / max) * 100}%"></i>
      <b style="left:${(p50 / max) * 100}%"></b>
    </div>
    <div class="rango-etq"><span>P10 ${Math.round(p10)}</span><span>P90 ${Math.round(p90)}</span></div>
    <dl class="filas">
      <dt>Día más lluvioso</dt><dd>${fechaCorta(r.fechas[r.dia_mas_lluvioso])}</dd>
      <dt>Tmax P90</dt><dd>${r.tmax_p90_c} °C</dd>
      <dt>Suelo al final</dt><dd>${Math.round(r.humedad_suelo_p50_final * 100)} % sat.</dd>
      <dt>Ensamble</dt><dd>${r.miembros} miembros · ${r.segundos_calculo.toFixed(2)} s</dd>
      <dt>Semilla</dt><dd>${r.semilla ?? 'aleatoria'}</dd>
    </dl>`;
  $('#escala-txt').textContent = r.escala;
}

function muestraAsimilacion(d) {
  const cont = $('#asim');
  cont.hidden = false;
  const pct = (x) => `${(x * 100).toFixed(0)} %`;
  cont.innerHTML = `
    <div class="fuente">${esc(d.fuente)}</div>
    <dl class="filas">
      <dt>Celdas observadas</dt><dd>${d.celdas_observadas} / ${d.celdas_totales}</dd>
      <dt>Peso del radar</dt><dd>${pct(d.ganancia_media)}</dd>
      <dt>Incertidumbre quitada</dt><dd>${pct(d.reduccion_varianza_media)}</dd>
      <dt>Corrección media</dt><dd>${d.incremento_medio > 0 ? '+' : ''}${d.incremento_medio.toFixed(3)}</dd>
    </dl>`;
}

async function cargaMalla(nivel) {
  const m = await api(`/api/malla?nivel=${nivel}`);
  E.malla = m;
  E.nivel = nivel;
  E.seleccion = null;
  $('#der').hidden = true;
  dibujaMalla();
  encuadra();
}

/* ---------------------------------------------------------- controles capa */

function pintaVariables() {
  const lista = $('#l-vars');
  lista.innerHTML = VARIABLES.map((v, i) => `
    <li data-v="${v.id}" class="${v.id === E.capa.variable ? 'on' : ''}">
      <span class="n">0${i + 1}</span><span class="t">${v.nombre}</span><span class="u">${v.u}</span>
    </li>`).join('');
  lista.querySelectorAll('li').forEach((li) => li.addEventListener('click', () => {
    E.capa.variable = li.dataset.v;
    E.capa.umbral = meta(li.dataset.v).umbral;
    $('#f-umbral').value = E.capa.umbral;
    if (SERIES_CELDA.includes(li.dataset.v)) E.serieCelda = li.dataset.v;
    sincronizaControles();
    refrescaCapa();
  }));
  $('#s-stat').innerHTML = ESTADISTICOS.map((s) => `<button data-s="${s}" class="${s === E.capa.stat ? 'on' : ''}">${s}</button>`).join('');
  $('#s-stat').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    E.capa.stat = b.dataset.s;
    sincronizaControles();
    refrescaCapa();
  }));
}

function sincronizaControles() {
  const { modo } = E.capa;
  document.querySelectorAll('#s-modo button').forEach((b) => b.classList.toggle('on', b.dataset.modo === modo));
  document.querySelectorAll('#l-vars li').forEach((li) => li.classList.toggle('on', li.dataset.v === E.capa.variable));
  document.querySelectorAll('#s-stat button').forEach((b) => b.classList.toggle('on', b.dataset.s === E.capa.stat));
  $('#l-vars').hidden = modo === 'riesgo';
  $('#c-stat').hidden = modo !== 'valor';
  $('#c-umbral').hidden = modo === 'valor';
  const v = meta(E.capa.variable);
  $('#u-unidad').textContent = modo === 'riesgo' ? '(mm de escurrimiento)' : `(${v.u})`;
  $('#f-umbral').value = modo === 'riesgo' ? E.capa.umbralRiesgo : E.capa.umbral;
  $('#n-modo').textContent = modo === 'riesgo'
    ? 'Probabilidad de que el escurrimiento acumulado pase el umbral. Sobre el mar no aplica: esas celdas quedan sin pintar.'
    : 'P(variable > umbral) en cada celda. Lluvia, escurrimiento y ET0 se acumulan en la ventana; temperatura y suelo toman el máximo.';
}

function enlazaControles() {
  document.querySelectorAll('#s-modo button').forEach((b) => b.addEventListener('click', () => {
    E.capa.modo = b.dataset.modo;
    sincronizaControles();
    refrescaCapa();
  }));
  $('#f-umbral').addEventListener('change', (ev) => {
    const x = Number(ev.target.value);
    if (!(x > 0)) return;
    if (E.capa.modo === 'riesgo') E.capa.umbralRiesgo = x; else E.capa.umbral = x;
    refrescaCapa();
  });
  $('#f-ventana').addEventListener('change', (ev) => { E.capa.ventana = Number(ev.target.value); refrescaCapa(); });
  $('#b-correr').addEventListener('click', corre);
  $('#b-play').addEventListener('click', alternaPlay);
  $('#x-der').addEventListener('click', cierraCelda);
  $('#b-expo').addEventListener('click', cruzaExposicion);
  $('#b-pie').addEventListener('click', () => {
    const t = $('#pie-txt');
    t.hidden = !t.hidden;
    $('#b-pie').setAttribute('aria-expanded', String(!t.hidden));
  });
  $('#f-nivel').addEventListener('change', () => { corre(); });
  document.addEventListener('keydown', (ev) => {
    if (/INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName || '')) return;
    if (ev.key === 'Escape') cierraCelda();
    if (!E.run) return;
    const n = E.run.resumen.fechas.length;
    if (ev.key === 'ArrowRight') muestraDia(Math.min(n - 1, E.dia + 1));
    if (ev.key === 'ArrowLeft') muestraDia(Math.max(0, E.dia - 1));
    if (ev.key === ' ') { ev.preventDefault(); alternaPlay(); }
  });
}

/* --------------------------------------------------------------- una celda */

function seleccionaCelda(id) {
  E.seleccion = id;
  $('#der').hidden = false;
  repinta();
  pintaCeldaDatos();
}

function cierraCelda() {
  if (!E.seleccion) return;
  E.seleccion = null;
  $('#der').hidden = true;
  repinta();
}

async function pintaCeldaDatos() {
  const id = E.seleccion;
  if (!id || !E.run) return;
  const props = E.malla.features[indice.get(id)].properties;
  $('#c-id').textContent = id;
  $('#c-geo').innerHTML = [
    props.es_tierra ? '<b>tierra</b>' : '<b class="mar">mar</b>',
    `${props.lat.toFixed(3)}°, ${props.lon.toFixed(3)}°`,
    props.es_tierra ? `<b>${Math.round(props.elevacion_m)} m</b> <small>(sintética)</small>` : '',
    props.dist_costa_km !== undefined ? `costa a ${Math.abs(props.dist_costa_km).toFixed(0)} km` : '',
  ].filter(Boolean).join(' · ');

  $('#s-serie').innerHTML = SERIES_CELDA.map((v) =>
    `<button data-v="${v}" class="${v === E.serieCelda ? 'on' : ''}">${meta(v).nombre.split(' ')[0]}${v === 'tmax' ? ' máx' : v === 'tmin' ? ' mín' : ''}</button>`).join('');
  $('#s-serie').querySelectorAll('button').forEach((b) => b.addEventListener('click', () => {
    E.serieCelda = b.dataset.v;
    $('#s-serie').querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b));
    pintaAbanico();
  }));

  const clave = `${E.run.id}|${id}`;
  if (!E.cacheCelda.has(clave)) {
    const serie = api(`/api/corrida/${encodeURIComponent(E.run.id)}/celda/${encodeURIComponent(id)}`);
    const obra = props.es_tierra
      ? api(`/api/corrida/${encodeURIComponent(E.run.id)}/ventanas?id_celda=${encodeURIComponent(id)}`).catch(() => null)
      : Promise.resolve(null);
    E.cacheCelda.set(clave, Promise.all([serie, obra]).then(([s, o]) => ({ serie: s, obra: o })));
  }
  try {
    const datos = await E.cacheCelda.get(clave);
    if (E.seleccion !== id) return;
    E.datosCelda = datos;
    pintaAbanico();
    pintaObra();
  } catch (e) {
    E.cacheCelda.delete(clave);
    manejaError(e);
  }
}

function pintaAbanico() {
  const cont = $('#abanico');
  const d = E.datosCelda?.serie;
  if (!d) { cont.innerHTML = ''; return; }
  const v = d.variables[E.serieCelda];
  const m = meta(E.serieCelda);
  const nota = $('#n-abanico');
  const lleno = v && [...(v.p50 || [])].some(esNum);
  if (!lleno) {
    cont.innerHTML = `<div class="vacio">${esc(m.nombre)} no existe sobre el mar.<br>No es cero: es “no aplica”.</div>`;
    nota.textContent = '';
    return;
  }
  const n = d.fechas.length;
  const W = 328, H = 168, mg = { l: 36, r: 6, t: 8, b: 22 };
  const miembros = v.miembros_muestra || [];
  const todos = [...v.p10, ...v.p90, ...miembros.flat()].filter(esNum);
  let lo = Math.min(...todos), hi = Math.max(...todos);
  if (E.serieCelda === 'lluvia' || E.serieCelda === 'humedad_suelo') lo = Math.min(lo, 0);
  const pad = (hi - lo) * 0.06 || 1;
  hi += pad; if (lo !== 0) lo -= pad;
  const X = (i) => mg.l + (i * (W - mg.l - mg.r)) / Math.max(1, n - 1);
  const Y = (x) => mg.t + (1 - (x - lo) / (hi - lo)) * (H - mg.t - mg.b);
  const linea = (arr) => arr.map((x, i) => (esNum(x) ? `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(x).toFixed(1)}` : '')).join('');
  const banda = v.p90.map((x, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(x).toFixed(1)}`).join('') +
    [...v.p10].map((x, i) => [x, i]).reverse().map(([x, i]) => `L${X(i).toFixed(1)},${Y(x).toFixed(1)}`).join('') + 'Z';
  const ticks = [0, 0.5, 1].map((t) => lo + (hi - lo) * t);
  const dec = m.dec;
  cont.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Abanico de ${esc(m.nombre)}">
      ${ticks.map((t) => `<line x1="${mg.l}" x2="${W - mg.r}" y1="${Y(t)}" y2="${Y(t)}" stroke="#2b3136" stroke-width="1"/>
        <text x="${mg.l - 5}" y="${Y(t) + 3}" text-anchor="end">${t.toFixed(dec)}</text>`).join('')}
      <path d="${banda}" fill="#78bfdc" opacity=".12"/>
      ${miembros.map((s) => `<path d="${linea(s)}" fill="none" stroke="#78bfdc" stroke-width=".8" opacity=".3"/>`).join('')}
      <path d="${linea(v.p10)}" fill="none" stroke="#78bfdc" stroke-width="1" stroke-dasharray="2 3" opacity=".8"/>
      <path d="${linea(v.p90)}" fill="none" stroke="#78bfdc" stroke-width="1" stroke-dasharray="2 3" opacity=".8"/>
      <path d="${linea(v.p50)}" fill="none" stroke="#f0a070" stroke-width="2.2"/>
      <line x1="${X(E.dia)}" x2="${X(E.dia)}" y1="${mg.t}" y2="${H - mg.b}" stroke="#e7e9eb" stroke-width="1"/>
      <circle cx="${X(E.dia)}" cy="${Y(v.p50[E.dia])}" r="3.6" fill="#f0a070" stroke="#1b1f23" stroke-width="1.5"/>
      <text x="${mg.l}" y="${H - 6}">${fechaCorta(d.fechas[0])}</text>
      <text x="${W - mg.r}" y="${H - 6}" text-anchor="end">${fechaCorta(d.fechas[n - 1])}</text>
    </svg>`;
  const act = v.p50[E.dia], a10 = v.p10[E.dia], a90 = v.p90[E.dia];
  nota.innerHTML = `<b style="color:var(--tinta)">${fechaCorta(d.fechas[E.dia])}</b> · mediana ${act?.toFixed(dec)} ${esc(v.unidad || m.u)} (P10 ${a10?.toFixed(dec)} – P90 ${a90?.toFixed(dec)}).
    Cada línea fina es un futuro posible y coherente del ensamble; la banda es el intervalo P10–P90.`;
}

function pintaObra() {
  const cont = $('#obra');
  const o = E.datosCelda?.obra;
  if (!E.seleccion) return;
  const props = E.malla.features[indice.get(E.seleccion)].properties;
  if (!props.es_tierra) { cont.innerHTML = '<p class="nota">Mar: no hay obra que programar.</p>'; return; }
  if (!o) { cont.innerHTML = '<p class="nota">Sin calendario para esta celda.</p>'; return; }
  const rampa = ['#8f3b2c', '#b9782f', '#c9b24a', '#78ad6a', '#3f9f78'];
  const filas = (o.actividades || []).map((a) => {
    const dias = a.por_dia.map((p, i) => {
      const f = o.fechas[i];
      if (!esNum(p)) return `<i class="sin" title="${fechaCorta(f)}: no aplica"></i>`;
      return `<i class="${i === E.dia ? 'hoy' : ''}" style="background:${muestrea(rampa, p)}" title="${fechaCorta(f)}: ${Math.round(p * 100)} % trabajable"></i>`;
    }).join('');
    return `<div class="obra-fila">
      <div class="cab"><span>${esc(a.etiqueta)}</span><span><b>${(a.dias_trabajables_esperados ?? 0).toFixed(1)}</b> de ${o.horizonte_dias} días</span></div>
      <div class="dias">${dias}</div>
    </div>`;
  }).join('');
  const omit = (o.omitidas || []).length
    ? `<p class="nota">No evaluadas: ${o.omitidas.map((x) => esc(x.etiqueta || x.actividad)).join(', ')}.</p>` : '';
  const adv = (o.advertencias || []).map((x) => `<p class="nota">${esc(typeof x === 'string' ? x : (x.detalle || x.mensaje || JSON.stringify(x)))}</p>`).join('');
  cont.innerHTML = `<div class="obra">${filas}</div>
    <p class="nota">Color: probabilidad de que el día sea trabajable, de rojo (nada) a verde (casi seguro). Los umbrales son de práctica constructiva, no una norma.</p>${omit}${adv}`;
}

/* -------------------------------------------------------------- exposición */

async function cruzaExposicion() {
  if (!E.run) return;
  const cont = $('#expo');
  const boton = $('#b-expo');
  boton.disabled = true;
  cont.innerHTML = `<p class="cargando">Cruzando con OpenStreetMap. La <em>primera vez</em> baja edificios y vías de Overpass y puede tardar varios minutos; después sale del caché.</p>`;
  try {
    const pide = (corte) => api(`/api/corrida/${encodeURIComponent(E.run.id)}/exposicion?` + new URLSearchParams({
      nivel: E.nivel, dia: E.dia, ventana_dias: E.capa.ventana, umbral_mm: E.capa.umbralRiesgo, corte,
    }));
    let r = await pide(0.3);
    // si ninguna celda llega al corte, se baja a 10 % para que haya algo que ver, y se dice
    if (r.corte_inalcanzable) r = await pide(0.1);
    pintaExposicion(r);
  } catch (e) {
    cont.innerHTML = `<p class="cargando">No se pudo: ${esc(e.message)}</p>`;
  } finally {
    boton.disabled = false;
  }
}

function pintaExposicion(r) {
  const cont = $('#expo');
  const elementos = Object.values(r.elementos || {});
  const prioridad = (r.celdas_prioritarias || []).slice(0, 8);
  const n = (x) => Math.round(x).toLocaleString('es-MX');
  const cifras = elementos.slice(0, 4).map((e) =>
    `<div><b>${n(e.expuesto)}</b><span>${esc(e.etiqueta)}<br>de ${n(e.total_dominio)} en el dominio</span></div>`).join('');
  const filas = prioridad.map((c) => {
    const txt = Object.entries(c.equipamientos || {}).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${v} ${k}`).join(' · ');
    return `<tr class="pick" data-id="${esc(c.id_celda)}"><td>${esc(c.id_celda)}
      <span class="desg">${n(c.edificios)} edificios · ${n(c.infraestructura_critica)} críticos</span>
      ${txt ? `<span class="desg">${esc(txt)}</span>` : ''}</td>
      <td>${esNum(c.probabilidad) ? Math.round(c.probabilidad * 100) + ' %' : ''}</td></tr>`;
  }).join('');
  const adv = (r.advertencias || []).map((x) => `<p class="nota">${esc(typeof x === 'string' ? x : (x.detalle || x.mensaje || JSON.stringify(x)))}</p>`).join('');
  const sinCorte = r.corte < 0.3
    ? `<p class="nota alerta">Ninguna celda llega a 30 %: el máximo del dominio es ${Math.round(r.probabilidad_maxima_dominio * 100)} %. Se bajó el corte a ${Math.round(r.corte * 100)} % para mostrar exposición.</p>` : '';
  cont.innerHTML = `
    <p class="nota">${esc(typeof r.resumen === 'string' ? r.resumen : '')}</p>
    ${sinCorte}
    <div class="cifras">${cifras}</div>
    ${filas ? `<table><thead><tr><th>Celdas prioritarias · clic para ir</th><th>P</th></tr></thead><tbody>${filas}</tbody></table>` : ''}
    ${adv}`;
  cont.querySelectorAll('tr.pick').forEach((tr) => tr.addEventListener('click', () => {
    const id = tr.dataset.id;
    seleccionaCelda(id);
    const capa = poligonos.get(id);
    if (capa) mapa.flyToBounds(capa.getBounds(), { maxZoom: 11, duration: 0.7, paddingTopLeft: [340, 0], paddingBottomRight: [380, 0] });
  }));
}

/* ------------------------------------------------------------------ arranque */

// Una URL como ?modo=riesgo&dia=3&celda=OT0.0.1 reproduce la vista exacta.
function aplicaEnlace() {
  const q = new URLSearchParams(location.search);
  const modo = q.get('modo');
  if (['valor', 'prob', 'riesgo'].includes(modo)) E.capa.modo = modo;
  const v = q.get('variable');
  if (v && meta(v)) { E.capa.variable = v; E.capa.umbral = meta(v).umbral; if (SERIES_CELDA.includes(v)) E.serieCelda = v; }
  if (ESTADISTICOS.includes(q.get('stat'))) E.capa.stat = q.get('stat');
  if (q.get('dia')) E.dia = Math.max(0, Number(q.get('dia')) || 0);
  sincronizaControles();
}

async function arranca() {
  pintaVariables();
  enlazaControles();
  sincronizaControles();
  try {
    const [area, escalas] = await Promise.all([api('/api/area'), api('/api/escalas')]);
    E.area = area;
    E.escalas = escalas;
    iniciaMapa();
    encuadra();
    api('/api/climatologia?mes=0').then((c) => {
      if (c.nota) $('#proc-clima').innerHTML = `<b>Sintético</b> climatología base. ${esc(c.nota)}`;
    }).catch(() => {});
    aplicaEnlace();
    await corre();
    const celda = new URLSearchParams(location.search).get('celda');
    if (celda && indice.has(celda)) seleccionaCelda(celda);
  } catch (e) {
    aviso(`No encuentro la API en ${API}. Arranca el backend con: uvicorn ojo_tlaloc.api.app:app --port 8000`, 20000);
  }
}

addEventListener('resize', () => { if (mapa) { mapa.invalidateSize(); } });
arranca();
})();
