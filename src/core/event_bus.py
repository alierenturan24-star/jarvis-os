class EventBus:

    def __init__(self):

        self.listeners = {}

    def subscribe(self, event, callback):

        if event not in self.listeners:
            self.listeners[event] = []

        self.listeners[event].append(callback)

    def publish(self, event, data=None):

        for callback in self.listeners.get(event, []):

            callback(data)