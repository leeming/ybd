import logging

try:
    _log_init
except:
    _log_init=False
    _log_default_lvl=logging.DEBUG
    _log_default_tag="YBD"

    _logger = logging.getLogger(__name__)
    _logger.setLevel(_log_default_lvl)
    
    fh = logging.FileHandler('ybd.log')
    fh.setLevel(_log_default_lvl)
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s',"%Y-%m-%d %H:%M:%S")
    fh.setFormatter(formatter)

    _logger.addHandler(fh)
    _log_init=True
    

    

def l(msg, level=logging.DEBUG, tag='',  *kargs, **kwargs):
    global _logger, _log_default_tag
    
    if _log_init:
        if tag is not '':
            msg = "[%s] %s"%(tag,msg)
        elif tag is "" and _log_default_tag is not None:
            msg = "[%s] %s"%(_log_default_tag,msg)
            
        
        if level in [logging.DEBUG,'d','debug']:
            _logger.debug(msg, *kargs, **kwargs)
            print msg
        elif level in [logging.INFO, 'i', 'info']:      
            _logger.info(msg, *kargs, **kwargs)
        elif level in [logging.WARN, 'w', 'warn']:      
            _logger.warn(msg, *kargs, **kwargs)
        elif level in [logging.ERROR, 'e', 'error']:      
            _logger.error(msg, *kargs, **kwargs)
        else:
            raise Exception("Unexpected log level of :%d"%level)
    else:
        print "Logging not en"
        return 
def log(*kargs, **kwargs):
    global _logger, _log_default_tag
    l(*kargs, **kwargs)
 
#dep?   
def _setup_logging(log_level=logging.DEBUG, filename='ybd.log'):
    '''
    Set up the standard python logging object for YBD.
    
    Defaults to only logging Warning and above to file
    '''
    global _logger
    global _log_init
    
    _logger = logging.getLogger(__name__)
    _logger.setLevel(log_level)
    
    fh = logging.FileHandler(filename)
    fh.setLevel(log_level)
    
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)

    _logger.addHandler(fh)
    _log_init=True
    l("logger.init()",'d',tag="INIT")
    
l("logger.init()",'d',tag="INIT")