"""DeskForge CLI entrypoint (`deskforge` command)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from deskforge import __app_name__, __version__
from deskforge.application import ServiceContainer, build_services
from deskforge.domain.categories import normalize_categories
from deskforge.domain.exceptions import DeskForgeError
from deskforge.domain.models import AppType, IssueSeverity, JavaOptions, ManagedApp, StorageMode

SUBCOMMANDS = {
    "integrate",
    "list",
    "launch",
    "update",
    "remove",
    "scan",
    "doctor",
    "install-self",
    "uninstall-self",
    "gui",
}


def _parse_env_pairs(pairs: list[str] | None) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in pairs or []:
        if "=" not in item:
            raise DeskForgeError(f"Variable de entorno inválida '{item}'. Usá el formato CLAVE=VALOR.")
        k, v = item.split("=", 1)
        result[k.strip()] = v
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deskforge",
        description="DeskForge — Integrador y gestor universal de aplicaciones de escritorio para Linux.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"{__app_name__} {__version__}")
    sub = parser.add_subparsers(dest="command")

    # gui
    p_gui = sub.add_parser("gui", help="Abrir la interfaz gráfica (opcionalmente precargando un archivo o URL)")
    p_gui.add_argument("target", nargs="?", help="Archivo o URL para abrir directo en el asistente de integración")

    # integrate
    p_int = sub.add_parser("integrate", help="Integrar una nueva aplicación (.AppImage, .jar, binario, script o URL)")
    p_int.add_argument("target", help="Ruta al archivo ejecutable o URL (https://...)")
    p_int.add_argument("--name", help="Nombre de la aplicación (auto-detectado si se omite)")
    p_int.add_argument("--comment", help="Descripción o comentario")
    p_int.add_argument("--icon", help="Ruta a un ícono personalizado o nombre de tema")
    p_int.add_argument("--type", dest="app_type", choices=[t.value for t in AppType], help="Forzar tipo de aplicación")
    p_int.add_argument("--category", action="append", help="Categoría FreeDesktop o en español (repetible)")
    mode_grp = p_int.add_mutually_exclusive_group()
    mode_grp.add_argument("--move", action="store_true", help="Mover el archivo a la carpeta gestionada")
    mode_grp.add_argument("--copy", action="store_true", help="Copiar el archivo a la carpeta gestionada")
    mode_grp.add_argument("--keep", action="store_true", help="Mantener el archivo en su ubicación original")
    p_int.add_argument("--desktop-shortcut", action="store_true", help="Crear también acceso directo en el Escritorio")
    p_int.add_argument("--terminal", action="store_true", help="Ejecutar en terminal")
    p_int.add_argument("--gpu", action="store_true", help="Preferir GPU dedicada")
    p_int.add_argument("--env", action="append", help="Variable de entorno CLAVE=VALOR (repetible)")
    p_int.add_argument("--arg", action="append", help="Argumento CLI extra para la app (repetible)")
    p_int.add_argument("--workdir", help="Directorio de trabajo (Path=)")
    p_int.add_argument("--java", help="Ruta al binario java/JDK para apps .jar")
    p_int.add_argument("--xmx", help="Memoria máxima JVM (ej. 2G, 512M)")
    p_int.add_argument("--xms", help="Memoria inicial JVM (ej. 256M)")
    p_int.add_argument("--jvm-arg", action="append", help="Flag JVM adicional (repetible)")
    p_int.add_argument("--json", action="store_true", help="Imprimir resultado en formato JSON")

    # list
    p_list = sub.add_parser("list", help="Listar aplicaciones gestionadas por DeskForge")
    p_list.add_argument("--type", dest="app_type", choices=[t.value for t in AppType], help="Filtrar por tipo")
    p_list.add_argument("--search", default="", help="Filtrar por texto")
    p_list.add_argument("--json", action="store_true", help="Salida en JSON")

    # launch
    p_launch = sub.add_parser("launch", help="Lanzar una aplicación gestionada por ID o nombre")
    p_launch.add_argument("query", help="ID o nombre de la aplicación")

    # update
    p_upd = sub.add_parser("update", help="Actualizar versión (reemplazar binario) manteniendo configuración")
    p_upd.add_argument("query", help="ID o nombre de la aplicación existente")
    p_upd.add_argument("new_file", help="Ruta al nuevo archivo .AppImage / .jar / binario")
    p_upd.add_argument("--refresh-icon", action="store_true", help="Reemplazar ícono con el del nuevo archivo")

    # remove
    p_rem = sub.add_parser("remove", help="Desinstalar lanzador de una aplicación gestionada")
    p_rem.add_argument("query", help="ID o nombre de la aplicación")
    p_rem.add_argument("--delete-file", action="store_true", help="También eliminar o enviar a papelera el archivo ejecutable")
    p_rem.add_argument("--no-trash", action="store_true", help="Eliminar permanentemente en lugar de mover a la Papelera")

    # scan
    p_scan = sub.add_parser("scan", help="Escanear una carpeta en busca de .AppImage y .jar sin integrar")
    p_scan.add_argument("directory", nargs="?", help="Directorio a escanear (por defecto Descargas)")
    p_scan.add_argument("--json", action="store_true", help="Salida en JSON")

    # doctor
    p_doc = sub.add_parser("doctor", help="Verificar salud de las aplicaciones gestionadas y herramientas del sistema")
    p_doc.add_argument("--fix", action="store_true", help="Reparar automáticamente los problemas solucionables")
    p_doc.add_argument("--json", action="store_true", help="Salida en JSON")

    # install-self / uninstall-self
    sub.add_parser("install-self", help="Instalar DeskForge en el menú del sistema y en 'Abrir con...'")
    sub.add_parser("uninstall-self", help="Desinstalar el lanzador de DeskForge del menú del sistema")

    return parser


def _cmd_integrate(args: argparse.Namespace, services: ServiceContainer) -> int:
    detection = services.app_service.inspect_target(args.target)
    app_type = AppType(args.app_type) if args.app_type else detection.app_type

    cfg = services.app_service.get_config()
    if args.move:
        storage_mode = StorageMode.MOVE
    elif args.copy:
        storage_mode = StorageMode.COPY
    elif args.keep:
        storage_mode = StorageMode.KEEP
    else:
        try:
            storage_mode = StorageMode(cfg.default_storage_mode)
        except ValueError:
            storage_mode = StorageMode.KEEP

    categories = normalize_categories(args.category) if args.category else detection.categories
    java_opts = JavaOptions(
        java_path=args.java or "java",
        max_memory=args.xmx or "",
        min_memory=args.xms or "",
        jvm_args=list(args.jvm_arg or []),
    )

    app = ManagedApp(
        name=args.name or detection.suggested_name,
        app_type=app_type,
        exec_target=detection.target,
        icon_path=args.icon if args.icon is not None else detection.selected_icon,
        comment=args.comment if args.comment is not None else detection.comment,
        categories=categories,
        args=list(args.arg or []),
        env_vars=_parse_env_pairs(args.env),
        working_dir=args.workdir if args.workdir is not None else detection.working_dir,
        terminal=bool(args.terminal or (detection.terminal and not args.app_type)),
        dedicated_gpu=bool(args.gpu),
        startup_wm_class=detection.startup_wm_class,
        create_desktop_shortcut=bool(args.desktop_shortcut or cfg.default_desktop_shortcut),
        storage_mode=storage_mode,
        java_options=java_opts,
        script_interpreter=detection.script_interpreter,
        webapp_browser=detection.webapp_browser,
        version=detection.version,
    )

    integrated = services.app_service.integrate_app(app, source_icon=app.icon_path)
    if args.json:
        print(json.dumps(integrated.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(f"✓ Integrada: {integrated.name} [{integrated.app_type.short_badge}] (id: {integrated.id})")
        print(f"  Desktop: {integrated.desktop_file_path}")
        print(f"  Destino: {integrated.exec_target}")
        for warn in detection.warnings:
            print(f"  ⚠ {warn}")
    return 0


def _cmd_list(args: argparse.Namespace, services: ServiceContainer) -> int:
    app_type = AppType(args.app_type) if args.app_type else None
    apps = services.app_service.list_apps(app_type=app_type, search=args.search)
    if args.json:
        print(json.dumps([a.to_dict() for a in apps], indent=2, ensure_ascii=False))
        return 0
    if not apps:
        print("No hay aplicaciones gestionadas todavía. Usá 'deskforge integrate <archivo>' o abrí la GUI.")
        return 0
    print(f"{'ID':<13} {'TIPO':<9} {'NOMBRE':<28} {'VERSIÓN':<10} DESTINO")
    print("-" * 92)
    for a in apps:
        ver = a.version[:9] if a.version else "-"
        print(f"{a.id:<13} {a.app_type.short_badge:<9} {a.name[:27]:<28} {ver:<10} {a.exec_target}")
    return 0


def _cmd_launch(args: argparse.Namespace, services: ServiceContainer) -> int:
    app = services.app_service.find_app(args.query)
    services.app_service.launch_app(app.id)
    print(f"▶ Lanzando {app.name}...")
    return 0


def _cmd_update(args: argparse.Namespace, services: ServiceContainer) -> int:
    app = services.app_service.find_app(args.query)
    updated = services.app_service.replace_binary(app.id, args.new_file, refresh_icon=args.refresh_icon)
    print(f"✓ Actualizada: {updated.name} -> {updated.exec_target} (v{updated.version or '-'})")
    return 0


def _cmd_remove(args: argparse.Namespace, services: ServiceContainer) -> int:
    app = services.app_service.find_app(args.query)
    removed = services.app_service.remove_app(
        app.id,
        delete_target_file=args.delete_file,
        use_trash=not args.no_trash,
    )
    print(f"✓ Eliminada: {removed.name} (id: {removed.id})")
    return 0


def _cmd_scan(args: argparse.Namespace, services: ServiceContainer) -> int:
    directory = Path(args.directory).expanduser() if args.directory else None
    candidates = services.app_service.scan_directory(directory)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "path": c.path,
                        "app_type": c.app_type.value,
                        "name_guess": c.name_guess,
                        "size_bytes": c.size_bytes,
                    }
                    for c in candidates
                ],
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if not candidates:
        print("No se encontraron archivos .AppImage o .jar sin integrar.")
        return 0
    print(f"Se encontraron {len(candidates)} candidato(s) sin integrar:")
    for c in candidates:
        size_mb = c.size_bytes / (1024 * 1024)
        print(f"  [{c.app_type.short_badge}] {c.name_guess} ({size_mb:.1f} MB) -> {c.path}")
    return 0


def _cmd_doctor(args: argparse.Namespace, services: ServiceContainer) -> int:
    if args.fix:
        fixed = services.doctor_service.repair_all()
        if not args.json:
            print(f"Se repararon automáticamente {fixed} problema(s).")

    issues = services.doctor_service.run_checks()
    tools = services.doctor_service.get_system_tools()

    if args.json:
        print(
            json.dumps(
                {
                    "tools": tools,
                    "issues": [
                        {
                            "code": i.code,
                            "severity": i.severity.value,
                            "app_id": i.app_id,
                            "app_name": i.app_name,
                            "message": i.message,
                            "fixable": i.fixable,
                        }
                        for i in issues
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0 if not any(i.severity == IssueSeverity.ERROR for i in issues) else 1

    print("Herramientas del sistema:")
    for tool, path in tools.items():
        mark = "✓" if path else "·"
        print(f"  {mark} {tool:<24} {path or 'no instalada (opcional)'}")
    print()
    if not issues:
        print("✓ Todas las aplicaciones gestionadas están en perfecto estado.")
        return 0

    print(f"Se detectaron {len(issues)} incidencia(s):")
    for issue in issues:
        tag = "ERROR" if issue.severity == IssueSeverity.ERROR else "AVISO"
        fix_hint = " [auto-reparable con --fix]" if issue.fixable else ""
        owner = f"{issue.app_name}: " if issue.app_name else ""
        print(f"  [{tag}] {owner}{issue.message}{fix_hint}")
    return 1 if any(i.severity == IssueSeverity.ERROR for i in issues) else 0


def main(argv: Sequence[str] | None = None, services: ServiceContainer | None = None) -> int:
    raw_args = list(sys.argv[1:] if argv is None else argv)

    # 1. No args -> launch GUI directly
    if not raw_args:
        from deskforge.ui.app import launch_gui

        launch_gui(services=services)
        return 0

    # 2. Single file path or URL (e.g. "Open With DeskForge" %f) -> launch GUI in Integrate mode
    if len(raw_args) == 1 and not raw_args[0].startswith("-") and raw_args[0] not in SUBCOMMANDS:
        from deskforge.ui.app import launch_gui

        launch_gui(initial_target=raw_args[0], services=services)
        return 0

    parser = build_parser()
    args = parser.parse_args(raw_args)

    if args.command == "gui":
        from deskforge.ui.app import launch_gui

        launch_gui(initial_target=args.target, services=services)
        return 0

    container = services or build_services()

    try:
        if args.command == "integrate":
            return _cmd_integrate(args, container)
        if args.command == "list":
            return _cmd_list(args, container)
        if args.command == "launch":
            return _cmd_launch(args, container)
        if args.command == "update":
            return _cmd_update(args, container)
        if args.command == "remove":
            return _cmd_remove(args, container)
        if args.command == "scan":
            return _cmd_scan(args, container)
        if args.command == "doctor":
            return _cmd_doctor(args, container)
        if args.command == "install-self":
            path = container.system.install_self_desktop_entry()
            print(f"✓ DeskForge instalado en el menú del sistema y 'Abrir con...': {path}")
            return 0
        if args.command == "uninstall-self":
            removed = container.system.uninstall_self_desktop_entry()
            print("✓ Lanzador de DeskForge eliminado." if removed else "DeskForge no estaba instalado en el menú.")
            return 0
    except DeskForgeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
