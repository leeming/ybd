#!/usr/bin/env python
# Copyright (C) 2016  Codethink Limited
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program.  If not, see <http://www.gnu.org/licenses/>.

import logging


def setup_logger():
    #Set up loggers
    logger = logging.getLogger(__name__)
    
    ##Define logging to file behaviour
    # All levels are logged to a single debug.log file
    fh = logging.FileHandler('ybd-debug.log',mode='w')
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] - %(message)s',
                                  "%Y-%m-%d %H:%M:%S")
    fh.setFormatter(formatter)
    fh.setLevel(logging.DEBUG)
    logger.addHandler(fh)
    
    ##Define logging out to stdout
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(name)s] %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    
    #Set minimum level for the global setting.
    logger.setLevel(logging.DEBUG)
    
    return logger

logger=setup_logger()

logger.debug("Logger init")

verbose = logging.getLogger('verbose')
fh = logging.FileHandler('ybd-verbose.log',mode='w')
formatter = logging.Formatter("[%(filename)s:%(lineno)s - %(funcName)20s() ] %(message)s")
fh.setFormatter(formatter)
fh.setLevel(logging.DEBUG)
verbose.addHandler(fh)
verbose.setLevel(logging.DEBUG)

verbose.info("Verbose init")