# classifiers/base.py

from abc import ABC, abstractmethod
from typing import Dict


class BaseClassifier(ABC):
    """
    Contrato base para clasificadores de clientes.
    Cada clasificador recibe una URL y devuelve
    información estructural para el metacrawler.
    """

    @abstractmethod
    def classify(self, url: str) -> Dict:
        """
        Clasifica una URL y devuelve un dict con:
        - source_id: identificador lógico de la fuente
        - subfolder: subcarpeta opcional (str o None)
        """
        pass
