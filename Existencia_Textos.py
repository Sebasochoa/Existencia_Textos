import customtkinter as ctk
from tkinter import filedialog, messagebox
import textwrap
import datetime
import threading
import io
import os
import sys
import json
import shutil

# ── Tema ──────────────────────────────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

# Imports pesados: se cargan en hilo de fondo mientras muestra el splash
pdfplumber  = None
canvas_mod  = None
letter_size = None
PdfReader   = None
PdfWriter   = None
ImageReader = None
colors_mod  = None

def _cargar_librerias():
    """Se ejecuta en un hilo secundario para no bloquear la UI."""
    global pdfplumber, canvas_mod, letter_size, PdfReader, PdfWriter, ImageReader, colors_mod
    import pdfplumber       as _pp;  pdfplumber  = _pp
    from reportlab.pdfgen import canvas as _c;  canvas_mod  = _c
    from reportlab.lib.pagesizes import letter as _l; letter_size = _l
    from PyPDF2 import PdfReader as _PR, PdfWriter as _PW
    PdfReader = _PR;  PdfWriter = _PW
    from reportlab.lib.utils import ImageReader as _IR; ImageReader = _IR
    from reportlab.lib import colors as _col;           colors_mod  = _col

# ── Helpers ───────────────────────────────────────────────────────────────────
def ruta_recurso(rel_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, rel_path)

# ── Perfiles persistentes (fuera del .exe, en %APPDATA%) ──────────────────────
# Se usan para "sembrar" perfiles.json la primera vez que la app corre en un PC.
# Después de eso, todo alta/edición de perfil se guarda en %APPDATA% y estos
# valores ya no se vuelven a leer.
PERFILES_DEFAULT = {
    "600438": {"nombre": "Sebastian Ochoa",  "firma": "600438_firma.png"},
    "442630": {"nombre": "Valeria Luque",    "firma": "442630_firma.png"},
    "151378": {"nombre": "Diana Palacios",   "firma": "151378_firma.png"},
    "5065":   {"nombre": "Eva Choquepuma",   "firma": "5065_firma.png"},
    "62842":  {"nombre": "Daneska Urbina",   "firma": "62842_firma.png"},
    "600445": {"nombre": "Mathias Sotelo",   "firma": "600445_firma.png"},
}

def ruta_datos_usuario():
    """Carpeta persistente fuera del .exe (sys._MEIPASS es de solo lectura)."""
    base = os.getenv("APPDATA", os.path.expanduser("~"))
    carpeta = os.path.join(base, "StockControl")
    os.makedirs(os.path.join(carpeta, "Firmas"), exist_ok=True)
    return carpeta

def ruta_perfiles_json():
    return os.path.join(ruta_datos_usuario(), "perfiles.json")

def cargar_perfiles():
    """Carga perfiles.json; si no existe, lo siembra con los perfiles por defecto
    (copiando también sus firmas desde el recurso empaquetado, si están)."""
    ruta = ruta_perfiles_json()
    if not os.path.exists(ruta):
        perfiles_sembrados = {}
        for codigo, datos in PERFILES_DEFAULT.items():
            origen = ruta_recurso(os.path.join("Firmas", datos["firma"]))
            destino = os.path.join(ruta_datos_usuario(), "Firmas", datos["firma"])
            if os.path.exists(origen):
                try:
                    shutil.copy(origen, destino)
                except Exception:
                    pass
            perfiles_sembrados[codigo] = {"nombre": datos["nombre"], "firma": destino}
        with open(ruta, "w", encoding="utf-8") as f:
            json.dump(perfiles_sembrados, f, ensure_ascii=False, indent=2)
        return perfiles_sembrados
    with open(ruta, "r", encoding="utf-8") as f:
        return json.load(f)

def guardar_perfiles(perfiles):
    with open(ruta_perfiles_json(), "w", encoding="utf-8") as f:
        json.dump(perfiles, f, ensure_ascii=False, indent=2)

