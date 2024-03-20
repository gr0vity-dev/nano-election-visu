class MessageCounter:
    def __init__(self, logger):
        self.count = 0
        self.logger = logger

    def increment(self, log_interval=1000):
        self.count += 1
        if self.count % log_interval == 0:
            self.logger.info(self.count)
