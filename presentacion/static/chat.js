// =====================================================================
// NEXO · lógica del chat en el navegador
// SEGURIDAD: todo el texto se pone con textContent, NUNCA con innerHTML.
// Si el LLM (o alguien) devolviera "<script>...</script>", se vería como
// texto y no se ejecutaría (así se evita un ataque XSS).
// =====================================================================

const $ = (id) => document.getElementById(id);
const chat = $("chat");
const formulario = $("formulario");
const caja = $("mensaje");
const botonEnviar = $("enviar");
const bienvenida = $("bienvenida");
const botonEco = $("eco");
const aviso = $("aviso");

let ocupado = false;
let conversacionActual = null;
let rayosActivo = false;

// ---------- utilidades ----------
function crear(etiqueta, clase, texto) {
  const el = document.createElement(etiqueta);
  if (clase) el.className = clase;
  if (texto !== undefined) el.textContent = texto;
  return el;
}

function icono(nombre) {
  // <svg class="i"><use href="#i-nombre"/></svg>, creado sin innerHTML
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("class", "i");
  const use = document.createElementNS(ns, "use");
  use.setAttribute("href", `#i-${nombre}`);
  svg.appendChild(use);
  return svg;
}

function burbuja(clase, texto = "") {
  bienvenida.hidden = true;
  const div = crear("div", `mensaje ${clase}`);
  const cuerpo = crear("span", "cuerpo", texto);
  div.appendChild(cuerpo);
  chat.appendChild(div);
  bajar();
  return div;
}
const cuerpoDe = (burbujaEl) => burbujaEl.querySelector(".cuerpo");

function bajar() {
  chat.scrollTop = chat.scrollHeight;
}

function mostrarAviso(texto) {
  aviso.textContent = texto;
  aviso.hidden = false;
  clearTimeout(mostrarAviso.temporizador);
  mostrarAviso.temporizador = setTimeout(() => (aviso.hidden = true), 3200);
}

const euros = (valor) => valor.toFixed(6).replace(".", ",");

function pintarCoste(coste) {
  if (!coste) return;
  $("total-tokens").textContent = coste.tokens.toLocaleString("es-ES");
  $("total-coste").textContent = euros(coste.coste);
}

function pintarTitulo(titulo) {
  $("titulo").textContent = titulo || "Nueva conversación";
  document.title = titulo && titulo !== "Nueva conversación" ? `${titulo} · NEXO` : "NEXO · TechNova";
}

// El único "selector" de modelo que queda: el botón eco, discreto.
function marcarModelo(nombre) {
  botonEco.setAttribute("aria-pressed", String(nombre === "eco"));
}

function bloquear(si) {
  ocupado = si;
  botonEnviar.disabled = si;
  botonEco.disabled = si;
}

async function postJSON(url, datos = {}, metodo = "POST") {
  const r = await fetch(url, {
    method: metodo,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(datos),
  });
  const json = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(json.error || `Error ${r.status}`);
  return json;
}

// =====================================================================
// TEMA (Crema / Espresso)
// =====================================================================
const raiz = document.documentElement;
const medioOscuro = window.matchMedia("(prefers-color-scheme: dark)");
const temaActual = () => raiz.dataset.theme || (medioOscuro.matches ? "espresso" : "crema");

function pintarBotonTema() {
  const oscuro = temaActual() === "espresso";
  const boton = $("tema");
  boton.replaceChildren(icono(oscuro ? "sol" : "luna"));
  boton.setAttribute("aria-label", oscuro ? "Cambiar a tema Crema" : "Cambiar a tema Espresso");
  boton.title = oscuro ? "Tema Crema" : "Tema Espresso";
}
$("tema").addEventListener("click", () => {
  const nuevo = temaActual() === "espresso" ? "crema" : "espresso";
  raiz.dataset.theme = nuevo;
  try { localStorage.setItem("nexo-tema", nuevo); } catch (e) { /* modo privado */ }
  pintarBotonTema();
});
medioOscuro.addEventListener("change", pintarBotonTema);
pintarBotonTema();

