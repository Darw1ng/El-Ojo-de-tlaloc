/* Gráficas SVG de la historia NISAR: lluvia diaria, agua temporal, humedad, mar,
   polarizaciones, calibración y lagunas para las tarjetas, más la serie de un punto o
   de una laguna para el popup del explorador. Cada banda tiene su propia escala (nunca
   doble eje), marcas delgadas, cruz que sigue al puntero y al teclado, y una tabla
   plegable con los mismos datos como alternativa accesible. */
(function () {
  const C = {
    hh: '#d946ef', hv: '#65a30d', mar: '#3b82f6', tierra: '#d97706', agua: '#22d3ee',
    lluvia: '#5f8aa6', humedad: '#2fb3a0', rejilla: '#2b3136', eje: '#3d454c',
    texto: '#a3abb1', sup: '#1b1f23', actual: '#78bfdc', vacio: '#2b3136', mar_f: '#1e3a8a'
  };
  const W = 340;
  const G = { colores: C };

  function pasoBonito(r) {
    if (!(r > 0)) return 1;
    const e = Math.pow(10, Math.floor(Math.log10(r)));
    const f = r / e;
    return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * e;
  }

  function dominio(valores, cero, partes = 3) {
    const v = valores.filter(Number.isFinite);
    let lo = v.length ? Math.min(...v) : 0;
    let hi = v.length ? Math.max(...v) : 1;
    if (cero) {
      lo = Math.min(0, lo);
      hi = Math.max(0, hi);
    }
    if (hi - lo < 1e-9) {
      lo -= 1;
      hi += 1;
    }
    const paso = pasoBonito((hi - lo) / partes);
    lo = Math.floor(lo / paso + 1e-9) * paso;
    hi = Math.ceil(hi / paso - 1e-9) * paso;
    const ticks = [];
    for (let t = lo; t <= hi + paso * 1e-6; t += paso) ticks.push(Math.round(t / paso) * paso);
    return { lo, hi, ticks, dec: paso < 1 ? Math.min(2, Math.ceil(-Math.log10(paso))) : 0 };
  }

  const lineal = (d0, d1, r0, r1) => (v) => r0 + (v - d0) / ((d1 - d0) || 1) * (r1 - r0);

  function barraArriba(x, y, w, h, r) {
    if (!(h > 0.2)) return '';
    r = Math.min(r, w / 2, h);
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  }
  function barraAbajo(x, y, w, h, r) {
    if (!(h > 0.2)) return '';
    r = Math.min(r, w / 2, h);
    return `M${x},${y}V${y + h - r}Q${x},${y + h} ${x + r},${y + h}H${x + w - r}Q${x + w},${y + h} ${x + w},${y + h - r}V${y}Z`;
  }

  function texto(x, y, s, extra = {}) {
    return U.svg('text', { x, y, class: 'gr-txt', ...extra, text: s });
  }

  function ejeMeses(g, f0, fN, x, y) {
    const [a0, m0] = f0.split('-').map(Number);
    let anio = a0;
    let mes = m0 + 1;
    for (let k = 0; k < 14; k++) {
      if (mes > 12) {
        mes = 1;
        anio += 1;
      }
      const iso = `${anio}-${String(mes).padStart(2, '0')}-01`;
      if (iso > fN) break;
      const px = x(iso);
      g.append(U.svg('line', { x1: px, x2: px, y1: y - 13, y2: y - 10, class: 'gr-tick' }));
      g.append(texto(px, y, U.fecha(iso, 'mes'), { 'text-anchor': 'middle' }));
      mes += 1;
    }
  }

  function clave(color, forma) {
    return U.el('i', { class: 'k k-' + forma, style: { background: color } });
  }

  function leyenda(items) {
    return U.el('div', { class: 'gr-ley' }, items.map((it) => U.el('span', {}, clave(it.color, it.forma), it.nombre)));
  }

  function fila(color, forma, valor, etiqueta) {
    return U.el('div', { class: 'tf' }, color ? clave(color, forma) : null, U.el('b', { text: valor }), U.el('span', { text: etiqueta }));
  }

  function tablaDatos(cabeceras, filas) {
    const t = U.el('table', { class: 'gr-tab' },
      U.el('thead', {}, U.el('tr', {}, cabeceras.map((c, i) => U.el('th', { scope: 'col', class: i ? 'num' : null, text: c })))),
      U.el('tbody', {}, filas.map((f) => U.el('tr', {}, f.map((v, i) => (i ? U.el('td', { class: 'num', text: v }) : U.el('th', { scope: 'row', text: v })))))));
    return U.el('details', { class: 'gr-tabla' }, U.el('summary', { text: U.t('g_tabla') }), U.el('div', { class: 'gr-tab-cont' }, t));
  }

  function envolver({ titulo, items, svg, alto, xs, cruz, contenido, aria, tabla, nota, sub }) {
    svg.setAttribute('viewBox', `0 0 ${W} ${alto}`);
    svg.setAttribute('class', 'gr-svg');
    svg.setAttribute('aria-hidden', 'true');
    const linea = U.svg('line', { class: 'gr-cruz', x1: 0, x2: 0, y1: cruz[0], y2: cruz[1], visibility: 'hidden' });
    svg.append(linea);
    const tip = U.el('div', { class: 'gr-tip', hidden: true });
    const lienzo = U.el('div', { class: 'gr-lienzo', tabindex: '0', role: 'img', 'aria-label': aria }, svg, tip);
    let actual = -1;
    const mostrar = (i) => {
      if (i < 0) {
        linea.setAttribute('visibility', 'hidden');
        tip.hidden = true;
        actual = -1;
        return;
      }
      actual = i;
      const x = xs[i];
      linea.setAttribute('x1', x);
      linea.setAttribute('x2', x);
      linea.setAttribute('visibility', 'visible');
      tip.replaceChildren(...contenido(i));
      tip.hidden = false;
      const esc = lienzo.clientWidth / W;
      const px = x * esc;
      const ancho = tip.offsetWidth;
      const izq = px + 14 + ancho > lienzo.clientWidth ? px - 14 - ancho : px + 14;
      tip.style.left = Math.max(0, Math.min(lienzo.clientWidth - ancho, izq)) + 'px';
    };
    const cercano = (clientX) => {
      const r = svg.getBoundingClientRect();
      const x = (clientX - r.left) / r.width * W;
      let mejor = 0;
      for (let i = 1; i < xs.length; i++) if (Math.abs(xs[i] - x) < Math.abs(xs[mejor] - x)) mejor = i;
      return mejor;
    };
    lienzo.addEventListener('pointermove', (e) => mostrar(cercano(e.clientX)));
    lienzo.addEventListener('pointerdown', (e) => mostrar(cercano(e.clientX)));
    lienzo.addEventListener('pointerleave', () => {
      if (document.activeElement !== lienzo) mostrar(-1);
    });
    lienzo.addEventListener('focus', () => mostrar(actual < 0 ? xs.length - 1 : actual));
    lienzo.addEventListener('blur', () => mostrar(-1));
    lienzo.addEventListener('keydown', (e) => {
      const base = actual < 0 ? 0 : actual;
      let i = null;
      if (e.key === 'ArrowRight') i = base + 1;
      else if (e.key === 'ArrowLeft') i = base - 1;
      else if (e.key === 'Home') i = 0;
      else if (e.key === 'End') i = xs.length - 1;
      else if (e.key === 'Escape') {
        mostrar(-1);
        return;
      }
      if (i == null) return;
      e.preventDefault();
      mostrar(U.limitar(i, 0, xs.length - 1));
    });
    return U.el('figure', { class: 'gr' },
      titulo ? U.el('figcaption', { class: 'gr-tit' }, U.el('span', { text: titulo }), sub ? U.el('small', { text: sub }) : null) : null,
      items && items.length ? leyenda(items) : null,
      lienzo,
      nota ? U.el('p', { class: 'gr-nota', text: nota }) : null,
      tabla || null);
  }

  function bandas(meta, cfg) {
    const fechas = meta.fechas;
    const f0 = fechas[0];
    const fN = fechas[fechas.length - 1];
    const series = cfg.arriba.series;
    const conFinal = series.length > 1;
    const m = { l: 36, r: conFinal ? 52 : 14 };
    const x = lineal(0, U.dias(f0, fN), m.l + 6, W - m.r - 6);
    const xf = (iso) => x(U.dias(f0, iso));
    const xs = fechas.map(xf);
    const svg = U.svg('svg', {});
    const g = U.svg('g', {});
    svg.append(g);
    const rotular = Boolean(cfg.abajo || cfg.franja);
    let y = 6;
    if (rotular && cfg.arriba.rotulo) {
      g.append(texto(m.l - 30, y + 8, cfg.arriba.rotulo, { class: 'gr-txt gr-rot' }));
      y += 16;
    }
    const hA = cfg.arriba.alto || (rotular ? 80 : 104);
    const yA0 = y;
    const yA1 = y + hA;
    const todos = series.flatMap((s) => s.valores);
    const dA = dominio(todos, cfg.arriba.cero);
    const yA = lineal(dA.lo, dA.hi, yA1, yA0);
    for (const t of dA.ticks) {
      const py = yA(t);
      g.append(U.svg('line', { x1: m.l, x2: W - m.r, y1: py, y2: py, class: 'gr-rej' }));
      g.append(texto(m.l - 6, py + 3.5, U.num(t, dA.dec).replace('-', '−'), { 'text-anchor': 'end', class: 'gr-txt gr-num' }));
    }
    y = yA1 + 10;
    let yF = null;
    if (cfg.franja) {
      yF = y;
      g.append(texto(m.l - 30, yF + 9, cfg.franja.rotulo, { class: 'gr-txt gr-rot' }));
      const ancho = Math.min(22, (W - m.l - m.r) / fechas.length - 3);
      cfg.franja.colores.forEach((col, i) => {
        g.append(U.svg('rect', { x: xs[i] - ancho / 2, y: yF, width: ancho, height: 12, rx: 3, fill: col }));
      });
      y = yF + 12 + 12;
    }
    let yB0 = null;
    let yB1 = null;
    if (cfg.abajo) {
      g.append(texto(m.l - 30, y + 8, cfg.abajo.rotulo || cfg.abajo.nombre, { class: 'gr-txt gr-rot' }));
      y += 14;
      yB0 = y;
      yB1 = y + (cfg.abajo.alto || 34);
      const vb = cfg.abajo.valores;
      const maxB = Math.max(1e-9, ...vb.filter(Number.isFinite));
      const techo = dominio([0, maxB], true, 2).hi;
      const yB = lineal(0, techo, yB1, yB0);
      g.append(U.svg('line', { x1: m.l, x2: W - m.r, y1: yB1, y2: yB1, class: 'gr-eje' }));
      g.append(U.svg('line', { x1: m.l, x2: W - m.r, y1: yB0, y2: yB0, class: 'gr-rej' }));
      g.append(texto(m.l - 6, yB0 + 3.5, U.num(techo, techo < 10 ? 1 : 0), { 'text-anchor': 'end', class: 'gr-txt gr-num' }));
      g.append(texto(m.l - 6, yB1 + 3.5, '0', { 'text-anchor': 'end', class: 'gr-txt gr-num' }));
      const ancho = Math.min(14, (W - m.l - m.r) / fechas.length - 6);
      vb.forEach((v, i) => {
        if (!Number.isFinite(v)) return;
        const h = yB1 - yB(v);
        const d = barraArriba(xs[i] - ancho / 2, yB(v), ancho, h, 3);
        if (d) g.append(U.svg('path', { d, fill: cfg.abajo.color }));
      });
      y = yB1 + 4;
    }
    if (cfg.actual != null && cfg.actual >= 0) {
      g.append(U.svg('line', { x1: xs[cfg.actual], x2: xs[cfg.actual], y1: yA0 - 2, y2: (yB1 || (yF != null ? yF + 12 : yA1)) + 2, class: 'gr-actual' }));
      if (yF != null) {
        const ancho = Math.min(22, (W - m.l - m.r) / fechas.length - 3);
        g.append(U.svg('rect', { x: xs[cfg.actual] - ancho / 2 - 2, y: yF - 2, width: ancho + 4, height: 16, rx: 4, class: 'gr-actual-caja' }));
      }
    }
    for (const s of series) {
      let d = '';
      let pluma = false;
      s.valores.forEach((v, i) => {
        if (!Number.isFinite(v)) {
          pluma = false;
          return;
        }
        d += (pluma ? 'L' : 'M') + xs[i].toFixed(1) + ',' + yA(v).toFixed(1);
        pluma = true;
      });
      g.append(U.svg('path', { d, class: 'gr-linea', stroke: s.color }));
      s.valores.forEach((v, i) => {
        if (Number.isFinite(v)) g.append(U.svg('circle', { cx: xs[i], cy: yA(v), r: 3.5, fill: s.color, class: 'gr-punto' }));
      });
      if (conFinal) {
        let k = s.valores.length - 1;
        while (k >= 0 && !Number.isFinite(s.valores[k])) k--;
        if (k >= 0) g.append(texto(xs[k] + 8, yA(s.valores[k]) + 4, s.corto || s.nombre, { class: 'gr-txt gr-fin' }));
      }
    }
    if (cfg.marcarMax) {
      const s = series[0];
      let k = 0;
      s.valores.forEach((v, i) => {
        if (Number.isFinite(v) && v > s.valores[k]) k = i;
      });
      const etq = U.num(s.valores[k], cfg.arriba.dec) + ' ' + cfg.arriba.unidad;
      const anchor = xs[k] > W - 60 ? 'end' : xs[k] < m.l + 30 ? 'start' : 'middle';
      g.append(texto(xs[k], yA(s.valores[k]) - 9, etq, { 'text-anchor': anchor, class: 'gr-txt gr-dest' }));
    }
    const yM = y + 12;
    ejeMeses(g, f0, fN, xf, yM);
    const alto = yM + 4;
    const items = conFinal ? series.map((s) => ({ color: s.color, forma: 'linea', nombre: s.nombre })) : null;
    const contenido = (i) => {
      const out = [U.el('div', { class: 'tf-fecha', text: U.fecha(fechas[i], 'larga') })];
      for (const s of series) {
        const v = s.valores[i];
        out.push(fila(s.color, 'linea', Number.isFinite(v) ? U.num(v, cfg.arriba.dec).replace('-', '−') + (cfg.arriba.unidad ? ' ' + cfg.arriba.unidad : '') : '—', s.nombre));
      }
      if (cfg.franja) out.push(fila(cfg.franja.colores[i], 'caja', cfg.franja.textos[i], cfg.franja.nombre));
      if (cfg.abajo) {
        const v = cfg.abajo.valores[i];
        out.push(fila(cfg.abajo.color, 'barra', Number.isFinite(v) ? U.num(v, cfg.abajo.dec) + ' ' + cfg.abajo.unidad : '—', cfg.abajo.nombre));
      }
      return out;
    };
    const cab = [U.t('g_fecha'), ...series.map((s) => s.nombre + (cfg.arriba.unidad ? ` (${cfg.arriba.unidad})` : ''))];
    if (cfg.franja) cab.push(cfg.franja.nombre);
    if (cfg.abajo) cab.push(cfg.abajo.nombre + ` (${cfg.abajo.unidad})`);
    const filasT = fechas.map((f, i) => {
      const r = [U.fecha(f, 'larga'), ...series.map((s) => (Number.isFinite(s.valores[i]) ? U.num(s.valores[i], cfg.arriba.dec) : '—'))];
      if (cfg.franja) r.push(cfg.franja.textos[i]);
      if (cfg.abajo) r.push(Number.isFinite(cfg.abajo.valores[i]) ? U.num(cfg.abajo.valores[i], cfg.abajo.dec) : '—');
      return r;
    });
    return envolver({
      titulo: cfg.titulo, sub: cfg.sub, items, svg, alto, xs,
      cruz: [yA0 - 2, (yB1 || (yF != null ? yF + 12 : yA1)) + 2],
      contenido, aria: cfg.aria || cfg.titulo, nota: cfg.nota,
      tabla: tablaDatos(cab, filasT)
    });
  }

  function lluvia(meta) {
    const d = meta.lluvia.diaria;
    const fechas = meta.fechas;
    const f0 = d[0].fecha;
    const fN = d[d.length - 1].fecha;
    const m = { l: 36, r: 12 };
    const n = d.length;
    const x = (i) => m.l + 2 + (i + 0.5) / n * (W - m.l - m.r - 4);
    const xf = (iso) => x(U.dias(f0, iso));
    const valores = d.map((v) => (v.mm == null ? null : v.mm));
    const dY = dominio([0, ...valores.filter(Number.isFinite)], true);
    const yA0 = 18;
    const yA1 = 118;
    const y = lineal(0, dY.hi, yA1, yA0);
    const svg = U.svg('svg', {});
    const g = U.svg('g', {});
    svg.append(g);
    for (const t of dY.ticks) {
      g.append(U.svg('line', { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), class: t === 0 ? 'gr-eje' : 'gr-rej' }));
      g.append(texto(m.l - 6, y(t) + 3.5, U.num(t), { 'text-anchor': 'end', class: 'gr-txt gr-num' }));
    }
    const indicesPasada = new Set(fechas.map((f) => U.dias(f0, f)));
    for (const i of indicesPasada) {
      if (i < 0 || i >= n) continue;
      g.append(U.svg('line', { x1: x(i), x2: x(i), y1: yA0, y2: yA1, class: 'gr-pasada' }));
      g.append(U.svg('circle', { cx: x(i), cy: yA1 + 8, r: 3.5, fill: C.agua, class: 'gr-punto' }));
    }
    const bw = Math.max(1, (W - m.l - m.r) / n - 0.6);
    let kMax = 0;
    valores.forEach((v, i) => {
      if (!Number.isFinite(v)) return;
      if (v > (valores[kMax] || 0)) kMax = i;
      const dd = barraArriba(x(i) - bw / 2, y(v), bw, yA1 - y(v), 1);
      if (dd) g.append(U.svg('path', { d: dd, fill: C.lluvia }));
    });
    const anchor = x(kMax) > W - 70 ? 'end' : x(kMax) < m.l + 40 ? 'start' : 'middle';
    g.append(texto(x(kMax), y(valores[kMax]) - 6, U.num(valores[kMax], 0) + ' mm · ' + U.fecha(d[kMax].fecha, 'corta'), { 'text-anchor': anchor, class: 'gr-txt gr-dest' }));
    ejeMeses(g, f0, fN, xf, yA1 + 28);
    const xs = d.map((v, i) => x(i));
    const contenido = (i) => {
      const out = [U.el('div', { class: 'tf-fecha', text: U.fecha(d[i].fecha, 'larga') })];
      out.push(fila(C.lluvia, 'barra', Number.isFinite(valores[i]) ? U.num(valores[i], 1) + ' mm' : '—', U.t('g_lluvia_dia')));
      if (indicesPasada.has(i)) out.push(fila(C.agua, 'punto', U.t('g_pasada'), ''));
      return out;
    };
    const pp = meta.lluvia.por_paso || [];
    return envolver({
      titulo: U.t('g_lluvia_tit'), sub: U.t('g_fuente_power'),
      items: [{ color: C.lluvia, forma: 'barra', nombre: U.t('g_lluvia_dia') }, { color: C.agua, forma: 'punto', nombre: U.t('g_pasada') }],
      svg, alto: yA1 + 32, xs, cruz: [yA0 - 4, yA1], contenido, aria: U.t('g_lluvia_tit'),
      tabla: tablaDatos([U.t('g_fecha'), U.t('g_3d'), U.t('g_7d'), U.t('g_desde')],
        pp.map((p) => [U.fecha(p.fecha, 'larga'), U.num(p.previos_3d_mm, 1), U.num(p.previos_7d_mm, 1), U.num(p.desde_paso_anterior_mm, 1)]))
    });
  }

  function calibracion(meta) {
    const nm = meta.normalizacion;
    if (!nm) return null;
    const fechas = meta.fechas;
    const f0 = fechas[0];
    const fN = fechas[fechas.length - 1];
    const m = { l: 36, r: 14 };
    const x = lineal(0, U.dias(f0, fN), m.l + 12, W - m.r - 12);
    const xf = (iso) => x(U.dias(f0, iso));
    const xs = fechas.map(xf);
    const sHH = nm.ajuste_hh_db || [];
    const sHV = nm.ajuste_hv_db || [];
    const dY = dominio([...sHH, ...sHV], true, 4);
    const yA0 = 12;
    const yA1 = 118;
    const y = lineal(dY.lo, dY.hi, yA1, yA0);
    const svg = U.svg('svg', {});
    const g = U.svg('g', {});
    svg.append(g);
    for (const t of dY.ticks) {
      g.append(U.svg('line', { x1: m.l, x2: W - m.r, y1: y(t), y2: y(t), class: Math.abs(t) < 1e-9 ? 'gr-eje' : 'gr-rej' }));
      g.append(texto(m.l - 6, y(t) + 3.5, U.firmado(t, dY.dec).replace(/^\+?0([.,]0+)?$/, '0'), { 'text-anchor': 'end', class: 'gr-txt gr-num' }));
    }
    const bw = Math.min(9, ((W - m.l - m.r) / fechas.length - 6) / 2);
    const y0 = y(0);
    const dibujar = (valores, color, dx) => {
      valores.forEach((v, i) => {
        if (!Number.isFinite(v)) return;
        const xx = xs[i] + dx;
        const d = v >= 0 ? barraArriba(xx, y(v), bw, y0 - y(v), 3) : barraAbajo(xx, y0, bw, y(v) - y0, 3);
        if (d) g.append(U.svg('path', { d, fill: color }));
      });
    };
    dibujar(sHH, C.hh, -bw - 1);
    dibujar(sHV, C.hv, 1);
    ejeMeses(g, f0, fN, xf, yA1 + 22);
    const contenido = (i) => [
      U.el('div', { class: 'tf-fecha', text: U.fecha(fechas[i], 'larga') }),
      fila(C.hh, 'barra', U.firmado(sHH[i], 2) + ' dB', 'HH'),
      fila(C.hv, 'barra', U.firmado(sHV[i], 2) + ' dB', 'HV')
    ];
    return envolver({
      titulo: U.t('g_cal_tit'),
      items: [{ color: C.hh, forma: 'barra', nombre: 'HH' }, { color: C.hv, forma: 'barra', nombre: 'HV' }],
      svg, alto: yA1 + 26, xs, cruz: [yA0, yA1], contenido, aria: U.t('g_cal_tit'),
      nota: U.t('g_cal_nota', { n: U.num(nm.pixeles_estables || 0) }),
      tabla: tablaDatos([U.t('g_fecha'), 'HH (dB)', 'HV (dB)'], fechas.map((f, i) => [U.fecha(f, 'larga'), U.firmado(sHH[i], 2), U.firmado(sHV[i], 2)]))
    });
  }

  const r2 = (v) => (Number.isFinite(v) ? U.firmado(v, 2) : '—');

  G.tarjeta = (tipo, meta, extra = {}) => {
    try {
      const pp = meta.lluvia.por_paso || [];
      const corr = meta.lluvia.correlaciones || {};
      const rd = meta.retrodispersion || {};
      if (tipo === 'lluvia') return lluvia(meta);
      if (tipo === 'calibracion') return calibracion(meta);
      if (tipo === 'agua') {
        return bandas(meta, {
          titulo: U.t('g_agua_tit'), marcarMax: true,
          arriba: { series: [{ nombre: U.t('g_agua_serie'), color: C.agua, valores: meta.agua.temporal_km2 }], unidad: 'km²', dec: 2, cero: true, rotulo: U.t('g_agua_rot') },
          abajo: { nombre: U.t('g_lluvia7'), rotulo: U.t('g_lluvia7_rot'), color: C.lluvia, valores: pp.map((p) => p.previos_7d_mm), unidad: 'mm', dec: 0 },
          nota: U.t('g_r_agua', { r7: r2(corr.agua_temporal_vs_lluvia_7d != null ? corr.agua_temporal_vs_lluvia_7d : meta.lluvia.correlacion_agua_temporal_vs_7d), r3: r2(corr.agua_temporal_vs_lluvia_3d) })
        });
      }
      if (tipo === 'humedad') {
        if (!meta.humedad) return null;
        return bandas(meta, {
          titulo: U.t('g_hum_tit'),
          arriba: { series: [{ nombre: U.t('g_hum_serie'), color: C.humedad, valores: meta.humedad.indice_medio }], unidad: '', dec: 2, rotulo: U.t('g_hum_rot') },
          abajo: { nombre: U.t('g_lluvia3'), rotulo: U.t('g_lluvia3_rot'), color: C.lluvia, valores: pp.map((p) => p.previos_3d_mm), unidad: 'mm', dec: 0 },
          nota: U.t('g_r_hum', { r3: r2(corr.humedad_vs_lluvia_3d), r7: r2(corr.humedad_vs_lluvia_7d) })
        });
      }
      if (tipo === 'mar') {
        return bandas(meta, {
          titulo: U.t('g_mar_tit'),
          arriba: { series: [
            { nombre: U.t('g_mar'), color: C.mar, valores: rd.mar_hh_db_mediana },
            { nombre: U.t('g_tierra'), color: C.tierra, valores: rd.hh_db_mediana }
          ], unidad: 'dB', dec: 1 },
          nota: U.t('g_mar_nota')
        });
      }
      if (tipo === 'polarizaciones') {
        return bandas(meta, {
          titulo: U.t('g_pol_tit'),
          arriba: { series: [
            { nombre: 'HH', color: C.hh, valores: rd.hh_db_mediana },
            { nombre: 'HV', color: C.hv, valores: rd.hv_db_mediana }
          ], unidad: 'dB', dec: 1 },
          nota: U.t('g_pol_nota')
        });
      }
      if (tipo === 'laguna') {
        const s = extra.laguna;
        if (!s) return U.el('p', { class: 'gr-nota', text: U.t('g_laguna_sin') });
        return G.laguna(meta, s, extra.actual != null ? extra.actual : null, true);
      }
    } catch (e) {
      return null;
    }
    return null;
  };

  G.laguna = (meta, s, actual, conTitulo) => {
    const algunaAbierta = s.agua_abierta_pct.some((v) => v > 0);
    return bandas(meta, {
      titulo: conTitulo ? (s.nombre || U.t('laguna_sin_nombre')) : null,
      sub: conTitulo ? U.t('g_laguna_sub', { ha: U.num(s.area_ha, 1), firma: U.t('firma_' + claveFirma(s.firma)) }) : null,
      actual,
      arriba: { series: [
        { nombre: 'HH', color: C.hh, valores: s.hh },
        { nombre: 'HV', color: C.hv, valores: s.hv }
      ], unidad: 'dB', dec: 1, rotulo: U.t('g_retro_rot'), alto: 84 },
      abajo: algunaAbierta ? { nombre: U.t('g_abierta'), rotulo: U.t('g_abierta_rot'), color: C.agua, valores: s.agua_abierta_pct, unidad: '%', dec: 1, alto: 32 } : null,
      nota: algunaAbierta ? null : U.t('g_abierta_cero')
    });
  };

  function claveFirma(f) {
    return f === 'vegetacion sobre agua' ? 'veg' : f === 'agua abierta' ? 'abierta' : 'mixta';
  }
  G.claveFirma = claveFirma;

  G.serie = (meta, s, lluvia7, actual) => {
    const colores = s.agua.map((a) => (s.mascara === 2 ? C.mar_f : a ? C.agua : C.vacio));
    const textos = s.agua.map((a, i) => (s.hh[i] == null ? '—' : s.mascara === 2 ? U.t('pp_mar') : a ? U.t('pp_agua') : U.t('pp_sin_agua')));
    return bandas(meta, {
      actual,
      arriba: { series: [
        { nombre: 'HH', color: C.hh, valores: s.hh.map((v) => (v == null ? NaN : v)) },
        { nombre: 'HV', color: C.hv, valores: s.hv.map((v) => (v == null ? NaN : v)) }
      ], unidad: 'dB', dec: 1, rotulo: U.t('g_retro_rot'), alto: 84 },
      franja: { colores, textos, nombre: U.t('pp_clasif'), rotulo: U.t('pp_clasif_rot') },
      abajo: { nombre: U.t('g_lluvia7'), rotulo: U.t('g_lluvia7_rot'), color: C.lluvia, valores: lluvia7, unidad: 'mm', dec: 0, alto: 30 }
    });
  };

  window.Graficas = G;
})();
