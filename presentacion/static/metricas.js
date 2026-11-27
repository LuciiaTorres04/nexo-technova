// Panel de métricas: lee /api/metricas y dibuja todo con HTML y SVG a mano
// (sin librerías de gráficas). Igual que en el chat, el texto va siempre con
// textContent.

const $ = (id) => document.getElementById(id);
const crear = (etiqueta, clase, texto) => {
  const el = document.createElement(etiqueta);
  if (clase) el.className = clase;
  if (texto !== undefined) el.textContent = texto;
  return el;
};
const euros = (v, d = 4) => `${v.toFixed(d).replace(".", ",")} €`;
const entero = (v) => Math.round(v).toLocaleString("es-ES");
const tiempo = (ms) => (ms < 1000 ? `${ms.toFixed(ms < 10 ? 1 : 0).replace(".", ",")} ms` : `${(ms / 1000).toFixed(2).replace(".", ",")} s`);
const NOMBRES = { reglas: "Reglas de NEXO", ia: "IA", eco: "Eco" };

async function cargar() {
  const r = await fetch("/api/metricas");
  const datos = await r.json();
  if (!r.ok) {
    document.querySelector(".metricas").appendChild(crear("p", "vacio-grafica", datos.error));
    return;
  }
  const m = datos.metricas;
  pintarHeroe(m, datos.coste);
  pintarReparto(m);
  pintarVelocidad(m);
  pintarOpiniones(datos.valoraciones);
  pintarDias(m.por_dia);
  pintarTabla(m.ultimas);
}

// ---------- cifra principal + fichas ----------
function pintarHeroe(m, coste) {
  const reglas = m.por_fuente.reglas;
  const ia = m.por_fuente.ia;
  $("ahorro").textContent = euros(m.ahorro);
  $("ahorro-detalle").textContent = ia.respuestas
    ? `${reglas.respuestas} respuestas de las reglas × ${euros(m.coste_medio_ia, 6)} (coste medio de una respuesta de IA).`
    : "Aún no hay respuestas de IA para calcular el coste medio.";

  const respondidas = reglas.respuestas + ia.respuestas;
  const fichas = [
    ["Respuestas totales", entero(m.total), `${m.por_fuente.eco.respuestas} en modo eco`],
    ["Resueltas sin IA", respondidas ? `${Math.round((reglas.respuestas / respondidas) * 100)} %` : "—", `${reglas.respuestas} de ${respondidas}`],
    ["Tokens de IA", entero(ia.tokens), "solo en el chat"],
    ["Gasto total en IA", euros(coste ? coste.coste : ia.coste), "incluye el laboratorio"],
  ];
  $("fichas").replaceChildren(...fichas.map(([etiqueta, valor, detalle]) => {
    const f = crear("div", "stat");
    f.append(crear("div", "etiqueta", etiqueta), crear("div", "valor", valor), crear("div", "detalle", detalle));
    return f;
  }));
}

// ---------- barra segmentada: quién responde ----------
function pintarReparto(m) {
  const partes = ["reglas", "ia", "eco"].map((f) => [f, m.por_fuente[f].respuestas]).filter(([, n]) => n > 0);
  const total = partes.reduce((s, [, n]) => s + n, 0);
  if (!total) {
    $("reparto").replaceChildren(crear("p", "vacio-grafica", "Todavía no hay respuestas. Escribe algo en el chat."));
    return;
  }
  const barra = crear("div", "segmentada");
  barra.setAttribute("role", "img");
  barra.setAttribute("aria-label", partes.map(([f, n]) => `${NOMBRES[f]}: ${n} (${Math.round((n / total) * 100)} %)`).join(", "));
  for (const [fuente, n] of partes) {
    const seg = crear("div", `segmento ${fuente}`);
    seg.style.flex = String(n);
    const porcentaje = Math.round((n / total) * 100);
    seg.title = `${NOMBRES[fuente]}: ${n} respuestas (${porcentaje} %)`;
    if (porcentaje >= 12) seg.textContent = `${porcentaje} %`; // solo si cabe
    barra.appendChild(seg);
  }
  const leyenda = crear("div", "leyenda");
  for (const [fuente, n] of partes) {
    const s = crear("span");
    const muestra = crear("i");
    muestra.style.background = fuente === "eco" ? "var(--eje)" : `var(--serie-${fuente})`;
    s.append(muestra, `${NOMBRES[fuente]} · ${n}`);
    leyenda.appendChild(s);
  }
  $("reparto").replaceChildren(barra, leyenda);
}

