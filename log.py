import logging

def patch_logging():
    """Add TRACE support to logging system.

       (cfr. https://gist.github.com/numberoverzero/f803ebf29a0677b6980a5a733a10ca71)"""
    # add TRACE level to logging
    logging.TRACE = logging.DEBUG - 5
    logging.addLevelName(logging.TRACE, "TRACE")
    # add trace() method to Logger 
    def log_logger(self, message, *args, **kwargs):
        if self.isEnabledFor(logging.TRACE):
            self._log(logging.TRACE, message, args, **kwargs)
    logging.getLoggerClass().trace = log_logger
    # add trace() method to root 
    def log_root(msg, *args, **kwargs):
        logging.log(logging.TRACE, msg, *args, **kwargs)
    logging.trace = log_root

def init_logging(level = logging.INFO) -> None:
    """Init logging system so that any application logger uses input level.

    Args:
        level (optional): can be any logging level, also custom logging.TRACE. Defaults to logging.INFO.
    """
    # set root logger to 'level' (can be logging.INFO, logging.DEBUG or logging.TRACE)
    logging.basicConfig(level=level, format="%(levelname)s [%(module)s] %(message)s")
    # Set to Warning all loggers imported from libraries
    for name, _ in logging.Logger.manager.loggerDict.items():
        if name.startswith('xiaomi')==False:
            logging.getLogger(name).setLevel(logging.WARNING)
