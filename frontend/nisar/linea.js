/* Línea de tiempo reutilizable de la historia NISAR: lluvia diaria de NASA POWER en
   barras, agua temporal en km² como línea en su propia banda (sin doble eje) y las
   pasadas de NISAR como nodos. Se arrastra (se ajusta a la pasada más cercana), se
   reproduce en bucle y funciona con teclado como slider ARIA. */
(function () {
  const ICONO_PLAY = 'M7 4.5v15l12-7.5z';
  const ICONO_PAUSA = 'M7 4.5h3.6v15H7zM13.4 4.5H17v15h-3.6z';

  class LineaTiempo {
    constructor(raiz, { meta, alCambiar, alReproducir }) {
      this.raiz = raiz;
      this.meta = meta;
      this.alCambiar = alCambiar;
      this.alReproducir = alReproducir;
      this.i = 0;
      this.timer = null;
      this.arrastre = false;
      this.construir();
      this.observador = new ResizeObserver(() => this.dibujar());
      this.observador.observe(this.zona);
    }

    construir() {
      const n = this.meta.fechas.length;
      this.icono = U.svg('path', { d: ICONO_PLAY });
      this.boton = U.el('button', { type: 'button', class: 'lt-play', onclick: () => this.alternar() },
        U.svg('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' }, this.icono));
      this.pasadaEl = U.el('span', { class: 'lt-pasada' });
      this.fechaEl = U.el('strong', { class: 'lt-fecha' });
      this.datoEl = U.el('span', { class: 'lt-dato' });
      this.leyendaEl = U.el('span', { class: 'lt-ley' });
      this.info = U.el('div', { class: 'lt-info' }, this.pasadaEl, this.fechaEl, this.datoEl, this.leyendaEl);
      this.svg = U.svg('svg', { class: 'lt-svg', 'aria-hidden': 'true' });
      this.tip = U.el('div', { class: 'lt-tip', hidden: true });
      this.zona = U.el('div', {
        class: 'lt-zona', role: 'slider', tabindex: '0',
        'aria-valuemin': '1', 'aria-valuemax': String(n), 'aria-valuenow': '1'
      }, this.svg, this.tip);
      this.raiz.replaceChildren(this.boton, this.info, this.zona);

      this.zona.addEventListener('pointerdown', (e) => {
        if (e.button !== 0) return;
        this.arrastre = true;
        this.zona.setPointerCapture(e.pointerId);
        this.pausar();
        this.desdePuntero(e);
      });
      this.zona.addEventListener('pointermove', (e) => {
        if (this.arrastre) this.desdePuntero(e);
        this.flotar(e);
      });
      const soltar = () => { this.arrastre = false; };
      this.zona.addEventListener('pointerup', soltar);
      this.zona.addEventListener('pointercancel', soltar);
      this.zona.addEventListener('pointerleave', () => { this.tip.hidden = true; this.cruz && this.cruz.setAttribute('visibility', 'hidden'); });
      this.zona.addEventListener('keydown', (e) => {
        const n = this.meta.fechas.length;
        const mapa = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 3, PageDown: -3 };
        let i = null;
        if (e.key in mapa) i = this.i + mapa[e.key];
        else if (e.key === 'Home') i = 0;
        else if (e.key === 'End') i = n - 1;
        else if (e.key === ' ' || e.key === 'Enter') {
          e.preventDefault();
          this.alternar();
          return;
        }
        if (i == null) return;
        e.preventDefault();
        this.pausar();
        this.fijar(U.limitar(i, 0, n - 1), true);
      });
      this.textos();
    }

    textos() {
      this.boton.setAttribute('aria-label', this.timer ? U.t('tl_pausa') : U.t('tl_play'));
      this.zona.setAttribute('aria-label', U.t('tl_aria'));
      this.leyendaEl.replaceChildren(
        U.el('span', {}, U.el('i', { class: 'k k-linea', style: { background: Graficas.colores.agua } }), U.t('tl_agua')),
        U.el('span', {}, U.el('i', { class: 'k k-barra', style: { background: Graficas.colores.lluvia } }), U.t('tl_lluvia')));
      this.dibujar();
    }

    dibujar() {
      const W = this.zona.clientWidth;
      if (!W) return;
      const H = 84;
      const meta = this.meta;
      const d = meta.lluvia.diaria;
      const f0 = d[0].fecha;
      const T = d.length;
      const pad = 10;
      const x = (iso) => pad + (U.dias(f0, iso) + 0.5) / T * (W - pad * 2);
      this.x = x;
      this.W = W;
      const svg = this.svg;
      svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
      svg.setAttribute('width', W);
      svg.setAttribute('height', H);
      svg.replaceChildren();
      const yA0 = 10;
      const yA1 = 34;
      const yB0 = 44;
      const yB1 = 64;
      const agua = (meta.agua && meta.agua.temporal_km2) || [];
      const maxA = Math.max(0.001, ...agua.filter(Number.isFinite));
      const yA = (v) => yA1 - v / maxA * (yA1 - yA0);
      const mm = d.map((v) => v.mm || 0);
      const maxB = Math.max(1, ...mm);
      svg.append(U.svg('line', { x1: pad, x2: W - pad, y1: yB1 + 0.5, y2: yB1 + 0.5, class: 'lt-base' }));
      const bw = Math.max(1, (W - pad * 2) / T - (W > 600 ? 1.2 : 0.4));
      d.forEach((v, k) => {
        if (!v.mm) return;
        const h = v.mm / maxB * (yB1 - yB0);
        const xx = x(v.fecha) - bw / 2;
        svg.append(U.svg('rect', { x: xx, y: yB1 - h, width: bw, height: h, rx: Math.min(1.5, bw / 2), class: 'lt-lluvia' }));
      });
      const fechas = meta.fechas;
      this.xs = fechas.map(x);
      let dl = '';
      fechas.forEach((f, k) => {
        if (Number.isFinite(agua[k])) dl += (dl ? 'L' : 'M') + this.xs[k].toFixed(1) + ',' + yA(agua[k]).toFixed(1);
      });
      svg.append(U.svg('path', { d: dl, class: 'lt-agua' }));
      this.sel = U.svg('line', { x1: 0, x2: 0, y1: 4, y2: yB1, class: 'lt-sel' });
      svg.append(this.sel);
      this.nodos = fechas.map((f, k) => {
        const cy = Number.isFinite(agua[k]) ? yA(agua[k]) : yA1;
        const gr = U.svg('g', { class: 'lt-nodo', transform: `translate(${this.xs[k]},${cy})` },
          U.svg('circle', { r: 9, class: 'lt-ping' }),
          U.svg('circle', { r: 4, class: 'lt-punto' }));
        svg.append(gr);
        return gr;
      });
      const [a0, m0] = f0.split('-').map(Number);
      let anio = a0;
      let mes = m0 + 1;
      const fN = d[d.length - 1].fecha;
      for (let k = 0; k < 14; k++) {
        if (mes > 12) { mes = 1; anio += 1; }
        const iso = `${anio}-${String(mes).padStart(2, '0')}-01`;
        if (iso > fN) break;
        const px = x(iso);
        svg.append(U.svg('line', { x1: px, x2: px, y1: yB1 + 2, y2: yB1 + 6, class: 'lt-tick' }));
        svg.append(U.svg('text', { x: px + 3, y: H - 6, class: 'lt-mes', text: U.fecha(iso, 'mes') }));
        mes += 1;
      }
      this.cruz = U.svg('line', { x1: 0, x2: 0, y1: 4, y2: yB1, class: 'lt-cruz', visibility: 'hidden' });
      svg.append(this.cruz);
      this.actualizar(false);
    }

    desdePuntero(e) {
      if (!this.xs) return;
      const r = this.zona.getBoundingClientRect();
      const px = e.clientX - r.left;
      let mejor = 0;
      this.xs.forEach((v, k) => {
        if (Math.abs(v - px) < Math.abs(this.xs[mejor] - px)) mejor = k;
      });
      this.fijar(mejor, true);
    }

    flotar(e) {
      if (!this.x) return;
      const d = this.meta.lluvia.diaria;
      const r = this.zona.getBoundingClientRect();
      const px = e.clientX - r.left;
      const T = d.length;
      const k = U.limitar(Math.round((px - 10) / (this.W - 20) * T - 0.5), 0, T - 1);
      const dia = d[k];
      const xx = this.x(dia.fecha);
      this.cruz.setAttribute('x1', xx);
      this.cruz.setAttribute('x2', xx);
      this.cruz.setAttribute('visibility', 'visible');
      const idx = this.meta.fechas.indexOf(dia.fecha);
      const filas = [
        U.el('div', { class: 'tf-fecha', text: U.fecha(dia.fecha, 'larga') }),
        U.el('div', { class: 'tf' }, U.el('i', { class: 'k k-barra', style: { background: Graficas.colores.lluvia } }),
          U.el('b', { text: dia.mm == null ? '—' : U.num(dia.mm, 1) + ' mm' }), U.el('span', { text: U.t('tl_lluvia') }))
      ];
      if (idx >= 0 && this.meta.agua) {
        filas.push(U.el('div', { class: 'tf' }, U.el('i', { class: 'k k-linea', style: { background: Graficas.colores.agua } }),
          U.el('b', { text: U.num(this.meta.agua.temporal_km2[idx], 2) + ' km²' }), U.el('span', { text: U.t('tl_agua') })));
        filas.push(U.el('div', { class: 'tf-nota', text: U.t('tl_pasada_n', { i: idx + 1, n: this.meta.fechas.length }) }));
      }
      this.tip.replaceChildren(...filas);
      this.tip.hidden = false;
      const ancho = this.tip.offsetWidth;
      const izq = xx + 14 + ancho > this.W ? xx - 14 - ancho : xx + 14;
      this.tip.style.left = U.limitar(izq, 0, Math.max(0, this.W - ancho)) + 'px';
    }

    fijar(i, emitir = false) {
      const n = this.meta.fechas.length;
      i = U.limitar(i | 0, 0, n - 1);
      const cambio = i !== this.i;
      this.i = i;
      this.actualizar(cambio);
      if (emitir && cambio && this.alCambiar) this.alCambiar(i);
    }

    actualizar(ping) {
      const meta = this.meta;
      const n = meta.fechas.length;
      const i = this.i;
      const f = meta.fechas[i];
      this.pasadaEl.textContent = U.t('tl_pasada_n', { i: i + 1, n });
      this.fechaEl.textContent = U.fecha(f, 'larga');
      const pp = meta.lluvia.por_paso && meta.lluvia.por_paso[i];
      const km = meta.agua && meta.agua.temporal_km2 ? meta.agua.temporal_km2[i] : null;
      this.datoEl.textContent = U.t('tl_dato', {
        km: km == null ? '—' : U.num(km, 2),
        mm: pp ? U.num(pp.previos_7d_mm, 0) : '—'
      });
      this.zona.setAttribute('aria-valuenow', String(i + 1));
      this.zona.setAttribute('aria-valuetext', U.t('tl_valor', { i: i + 1, n, fecha: U.fecha(f, 'completa') }));
      if (this.xs) {
        this.sel.setAttribute('x1', this.xs[i]);
        this.sel.setAttribute('x2', this.xs[i]);
        this.nodos.forEach((g, k) => {
          g.classList.toggle('on', k === i);
          g.classList.remove('pinga');
        });
        if (ping && !U.reducido()) {
          const g = this.nodos[i];
          void g.getBoundingClientRect();
          g.classList.add('pinga');
        }
      }
    }

    reproducir() {
      if (this.timer) return;
      const n = this.meta.fechas.length;
      this.timer = setInterval(() => this.fijar((this.i + 1) % n, true), 1700);
      this.icono.setAttribute('d', ICONO_PAUSA);
      this.boton.classList.add('on');
      this.boton.setAttribute('aria-label', U.t('tl_pausa'));
      if (this.alReproducir) this.alReproducir(true);
    }

    pausar() {
      if (!this.timer) return;
      clearInterval(this.timer);
      this.timer = null;
      this.icono.setAttribute('d', ICONO_PLAY);
      this.boton.classList.remove('on');
      this.boton.setAttribute('aria-label', U.t('tl_play'));
      if (this.alReproducir) this.alReproducir(false);
    }

    alternar() {
      if (this.timer) this.pausar();
      else this.reproducir();
    }
  }

  window.LineaTiempo = LineaTiempo;
})();
