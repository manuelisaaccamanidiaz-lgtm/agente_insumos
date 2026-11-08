// Abona · lógica de la interfaz (sin librerías)
const $ = (id) => document.getElementById(id);
const mensajes = $("mensajes"), formulario = $("redactor"), campo = $("pregunta"), boton = $("enviar");

const NOMBRES = {
  consultar_precios: "precios DANE", analizar_tendencia: "tendencia", calcular_costo_compra: "costo de compra",
  consultar_regiones_vecinas: "departamentos vecinos", consultar_trm: "dólar (TRM)", enviar_alerta: "alerta Telegram",
};
const MESES = ["enero","febrero","marzo","abril","mayo","junio","julio","agosto","septiembre","octubre","noviembre","diciembre"];
const miles = (n, d = 0) => Number(n).toLocaleString("es-CO", { minimumFractionDigits: d, maximumFractionDigits: d });
const mesTexto = (p) => p ? `${MESES[Number(p.slice(5, 7)) - 1]} de ${p.slice(0, 4)}` : "—";

function escapar(t) {
  return t.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
const enLinea = (t) => escapar(t).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");

// Separa la respuesta en: cifra principal, cuerpo, recomendación y fuente.
function armarRespuesta(texto) {
  let recomendacion = null, fuente = null;
  const lineas = [];
  for (const cruda of texto.split("\n")) {
    const limpia = cruda.replace(/\*\*/g, "").trim();
    const r = limpia.match(/^Recomendaci[oó]n:\s*(Comprar ya|Esperar|Sin apuro)/i);
    if (r) { recomendacion = r[1]; continue; }
    if (/^Fuente:/i.test(limpia)) { fuente = limpia; continue; }
    lineas.push(cruda);
  }
  const bloques = lineas.join("\n").trim().split(/\n\s*\n/).filter(Boolean);
  const html = [];
  bloques.forEach((bloque, i) => {
    const filas = bloque.split("\n").filter((l) => l.trim());
    if (filas.every((l) => /^\s*[-•*]\s+/.test(l))) {
      html.push("<ul>" + filas.map((l) => `<li>${enLinea(l.replace(/^\s*[-•*]\s+/, ""))}</li>`).join("") + "</ul>");
    } else {
      filas.forEach((l, j) => {
        const esCifra = i === 0 && j === 0 && /^\*\*\$[\d.]+\*\*/.test(l.trim());
        html.push(`<p${esCifra ? ' class="cifra-linea"' : ""}>${enLinea(l)}</p>`);
      });
    }
  });
  return { html: html.join(""), recomendacion, fuente };
}

function claseRec(r) {
  const t = (r || "").toLowerCase();
  return t.startsWith("comprar") ? "sube" : t.startsWith("esperar") ? "baja" : "quieto";
}

function pie(datos) {
  const h = datos.herramientas || [], u = datos.uso || {};
  const usadas = h.length ? h.map((x) => NOMBRES[x.nombre] + (x.exito ? "" : " (sin dato)")).join(", ") : "ninguna";
  const partes = [`Consultó: ${usadas}`];
  if (u.llamadas_llm) partes.push(`${u.llamadas_llm} llamada${u.llamadas_llm === 1 ? "" : "s"} al modelo`);
  if (u.duracion_ms) partes.push(`${miles(u.duracion_ms / 1000, 1)} s`);
  if (u.costo_usd != null) partes.push(`US$ ${miles(u.costo_usd, 4)}`);
  return partes.join(" · ");
}

function agregar(clase, html) {
  const el = document.createElement("article");
  el.className = "msg " + clase;
  el.innerHTML = html;
  mensajes.appendChild(el);
  el.scrollIntoView({ behavior: "smooth", block: "end" });
  return el;
}

async function preguntar(texto) {
  texto = texto.trim();
  if (texto.length < 2) return;
  $("bienvenida")?.classList.add("compacta");
  agregar("yo", `<p>${escapar(texto)}</p>`);
  const espera = agregar("abona", `<p class="pensando">Consultando precios del DANE</p>`);
  boton.disabled = true; campo.value = ""; ajustarAltura();
  try {
    const resp = await fetch("/api/preguntar", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pregunta: texto }),
    });
    const datos = await resp.json();
    if (!resp.ok) throw new Error(datos.detail?.[0]?.msg || datos.detail || `Error ${resp.status}`);
    const r = armarRespuesta(datos.respuesta || "");
    espera.classList.toggle("error", Boolean(datos.error));
    espera.innerHTML =
      (r.recomendacion ? `<span class="rec ${claseRec(r.recomendacion)}">${escapar(r.recomendacion)}</span>` : "") +
      r.html +
      `<p class="pie">${escapar([r.fuente, pie(datos)].filter(Boolean).join(" · "))}</p>`;
  } catch (e) {
    espera.classList.add("error");
    espera.innerHTML = `<p>No se pudo obtener la respuesta: ${escapar(String(e.message || e))}</p>` +
      `<p class="pie">Revise que el servidor siga corriendo y que el archivo .env tenga la llave y el modelo.</p>`;
  } finally {
    boton.disabled = false; campo.focus();
    espera.scrollIntoView({ behavior: "smooth", block: "end" });
  }
}

function ajustarAltura() { campo.style.height = "auto"; campo.style.height = Math.min(campo.scrollHeight, 160) + "px"; }

formulario.addEventListener("submit", (e) => { e.preventDefault(); preguntar(campo.value); });
campo.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); formulario.requestSubmit(); }
});
campo.addEventListener("input", ajustarAltura);
$("sugerencias").addEventListener("click", (e) => {
  const q = e.target.closest("button")?.dataset.q;
  if (q && !boton.disabled) preguntar(q);
});

async function cargarEstado() {
  try {
    const d = await (await fetch("/api/estado")).json();
    $("d-periodo").textContent = mesTexto(d.periodo);
    $("d-insumos").textContent = d.insumos ? `${d.insumos} productos` : "—";
    $("estado-datos").textContent = d.periodo
      ? `Datos DANE hasta ${mesTexto(d.periodo)}${d.modelo ? " · " + d.modelo : ""}` : "Base de datos sin crear";
  } catch { $("estado-datos").textContent = "Sin conexión con el servidor"; }
}

async function cargarCorrida() {
  try {
    const d = await (await fetch("/api/carga")).json();
    if (!d.disponible || !d.tareas) return;
    $("c-vacio").hidden = true; $("c-datos").hidden = false;
    $("c-tareas").textContent = d.total ? `${miles(d.tareas)} / ${miles(d.total)}` : miles(d.tareas);
    $("c-exito").textContent = `${miles((d.exitos / d.tareas) * 100, 1)} %`;
    $("c-costo").textContent = `US$ ${miles(d.costo_usd, 2)}`;
    const horas = (new Date(d.ultima) - new Date(d.inicio)) / 3.6e6;
    $("c-horas").textContent = `${miles(horas, 1)} h`;
    $("c-barra").style.width = d.total ? `${Math.min(100, (d.tareas / d.total) * 100)}%` : "0";
  } catch { /* el panel queda como está */ }
}

cargarEstado(); cargarCorrida(); setInterval(cargarCorrida, 30000);