def agregar_perfil(codigo, nombre, ruta_imagen_firma):
    """Agrega o edita un perfil: copia la firma a la carpeta persistente y
    guarda el registro en perfiles.json. Devuelve el diccionario actualizado."""
    perfiles = cargar_perfiles()
    _, ext = os.path.splitext(ruta_imagen_firma)
    destino = os.path.join(ruta_datos_usuario(), "Firmas", f"{codigo}_firma{ext or '.png'}")
    shutil.copy(ruta_imagen_firma, destino)
    perfiles[codigo] = {"nombre": nombre, "firma": destino}
    guardar_perfiles(perfiles)
    global PERFILES
    PERFILES = perfiles
    return perfiles

def eliminar_perfil(codigo):
    perfiles = cargar_perfiles()
    if codigo in perfiles:
        del perfiles[codigo]
        guardar_perfiles(perfiles)
    global PERFILES
    PERFILES = perfiles
    return perfiles

# Se carga una vez al iniciar el módulo; el resto del programa lee de PERFILES.
PERFILES = cargar_perfiles()

libros_detectados = []
faltantes_dict    = {}
botones_libros    = {}
frames_libros     = {}
combo_perfiles    = None


def agregar_firma_y_nombre(can, perfil_id, y_firma=325):
    perfil = PERFILES.get(perfil_id)
    if not perfil:
        return
    nombre     = perfil["nombre"]
    ruta_firma = perfil["firma"]
    # Compatibilidad: si "firma" es solo un nombre de archivo (perfil viejo),
    # se busca en el recurso empaquetado; si es una ruta absoluta, se usa tal cual.
    if not os.path.isabs(ruta_firma):
        ruta_firma = ruta_recurso(os.path.join("Firmas", ruta_firma))
    can.setFillColor(colors_mod.black)
    can.setFont("Helvetica", 15)
    can.drawString(350, y_firma, nombre)
    if os.path.exists(ruta_firma):
        firma_img = ImageReader(ruta_firma)
        can.drawImage(firma_img, 470, y_firma, width=120, height=40, mask='auto')

def obtener_filas_con_erp(ruta_pdf):
    filas = []
    with pdfplumber.open(ruta_pdf) as pdf:
        pagina   = pdf.pages[0]
        tabla    = pagina.extract_table()
        palabras = pagina.extract_words()
        posiciones = {}
        for palabra in palabras:
            if palabra["text"].isdigit() and len(palabra["text"]) == 6 and palabra["text"].startswith("0"):
                posiciones[palabra["text"]] = palabra["top"]
        for fila in tabla[1:]:
            erp         = fila[1]
            descripcion = fila[2]
            total       = int(fila[7]) if fila[7] else 0
            if erp in posiciones:
                filas.append({"erp": erp, "descripcion": descripcion, "y": posiciones[erp], "total": total})
    return filas

def obtener_y_firma(ruta_pdf):
    """Ubica la posición real de la línea 'Nombre y Firma' en el PDF fuente,
    para no depender de un cálculo por cantidad de filas. Si no la encuentra,
    devuelve None y el llamador debe usar un valor por defecto."""
    with pdfplumber.open(ruta_pdf) as pdf:
        pagina   = pdf.pages[0]
        palabras = pagina.extract_words()
        for palabra in palabras:
            if palabra["text"] in ("Firma", "Nombre"):
                # +12 aprox. para que el nombre/firma queden pegados encima
                # de la línea de guiones, con el mismo criterio siempre.
                return (835 - palabra["top"]) + 16
    return None