// =====================================================================
// ENVIAR Y RECIBIR EN STREAMING
// =====================================================================
async function enviar(texto) {
  if (ocupado || !texto.trim()) return;
  pararLectura();
  bloquear(true);
  const pregunta = burbuja("usuario", texto);
  const respuesta = burbuja("asistente escribiendo");
  if (rayosActivo) radiografiar([pregunta]);

  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mensaje: texto }),
    });
    if (!r.ok) {
      const json = await r.json().catch(() => ({}));
      throw new Error(json.error || `Error ${r.status}`);
    }

    // Leemos la respuesta POCO A POCO (streaming). Llegan líneas JSON,
    // pero un trozo de red puede cortar una línea por la mitad: guardamos
    // lo incompleto en "pendiente" hasta que llegue el resto.
    const lector = r.body.getReader();
    const decodificador = new TextDecoder();
    let pendiente = "";
    for (;;) {
      const { value, done } = await lector.read();
      if (done) break;
      pendiente += decodificador.decode(value, { stream: true });
      const lineas = pendiente.split("\n");
      pendiente = lineas.pop(); // la última puede estar a medias
      for (const linea of lineas) {
        if (linea.trim()) procesarEvento(JSON.parse(linea), respuesta);
      }
    }
  } catch (error) {
    respuesta.remove();
    burbuja("error", `No he podido responder: ${error.message}`);
  } finally {
    respuesta.classList.remove("escribiendo");
    if (respuesta.isConnected && !cuerpoDe(respuesta).textContent) respuesta.remove();
    bloquear(false);
    caja.focus();
  }
}

// Pie de cada respuesta: quién respondió, cuánto costó, 👍/👎 y, en el móvil, Escuchar.
function ponerPie(respuesta, evento) {
  const pie = crear("div", "pie-mensaje");
  const { fuente, uso } = evento;
  if (fuente?.tipo === "ia") {
    const f = crear("span", "fuente ia");
    f.append(crear("i", "punto"), `Respondido con IA · ${fuente.detalle}`);
    pie.appendChild(f);
    if (uso) {
      pie.appendChild(crear("span", "", `${uso.estimado ? "≈" : ""}${uso.output_tokens} tokens · ${euros(uso.coste)} €`));
      // Lo guardamos para que Rayos X compare cobrados frente a visibles.
      if (!uso.estimado) respuesta.dataset.cobrados = uso.output_tokens;
    }
  } else if (fuente?.tipo === "reglas") {
    const f = crear("span", "fuente reglas");
    f.append(crear("i", "punto"), "Respuesta directa de NEXO · 0 tokens");
    pie.appendChild(f);
  }
  if (evento.ms !== undefined) pie.appendChild(crear("span", "", formatearMs(evento.ms)));
  if (puedeLeer && esMovil.matches) pie.appendChild(botonLeer(respuesta));
  if (fuente?.tipo === "ia" || fuente?.tipo === "reglas") {
    pie.appendChild(crearValoracion(fuente.tipo, evento.conversacion));
  }
  respuesta.appendChild(pie);
}

// ---------- Escuchar (solo en el móvil) ----------
// La voz la pone el propio navegador (speechSynthesis), sin librerías.
// "pointer: coarse" = se maneja con el dedo: móvil o tableta.
const puedeLeer = "speechSynthesis" in window;
const esMovil = window.matchMedia("(pointer: coarse)");
let leyendo = null; // botón de la respuesta que se está leyendo

function pararLectura() {
  if (!puedeLeer) return;
  speechSynthesis.cancel();
  if (leyendo) {
    leyendo.textContent = "🔊 Escuchar";
    leyendo.setAttribute("aria-pressed", "false");
    leyendo = null;
  }
}

