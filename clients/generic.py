# classifiers/clients/generic.py

from classifiers.base import BaseClassifier
from urllib.parse import urlparse


class Classifier(BaseClassifier):
    def classify(self, url: str):
        domain = urlparse(url).netloc.lower()

        return {
            "source_id": "generic",
            "subfolder": None,
            "domain": domain
        }