def escribir_sobre_pdf(ruta_pdf, salida_pdf, excepciones, perfil_id, comentario):
    filas  = obtener_filas_con_erp(ruta_pdf)
    packet = io.BytesIO()
    can    = canvas_mod.Canvas(packet, pagesize=letter_size)
    can.setFont("Helvetica", 8)

    x_stock_ok = 495
    x_faltante = 533
    x_sobrante = 568

    for fila in filas:
        y_corregido = 835 - fila["y"]
        erp   = fila["erp"]
        total = fila["total"]
        if erp in excepciones:
            valor = int(excepciones[erp])
            if valor < 0:
                faltante   = abs(valor)
                stock_real = total - faltante
                can.drawString(x_faltante, y_corregido, str(faltante))
                offset = -4 if stock_real > 100 else (-2 if stock_real > 10 else 0)
                can.drawString(x_stock_ok + offset, y_corregido, str(stock_real))
            elif valor > 0:
                sobrante   = valor
                stock_real = total + sobrante
                can.drawString(x_sobrante, y_corregido, str(sobrante))
                offset = -4 if stock_real > 100 else (-2 if stock_real > 10 else 0)
                can.drawString(x_stock_ok + offset, y_corregido, str(stock_real))
        else:
            can.drawString(x_stock_ok, y_corregido, "✔")

    if comentario:
        can.setFont("Helvetica-Bold", 9)
        can.drawString(20, 350, "Comentarios:")
        can.setFont("Helvetica", 9)
        y = 335
        for parrafo in comentario.splitlines():
            for linea in textwrap.wrap(parrafo, width=100) or [""]:
                can.drawString(20, y, linea)
                y -= 12

    y_firma = obtener_y_firma(ruta_pdf)
    if y_firma is None:
        y_firma = 325  # fallback por si el formato del PDF cambia y no se detecta la línea
    agregar_firma_y_nombre(can, perfil_id, y_firma)
    can.save()
    packet.seek(0)

    original = PdfReader(ruta_pdf)
    overlay  = PdfReader(packet)
    writer   = PdfWriter()
    page = original.pages[0]
    page.merge_page(overlay.pages[0])
    writer.add_page(page)
    with open(salida_pdf, "wb") as f:
        writer.write(f)

# ── Handlers UI ───────────────────────────────────────────────────────────────

def seleccionar_pdf():
    ruta = filedialog.askopenfilename(filetypes=[("PDF files", "*.pdf")])
    if ruta:
        entry_pdf.delete(0, "end")
        entry_pdf.insert(0, ruta)

def cargar_libros():
    global libros_detectados
    if pdfplumber is None:
        messagebox.showwarning("Espera", "Las librerias aun se estan cargando, intentá en unos segundos.")
        return
    ruta_pdf = entry_pdf.get()
    if not ruta_pdf:
        messagebox.showerror("Error", "Seleccione un PDF primero")
        return
    libros_detectados = obtener_filas_con_erp(ruta_pdf)
    for widget in frame_libros.winfo_children():
        widget.destroy()
    botones_libros.clear()
    frames_libros.clear()
    columnas = 3
    for i, libro in enumerate(libros_detectados):
        fila_grid = i // columnas
        col_grid  = i % columnas
        frame_item = ctk.CTkFrame(frame_libros, fg_color="transparent")
        frame_item.grid(row=fila_grid, column=col_grid, padx=5, pady=5, sticky="ew")
        frame_libros.grid_columnconfigure(col_grid, weight=1)
        btn = ctk.CTkButton(
            frame_item,
            text=libro["descripcion"],
            height=36, corner_radius=8,
            fg_color="transparent", border_width=1,
            text_color=("gray20", "gray85"),
            font=ctk.CTkFont(size=11),
            command=lambda l=libro, f=frame_item: mostrar_input(l, f),
        )
        btn.pack(fill="x")
        botones_libros[libro["erp"]] = btn
        frames_libros[libro["erp"]]  = frame_item
    lbl_count.configure(text=f"{len(libros_detectados)} libros cargados")

def mostrar_input(libro, frame_item):
    for widget in frame_item.winfo_children():
        if isinstance(widget, ctk.CTkEntry):
            return
    entry = ctk.CTkEntry(
        frame_item, width=80, height=30, corner_radius=6,
        placeholder_text="ej: -2 / +3", font=ctk.CTkFont(size=11),
    )
    entry.pack(pady=(4, 0))

    def guardar(event=None):
        try:
            valor = int(entry.get())
            faltantes_dict[libro["erp"]] = valor
            btn = botones_libros[libro["erp"]]
            if valor < 0:
                btn.configure(fg_color="#7f1d1d", text_color="#fca5a5", border_width=0)
            elif valor > 0:
                btn.configure(fg_color="#14532d", text_color="#86efac", border_width=0)
        except Exception:
            messagebox.showerror("Error", "Ingrese un numero valido (ej: -2 o 3)")

    entry.bind("<Return>", guardar)
    entry.focus()