function textoParaLeer(respuesta) {
  let texto = cuerpoDe(respuesta).textContent;
  const anterior = respuesta.previousElementSibling;
  // La memoria del historial deja los resultados en la burbuja de la herramienta.
  if (texto.startsWith("Eso es lo que encuentro") && anterior?.classList.contains("herramienta")) {
    texto = `${cuerpoDe(anterior).textContent}\n${texto}`;
  }
  // Fuera los símbolos que la voz leería en alto ("asterisco", "viñeta"...).
  // En "6 * 7" el asterisco sí se dice: "6 por 7".
  return texto
    .replace(/(\d)\s*\*\s*(?=\d)/g, "$1 por ")
    .replace(/🔧|[*#_`«»•|]/g, "")
    .replace(/\s*→/g, ":");
}

function botonLeer(respuesta) {
  const boton = crear("button", "leer", "🔊 Escuchar");
  boton.type = "button";
  boton.setAttribute("aria-pressed", "false");
  boton.addEventListener("click", () => {
    const estaba = leyendo === boton;
    pararLectura();
    if (estaba) return; // segundo toque = parar
    const frase = new SpeechSynthesisUtterance(textoParaLeer(respuesta));
    frase.lang = "es-ES";
    const vozEs = speechSynthesis.getVoices().find((v) => v.lang.startsWith("es"));
    if (vozEs) frase.voice = vozEs;
    const alTerminar = () => {
      if (leyendo === boton) pararLectura();
    };
    frase.addEventListener("end", alTerminar);
    frase.addEventListener("error", alTerminar);
    boton.textContent = "⏹ Parar";
    boton.setAttribute("aria-pressed", "true");
    leyendo = boton;
    speechSynthesis.speak(frase);
  });
  return boton;
}
window.addEventListener("pagehide", pararLectura);

// 👍 / 👎: se guarda quién respondió (reglas o IA) para compararlos en el panel.
function crearValoracion(fuente, conversacion) {
  const grupo = crear("span", "valoracion");
  const botones = [
    [1, "👍", "Respuesta útil"],
    [-1, "👎", "Respuesta mejorable"],
  ].map(([valor, emoji, etiqueta]) => {
    const boton = crear("button", "", emoji);
    boton.type = "button";
    boton.title = etiqueta;
    boton.setAttribute("aria-label", etiqueta);
    boton.addEventListener("click", async () => {
      botones.forEach((b) => (b.disabled = true)); // una sola valoración por respuesta
      try {
        await postJSON("/api/valoracion", { conversacion, fuente, valor });
        boton.classList.add("elegido");
        mostrarAviso("¡Gracias por tu opinión!");
      } catch (error) {
        botones.forEach((b) => (b.disabled = false));
        mostrarAviso(error.message);
      }
    });
    return boton;
  });
  grupo.append(...botones);
  return grupo;
}

const formatearMs = (ms) => (ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1).replace(".", ",")} s`);

function procesarEvento(evento, respuesta) {
  switch (evento.tipo) {
    case "fragmento":
      cuerpoDe(respuesta).textContent += evento.texto;
      bajar();
      break;
    case "herramienta":
      // Va ANTES de la respuesta: así se ve qué herramienta usó el agente.
      chat.insertBefore(burbuja("herramienta", `🔧 ${evento.texto}`), respuesta);
      break;
    case "fin":
      if (cuerpoDe(respuesta).textContent) {
        ponerPie(respuesta, evento);
        if (rayosActivo) radiografiar([respuesta]);
      }
      pintarCoste(evento.coste);
      if (evento.modelo) marcarModelo(evento.modelo);
      if (evento.titulo) pintarTitulo(evento.titulo);
      // Se acaba de guardar sola: refrescamos el historial lateral.
      if (evento.conversacion) {
        conversacionActual = evento.conversacion;
        cargarHistorial();
      }
      bajar();
      break;
    case "aviso":
      mostrarAviso(evento.mensaje);
      break;
    case "error": {
      let texto = evento.mensaje;
      if (texto.includes("límite")) texto += " Pulsa «Nueva conversación».";
      burbuja("error", texto);
      break;
    }
  }
}

// ---------- caja de texto ----------
formulario.addEventListener("submit", (e) => {
  e.preventDefault();
  // Si aún no se puede enviar, dejamos el texto en la caja (no se pierde).
  if (ocupado || !caja.value.trim()) return;
  const texto = caja.value;
  caja.value = "";
  ajustarAltura();
  enviar(texto);
});
caja.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    formulario.requestSubmit();
  }
});
function ajustarAltura() {
  caja.style.height = "auto";
  caja.style.height = `${caja.scrollHeight}px`;
}
caja.addEventListener("input", ajustarAltura);

document.querySelectorAll(".sugerencia").forEach((b) => b.addEventListener("click", () => enviar(b.dataset.texto)));

// Botón eco: alterna entre NEXO (normal) y eco.
botonEco.addEventListener("click", async () => {
  if (ocupado) return;
  const destino = botonEco.getAttribute("aria-pressed") === "true" ? "nexo" : "eco";
  bloquear(true); // hasta que el servidor confirme, no se puede enviar
  try {
    const r = await postJSON("/api/modelo", { modelo: destino });
    marcarModelo(r.modelo);
    mostrarAviso(r.modelo === "eco" ? "Modo eco activado" : "NEXO normal");
  } catch (error) {
    mostrarAviso(error.message);
  } finally {
    bloquear(false);
  }
});

// =====================================================================
// RAYOS X: cómo ve la IA cada mensaje (tokens BPE reales)
// =====================================================================
$("rayos").addEventListener("click", () => {
  rayosActivo = !rayosActivo;
  $("rayos").setAttribute("aria-pressed", String(rayosActivo));
  if (rayosActivo) {
    radiografiar([...chat.querySelectorAll(".mensaje.usuario, .mensaje.asistente")]);
    mostrarAviso("Rayos X: cada color es un token");
  } else {
    chat.querySelectorAll(".rayos").forEach((r) => r.remove());
  }
});

async function radiografiar(burbujas) {
  const pendientes = burbujas.filter((b) => !b.querySelector(".rayos") && cuerpoDe(b)?.textContent);
  if (!pendientes.length) return;
  try {
    const { resultados } = await postJSON("/api/tokens", { textos: pendientes.map((b) => cuerpoDe(b).textContent) });
    pendientes.forEach((b, i) => {
      if (!rayosActivo || !b.isConnected) return;
      b.appendChild(crearRadiografia(resultados[i], Number(b.dataset.cobrados) || 0));
    });
    bajar();
  } catch (error) {
    mostrarAviso(error.message);
  }
}

function crearRadiografia(r, cobrados = 0) {
  const contenedor = crear("div", "rayos");
  const info = crear("div", "rayos-info");
  const total = crear("span");
  total.append(crear("strong", "", r.total), " tokens visibles");
  const diferencia = r.estimado - r.total;
  const signo = diferencia > 0 ? "+" : "";
  info.append(
    total,
    crear("span", "", `estimación palabras×1,3: ${r.estimado} (${signo}${diferencia})`),
    crear("span", "", `${(r.caracteres / Math.max(r.total, 1)).toFixed(1).replace(".", ",")} caracteres/token`),
  );
  // Si la API cobró más tokens de los que se ven, la diferencia es el
  // razonamiento oculto del modelo (gpt-oss "piensa" antes de responder).
  if (cobrados > r.total) {
    const oculto = crear("span");
    oculto.append(crear("strong", "", cobrados - r.total), ` de razonamiento oculto (cobrados: ${cobrados})`);
    info.appendChild(oculto);
  }
  const fichas = crear("div", "fichas");
  const MAX = 400; // las respuestas largas se recortan para no saturar
  r.tokens.slice(0, MAX).forEach((t, i) => {
    const ficha = crear("span", "ficha", t);
    ficha.title = `token #${i + 1} · id ${r.ids[i]}`;
    fichas.appendChild(ficha);
  });
  if (r.tokens.length > MAX) fichas.appendChild(crear("span", "", ` … y ${r.tokens.length - MAX} más`));
  contenedor.append(info, fichas);
  return contenedor;
}