// ---------- velocidad: dos barras en la misma escala ----------
function pintarVelocidad(m) {
  const reglas = m.por_fuente.reglas;
  const ia = m.por_fuente.ia;
  const filas = [["reglas", reglas], ["ia", ia]].filter(([, d]) => d.respuestas);
  if (!filas.length) {
    $("velocidad").replaceChildren(crear("p", "vacio-grafica", "Sin datos todavía."));
    return;
  }
  const maximo = Math.max(...filas.map(([, d]) => d.ms_medio)) || 1;
  const elementos = filas.map(([fuente, d]) => {
    const fila = crear("div", "fila");
    const pista = crear("div", "pista");
    const barra = crear("div", `barra ${fuente}`);
    barra.style.width = `${(d.ms_medio / maximo) * 100}%`;
    pista.appendChild(barra);
    fila.append(crear("span", "", fuente === "ia" ? "IA" : "Reglas"), pista, crear("span", "valor", tiempo(d.ms_medio)));
    fila.title = `${NOMBRES[fuente]}: ${tiempo(d.ms_medio)} de media en ${d.respuestas} respuestas`;
    return fila;
  });
  if (reglas.respuestas && ia.respuestas && reglas.ms_medio > 0) {
    const veces = ia.ms_medio / reglas.ms_medio;
    elementos.push(crear("p", "nota", `Las reglas responden ${entero(veces)} veces más rápido que la IA.`));
  }
  $("velocidad").replaceChildren(...elementos);
}

// ---------- opiniones: % de 👍 de reglas frente a IA ----------
function pintarOpiniones(valoraciones) {
  const filas = ["reglas", "ia"]
    .map((fuente) => [fuente, valoraciones?.[fuente]])
    .filter(([, v]) => v && v.positivas + v.negativas > 0);
  if (!filas.length) {
    $("opiniones").replaceChildren(crear("p", "vacio-grafica", "Aún no hay valoraciones. Pulsa 👍 o 👎 bajo una respuesta del chat."));
    return;
  }
  $("opiniones").replaceChildren(...filas.map(([fuente, v]) => {
    const total = v.positivas + v.negativas;
    const porcentaje = Math.round((v.positivas / total) * 100);
    const fila = crear("div", "fila");
    const pista = crear("div", "pista");
    const barra = crear("div", `barra ${fuente}`);
    barra.style.width = `${porcentaje}%`;
    pista.appendChild(barra);
    fila.append(crear("span", "", fuente === "ia" ? "IA" : "Reglas"), pista, crear("span", "valor", `${porcentaje} % 👍`));
    fila.title = `${NOMBRES[fuente]}: ${v.positivas} 👍 y ${v.negativas} 👎 (${total} valoradas)`;
    return fila;
  }));
}

// ---------- columnas: tokens por día (SVG) ----------
function pasoLimpio(maximo) {
  // Elige un paso "redondo" para el eje (1, 2, 5, 10, 20, 50…).
  const bruto = maximo / 4;
  const potencia = 10 ** Math.floor(Math.log10(bruto || 1));
  return [1, 2, 5, 10].map((m) => m * potencia).find((p) => p >= bruto) || potencia * 10;
}