def abrir_config_perfiles():
    """Ventana para agregar/editar/eliminar perfiles (código, nombre, firma)."""
    win = ctk.CTkToplevel()
    win.title("Perfiles")
    win.geometry("1100x860")
    win.grab_set()

    ruta_ico = ruta_recurso("Icono.ico")
    if os.path.exists(ruta_ico):
        win.after(200, lambda: win.iconbitmap(ruta_ico))

    ctk.CTkLabel(win, text="Perfiles", font=ctk.CTkFont(size=16, weight="bold")).pack(
        pady=(20, 4), padx=20, anchor="w")
    ctk.CTkLabel(
        win, text="Agrega o edita un asesor. El código es el mismo que se usa como Usuario en Campus.",
        font=ctk.CTkFont(size=11), text_color=("gray45", "gray60"), wraplength=380, justify="left",
    ).pack(padx=20, anchor="w")

    frame_form = ctk.CTkFrame(win, corner_radius=12)
    frame_form.pack(fill="x", padx=20, pady=16)
    frame_form.grid_columnconfigure(0, weight=1)

    entry_codigo = ctk.CTkEntry(frame_form, placeholder_text="Código (ej: 600438)", height=36)
    entry_codigo.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
    entry_nombre = ctk.CTkEntry(frame_form, placeholder_text="Nombre completo", height=36)
    entry_nombre.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 8))

    lbl_firma_sel = ctk.CTkLabel(frame_form, text="Sin imagen seleccionada",
                                  font=ctk.CTkFont(size=11), text_color=("gray50", "gray50"))
    ruta_firma_elegida = {"valor": None}

    def elegir_firma():
        ruta = filedialog.askopenfilename(
            title="Seleccionar imagen de firma",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg")],
        )
        if ruta:
            ruta_firma_elegida["valor"] = ruta
            lbl_firma_sel.configure(text=os.path.basename(ruta))

    ctk.CTkButton(frame_form, text="Elegir imagen de firma…", height=36,
                  fg_color="transparent", border_width=1,
                  command=elegir_firma).grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 4))
    lbl_firma_sel.grid(row=3, column=0, sticky="w", padx=16, pady=(0, 16))

    def guardar():
        global PERFILES
        codigo = entry_codigo.get().strip()
        nombre = entry_nombre.get().strip()
        firma  = ruta_firma_elegida["valor"]
        if not codigo or not nombre:
            messagebox.showerror("Error", "Ingrese código y nombre", parent=win)
            return
        if not firma and codigo not in PERFILES:
            messagebox.showerror("Error", "Seleccione una imagen de firma", parent=win)
            return
        if firma:
            agregar_perfil(codigo, nombre, firma)
        else:
            # Se editó nombre sin cambiar la firma existente
            perfiles = cargar_perfiles()
            perfiles[codigo]["nombre"] = nombre
            guardar_perfiles(perfiles)
            PERFILES = perfiles
        refrescar_lista()
        refrescar_combo_perfiles()
        entry_codigo.delete(0, "end")
        entry_nombre.delete(0, "end")
        ruta_firma_elegida["valor"] = None
        lbl_firma_sel.configure(text="Sin imagen seleccionada")

    ctk.CTkButton(frame_form, text="Guardar perfil", height=38,
                  command=guardar).grid(row=4, column=0, sticky="ew", padx=16, pady=(0, 16))

    ctk.CTkLabel(win, text="PERFILES EXISTENTES", font=ctk.CTkFont(size=10, weight="bold"),
                 text_color=("gray50", "gray50")).pack(padx=20, anchor="w")
    frame_lista = ctk.CTkScrollableFrame(win, height=140)
    frame_lista.pack(fill="both", expand=True, padx=20, pady=(4, 20))

    def refrescar_lista():
        for w in frame_lista.winfo_children():
            w.destroy()
        for codigo, datos in PERFILES.items():
            fila = ctk.CTkFrame(frame_lista, fg_color="transparent")
            fila.pack(fill="x", pady=2)
            ctk.CTkLabel(fila, text=f"{codigo} — {datos['nombre']}",
                         font=ctk.CTkFont(size=12)).pack(side="left")

            def hacer_eliminar(cod=codigo):
                if messagebox.askyesno("Confirmar", f"¿Eliminar el perfil {cod}?", parent=win):
                    eliminar_perfil(cod)
                    refrescar_lista()
                    refrescar_combo_perfiles()

            ctk.CTkButton(fila, text="Eliminar", width=70, height=24,
                          fg_color="#7f1d1d", hover_color="#991b1b",
                          command=hacer_eliminar).pack(side="right")

    refrescar_lista()