// =====================================================================
// LABORATORIO: la misma pregunta 3 veces con la temperature elegida
// =====================================================================
const lab = $("laboratorio");
$("abrir-lab").addEventListener("click", () => {
  lab.showModal();
  $("lab-pregunta").focus();
});
$("cerrar-lab").addEventListener("click", () => lab.close());
lab.addEventListener("click", (e) => {
  if (e.target === lab) lab.close(); // clic fuera = cerrar
});
// Al mover el deslizador se actualiza el número que se ve al lado.
$("lab-temperatura").addEventListener("input", () => {
  $("out-temperatura").value = Number($("lab-temperatura").value).toFixed(1);
});

$("form-lab").addEventListener("submit", async (e) => {
  e.preventDefault();
  const resultados = $("lab-resultados");
  const boton = $("lanzar-lab");
  boton.disabled = true;
  boton.textContent = "Generando…";
  resultados.replaceChildren(...[1, 2, 3].map((n) => {
    const t = crear("div", "tarjeta cargando");
    t.append(crear("h3", "", `Respuesta ${n}`), "Pensando…");
    return t;
  }));
  try {
    const r = await postJSON("/api/laboratorio", {
      pregunta: $("lab-pregunta").value,
      temperature: Number($("lab-temperatura").value),
      veces: 3,
    });
    resultados.replaceChildren(...r.resultados.map((res, i) => {
      const t = crear("div", "tarjeta");
      t.append(
        crear("h3", "", `Respuesta ${i + 1}`),
        res.texto,
        crear("span", "datos", `${res.tokens} tokens · ${formatearMs(res.ms)} · ${euros(res.coste)} €`),
      );
      return t;
    }));
    const porcentaje = Math.round(r.parecido * 100);
    $("lab-parecido").hidden = false;
    $("lab-relleno").style.width = `${porcentaje}%`;
    $("lab-porcentaje").textContent = `${porcentaje} %`;
    pintarCoste(r.coste);
  } catch (error) {
    resultados.replaceChildren(crear("div", "tarjeta", `No se pudo: ${error.message}`));
  } finally {
    boton.disabled = false;
    boton.textContent = "Lanzar 3 veces";
  }
});

