"""Capa HTTP. El nucleo (malla, modelo, ensamble) no depende de FastAPI."""

from .app import crear_app

__all__ = ["crear_app"]