def refrescar_combo_perfiles():
    if combo_perfiles is not None:
        combo_perfiles.configure(values=list(PERFILES.keys()))
        if combo_perfiles.get() not in PERFILES:
            valores = list(PERFILES.keys())
            combo_perfiles.set(valores[0] if valores else "")

def actualizar_turno_botones():
    seleccionado = turno_var.get()
    btn_am.configure(
        fg_color="#1a5e2a" if seleccionado == "AM" else "transparent",
        text_color="white"  if seleccionado == "AM" else ("gray40", "gray60"),
        border_width=0      if seleccionado == "AM" else 1,
    )
    btn_pm.configure(
        fg_color="#1a5e2a" if seleccionado == "PM" else "transparent",
        text_color="white"  if seleccionado == "PM" else ("gray40", "gray60"),
        border_width=0      if seleccionado == "PM" else 1,
    )
    fecha = datetime.datetime.now().strftime("%Y%m%d")
    lbl_nombre_preview.configure(text=f"Inventory Report {fecha} - {seleccionado}.pdf")

def generar_pdf():
    if pdfplumber is None:
        messagebox.showwarning("Espera", "Las librerias aun se estan cargando, intentá en unos segundos.")
        return
    ruta_pdf   = entry_pdf.get()
    perfil_id  = combo_perfiles.get()
    comentario = entry_comentarios.get("1.0", "end").strip()
    turno      = turno_var.get()
    if not ruta_pdf:
        messagebox.showerror("Error", "Seleccione un PDF")
        return
    if perfil_id not in PERFILES:
        messagebox.showerror("Error", "Seleccione un perfil valido")
        return
    fecha          = datetime.datetime.now().strftime("%Y%m%d")
    nombre_default = f"Inventory Report {fecha}-{turno}.pdf"

    nombre_salida = filedialog.asksaveasfilename(
        defaultextension=".pdf",
        filetypes=[("PDF files", "*.pdf")],
        initialfile=nombre_default,
        title="Guardar reporte como",
    )

    if not nombre_salida:
        return

    escribir_sobre_pdf(ruta_pdf, nombre_salida, faltantes_dict, perfil_id, comentario)
    lbl_status.configure(
        text=f"✔  PDF guardado: {os.path.basename(nombre_salida)}",
        text_color="#86efac"
    )


# ── SPLASH SCREEN ─────────────────────────────────────────────────────────────