// =====================================================================
// HISTORIAL LATERAL
// =====================================================================
const lateral = $("lateral");
const fondoLateral = $("fondo-lateral");
const lista = $("lista");
const vacio = $("vacio");
const buscador = $("buscar");

function pintarConversacion(estado) {
  // Si cambiamos de conversación, dejamos de leer (al volver a la misma, no).
  if (estado.id !== conversacionActual) pararLectura();
  conversacionActual = estado.id;
  marcarModelo(estado.modelo);
  pintarCoste(estado.coste);
  pintarTitulo(estado.titulo);
  chat.querySelectorAll(".mensaje").forEach((m) => m.remove());
  bienvenida.hidden = estado.mensajes.length > 0;
  for (const m of estado.mensajes) {
    const clase = m.rol === "herramienta" ? "herramienta" : m.rol;
    burbuja(clase, m.rol === "herramienta" ? `🔧 ${m.contenido}` : m.contenido);
  }
  if (rayosActivo) radiografiar([...chat.querySelectorAll(".mensaje.usuario, .mensaje.asistente")]);
  marcarActiva();
}

async function sincronizar() {
  const r = await fetch("/api/estado");
  // Modo móvil: si NEXO se reinició, hay que volver a escribir el código.
  if (r.status === 401) return location.assign("/acceso");
  pintarConversacion(await r.json());
  await cargarHistorial();
}

// "Hoy", "Ayer", "Últimos 7 días" o "Anteriores".
function grupoDe(conversacion) {
  const dia = new Date(conversacion.fecha);
  const hoy = new Date();
  hoy.setHours(0, 0, 0, 0);
  const diferencia = Math.floor((hoy - new Date(dia).setHours(0, 0, 0, 0)) / 86400000);
  if (diferencia <= 0) return "Hoy";
  if (diferencia === 1) return "Ayer";
  if (diferencia < 7) return "Últimos 7 días";
  return "Anteriores";
}