function pintarDias(dias) {
  const caja = $("grafica-dias");
  const conTokens = dias.filter((d) => d.tokens > 0).slice(-14); // últimos 14 días con uso
  if (!conTokens.length) {
    caja.replaceChildren(crear("p", "vacio-grafica", "La IA aún no ha gastado tokens en el chat."));
    return;
  }
  const ns = "http://www.w3.org/2000/svg";
  const svgEl = (etiqueta, atributos) => {
    const el = document.createElementNS(ns, etiqueta);
    for (const [k, v] of Object.entries(atributos)) el.setAttribute(k, v);
    return el;
  };
  const ancho = caja.clientWidth || 800;
  const alto = 220;
  const margen = { arriba: 12, derecha: 8, abajo: 26, izquierda: 44 };
  const zonaAncho = ancho - margen.izquierda - margen.derecha;
  const zonaAlto = alto - margen.arriba - margen.abajo;
  const maxDato = Math.max(...conTokens.map((d) => d.tokens));
  const paso = pasoLimpio(maxDato);
  const techo = Math.ceil(maxDato / paso) * paso;
  const y = (v) => margen.arriba + zonaAlto - (v / techo) * zonaAlto;

  const svg = svgEl("svg", { viewBox: `0 0 ${ancho} ${alto}`, role: "img", "aria-label": "Tokens de IA por día" });
  for (let v = 0; v <= techo; v += paso) {
    svg.appendChild(svgEl("line", { class: v === 0 ? "base" : "rejilla-linea", x1: margen.izquierda, x2: ancho - margen.derecha, y1: y(v), y2: y(v) }));
    const etiqueta = svgEl("text", { x: margen.izquierda - 8, y: y(v) + 4, "text-anchor": "end" });
    etiqueta.textContent = entero(v);
    svg.appendChild(etiqueta);
  }
  const banda = zonaAncho / conTokens.length;
  const grosor = Math.min(24, banda * 0.6); // columnas finas: como mucho 24 px
  const tooltip = crear("div", "tooltip");
  tooltip.hidden = true;

  conTokens.forEach((d, i) => {
    const cx = margen.izquierda + banda * i + banda / 2;
    const alturaCol = (d.tokens / techo) * zonaAlto;
    const top = y(d.tokens);
    const r = Math.min(4, alturaCol); // extremo redondeado de 4 px, base recta
    const xi = cx - grosor / 2;
    const base = y(0);
    const camino = `M${xi},${base} V${top + r} Q${xi},${top} ${xi + r},${top} H${xi + grosor - r} Q${xi + grosor},${top} ${xi + grosor},${top + r} V${base} Z`;
    // Zona de "hover" más grande que la columna, para que sea fácil apuntar.
    const zona = svgEl("rect", { class: "columna-hit", x: cx - banda / 2, y: margen.arriba, width: banda, height: zonaAlto });
    const columna = svgEl("path", { class: "columna", d: camino });
    const fecha = new Date(`${d.dia}T12:00:00`);
    const textoFecha = fecha.toLocaleDateString("es-ES", { day: "numeric", month: "short" });
    zona.addEventListener("mouseenter", () => {
      columna.classList.add("activa");
      tooltip.textContent = `${textoFecha} · ${entero(d.tokens)} tokens · ${euros(d.coste, 6)} · ${d.ia} respuestas de IA`;
      tooltip.style.left = `${(cx / ancho) * 100}%`;
      tooltip.style.top = `${top}px`; // el SVG mide 220 px de alto, igual que su viewBox
      tooltip.hidden = false;
    });
    zona.addEventListener("mouseleave", () => {
      columna.classList.remove("activa");
      tooltip.hidden = true;
    });
    svg.append(zona, columna);
    const etiqueta = svgEl("text", { x: cx, y: alto - 6, "text-anchor": "middle" });
    etiqueta.textContent = textoFecha;
    svg.appendChild(etiqueta);
  });
  caja.replaceChildren(svg, tooltip);
}

// ---------- tabla ----------
function pintarTabla(filas) {
  if (!filas.length) {
    $("tabla").replaceChildren(crear("p", "vacio-grafica", "Sin respuestas registradas."));
    return;
  }
  const tabla = crear("table", "tabla");
  const cabecera = crear("tr");
  for (const [texto, clase] of [["Hora", ""], ["Quién", ""], ["Tiempo", "num"], ["Tokens", "num"], ["Coste", "num"]]) {
    cabecera.appendChild(crear("th", clase, texto));
  }
  const thead = crear("thead");
  thead.appendChild(cabecera);
  const tbody = crear("tbody");
  for (const f of filas) {
    const tr = crear("tr");
    const quien = crear("td");
    const punto = crear("i");
    punto.style.cssText = "display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;";
    punto.style.background = f.fuente === "ia" ? "var(--serie-ia)" : f.fuente === "reglas" ? "var(--serie-reglas)" : "var(--eje)";
    quien.append(punto, NOMBRES[f.fuente] || f.fuente);
    tr.append(
      crear("td", "", new Date(f.timestamp).toLocaleString("es-ES", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })),
      quien,
      crear("td", "num", tiempo(Number(f.ms))),
      crear("td", "num", entero(Number(f.tokens))),
      crear("td", "num", euros(Number(f.coste), 6)),
    );
    tbody.appendChild(tr);
  }
  tabla.append(thead, tbody);
  $("tabla").replaceChildren(tabla);
}

cargar();
// Redibuja la gráfica al cambiar el tamaño de la ventana.
let temporizador;
window.addEventListener("resize", () => {
  clearTimeout(temporizador);
  temporizador = setTimeout(cargar, 200);
});