def mostrar_splash():
    splash = ctk.CTkToplevel()
    splash.overrideredirect(True)           # sin barra de título
    splash.resizable(False, False)

    ancho, alto = 340, 280
    sw = splash.winfo_screenwidth()
    sh = splash.winfo_screenheight()
    x  = (sw - ancho) // 2
    y  = (sh - alto)  // 2
    splash.geometry(f"{ancho}x{alto}+{x}+{y}")
    splash.configure(fg_color="#1a1a1a")

    # Ícono grande en el splash
    ruta_ico = ruta_recurso("Icono.png")
    if os.path.exists(ruta_ico):
        try:
            from PIL import Image as PilImage
            img = PilImage.open(ruta_ico).resize((90, 90))
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(90, 90))
            ctk.CTkLabel(splash, image=ctk_img, text="").pack(pady=(36, 8))
        except Exception:
            ctk.CTkLabel(splash, text="📦", font=ctk.CTkFont(size=56)).pack(pady=(36, 8))
    else:
        ctk.CTkLabel(splash, text="📦", font=ctk.CTkFont(size=56)).pack(pady=(36, 8))

    ctk.CTkLabel(splash, text="Stock Control",
                 font=ctk.CTkFont(size=20, weight="bold"),
                 text_color="white").pack(pady=(0, 4))

    lbl_estado = ctk.CTkLabel(splash, text="Iniciando...",
                               font=ctk.CTkFont(size=12),
                               text_color="#888888")
    lbl_estado.pack()

    barra = ctk.CTkProgressBar(splash, width=240, mode="indeterminate")
    barra.pack(pady=20)
    barra.start()

    return splash, lbl_estado, barra

# ── VENTANA PRINCIPAL ─────────────────────────────────────────────────────────

