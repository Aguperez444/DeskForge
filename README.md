# DeskForge *(formerly AutoJar)*

**DeskForge** es un integrador y gestor universal de aplicaciones de escritorio para Linux estilo **Gear Lever+**.
Permite integrar, organizar, configurar, actualizar y desinstalar **AppImages**, archivos **`.jar` (Java)**, **binarios portables (ELF)**, **scripts** (`.sh`, `.py`, etc.) y **WebApps / PWAs** con total conformidad a la especificación **FreeDesktop Desktop Entry v1.5**.

---

## Características principales

- **Soporte universal (5 tipos)**:
  - **AppImage**: extracción segura de metadatos (`.desktop`) e íconos sin ejecutar código del binario (vía offset SquashFS + `unsquashfs`/`7z`).
  - **JAR (Java)** *(legado AutoJar)*: inspección de `META-INF/MANIFEST.MF`, extracción automática de íconos embebidos, detección de múltiples JDKs instalados (`/usr/lib/jvm`, SDKMAN, `~/.jdks`, `PATH`) y controles dedicados para `-Xmx`, `-Xms` y flags JVM.
  - **Binarios portables (ELF)**: detección de cabecera ELF, búsqueda de íconos cercanos, permisos `+x` y directorio de trabajo (`Path=`).
  - **Scripts**: detección de shebang (`#!`), intérprete opcional y modo terminal.
  - **WebApps / PWAs**: extracción automática de `<title>`, descripción y favicon; lanzamiento en modo ventana independiente (`--app=`) con Chromium/Chrome/Brave/Vivaldi/Edge/Firefox.
- **Gestión completa estilo Gear Lever**:
  - Biblioteca visual filtrable por tipo y búsqueda en tiempo real.
  - Gestión de almacenamiento (`Mover` a `~/Applications/DeskForge`, `Copiar` o `Mantener`).
  - **Actualización de versión in-place**: reemplazá el `.AppImage`/`.jar` conservando tus variables de entorno, configuración JVM, GPU y categorías.
  - **Escáner de Descargas** + **Importador de `.desktop` existentes** (incluyendo lanzadores creados con la versión original de AutoJar).
  - **Diagnóstico y auto-reparación (`Doctor`)** para detectar binarios rotos, permisos faltantes o `.desktop` inválidos.
- **Integración nativa con el escritorio Linux (KDE / GNOME / Wayland / XDG)**:
  - Interfaz nativa en **PySide6 (Qt 6)** con soporte real para **Wayland**, HiDPI, renderizado nativo de SVG e íconos del tema del sistema (`QIcon.fromTheme`).
  - Cumplimiento FreeDesktop v1.5 con validación integrada (`desktop-file-validate`), escapado seguro de `Exec=`, `xdg-user-dir`, `gio metadata::trusted`, `update-desktop-database` y `kbuildsycoca6`.
  - Temas claro y oscuro (QSS) con detección automática del tema del sistema.
  - **Drag & Drop nativo de Qt 6** sobre la ventana principal, `Ctrl+V` global para pegar archivos/URLs, **"Abrir con DeskForge"** (`install-self`) y **CLI completo**.

---

## Arquitectura

El proyecto sigue una **Arquitectura en Capas (Clean Layered Architecture)** con estricta separación de responsabilidades:

```text
src/deskforge/
├── domain/          # Entidades puras, enums, catálogo FreeDesktop y excepciones
├── infrastructure/  # Repositorios JSON atómicos, XDG, motor .desktop v1.5, OS e inspectors/ (Strategy)
├── application/     # Casos de uso (AppService, DoctorService) y composición (ServiceContainer)
├── cli/             # Adaptador CLI (argparse, soporte --json)
├── ui/              # Adaptador GUI modular en PySide6 (Qt 6)
└── assets/          # Íconos de DeskForge y legado AutoJar
```

---

## Instalación y Uso

### Requisitos
- Python 3.11+
- `PySide6` y `Pillow` (`pip install PySide6 pillow`)

### Ejecución directa
```bash
python3 main.py
```

### Instalación editable en tu entorno (habilita el comando `deskforge`)
```bash
pip install -e .
# O con uv:
uv pip install -e .
```

### Instalar en el menú de aplicaciones y en "Abrir con..."
```bash
python3 main.py install-self
# (o desde la GUI: Ajustes ⚙ -> Instalar en menú del sistema)
```

---

## Referencia rápida del CLI

```bash
# Abrir interfaz gráfica
deskforge

# Abrir asistente de integración precargado (usado por "Abrir con DeskForge")
deskforge ~/Descargas/MiApp.AppImage

# Integrar desde terminal
deskforge integrate ~/Descargas/app.jar --move --xmx 4G --gpu --env SDL_VIDEODRIVER=wayland --desktop-shortcut
deskforge integrate https://excalidraw.com --name Excalidraw

# Listar, lanzar, actualizar y eliminar
deskforge list
deskforge list --type jar --json
deskforge launch Excalidraw
deskforge update MiApp ~/Descargas/MiApp-2.0.AppImage --refresh-icon
deskforge remove MiApp --delete-file

# Escanear descargas y diagnosticar
deskforge scan
deskforge doctor --fix
```

---

## Pruebas automatizadas

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```
