/* Orquesta la historia NISAR de El Ojo de Tláloc: datos, portada con
   time-lapse, capítulos con scrollytelling (IntersectionObserver, flyTo, cifras y
   gráficas), explorador con capas, línea de tiempo, comparador, serie por punto o
   laguna, equipamientos y leyenda; idioma ES/EN, estado en el hash y créditos.
   Un capítulo puede añadir base: 'satelite' y hex: 'humedad'|'agua' al esquema. */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const ORDEN_CAPAS = ['rgb', 'hh', 'hv', 'agua', 'cambio', 'humedad', 'frecuencia', 'lagunas', 'hex'];
  const SIN_FECHA = new Set(['frecuencia']);
  const NO_COMPARABLES = new Set(['frecuencia', 'hex']);
  const S = {
    modo: 'historia', capa: 'rgb', fecha: 0, base: 'oscuro', pois: 'ninguno', hexColor: 'humedad',
    comparar: false, cmpDer: null, opacidad: 1, capitulo: null, contexto: 'portada',
    anim: null, etiquetas: null, popup: null, animables: false
  };
  let meta = null;
  let capitulos = [];
  let linea = null;
  let mapaListo = false;
  let scrollGuardado = 0;
  let tHash = 0;
  let avisoMapa = false;
  const animados = new Set();
  const n = () => meta.fechas.length;
  const nombreCapa = (c) => U.t('capa_' + c);
  const capasDisponibles = () => ORDEN_CAPAS.filter((c) => {
    if (c === 'frecuencia') return Boolean(meta.imagen.frecuencia);
    if (c === 'lagunas') return Boolean(meta.lagunas);
    if (c === 'hex') return Boolean(meta.hex);
    return Boolean(meta.imagen.capas[c]);
  });
  const comparable = (c) => !NO_COMPARABLES.has(c);
  const fechaCorta = (i) => U.fecha(meta.fechas[i], 'larga');

  function aplicarTextos() {
    for (const nodo of $$('[data-t]')) nodo.textContent = U.t(nodo.dataset.t);
    for (const nodo of $$('[data-t-aria]')) nodo.setAttribute('aria-label', U.t(nodo.dataset.tAria));
    for (const b of $$('.idioma button')) b.setAttribute('aria-pressed', String(b.dataset.lang === U.idioma()));
    $('#b-explorar').textContent = S.modo === 'explorar' ? U.t('nav_historia') : U.t('nav_explorar');
  }

  function mostrarAviso(tipo, bloqueante) {
    const av = $('#aviso');
    const nodos = [U.el('strong', { text: U.t('err_' + tipo + '_tit') }), U.el('p', { html: U.t('err_' + tipo) })];
    if (!bloqueante) nodos.push(U.el('button', { type: 'button', class: 'btn-txt', text: U.t('cerrar'), onclick: () => { av.hidden = true; } }));
    av.replaceChildren(...nodos);
    av.classList.toggle('bloqueante', Boolean(bloqueante));
    av.hidden = false;
  }

  function errorMapa(tipo) {
    if (tipo === 'token') {
      $('#cargando').hidden = true;
      mostrarAviso('tokenmalo', true);
      actualizarChip();
    } else if (tipo === 'imagen') {
      if (!avisoMapa) mostrarAviso('imagen', false);
      avisoMapa = true;
    }
  }

  function paddingHistoria() {
    const W = window.innerWidth;
    const H = window.innerHeight;
    if (U.estrecho()) return { top: 64, bottom: Math.round(H * 0.46), left: 12, right: 12 };
    const t = $('.tarjeta');
    const r = t ? t.getBoundingClientRect() : null;
    const izq = r && r.width ? Math.round(r.right + 28) : 520;
    return { top: 76, bottom: 36, left: Math.min(izq, Math.round(W * 0.55)), right: 36 };
  }
  function paddingPortada() {
    const W = window.innerWidth;
    const H = window.innerHeight;
    if (U.estrecho()) return { top: 64, bottom: Math.round(H * 0.5), left: 0, right: 0 };
    return { top: 64, bottom: 24, left: Math.min(Math.round(W * 0.42), 640), right: 24 };
  }
  function paddingExplorador() {
    if (U.estrecho()) return { top: 112, bottom: 156, left: 0, right: 0 };
    return { top: 70, bottom: 150, left: 356, right: 64 };
  }
  function ajustarCamara(cam, pad) {
    const visW = window.innerWidth - pad.left - pad.right;
    const visH = window.innerHeight - pad.top - pad.bottom;
    const k = Math.min(visW / 900, visH / 760);
    const dz = Math.max(-1.8, Math.min(0, Math.log2(k)));
    return { ...cam, zoom: cam.zoom + dz };
  }
  function corteCentral(pad) {
    const W = window.innerWidth;
    return (pad.left + (W - pad.left - pad.right) / 2) / W;
  }

  function numeroAnimable(etiqueta, valor, dec, hecho) {
    return U.el(etiqueta, { class: 'num-anim' },
      U.el('span', { class: 'num-fantasma', 'aria-hidden': 'true', text: U.num(valor, dec) }),
      U.el('span', { class: 'num-vivo', 'data-valor': valor, 'data-dec': dec, text: U.num(hecho ? valor : 0, dec) }));
  }

  function rellenarPortada() {
    const f0 = meta.fechas[0];
    const fN = meta.fechas[n() - 1];
    $('#portada-sub').textContent = U.t('portada_sub', { n: n(), desde: U.fecha(f0, 'completa'), hasta: U.fecha(fN, 'completa') });
    const lluvia = meta.lluvia.diaria.filter((d) => d.fecha >= f0 && d.fecha <= fN).reduce((a, d) => a + (d.mm || 0), 0);
    const cifras = [
      { v: n(), dec: 0, u: U.t('portada_c1') },
      { v: U.dias(f0, fN), dec: 0, u: U.t('portada_c2') },
      { v: Math.round(lluvia), dec: 0, u: U.t('portada_c3') }
    ];
    const dl = $('#portada-cifras');
    dl.replaceChildren(...cifras.map((c) => U.el('div', { class: 'cifra-gran' },
      U.el('dt', {}, numeroAnimable('span', c.v, c.dec, animados.has('portada') || U.reducido())),
      U.el('dd', { text: c.u }))));
  }

  function animarCifras(raiz, clave) {
    const nodos = $$('[data-valor]', raiz);
    const ya = animados.has(clave);
    animados.add(clave);
    for (const b of nodos) {
      const v = parseFloat(b.dataset.valor);
      const dec = parseInt(b.dataset.dec || '0', 10);
      if (!Number.isFinite(v)) continue;
      if (ya || U.reducido() || v === 0) {
        b.textContent = U.num(v, dec);
        continue;
      }
      const t0 = performance.now();
      const dur = 1100;
      const paso = (t) => {
        const k = Math.min(1, (t - t0) / dur);
        const e = 1 - Math.pow(1 - k, 3);
        b.textContent = U.num(k < 1 ? v * e : v, dec);
        if (k < 1) requestAnimationFrame(paso);
      };
      requestAnimationFrame(paso);
    }
  }

  function construirHistoria() {
    const cont = $('#pasos');
    cont.replaceChildren();
    capitulos.forEach((cap, k) => {
      const sec = U.el('section', { class: 'paso', id: 'cap-' + cap.id, 'data-cap': cap.id, 'aria-labelledby': 't-' + cap.id });
      const art = U.el('article', { class: 'tarjeta' });
      sec.append(art);
      cont.append(sec);
      llenarTarjeta(art, cap, k);
    });
  }

  function llenarTarjeta(art, cap, k) {
    const capa = cap.capa && cap.capa !== 'base' ? nombreCapa(cap.capa) : null;
    const nodos = [
      U.el('p', { class: 'num' }, U.el('span', { text: U.t('capitulo_n', { n: k + 1, total: capitulos.length }) }), capa ? U.el('span', { class: 'num-capa', text: capa }) : null),
      U.el('h2', { id: 't-' + cap.id, text: U.loc(cap.titulo) }),
      U.el('div', { class: 'texto', html: U.loc(cap.texto) })
    ];
    if (cap.cifras && cap.cifras.length) {
      const hecho = animados.has(cap.id) || U.reducido();
      nodos.push(U.el('div', { class: 'cifras' }, cap.cifras.map((c) => {
        const num = typeof c.valor === 'number' ? c.valor : parseFloat(c.valor);
        const dec = U.decimales(c.valor);
        const v = Number.isFinite(num) ? numeroAnimable('b', num, dec, hecho) : U.el('b', { text: String(c.valor) });
        const unidad = U.loc(c.unidad);
        return U.el('div', { class: 'cifra' },
          U.el('p', { class: 'cifra-v' }, v, unidad ? U.el('span', { class: 'u', text: unidad }) : null),
          U.el('p', { class: 'cifra-t', text: U.loc(c.texto) }));
      })));
    }
    if (cap.grafica) {
      const caja = U.el('div', { class: 'grafica' });
      nodos.push(caja);
      if (cap.grafica === 'laguna') {
        caja.classList.add('esperando');
        Mapa.datosListos.then(() => {
          const g = Graficas.tarjeta('laguna', meta, { laguna: Mapa.serieLaguna(cap.laguna), actual: Number.isInteger(cap.fecha) ? cap.fecha : null });
          caja.classList.remove('esperando');
          if (g) caja.replaceChildren(g);
        });
      } else {
        const g = Graficas.tarjeta(cap.grafica, meta);
        if (g) caja.append(g);
        else caja.remove();
      }
    }
    if (cap.comparar) {
      nodos.push(U.el('p', { class: 'pista-cmp', text: U.t('cmp_pista', { a: fechaCorta(cap.comparar[0]), b: fechaCorta(cap.comparar[1]) }) }));
    }
    art.replaceChildren(...nodos);
  }

  function actualizarChip(ping) {
    const chip = $('#chip');
    if (!meta || !mapaListo || S.modo === 'explorar') {
      chip.hidden = true;
      return;
    }
    chip.hidden = false;
    let txt;
    if (S.comparar && S.cmpDer != null && S.modo === 'historia') {
      txt = `${U.fecha(meta.fechas[S.fecha], 'corta')} ↔ ${U.fecha(meta.fechas[S.cmpDer], 'larga')} · ${nombreCapa(S.capa)}`;
    } else if (SIN_FECHA.has(S.capa)) {
      txt = `${U.t('chip_temporada', { n: n() })} · ${nombreCapa(S.capa)}`;
    } else if (S.capa === 'base') {
      txt = U.t('capa_base');
    } else {
      txt = `${fechaCorta(S.fecha)} · ${U.t('chip_pasada', { i: S.fecha + 1, n: n() })} · ${nombreCapa(S.capa)}`;
    }
    $('#chip-txt').textContent = txt;
    const play = $('#chip-play');
    play.hidden = !S.animables;
    play.replaceChildren(U.svg('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' }, U.svg('path', { d: S.anim ? 'M7 4.5h3.6v15H7zM13.4 4.5H17v15h-3.6z' : 'M7 4.5v15l12-7.5z' })));
    play.setAttribute('aria-label', S.anim ? U.t('anim_pausa') : U.t('anim_play'));
    if (ping && !U.reducido()) {
      const p = $('#chip-punto');
      p.classList.remove('pinga');
      void p.offsetWidth;
      p.classList.add('pinga');
    }
  }

  function detenerAnim() {
    S.anim = null;
  }

  async function bucleAnim(token) {
    while (S.anim === token) {
      await U.esperar(1700);
      if (S.anim !== token) return;
      S.fecha = (S.fecha + 1) % n();
      Mapa.precargar(S.capa, (S.fecha + 1) % n());
      await Mapa.vista(S.capa, S.fecha, { duracion: 900 });
      if (S.anim !== token) return;
      actualizarChip(true);
    }
  }

  function iniciarAnim() {
    const token = Symbol('anim');
    S.anim = token;
    Mapa.precargar(S.capa, (S.fecha + 1) % n());
    actualizarChip();
    bucleAnim(token);
  }

  function alternarAnim() {
    if (S.anim) detenerAnim();
    else iniciarAnim();
    actualizarChip();
  }

  function activarSeccion(sec) {
    if (S.modo !== 'historia' || !meta) return;
    for (const s of $$('.paso.activo')) if (s !== sec) s.classList.remove('activo');
    if (sec.id === 'portada') activarPortada(false);
    else if (sec.id === 'final') activarFinal();
    else {
      sec.classList.add('activo');
      const cap = capitulos.find((c) => c.id === sec.dataset.cap);
      if (cap) aplicarCapitulo(cap, sec);
    }
  }

  function activarPortada(inmediato) {
    S.contexto = 'portada';
    S.capitulo = null;
    detenerAnim();
    S.capa = 'rgb';
    S.comparar = false;
    S.animables = true;
    S.etiquetas = null;
    if (mapaListo) {
      Mapa.base('oscuro');
      S.base = 'oscuro';
      const pad = paddingPortada();
      Mapa.camara(Mapa.encuadre(pad), { padding: pad, inmediato, duracion: 2000 });
      Mapa.comparar(null);
      Mapa.pois('ninguno');
      Mapa.zona(null);
      Mapa.laguna(null);
      Mapa.etiquetas(null);
      Mapa.vista('rgb', S.fecha);
      if (!U.reducido()) iniciarAnim();
    }
    animarCifras($('#portada'), 'portada');
    actualizarChip();
    escribirHash();
  }

  function activarFinal() {
    S.contexto = 'final';
    S.capitulo = null;
    detenerAnim();
    S.animables = false;
    S.comparar = false;
    S.etiquetas = null;
    if (!mapaListo) return;
    const pad = { top: 64, bottom: 24, left: 24, right: 24 };
    Mapa.camara(Mapa.encuadre(pad), { padding: pad, duracion: 2200 });
    Mapa.comparar(null);
    Mapa.zona(null);
    Mapa.laguna(null);
    Mapa.etiquetas(null);
    Mapa.pois('ninguno');
    if (!meta.imagen.frecuencia) S.capa = 'rgb';
    else S.capa = 'frecuencia';
    Mapa.vista(S.capa, S.fecha);
    actualizarChip();
  }

  function aplicarCapitulo(cap, sec, inmediato) {
    S.contexto = 'capitulo';
    S.capitulo = cap.id;
    detenerAnim();
    const capa = cap.capa || 'rgb';
    const capaReal = capa === 'base' ? 'base' : capa;
    let fecha = Number.isInteger(cap.fecha) ? U.limitar(cap.fecha, 0, n() - 1) : S.fecha;
    const animar = cap.fecha === 'animar' && !SIN_FECHA.has(capa) && capa !== 'base';
    if (cap.comparar) fecha = U.limitar(cap.comparar[0] | 0, 0, n() - 1);
    S.capa = capaReal;
    S.fecha = fecha;
    S.animables = animar;
    S.comparar = Boolean(cap.comparar);
    S.cmpDer = cap.comparar ? U.limitar(cap.comparar[1] | 0, 0, n() - 1) : S.cmpDer;
    S.etiquetas = cap.etiquetas && cap.etiquetas.length ? cap.etiquetas : null;
    actualizarChip();
    escribirHash();
    animarCifras(sec, cap.id);
    if (!mapaListo) return;
    const base = cap.base === 'satelite' ? 'satelite' : 'oscuro';
    if (base !== S.base) {
      S.base = base;
      Mapa.base(base);
    }
    if (capa === 'hex') {
      S.hexColor = cap.hex === 'agua' ? 'agua' : 'humedad';
      Mapa.colorHex(S.hexColor);
    }
    const pad = paddingHistoria();
    const caja = Mapa.laguna(cap.laguna || null);
    if (cap.camara) Mapa.camara(ajustarCamara(cap.camara, pad), { padding: pad, inmediato });
    else if (cap.laguna) {
      Mapa.datosListos.then(() => {
        const c = Mapa.laguna(cap.laguna);
        if (c && S.capitulo === cap.id) Mapa.camara(Mapa.encuadre(pad, 60, c, 15.5), { padding: pad, inmediato });
      });
    } else if (cap.zona) {
      const z = (meta.zonas || []).find((x) => x.id === cap.zona);
      if (z && z.caja) Mapa.camara(Mapa.encuadre(pad, 60, z.caja, 15), { padding: pad, inmediato });
    }
    if (!caja && cap.laguna) Mapa.datosListos.then(() => { if (S.capitulo === cap.id) Mapa.laguna(cap.laguna); });
    Mapa.vista(capaReal === 'base' ? 'ninguna' : capaReal, fecha);
    if (cap.comparar && comparable(capa)) {
      Mapa.corte(corteCentral(pad));
      Mapa.comparar({ capa: capaReal, i: fecha, j: S.cmpDer });
      actualizarCortina();
    } else {
      S.comparar = false;
      Mapa.comparar(null);
    }
    Mapa.pois(cap.pois === 'expuestos' ? 'expuestos' : cap.pois ? 'todos' : 'ninguno');
    Mapa.zona(cap.zona ? (meta.zonas || []).find((z) => z.id === cap.zona) : null);
    Mapa.etiquetas(S.etiquetas);
    if (animar && !U.reducido()) iniciarAnim();
    else Mapa.precargar(capa, (fecha + 1) % n());
    actualizarChip();
  }

  function seccionCentral() {
    const y = window.innerHeight / 2;
    return $$('#portada, .paso, #final').find((s) => {
      const r = s.getBoundingClientRect();
      return r.top <= y && r.bottom >= y;
    }) || null;
  }

  function observar() {
    const io = new IntersectionObserver((entradas) => {
      if (S.modo !== 'historia') return;
      for (const e of entradas) if (e.isIntersecting) activarSeccion(e.target);
    }, { rootMargin: '-48% 0px -51% 0px', threshold: 0 });
    for (const s of $$('#portada, .paso, #final')) io.observe(s);
  }

  function escribirHash() {
    clearTimeout(tHash);
    tHash = setTimeout(() => {
      const lang = U.idioma() === 'en' ? 'en' : null;
      if (S.modo === 'explorar') {
        const c = Mapa.camaraActual();
        U.hash.escribir({
          modo: 'explorar', capa: S.capa, f: S.fecha,
          base: S.base !== 'oscuro' ? S.base : null,
          pois: S.pois !== 'ninguno' ? S.pois : null,
          hexc: S.capa === 'hex' && S.hexColor !== 'humedad' ? S.hexColor : null,
          cmp: S.comparar ? S.fecha + ',' + S.cmpDer : null,
          op: S.opacidad < 1 ? Math.round(S.opacidad * 100) : null,
          c: c ? [c.center[0].toFixed(4), c.center[1].toFixed(4), c.zoom.toFixed(2), Math.round(c.bearing), Math.round(c.pitch)].join(',') : null,
          lang
        });
      } else {
        U.hash.escribir({ cap: S.capitulo, lang });
      }
    }, 250);
  }

  function construirListaCapas() {
    const cont = $('#lista-capas');
    cont.replaceChildren(...capasDisponibles().map((c) => {
      const id = 'capa-' + c;
      const input = U.el('input', { type: 'radio', name: 'capa', id, value: c });
      input.checked = S.capa === c;
      input.addEventListener('change', () => elegirCapa(c));
      return U.el('label', { class: 'capa-op', for: id }, input,
        U.el('span', { class: 'muestra muestra-' + c, 'aria-hidden': 'true' }),
        U.el('span', { class: 'capa-txt' }, U.el('b', { text: nombreCapa(c) }), U.el('small', { text: U.t('desc_' + c) })));
    }));
  }

  function llenarSelects() {
    for (const id of ['#s-izq', '#s-der']) {
      const s = $(id);
      s.replaceChildren(...meta.fechas.map((f, i) => U.el('option', { value: i, text: `${i + 1}. ${U.fecha(f, 'larga')}` })));
    }
    $('#s-izq').value = String(S.fecha);
    $('#s-der').value = String(S.cmpDer != null ? S.cmpDer : n() - 1);
  }

  function rampa(colores, etiquetas) {
    return U.el('div', { class: 'ley-rampa' },
      U.el('div', { class: 'ley-barra', style: { background: `linear-gradient(90deg, ${colores.join(', ')})` } }),
      U.el('div', { class: 'ley-ticks' }, etiquetas.map((t) => U.el('span', { text: t }))));
  }
  function muestras(items) {
    return U.el('ul', { class: 'ley-items' }, items.map(([color, texto, forma]) =>
      U.el('li', {}, U.el('i', { class: 'ley-m ' + (forma || ''), style: forma === 'borde' ? { borderColor: color } : { background: color } }), U.el('span', { text: texto }))));
  }

  function construirLeyenda() {
    const c = S.capa;
    const cont = $('#leyenda');
    const partes = [U.el('h3', { class: 'ley-tit', text: U.t('leyenda') + ' · ' + nombreCapa(c) })];
    if (c === 'rgb') {
      partes.push(muestras([['#ff3b6b', U.t('ley_rgb_r')], ['#7fdc3a', U.t('ley_rgb_g')], ['#4f6bff', U.t('ley_rgb_b')]]));
      partes.push(U.el('p', { class: 'nota', text: U.t('ley_rgb_nota') }));
    } else if (c === 'hh') {
      partes.push(rampa(['#000', '#fff'], ['−24 dB', '−12', '0 dB']));
      partes.push(U.el('p', { class: 'nota', text: U.t('ley_hh_nota') }));
    } else if (c === 'hv') {
      partes.push(rampa(['rgb(8,12,10)', 'rgb(40,90,50)', 'rgb(120,190,90)', 'rgb(225,255,190)'], ['−31 dB', '−19,5', '−8 dB'].map((t) => (U.idioma() === 'en' ? t.replace(',', '.') : t))));
      partes.push(U.el('p', { class: 'nota', text: U.t('ley_hv_nota') }));
    } else if (c === 'agua') {
      partes.push(muestras([['#2563eb', U.t('ley_agua_perm')], ['#22d3ee', U.t('ley_agua_temp')]]));
      partes.push(U.el('p', { class: 'nota', text: U.t('ley_agua_nota', { hh: U.num(meta.umbrales.hh_db, 2), hv: U.num(meta.umbrales.hv_db, 2) }).replace(/-/g, '−') }));
    } else if (c === 'cambio') {
      partes.push(muestras([['#38bdf8', U.t('ley_cambio_osc')], ['#fb923c', U.t('ley_cambio_cla')]]));
      partes.push(U.el('p', { class: 'nota', text: U.t('ley_cambio_nota') }));
    } else if (c === 'humedad') {
      partes.push(rampa(['rgb(146,94,48)', 'rgb(214,178,112)', 'rgb(110,170,120)', 'rgb(40,150,170)', 'rgb(30,90,200)'], [U.t('ley_seco'), '0,5'.replace(',', U.idioma() === 'en' ? '.' : ','), U.t('ley_humedo')]));
      partes.push(U.el('p', { class: 'nota', text: U.t('ley_humedad_nota') }));
    } else if (c === 'frecuencia') {
      partes.push(rampa(['#facc15', '#22d3ee', '#2563eb', '#1e3a8a'], [U.t('ley_ocasional'), U.t('ley_estacional'), U.t('ley_permanente')]));
      partes.push(U.el('p', { class: 'nota', text: U.t('ley_frec_nota', { n: n() }) }));
    } else if (c === 'lagunas') {
      partes.push(muestras([['#4ade80', U.t('firma_veg'), 'borde'], ['#22d3ee', U.t('firma_mixta'), 'borde'], ['#818cf8', U.t('firma_abierta'), 'borde']]));
      const r = meta.lagunas && meta.lagunas.ramsar;
      partes.push(U.el('p', { class: 'nota', text: U.t('ley_lagunas_nota') }));
      if (r) partes.push(U.el('p', { class: 'nota', text: U.t('ley_ramsar', { sitio: r.sitio, nombre: r.nombre, ha: U.num(r.area_ha, 1), n: r.lagunas }) }));
    } else if (c === 'hex') {
      if (S.hexColor === 'humedad') {
        partes.push(rampa(['#925e30', '#d6b270', '#6eaa78', '#2896aa', '#1e5ac8'], [U.t('ley_seco'), '', U.t('ley_humedo')]));
        partes.push(U.el('p', { class: 'nota', text: U.t('ley_hex_hum_nota') }));
      } else {
        partes.push(rampa(['#27343b', '#1d5f72', '#1aa3bd', '#22d3ee'], ['0 %', '10 %', '≥30 %']));
        partes.push(muestras([['#e8845a', U.t('ley_hex_expuesta')]]));
        partes.push(U.el('p', { class: 'nota', text: U.t('ley_hex_agua_nota') }));
      }
    }
    if (S.pois !== 'ninguno') {
      partes.push(U.el('h3', { class: 'ley-tit sub', text: U.t('exp_pois') }));
      partes.push(muestras([['#b8860b', U.t('grupo_escuelas'), 'punto'], ['#db2777', U.t('grupo_salud'), 'punto'], ['#7c5cff', U.t('grupo_emergencia'), 'punto']]));
      partes.push(U.el('p', { class: 'nota', text: U.t('ley_pois_nota', { m: meta.exposicion ? meta.exposicion.radio_m : 200 }) }));
    }
    cont.replaceChildren(...partes);
  }

  function resumenPois() {
    const e = meta.exposicion;
    if (!e) return '';
    const g = e.grupos || {};
    const total = Object.values(g).reduce((a, x) => a + (x.total || 0), 0);
    const exp = Object.values(g).reduce((a, x) => a + (x.a_200m_de_agua_temporal || 0), 0);
    return U.t('pois_resumen', {
      e: U.num((g.escuelas && g.escuelas.total) || 0), s: U.num((g.salud && g.salud.total) || 0), m: U.num((g.emergencia && g.emergencia.total) || 0),
      x: U.num(exp), t: U.num(total), r: e.radio_m
    });
  }

  function sincronizarPanel() {
    for (const i of $$('#lista-capas input')) i.checked = i.value === S.capa;
    for (const b of $$('#seg-base button')) b.setAttribute('aria-pressed', String(b.dataset.base === S.base));
    for (const b of $$('#seg-pois button')) b.setAttribute('aria-pressed', String(b.dataset.pois === S.pois));
    for (const b of $$('#seg-hex button')) b.setAttribute('aria-pressed', String(b.dataset.hex === S.hexColor));
    $('#grupo-hex').hidden = S.capa !== 'hex';
    $('#grupo-opacidad').hidden = S.capa === 'hex';
    $('#r-opacidad').value = String(Math.round(S.opacidad * 100));
    $('#o-opacidad').textContent = Math.round(S.opacidad * 100) + ' %';
    $('#pois-resumen').textContent = resumenPois();
    const cmpOk = comparable(S.capa);
    const chk = $('#c-comparar');
    chk.disabled = !cmpOk;
    chk.checked = S.comparar && cmpOk;
    $('#cmp-fechas').hidden = !chk.checked;
    $('#cmp-nota').hidden = cmpOk;
    if (chk.checked) {
      $('#s-izq').value = String(S.fecha);
      $('#s-der').value = String(S.cmpDer);
    }
    construirLeyenda();
  }

  function actualizarCortina() {
    if (!S.comparar || S.cmpDer == null) return;
    $('#cortina-izq').textContent = fechaCorta(S.fecha);
    $('#cortina-der').textContent = fechaCorta(S.cmpDer);
    $('#cortina-asa').setAttribute('aria-label', U.t('cmp_asa_fechas', { a: fechaCorta(S.fecha), b: fechaCorta(S.cmpDer) }));
  }

  function elegirCapa(c) {
    S.capa = c;
    if (c === 'hex') {
      Mapa.colorHex(S.hexColor);
      const cam = Mapa.camaraActual();
      if (cam && cam.pitch < 20 && !U.reducido()) Mapa.mapa().easeTo({ pitch: 48, bearing: cam.bearing || -18, duration: 900 });
    }
    Mapa.vista(c, S.fecha);
    if (S.comparar) {
      if (!comparable(c)) {
        S.comparar = false;
        Mapa.comparar(null);
      } else {
        Mapa.compararFechaB(c, S.cmpDer);
      }
    }
    sincronizarPanel();
    refrescarPopup();
    escribirHash();
  }

  function cambiarFecha(i) {
    S.fecha = i;
    Mapa.vista(S.capa, i, { duracion: U.reducido() ? 0 : linea && linea.timer ? 520 : 380 });
    Mapa.precargar(S.capa, (i + 1) % n());
    if (S.comparar) {
      $('#s-izq').value = String(i);
      actualizarCortina();
    }
    refrescarPopup();
    escribirHash();
  }

  function activarComparar(si) {
    S.comparar = si && comparable(S.capa);
    if (S.comparar) {
      if (S.cmpDer == null || S.cmpDer === S.fecha) S.cmpDer = S.fecha === n() - 1 ? 0 : n() - 1;
      Mapa.corte(corteCentral(paddingExplorador()));
      Mapa.comparar({ capa: S.capa, i: S.fecha, j: S.cmpDer });
      actualizarCortina();
    } else {
      Mapa.comparar(null);
    }
    sincronizarPanel();
    escribirHash();
  }

  function abrirExplorador(p) {
    if (!meta) return;
    const yaAbierto = S.modo === 'explorar';
    if (!yaAbierto) scrollGuardado = window.scrollY;
    S.modo = 'explorar';
    S.contexto = 'explorar';
    detenerAnim();
    S.animables = false;
    document.body.classList.remove('modo-historia');
    document.body.classList.add('modo-explorar');
    $('#historia').hidden = true;
    $('#explorador').hidden = false;
    for (const s of $$('.paso.activo')) s.classList.remove('activo');
    const disponibles = capasDisponibles();
    if (p && p.get('capa') && disponibles.includes(p.get('capa'))) S.capa = p.get('capa');
    if (!disponibles.includes(S.capa)) S.capa = 'rgb';
    if (p && p.get('f') != null && p.get('f') !== '') S.fecha = U.limitar(parseInt(p.get('f'), 10) || 0, 0, n() - 1);
    if (p && p.get('base')) S.base = p.get('base') === 'satelite' ? 'satelite' : 'oscuro';
    if (p && p.get('pois')) S.pois = ['todos', 'expuestos', 'ninguno'].includes(p.get('pois')) ? p.get('pois') : 'ninguno';
    if (p && p.get('hexc')) S.hexColor = p.get('hexc') === 'agua' ? 'agua' : 'humedad';
    if (p && p.get('op')) S.opacidad = U.limitar((parseInt(p.get('op'), 10) || 100) / 100, 0, 1);
    let cmp = null;
    if (p && p.get('cmp')) {
      const [a, b] = p.get('cmp').split(',').map((v) => parseInt(v, 10));
      if (Number.isFinite(a) && Number.isFinite(b)) cmp = [U.limitar(a, 0, n() - 1), U.limitar(b, 0, n() - 1)];
    }
    if (cmp) {
      S.fecha = cmp[0];
      S.cmpDer = cmp[1];
    }
    S.comparar = Boolean(cmp) || (yaAbierto && S.comparar);
    aplicarTextos();
    llenarSelects();
    construirListaCapas();
    sincronizarPanel();
    if (linea) linea.fijar(S.fecha);
    actualizarChip();
    if (!mapaListo) return;
    Mapa.interactivo(true);
    Mapa.etiquetas(null);
    Mapa.zona(null);
    Mapa.laguna(null);
    S.etiquetas = null;
    Mapa.base(S.base);
    Mapa.opacidad(S.opacidad);
    Mapa.colorHex(S.hexColor);
    Mapa.pois(S.pois);
    Mapa.vista(S.capa, S.fecha);
    const pad = paddingExplorador();
    const c = p && p.get('c') ? p.get('c').split(',').map(Number) : null;
    if (c && c.length >= 3 && c.every(Number.isFinite)) {
      Mapa.camara({ center: [c[0], c[1]], zoom: c[2], bearing: c[3] || 0, pitch: c[4] || 0 }, { padding: pad, inmediato: true });
    } else {
      Mapa.relleno(pad, 700);
    }
    if (S.comparar && comparable(S.capa)) {
      Mapa.corte(corteCentral(pad));
      Mapa.comparar({ capa: S.capa, i: S.fecha, j: S.cmpDer });
      actualizarCortina();
    } else {
      S.comparar = false;
      Mapa.comparar(null);
    }
    sincronizarPanel();
    escribirHash();
    if (!yaAbierto) $('#panel-titulo').focus({ preventScroll: true });
  }

  function cerrarExplorador() {
    if (S.modo !== 'explorar') return;
    S.modo = 'historia';
    document.body.classList.remove('modo-explorar', 'panel-abierto');
    document.body.classList.add('modo-historia');
    $('#b-panel').setAttribute('aria-expanded', 'false');
    $('#explorador').hidden = true;
    $('#historia').hidden = false;
    $('#tip-mapa').hidden = true;
    if (linea) linea.pausar();
    if (mapaListo) {
      Mapa.interactivo(false);
      Mapa.cerrarPopup();
      Mapa.comparar(null);
      S.comparar = false;
    }
    aplicarTextos();
    window.scrollTo(0, scrollGuardado);
    requestAnimationFrame(() => {
      const sec = seccionCentral();
      if (sec) activarSeccion(sec);
    });
  }

  function formatoCoord(lng, lat) {
    const ns = lat >= 0 ? 'N' : 'S';
    const eo = lng >= 0 ? 'E' : (U.idioma() === 'en' ? 'W' : 'O');
    return `${U.num(Math.abs(lat), 4)}° ${ns}, ${U.num(Math.abs(lng), 4)}° ${eo}`;
  }

  function nodoPunto(ctx) {
    const s = ctx.serie;
    const cont = U.el('div', { class: 'pp-cont' });
    const lugar = Mapa.lugarCercano(ctx.lngLat.lng, ctx.lngLat.lat);
    cont.append(U.el('p', { class: 'pp-kicker', text: U.t('pp_kicker') + ' · ' + formatoCoord(ctx.lngLat.lng, ctx.lngLat.lat) }));
    if (ctx.poi) {
      const p = ctx.poi.properties;
      const color = { escuelas: '#b8860b', salud: '#db2777', emergencia: '#7c5cff' }[p.grupo] || '#8a939a';
      cont.append(U.el('h3', { class: 'pp-tit' }, U.el('i', { class: 'pp-dot', style: { background: color } }), p.nombre || U.t('grupo_' + p.grupo)));
      const dist = p.dist_agua_temporal_m;
      cont.append(U.el('p', { class: 'pp-sub', text: [U.t('grupo_' + p.grupo), dist != null ? U.t('pp_dist', { m: U.num(dist) }) : null, lugar].filter(Boolean).join(' · ') }));
    } else {
      cont.append(U.el('h3', { class: 'pp-tit', text: lugar ? U.t('pp_cerca', { lugar }) : U.t('pp_titulo') }));
    }
    if (ctx.hex) {
      const h = ctx.hex.properties;
      const pois = (h.n_escuelas || 0) + (h.n_salud || 0) + (h.n_emergencia || 0);
      const hum = h.humedad_idx && h.humedad_idx[S.fecha] != null ? U.num(h.humedad_idx[S.fecha], 2) : '—';
      cont.append(U.el('p', { class: 'pp-hex', text: U.t('pp_hex', { hum, agua: U.num(Mapa.porcentajeTemporal(h, S.fecha), 1), pois: U.num(pois) }) }));
    }
    if (!s || s.fuera) {
      cont.append(U.el('p', { class: 'pp-vacio', text: U.t('pp_fuera') }));
      return cont;
    }
    const nAgua = s.agua.filter(Boolean).length;
    const clase = s.mascara === 2 ? U.t('pp_mar') : s.mascara === 1 ? U.t('pp_tierra') : U.t('pp_excluido');
    cont.append(U.el('p', { class: 'pp-resumen' },
      U.el('span', { class: 'insignia', text: clase }),
      s.mascara === 2 ? null : U.el('span', { text: U.t('pp_agua_n', { k: nAgua, n: n() }) })));
    const lluvia7 = (meta.lluvia.por_paso || []).map((p) => p.previos_7d_mm);
    cont.append(Graficas.serie(meta, s, lluvia7, S.fecha));
    const hh = s.hh[S.fecha];
    const hv = s.hv[S.fecha];
    cont.append(U.el('p', { class: 'pp-actual' },
      U.el('b', { text: fechaCorta(S.fecha) }),
      ' · HH ' + (hh == null ? '—' : U.num(hh, 1).replace('-', '−') + ' dB') + ' · HV ' + (hv == null ? '—' : U.num(hv, 1).replace('-', '−') + ' dB')));
    return cont;
  }

  function nodoLaguna(ctx) {
    const f = ctx.laguna.rasgo;
    const p = f.properties;
    const s = p.nombre ? Mapa.serieLaguna(p.nombre) : Mapa.agregarLagunas([f]);
    const cont = U.el('div', { class: 'pp-cont' });
    cont.append(U.el('p', { class: 'pp-kicker', text: U.t('pp_laguna_kicker') }));
    cont.append(U.el('h3', { class: 'pp-tit' }, U.el('i', { class: 'pp-dot borde', style: { borderColor: { veg: '#4ade80', mixta: '#22d3ee', abierta: '#818cf8' }[Graficas.claveFirma(s.firma)] } }), s.nombre || U.t('laguna_sin_nombre')));
    cont.append(U.el('p', { class: 'pp-sub', text: U.t('pp_laguna_sub', { ha: U.num(s.area_ha, 1), firma: U.t('firma_' + Graficas.claveFirma(s.firma)), tipo: U.t('tipo_' + (p.tipo === 'wetland' ? 'humedal' : 'agua')), k: s.poligonos }) }));
    cont.append(Graficas.laguna(meta, s, S.fecha, false));
    return cont;
  }

  function pintarPopup(encuadrar) {
    const ctx = S.popup;
    if (!ctx) return;
    const nodo = ctx.laguna ? nodoLaguna(ctx) : nodoPunto(ctx);
    const pp = Mapa.popup(ctx.lngLat, nodo);
    if (encuadrar && pp) requestAnimationFrame(() => asegurarVisible(pp.getElement()));
  }

  function asegurarVisible(el) {
    const m = Mapa.mapa();
    if (!el || !m) return;
    const r = el.getBoundingClientRect();
    const W = window.innerWidth;
    const H = window.innerHeight;
    const estrecho = U.estrecho();
    const zona = {
      top: estrecho ? 112 : 72,
      left: estrecho || document.body.classList.contains('panel-oculto') ? 8 : 356,
      right: W - (estrecho ? 8 : 60),
      bottom: H - (estrecho ? 168 : 150)
    };
    let dx = 0;
    let dy = 0;
    if (r.top < zona.top) dy = r.top - zona.top;
    else if (r.bottom > zona.bottom) dy = Math.min(r.bottom - zona.bottom, r.top - zona.top);
    if (r.left < zona.left) dx = r.left - zona.left;
    else if (r.right > zona.right) dx = Math.min(r.right - zona.right, r.left - zona.left);
    if (dx || dy) m.panBy([dx, dy], { duration: U.reducido() ? 0 : 450 });
  }

  function refrescarPopup() {
    if (S.popup && Mapa.popupAbierto()) pintarPopup();
  }

  async function alClic(e) {
    $('#tip-mapa').hidden = true;
    if (e.laguna) {
      S.popup = { lngLat: e.lngLat, laguna: e.laguna };
      Mapa.seleccionarLaguna(e.laguna.indice);
      pintarPopup(true);
      return;
    }
    Mapa.seleccionarLaguna(null);
    S.popup = { lngLat: e.lngLat, poi: e.poi, hex: e.hex, serie: null };
    const ctx = S.popup;
    Mapa.popup(e.lngLat, U.el('div', { class: 'pp-cont' }, U.el('p', { class: 'pp-kicker', text: U.t('pp_cargando') })));
    let serie = null;
    try {
      serie = await Mapa.serieEn(e.lngLat.lng, e.lngLat.lat);
    } catch (err) {
      serie = null;
    }
    if (S.popup !== ctx) return;
    ctx.serie = serie;
    pintarPopup(true);
  }

  function alFlotar(e) {
    const tip = $('#tip-mapa');
    if (!e || window.matchMedia('(pointer: coarse)').matches || (!e.poi && !e.laguna && !e.hex)) {
      tip.hidden = true;
      return;
    }
    let lineas = [];
    if (e.poi) {
      const p = e.poi.properties;
      lineas = [p.nombre || U.t('grupo_' + p.grupo), U.t('grupo_' + p.grupo)];
    } else if (e.laguna) {
      const p = e.laguna.rasgo.properties;
      lineas = [p.nombre || U.t('laguna_sin_nombre'), U.t('firma_' + Graficas.claveFirma(p.firma)) + ' · ' + U.num(p.area_ha, 1) + ' ha'];
    } else if (e.hex) {
      const h = e.hex.properties;
      const pois = (h.n_escuelas || 0) + (h.n_salud || 0) + (h.n_emergencia || 0);
      const hum = h.humedad_idx && h.humedad_idx[S.fecha] != null ? U.num(h.humedad_idx[S.fecha], 2) : '—';
      lineas = [U.t('tip_hex', { hum }), U.t('tip_hex2', { agua: U.num(Mapa.porcentajeTemporal(h, S.fecha), 1), pois: U.num(pois) })];
    }
    tip.replaceChildren(U.el('b', { text: lineas[0] }), lineas[1] ? U.el('span', { text: lineas[1] }) : null);
    tip.hidden = false;
    const r = $('#mapa').getBoundingClientRect();
    const x = r.left + e.punto.x + 14;
    const y = r.top + e.punto.y + 14;
    tip.style.transform = `translate(${Math.min(x, window.innerWidth - tip.offsetWidth - 8)}px, ${Math.min(y, window.innerHeight - tip.offsetHeight - 8)}px)`;
  }

  function nodoCreditos() {
    const lluvia = meta.lluvia || {};
    const punto = lluvia.punto || [];
    const r = meta.lagunas && meta.lagunas.ramsar;
    const granulos = U.el('details', { class: 'cr-granulos' },
      U.el('summary', { text: U.t('cr_granulos', { n: (meta.granulos || []).length }) }),
      U.el('ol', {}, (meta.granulos || []).map((g) => U.el('li', {}, U.el('code', { text: g })))));
    const lista = [
      U.el('li', {}, U.el('b', { text: 'NISAR' }), ' — ', U.t('cr_nisar'), ' ', granulos),
      U.el('li', {}, U.el('b', { text: 'NASA POWER' }), ' — ', U.t('cr_power', { lat: punto[0], lon: punto[1] }), ' ',
        lluvia.url ? U.el('a', { href: lluvia.url, target: '_blank', rel: 'noopener', text: U.t('cr_consulta') }) : null),
      U.el('li', {}, U.el('b', {}, '© ', U.el('a', { href: 'https://www.openstreetmap.org/copyright', target: '_blank', rel: 'noopener', text: 'OpenStreetMap contributors' })), ' (ODbL) — ', U.t('cr_osm')),
      r ? U.el('li', {}, U.el('b', { text: 'Ramsar ' + r.sitio }), ' — ', U.t('cr_ramsar', { nombre: r.nombre, ha: U.num(r.area_ha, 1), anio: String(r.designado || '').slice(0, 4) })) : null,
      U.el('li', {}, U.el('b', { text: 'MapLibre GL JS' }), ' — ', U.t('cr_mapbox'))
    ];
    const metodo = U.t('cr_metodo', {
      hh: U.num(meta.umbrales.hh_db, 2).replace('-', '−'), hv: U.num(meta.umbrales.hv_db, 2).replace('-', '−'),
      km: meta.hex ? U.num(meta.hex.ancho_km, 2) : '1.44'
    });
    return [
      U.el('div', { class: 'cr-col' }, U.el('h3', { text: U.t('cr_datos') }), U.el('ul', { class: 'cr-lista' }, lista)),
      U.el('div', { class: 'cr-col' }, U.el('h3', { text: U.t('cr_metodo_tit') }), U.el('p', { text: metodo }),
        U.el('h3', { text: U.t('cr_equipo_tit') }), U.el('p', { text: U.t('cr_equipo') }),
        U.el('p', {}, U.el('a', { href: '../index.html', class: 'cr-volver enlace-tab', text: '← ' + U.t('cr_tablero') })))
    ];
  }

  // En un sitio estático no hay tablero (necesita el backend): sus enlaces van al repositorio.
  function apuntarTablero(conServidor) {
    if (conServidor) return;
    for (const a of document.querySelectorAll('a[href="../index.html"]')) {
      a.href = U.REPO;
      a.target = '_blank';
      a.rel = 'noopener';
    }
  }

  function construirCreditos() {
    $('#creditos').replaceChildren(U.el('div', { class: 'cr-cont' },
      U.el('div', { class: 'cr-marca' }, U.el('img', { src: '../logo.png', alt: '', width: 40, height: 40 }),
        U.el('div', {}, U.el('b', { text: 'El Ojo de Tláloc' }), U.el('span', { text: U.t('cr_lema') }))),
      U.el('div', { class: 'cr-cols' }, nodoCreditos())));
    $('#dlg-cuerpo').replaceChildren(U.el('div', { class: 'cr-cols' }, nodoCreditos()));
  }

  function cambiarIdioma(l) {
    if (l === U.idioma()) return;
    U.fijarIdioma(l);
    U.guardar('nisar.idioma', U.idioma());
    aplicarTextos();
    if (!meta) return;
    rellenarPortada();
    $$('.paso').forEach((sec) => {
      const k = capitulos.findIndex((c) => c.id === sec.dataset.cap);
      if (k >= 0) llenarTarjeta($('.tarjeta', sec), capitulos[k], k);
    });
    construirListaCapas();
    llenarSelects();
    sincronizarPanel();
    if (linea) linea.textos();
    construirCreditos();
    U.conServidor().then(apuntarTablero);
    actualizarChip();
    actualizarCortina();
    if (mapaListo) {
      Mapa.etiquetas(S.modo === 'historia' ? S.etiquetas : null);
      Mapa.idioma();
    }
    refrescarPopup();
    escribirHash();
  }

  function aplicarHash(inicial) {
    const h = U.hash.leer();
    if (h.get('lang') && h.get('lang') !== U.idioma()) cambiarIdioma(h.get('lang'));
    if (h.get('modo') === 'explorar') {
      abrirExplorador(h);
      return;
    }
    if (S.modo === 'explorar' && !inicial) cerrarExplorador();
    const cap = h.get('cap');
    const sec = cap ? document.getElementById('cap-' + cap) : null;
    if (sec && inicial) {
      sec.scrollIntoView({ block: 'center' });
    } else if (inicial) {
      const actual = seccionCentral();
      if (actual) activarSeccion(actual);
    }
  }

  function enlazar() {
    for (const b of $$('.idioma button')) b.addEventListener('click', () => cambiarIdioma(b.dataset.lang));
    $('#b-explorar').addEventListener('click', () => (S.modo === 'explorar' ? cerrarExplorador() : abrirExplorador(null)));
    $('#b-explorar-portada').addEventListener('click', () => abrirExplorador(null));
    $('#b-explorar-final').addEventListener('click', () => abrirExplorador(null));
    $('#b-volver').addEventListener('click', cerrarExplorador);
    $('#marca').addEventListener('click', (e) => {
      e.preventDefault();
      if (S.modo === 'explorar') cerrarExplorador();
      window.scrollTo({ top: 0, behavior: U.reducido() ? 'auto' : 'smooth' });
    });
    $('#b-comenzar').addEventListener('click', (e) => {
      e.preventDefault();
      const primero = $('.paso');
      if (primero) primero.scrollIntoView({ behavior: U.reducido() ? 'auto' : 'smooth', block: 'center' });
    });
    $('#chip-play').addEventListener('click', alternarAnim);
    $('#saltar').addEventListener('click', (e) => {
      e.preventDefault();
      abrirExplorador(null);
    });
    for (const b of $$('#seg-base button')) {
      b.addEventListener('click', () => {
        S.base = b.dataset.base;
        Mapa.base(S.base);
        sincronizarPanel();
        escribirHash();
      });
    }
    for (const b of $$('#seg-pois button')) {
      b.addEventListener('click', () => {
        S.pois = b.dataset.pois;
        Mapa.pois(S.pois);
        sincronizarPanel();
        escribirHash();
      });
    }
    for (const b of $$('#seg-hex button')) {
      b.addEventListener('click', () => {
        S.hexColor = Mapa.colorHex(b.dataset.hex);
        sincronizarPanel();
        escribirHash();
      });
    }
    $('#r-opacidad').addEventListener('input', (e) => {
      S.opacidad = parseInt(e.target.value, 10) / 100;
      $('#o-opacidad').textContent = e.target.value + ' %';
      Mapa.opacidad(S.opacidad);
      escribirHash();
    });
    $('#c-comparar').addEventListener('change', (e) => activarComparar(e.target.checked));
    $('#s-izq').addEventListener('change', (e) => {
      const i = parseInt(e.target.value, 10);
      if (linea) linea.fijar(i, true);
      else cambiarFecha(i);
    });
    $('#s-der').addEventListener('change', (e) => {
      S.cmpDer = parseInt(e.target.value, 10);
      Mapa.compararFechaB(S.capa, S.cmpDer);
      actualizarCortina();
      escribirHash();
    });
    $('#b-centro').addEventListener('click', () => {
      const m = Mapa.mapa();
      if (!m) return;
      alClic({ lngLat: m.getCenter(), poi: null, hex: null, laguna: null });
    });
    $('#b-creditos').addEventListener('click', () => {
      const d = $('#dlg-creditos');
      if (typeof d.showModal === 'function') d.showModal();
    });
    $('#dlg-cerrar').addEventListener('click', () => $('#dlg-creditos').close());
    $('#dlg-creditos').addEventListener('click', (e) => {
      if (e.target === e.currentTarget) e.currentTarget.close();
    });
    $('#b-panel').addEventListener('click', () => {
      const abierto = document.body.classList.toggle('panel-abierto');
      $('#b-panel').setAttribute('aria-expanded', String(abierto));
    });
    const asa = $('#cortina-asa');
    let arrastre = false;
    asa.addEventListener('pointerdown', (e) => {
      arrastre = true;
      asa.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    asa.addEventListener('pointermove', (e) => {
      if (arrastre) Mapa.corte(e.clientX / window.innerWidth);
    });
    const soltar = () => { arrastre = false; };
    asa.addEventListener('pointerup', soltar);
    asa.addEventListener('pointercancel', soltar);
    asa.addEventListener('keydown', (e) => {
      const paso = { ArrowLeft: -0.03, ArrowRight: 0.03, ArrowDown: -0.03, ArrowUp: 0.03, PageDown: -0.1, PageUp: 0.1 }[e.key];
      if (paso) {
        e.preventDefault();
        Mapa.corte(Mapa.corteActual() + paso);
      } else if (e.key === 'Home' || e.key === 'End') {
        e.preventDefault();
        Mapa.corte(e.key === 'Home' ? 0 : 1);
      }
    });
    window.addEventListener('hashchange', () => aplicarHash(false));
    let tRes = 0;
    window.addEventListener('resize', () => {
      clearTimeout(tRes);
      tRes = setTimeout(() => {
        if (!mapaListo) return;
        Mapa.redimensionar();
        if (S.modo === 'explorar') Mapa.relleno(paddingExplorador(), 0);
        else if (S.contexto === 'capitulo') {
          const cap = capitulos.find((c) => c.id === S.capitulo);
          const pad = paddingHistoria();
          if (cap && cap.camara) Mapa.camara(ajustarCamara(cap.camara, pad), { padding: pad, inmediato: true });
        } else if (S.contexto === 'portada') {
          const pad = paddingPortada();
          Mapa.camara(Mapa.encuadre(pad), { padding: pad, inmediato: true });
        }
      }, 180);
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && S.modo === 'explorar' && document.body.classList.contains('panel-abierto')) {
        document.body.classList.remove('panel-abierto');
        $('#b-panel').setAttribute('aria-expanded', 'false');
      }
    });
  }

  async function iniciar() {
    U.agregarTextos(window.UI_TEXTOS);
    U.agregarTextos(window.TEXTOS);
    const h = U.hash.leer();
    U.fijarIdioma(h.get('lang') || U.leer('nisar.idioma') || 'es');
    capitulos = Array.isArray(window.CAPITULOS) ? window.CAPITULOS.filter((c) => c && c.id) : [];
    aplicarTextos();
    enlazar();
    try {
      const r = await fetch('datos/meta.json', { cache: 'no-cache' });
      if (!r.ok) throw new Error(String(r.status));
      meta = await r.json();
    } catch (e) {
      $('#cargando').hidden = true;
      mostrarAviso('datos', true);
      return;
    }
    S.fecha = 0;
    S.cmpDer = n() - 1;
    rellenarPortada();
    construirHistoria();
    construirCreditos();
    construirListaCapas();
    llenarSelects();
    linea = new LineaTiempo($('#linea'), { meta, alCambiar: cambiarFecha });
    Mapa.cargarDatos(meta);
    U.conServidor().then(apuntarTablero);
    if (!window.maplibregl) {
      $('#cargando').hidden = true;
      mostrarAviso('mapbox', true);
      observar();
      return;
    }
    try {
      await Mapa.iniciar({
        meta, contenedor: 'mapa', base: S.base,
        manejadores: {
          error: errorMapa,
          clic: alClic,
          flotar: alFlotar,
          movido: () => { if (S.modo === 'explorar') escribirHash(); },
          popupCerrado: () => {
            S.popup = null;
            Mapa.seleccionarLaguna(null);
          }
        }
      });
    } catch (e) {
      $('#cargando').hidden = true;
      mostrarAviso(/webgl/i.test(String(e && e.message)) ? 'webgl' : 'tokenmalo', true);
      actualizarChip();
      observar();
      return;
    }
    mapaListo = true;
    Mapa.interactivo(false);
    document.body.classList.add('mapa-listo');
    $('#cargando').hidden = true;
    observar();
    aplicarHash(true);
    Mapa.precargar('rgb', 1);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', iniciar);
  else iniciar();
})();