def construir_ventana_principal():
    global entry_pdf, frame_libros, lbl_count
    global turno_var, btn_am, btn_pm, lbl_nombre_preview
    global combo_perfiles, entry_comentarios
    global lbl_status

    ventana = ctk.CTk()
    ventana.title("Sistema Control de Stock")
    ventana.geometry("1100x860")
    ventana.minsize(800, 600)

    # Ícono de ventana y barra de tareas
    ruta_ico = ruta_recurso("Icono.ico")
    ruta_png = ruta_recurso("Icono.png")
    if os.path.exists(ruta_ico):
        try:
            ventana.iconbitmap(ruta_ico)
        except Exception:
            pass
    if os.path.exists(ruta_png):
        try:
            from PIL import Image as PilImage
            img = PilImage.open(ruta_png)
            ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(32, 32))
            ventana.wm_iconphoto(True, ctk_img._light_image)
        except Exception:
            pass

    ventana.grid_columnconfigure(1, weight=1)
    ventana.grid_rowconfigure(0, weight=1)

    # ── Sidebar ───────────────────────────────────────────────────────────────
    sidebar = ctk.CTkFrame(ventana, width=200, corner_radius=0)
    sidebar.grid(row=0, column=0, sticky="nsew")
    sidebar.grid_propagate(False)
    sidebar.grid_rowconfigure(5, weight=1)

    # Logo en sidebar
    if os.path.exists(ruta_png):
        try:
            from PIL import Image as PilImage
            img_side = PilImage.open(ruta_png).resize((52, 52))
            ctk_side = ctk.CTkImage(light_image=img_side, dark_image=img_side, size=(52, 52))
            ctk.CTkLabel(sidebar, image=ctk_side, text="").grid(row=0, column=0, pady=(28, 4), padx=24)
        except Exception:
            ctk.CTkLabel(sidebar, text="📦", font=ctk.CTkFont(size=34)).grid(row=0, column=0, pady=(32, 2), padx=24)
    else:
        ctk.CTkLabel(sidebar, text="📦", font=ctk.CTkFont(size=34)).grid(row=0, column=0, pady=(32, 2), padx=24)

    ctk.CTkLabel(sidebar, text="Stock\nControl",
                 font=ctk.CTkFont(size=18, weight="bold"), justify="center").grid(
        row=1, column=0, padx=24, pady=(0, 28))
    ctk.CTkFrame(sidebar, height=1, fg_color=("gray75", "gray30")).grid(
        row=2, column=0, sticky="ew", padx=16)

    comandos_sidebar = {"Config": abrir_config_perfiles}
    for idx, (icon, label) in enumerate([("📄", "Reporte"), ("📚", "Libros"), ("⚙️", "Config")]):
        ctk.CTkButton(
            sidebar, text=f"  {icon}  {label}", anchor="w",
            fg_color="transparent", text_color=("gray20", "gray80"),
            hover_color=("gray88", "gray25"), corner_radius=8, height=40,
            command=comandos_sidebar.get(label),
        ).grid(row=3 + idx, column=0, padx=10, pady=2, sticky="ew")

    ctk.CTkLabel(sidebar, text="v1.0", font=ctk.CTkFont(size=11),
                 text_color=("gray50", "gray50")).grid(row=6, column=0, pady=16)

    # ── Panel principal scrollable ─────────────────────────────────────────────
    main = ctk.CTkScrollableFrame(ventana, corner_radius=0, fg_color="transparent")
    main.grid(row=0, column=1, sticky="nsew")
    main.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(main, text="Generar reporte PDF",
                 font=ctk.CTkFont(size=22, weight="bold")).grid(
        row=0, column=0, sticky="w", padx=32, pady=(32, 2))
    ctk.CTkLabel(main,
        text="Selecciona el archivo fuente, marca las diferencias por libro y genera el PDF firmado.",
        font=ctk.CTkFont(size=12), text_color=("gray45", "gray60"),
    ).grid(row=1, column=0, sticky="w", padx=32, pady=(0, 20))

    # ── Card: PDF ─────────────────────────────────────────────────────────────
    card_pdf = ctk.CTkFrame(main, corner_radius=12)
    card_pdf.grid(row=2, column=0, sticky="ew", padx=32, pady=(0, 14))
    card_pdf.grid_columnconfigure(1, weight=1)
    ctk.CTkLabel(card_pdf, text="ARCHIVO FUENTE",
                 font=ctk.CTkFont(size=10, weight="bold"),
                 text_color=("gray50", "gray50")).grid(
        row=0, column=0, columnspan=3, sticky="w", padx=20, pady=(16, 6))
    entry_pdf = ctk.CTkEntry(card_pdf, placeholder_text="Ruta del archivo PDF…",
                              height=40, corner_radius=8)
    entry_pdf.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(20, 8), pady=(0, 16))
    ctk.CTkButton(card_pdf, text="Buscar", width=110, height=40, corner_radius=8,
                  command=seleccionar_pdf).grid(row=1, column=2, padx=(0, 20), pady=(0, 16))

    # ── Card: Libros ──────────────────────────────────────────────────────────
    card_libros = ctk.CTkFrame(main, corner_radius=12)
    card_libros.grid(row=3, column=0, sticky="ew", padx=32, pady=(0, 14))
    card_libros.grid_columnconfigure(0, weight=1)
    header_libros = ctk.CTkFrame(card_libros, fg_color="transparent")
    header_libros.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
    header_libros.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(header_libros, text="LIBROS",
                 font=ctk.CTkFont(size=10, weight="bold"),
                 text_color=("gray50", "gray50")).grid(row=0, column=0, sticky="w")
    lbl_count = ctk.CTkLabel(header_libros, text="Sin cargar",
                              font=ctk.CTkFont(size=11), text_color=("gray50", "gray50"))
    lbl_count.grid(row=0, column=1, padx=12)
    ctk.CTkLabel(header_libros,
        text="Clic en un libro para ingresar diferencia  ( negativo = faltante · positivo = sobrante )",
        font=ctk.CTkFont(size=10), text_color=("gray50", "gray50"),
    ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
    ctk.CTkButton(header_libros, text="Cargar libros", width=120, height=32, corner_radius=8,
                  fg_color="transparent", border_width=1,
                  command=cargar_libros).grid(row=0, column=2)
    frame_libros = ctk.CTkFrame(card_libros, fg_color="transparent")
    frame_libros.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 16))

    # ── Card: Turno AM / PM ───────────────────────────────────────────────────
    card_turno = ctk.CTkFrame(main, corner_radius=12)
    card_turno.grid(row=4, column=0, sticky="ew", padx=32, pady=(0, 14))
    card_turno.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(card_turno, text="TURNO",
                 font=ctk.CTkFont(size=10, weight="bold"),
                 text_color=("gray50", "gray50")).grid(
        row=0, column=0, sticky="w", padx=20, pady=(16, 10))
    turno_var = ctk.StringVar(value="AM")
    frame_turno_btns = ctk.CTkFrame(card_turno, fg_color="transparent")
    frame_turno_btns.grid(row=1, column=0, sticky="w", padx=20, pady=(0, 10))
    btn_am = ctk.CTkButton(
        frame_turno_btns, text="AM", width=110, height=44, corner_radius=8,
        fg_color="#1a5e2a", text_color="white", font=ctk.CTkFont(size=15, weight="bold"),
        command=lambda: [turno_var.set("AM"), actualizar_turno_botones()],
    )
    btn_am.pack(side="left", padx=(0, 8))
    btn_pm = ctk.CTkButton(
        frame_turno_btns, text="PM", width=110, height=44, corner_radius=8,
        fg_color="transparent", border_width=1, text_color=("gray40", "gray60"),
        font=ctk.CTkFont(size=15, weight="bold"),
        command=lambda: [turno_var.set("PM"), actualizar_turno_botones()],
    )
    btn_pm.pack(side="left")
    lbl_nombre_preview = ctk.CTkLabel(
        card_turno,
        text=f"Inventory Report {datetime.datetime.now().strftime('%Y%m%d')} - AM.pdf",
        font=ctk.CTkFont(size=11), text_color=("gray50", "gray50"),
    )
    lbl_nombre_preview.grid(row=2, column=0, sticky="w", padx=20, pady=(0, 16))

    # ── Card: Perfil + Comentarios ────────────────────────────────────────────
    card_opciones = ctk.CTkFrame(main, corner_radius=12)
    card_opciones.grid(row=5, column=0, sticky="ew", padx=32, pady=(0, 14))
    card_opciones.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(card_opciones, text="PERFIL",
                 font=ctk.CTkFont(size=10, weight="bold"),
                 text_color=("gray50", "gray50")).grid(
        row=0, column=0, sticky="w", padx=20, pady=(16, 6))
    combo_perfiles = ctk.CTkOptionMenu(
        card_opciones, values=list(PERFILES.keys()),
        height=40, corner_radius=8, dynamic_resizing=False)
    combo_perfiles.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 16))
    ctk.CTkFrame(card_opciones, height=1, fg_color=("gray80", "gray30")).grid(
        row=2, column=0, sticky="ew", padx=20)
    ctk.CTkLabel(card_opciones, text="COMENTARIOS",
                 font=ctk.CTkFont(size=10, weight="bold"),
                 text_color=("gray50", "gray50")).grid(
        row=3, column=0, sticky="w", padx=20, pady=(16, 6))

    entry_comentarios = ctk.CTkTextbox(
        card_opciones, height=90, corner_radius=8,
        wrap="word",
    )
    entry_comentarios.grid(row=4, column=0, sticky="ew", padx=20, pady=(0, 20))

    lbl_status = ctk.CTkLabel(
        main, text="",
        font=ctk.CTkFont(size=12),
        text_color="#86efac",
    )
    lbl_status.grid(row=6, column=0, sticky="e", padx=32, pady=(4, 0))

    # ── Botón generar ─────────────────────────────────────────────────────────
    ctk.CTkButton(
        main, text="  Generar PDF  →",
        font=ctk.CTkFont(size=15, weight="bold"),
        height=52, corner_radius=12, command=generar_pdf,
    ).grid(row=7, column=0, sticky="e", padx=32, pady=(4, 40))

    return ventana

# ── MAIN ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # 1. Arrancar CTk y mostrar splash antes de cargar nada pesado
    ctk.CTk().withdraw()   # instancia root oculta necesaria para CTkToplevel
    splash, lbl_estado, barra = mostrar_splash()

    # 2. Cargar librerías pesadas en segundo plano
    hilo = threading.Thread(target=_cargar_librerias, daemon=True)
    hilo.start()

    def esperar_carga():
        if hilo.is_alive():
            lbl_estado.configure(text="Cargando librerias PDF...")
            splash.after(150, esperar_carga)
        else:
            lbl_estado.configure(text="Listo!")
            barra.stop()
            splash.after(400, lambda: _abrir_app(splash))

    def _abrir_app(splash):
        splash.destroy()
        ventana = construir_ventana_principal()
        ventana.state("zoomed")
        ventana.mainloop()

    splash.after(100, esperar_carga)
    splash.mainloop()
