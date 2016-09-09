#!/usr/bin/env python
# Copyright (C) 2014-2016  Codethink Limited
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
#
# =*= License: GPL-2 =*=

'''A module to build a definition.'''

import sys
sys.path.insert(0, "/home/andrewleeming/baserock/sandboxlib")

import os
import sys
import fcntl
import app
from app import cleanup, config, log, RetryException, setup, spawn, timer
from assembly import compose
from deployment import deploy
from pots import Pots
from concourse import Pipeline
import cache
from release_note import do_release_note
import sandbox
import sandboxlib
import yaml

from logger import logger, verbose
import pprint

def write_cache_key():
    with open(config['result-file'], 'w') as f:
        f.write(target['cache'] + '\n')
    for kind in ['systems', 'strata', 'chunks']:
        log('COUNT', '%s has %s %s' % (config['target'], config[kind], kind))
        logger.info('[COUNT] {} has {} {}'.format(config['target'], config[kind], kind))
        
    log('RESULT', 'Cache-key for target is at', config['result-file'])
    logger.info("[RESULT] Cache-key for target is at {}".format(config['result-file']))

def chdir_definitions():
    '''
    YBD expects to be run from the 'definitions' directory. This function makes
    sure that it is by doing a simple search.
    '''
    
    
    if not os.path.exists('./VERSION'):
        if os.path.basename(os.getcwd()) != 'definitions':
            if os.path.isdir(os.path.join(os.getcwd(), 'definitions')):
                logger.debug("Not in definitions, moving to {}"
                             .format(os.path.join(os.getcwd(), 'definitions')))
                os.chdir(os.path.join(os.getcwd(), 'definitions'))
            else:
                if os.path.isdir(os.path.join(os.getcwd(), '..', 'definitions')):
                    logger.debug("Not in definitions, moving to {}"
                             .format(os.path.join(os.getcwd(), '../definitions')))
                    os.chdir(os.path.join(os.getcwd(), '..', 'definitions'))

#Do some basic tool setup
original_cwd = os.getcwd()
chdir_definitions()
setup(sys.argv, original_cwd)
cleanup(config['tmp'])

#Dump out the loaded config
logger.debug(pprint.pformat(config))

with timer('TOTAL'):
    logger.info("Configuring the build")
    
    #Create lock file for YBD
    verbose.info("Creating lock file at {}"
                 .format(os.path.join(config['tmp'], 'lock')))
    tmp_lock = open(os.path.join(config['tmp'], 'lock'), 'r')
    fcntl.flock(tmp_lock, fcntl.LOCK_SH | fcntl.LOCK_NB)

    #Parse root definitions file
    target = os.path.join(config['defdir'], config['target'])
    logger.info("[TARGET] Target is {}:{}".format(target, config['arch']))
    with timer('DEFINITIONS', 'parsing %s' % config['def-version']):
        app.defs = Pots()
    
    logger.info("Fetched definitions tree")

    #
    target = app.defs.get(config['target'])
    if config.get('mode', 'normal') == 'parse-only':
        logger.debug("Only running pipeline")
        Pipeline(target)
        os._exit(0)

    #Calculate cache keys
    with timer('CACHE-KEYS', 'cache-key calculations'):
        logger.info("Calculating cache keys")
        cache.cache_key(target)
    logger.debug("All cache-keys calculated")

    if 'release-note' in config:
        do_release_note(config['release-note'])

    if config['total'] == 0 or (config['total'] == 1 and
                                target.get('kind') == 'cluster'):
        log.error("[ARCH] No definitions for".format(config['arch']))
        log('ARCH', 'No definitions for', config['arch'], exit=True)

    app.defs.save_trees()
    if config.get('mode', 'normal') == 'keys-only':
        write_cache_key()
        os._exit(0)

    cache.cull(config['artifacts'])

    #Set up the sandbox for building
    sandbox.executor = sandboxlib.executor_for_platform()

    log(config['target'], 'Sandbox using %s' % sandbox.executor)
    logger.info('[{}] Sandbox using {}'.format(config['target'],sandbox.executor))
    if sandboxlib.chroot == sandbox.executor:
        log(config['target'], 'WARNING: using chroot is less safe ' +
            'than using linux-user-chroot')

    #Spawn multiple instances of YBD for parallel builds
    if 'instances' in config:
        spawn()

    #Start to build definitions
    logger.info("Build starting...")
    while True:
        try:
            compose(target)
            break
        except KeyboardInterrupt:
            log(target, 'Interrupted by user')
            logger.error("{} Interrupted by user".format(target))
            os._exit(1)
        except RetryException:
            logger.warn("{} Retry compose exception".format(target))
            pass
        except:
            import traceback
            traceback.print_exc()
            log(target, 'Exiting: uncaught exception')
            logger.error("{} Exiting: uncaught exception".format(target))
            
            os._exit(1)

    if config.get('reproduce'):
        log('REPRODUCED',
            'Matched %s of' % len(config['reproduced']), config['tasks'])
        for match in config['reproduced']:
            print match[0], match[1]

    if target.get('kind') == 'cluster' and config.get('fork') is None:
        with timer(target, 'cluster deployment'):
            deploy(target)