function cuando(fechaISO) {
  const fecha = new Date(fechaISO);
  const hoy = new Date().toDateString() === fecha.toDateString();
  return hoy
    ? fecha.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })
    : fecha.toLocaleDateString("es-ES", { day: "numeric", month: "short" });
}

async function cargarHistorial() {
  const q = buscador.value.trim();
  const r = await fetch(`/api/conversaciones?q=${encodeURIComponent(q)}`);
  const datos = await r.json();
  conversacionActual = datos.actual;
  pintarHistorial(datos.conversaciones, q);
}

function pintarHistorial(conversaciones, q) {
  lista.replaceChildren();
  vacio.hidden = conversaciones.length > 0;
  vacio.textContent = q
    ? `Ninguna conversación contiene «${q}».`
    : "Aún no hay conversaciones. Se guardan solas al chatear.";
  let grupoAnterior = null;
  for (const c of conversaciones) {
    const grupo = grupoDe(c);
    if (grupo !== grupoAnterior) {
      const titulo = crear("div", "grupo", grupo);
      lista.appendChild(titulo);
      grupoAnterior = grupo;
    }
    lista.appendChild(crearItem(c, q));
  }
  marcarActiva();
}

// Resalta el texto buscado dentro del fragmento (con <mark>, sin innerHTML).
function resaltar(texto, q) {
  const fragmento = document.createDocumentFragment();
  if (!q) {
    fragmento.append(texto);
    return fragmento;
  }
  const minus = texto.toLocaleLowerCase();
  const buscado = q.toLocaleLowerCase();
  let desde = 0;
  let pos;
  while ((pos = minus.indexOf(buscado, desde)) !== -1) {
    fragmento.append(texto.slice(desde, pos), crear("mark", "", texto.slice(pos, pos + q.length)));
    desde = pos + q.length;
  }
  fragmento.append(texto.slice(desde));
  return fragmento;
}

function crearItem(c, q) {
  const item = crear("div", "item");
  item.dataset.id = c.id;

  const abrir = crear("button", "abrir");
  abrir.type = "button";
  abrir.title = `${c.tema} · ${c.titulo}`;
  const avatar = crear("span", "avatar", c.icono);
  avatar.setAttribute("aria-hidden", "true");
  const titulo = crear("span", "titulo", c.titulo);
  const meta = crear("span", "meta");
  if (c.fragmento) {
    meta.appendChild(resaltar(c.fragmento, q));
  } else {
    meta.textContent = `${c.preguntas} ${c.preguntas === 1 ? "pregunta" : "preguntas"} · ${cuando(c.fecha)}`;
  }
  abrir.append(avatar, titulo, meta);
  abrir.addEventListener("click", () => abrirConversacion(c.id));
  abrir.addEventListener("dblclick", () => empezarRenombrar(item, c));

  const herramientas = crear("div", "herramientas-item");
  const acciones = [
    ["lapiz", "Renombrar", () => empezarRenombrar(item, c), ""],
    ["papelera", "Borrar", () => borrarConversacion(c), "peligro"],
  ];
  for (const [nombre, etiqueta, accion, clase] of acciones) {
    const b = crear("button", clase);
    b.type = "button";
    b.title = etiqueta;
    b.setAttribute("aria-label", `${etiqueta}: ${c.titulo}`);
    b.appendChild(icono(nombre));
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      accion();
    });
    herramientas.appendChild(b);
  }
  item.append(abrir, herramientas);
  return item;
}

function marcarActiva() {
  lista.querySelectorAll(".item").forEach((i) => i.classList.toggle("activa", i.dataset.id === conversacionActual));
}

async function abrirConversacion(id) {
  if (ocupado) return;
  if (id === conversacionActual) return cerrarLateral();
  bloquear(true);
  try {
    pintarConversacion(await postJSON(`/api/conversaciones/${id}/abrir`));
    cerrarLateral();
  } catch (error) {
    mostrarAviso(error.message);
    cargarHistorial();
  } finally {
    bloquear(false);
  }
}

