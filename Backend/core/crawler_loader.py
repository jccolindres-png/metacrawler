#!/usr/bin/env python3

import importlib
import sys
from pathlib import Path
from types import ModuleType
from core.client_provider import provider_for


class CrawlerNotFoundError(RuntimeError):
    pass


class InvalidCountryCodeError(RuntimeError):
    pass


# -------------------------------------------------
# Asegurar root del proyecto como importable
# -------------------------------------------------

CODE_DIR = Path(__file__).resolve().parent
BACKEND_DIR = CODE_DIR.parent
PROJECT_ROOT = BACKEND_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def load_crawler(
    client: str,
    country: str,
    source_id: str,
) -> ModuleType:
    """
    Resuelve y carga el crawler correcto según:
      clients/<client>/crawlers/<country>/<source_id>.py

    ❗ NO corrige inputs
    ❗ NO normaliza
    ❗ FALLA si el country no es exactamente válido
    """

    if country != country.lower():
        raise InvalidCountryCodeError(
            "Código de país inválido\n"
            f"Valor recibido : {country}\n"
            "Regla          : country debe venir en minúscula\n"
            "Ejemplo válido : 'ti'\n"
        )

    provider = provider_for(client, "crawler")
    module_path = f"clients.{provider}.crawlers.{country}.{source_id}"

    try:
        return importlib.import_module(module_path)

    except ModuleNotFoundError as e:
        raise CrawlerNotFoundError(
            "Crawler no encontrado\n"
            f"Cliente : {client}\n"
            f"País    : {country}\n"
            f"Fuente  : {source_id}\n"
            f"Módulo  : {module_path}\n"
        ) from e
