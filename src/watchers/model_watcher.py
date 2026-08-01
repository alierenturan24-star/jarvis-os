from datetime import datetime

from src.watchers.model_catalog import ModelCatalog


class ModelWatcher:

    def __init__(self):

        self.catalog = ModelCatalog()

        self.last_scan = None

    def scan(self):

        self.last_scan = datetime.now()

        report = []

        for provider in self.catalog.enabled():

            report.append({

                "provider": provider.name,

                "category": provider.category,

                "sources": provider.official_sources,

                "keywords": provider.keywords,

                "status": "waiting",

            })

        return report

    def status(self):

        return {

            "providers": len(self.catalog.enabled()),

            "last_scan": self.last_scan,

        }