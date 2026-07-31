class PluginLoader:
    def __init__(self):
        self.plugins = {}

    def load_package(self, package):
        imported_package = importlib.import_module(package)

        for _, module_name, _ in pkgutil.iter_modules(
            imported_package.__path__
        ):
            full_name = f"{package}.{module_name}"

            module = importlib.import_module(full_name)

            self.plugins[module_name] = module

        return self.plugins