// Renombrar en el sitio: el título se convierte en una caja de texto.
function empezarRenombrar(item, c) {
  const titulo = item.querySelector(".titulo");
  const entrada = crear("input", "renombrar");
  entrada.value = c.titulo_personalizado ? c.titulo : "";
  entrada.placeholder = c.titulo;
  entrada.maxLength = 80;
  entrada.setAttribute("aria-label", "Nuevo título (vacío = automático)");
  titulo.replaceWith(entrada);
  entrada.focus();
  entrada.select();
  let terminado = false;
  const terminar = async (guardar) => {
    if (terminado) return;
    terminado = true;
    if (guardar) {
      try {
        await postJSON(`/api/conversaciones/${c.id}`, { titulo: entrada.value }, "PATCH");
        if (c.id === conversacionActual) pintarTitulo(entrada.value.trim() || c.titulo);
      } catch (error) {
        mostrarAviso(error.message);
      }
    }
    cargarHistorial();
  };
  entrada.addEventListener("click", (e) => e.stopPropagation());
  entrada.addEventListener("keydown", (e) => {
    if (e.key === "Enter") terminar(true);
    if (e.key === "Escape") terminar(false);
  });
  entrada.addEventListener("blur", () => terminar(true));
}

async function borrarConversacion(c) {
  if (ocupado) return;
  if (!confirm(`¿Borrar «${c.titulo}»? No se puede deshacer.`)) return;
  try {
    const r = await fetch(`/api/conversaciones/${c.id}`, { method: "DELETE" });
    const json = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(json.error || `Error ${r.status}`);
    if (c.id === conversacionActual) await sincronizar(); // era la abierta
    else await cargarHistorial();
    mostrarAviso("Conversación borrada");
  } catch (error) {
    mostrarAviso(error.message);
  }
}

async function nuevaConversacion() {
  if (ocupado) return;
  try {
    await postJSON("/api/nueva");
  } catch (error) {
    return mostrarAviso(error.message);
  }
  // No se guarda hasta el primer mensaje: así no quedan conversaciones vacías.
  await sincronizar();
  cerrarLateral();
  caja.focus();
}
$("nueva").addEventListener("click", nuevaConversacion);

// Buscar mientras escribes, esperando 250 ms a que pares de teclear
// (así no hacemos una petición por cada letra: "debounce").
let temporizadorBusqueda;
buscador.addEventListener("input", () => {
  clearTimeout(temporizadorBusqueda);
  temporizadorBusqueda = setTimeout(cargarHistorial, 250);
});

// En móvil el historial es un panel que se desliza.
function abrirLateral() {
  lateral.classList.add("abierta");
  fondoLateral.hidden = false;
}
function cerrarLateral() {
  lateral.classList.remove("abierta");
  fondoLateral.hidden = true;
}
$("abrir-lateral").addEventListener("click", abrirLateral);
$("cerrar-lateral").addEventListener("click", cerrarLateral);
fondoLateral.addEventListener("click", cerrarLateral);

// Atajos de teclado: Alt+N nueva conversación, / para buscar, Esc cierra.
document.addEventListener("keydown", (e) => {
  if (e.altKey && e.key.toLowerCase() === "n") {
    e.preventDefault();
    nuevaConversacion();
  } else if (e.key === "/" && document.activeElement === document.body) {
    e.preventDefault();
    abrirLateral();
    buscador.focus();
  } else if (e.key === "Escape") {
    cerrarLateral();
  }
});

// =====================================================================
// ARRANQUE
// =====================================================================
sincronizar().then(() => caja.focus());

// Al volver a esta pestaña (p. ej. tras reiniciar el servidor), nos
// volvemos a sincronizar para no mostrar un modo o historial viejos.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && !ocupado && !lab.open) sincronizar().catch(() => {});
});
