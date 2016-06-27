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

import os
import sys
import fcntl
import app
from app import cleanup, config, log, RetryException, setup, spawn, timer
from assembly import compose
from deployment import deploy
from pots import Pots
import cache
from release_note import do_release_note
import sandbox
import sandboxlib
import yaml
import logging
import logger
from logger import l

def write_cache_key():
    with open(config['result-file'], 'w') as f:
        f.write(target['cache'] + '\n')
    for kind in ['systems', 'strata', 'chunks']:
        log('COUNT', '%s has %s %s' % (config['target'], config[kind], kind))
    log('RESULT', 'Cache-key for target is at', config['result-file'])

if not os.path.exists('./VERSION'):
    #Make sure we are in the definitions directory
    if os.path.basename(os.getcwd()) != 'definitions':
        if os.path.isdir(os.path.join(os.getcwd(), 'definitions')):
            os.chdir(os.path.join(os.getcwd(), 'definitions'))
        else:
            if os.path.isdir(os.path.join(os.getcwd(), '..', 'definitions')):
                os.chdir(os.path.join(os.getcwd(), '..', 'definitions'))
#else assume version 1? TODO 

#Setup dev logging
logger._setup_logging(logging.DEBUG)

setup(sys.argv)
cleanup(config['tmp'])

# Time the total running of YBD
with timer('TOTAL'):
    # Create lock file
    tmp_lock = open(os.path.join(config['tmp'], 'lock'), 'r')
    fcntl.flock(tmp_lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
    l("Creating lock file at %s"%os.path.join(config['tmp'], 'lock'),"d")

    # Get target definitions
    target = os.path.join(config['defdir'], config['target'])
    log('TARGET', 'Target is %s' % target, config['arch'])
    l("Reading root definitions for %s"%target,"i")
    
    with timer('DEFINITIONS', 'parsing %s' % config['def-version']):
        app.defs = Pots()
        if 'release-note' in config:
            do_release_note(config['release-note'])

    target = app.defs.get(config['target'])
    if config.get('mode', 'normal') in ['parse-only', 'no-build']:
        write_yaml(target)

    if config.get('mode', 'normal') == 'parse-only':
        os._exit(0)
    os._exit(0)
    with timer('CACHE-KEYS', 'cache-key calculations'):
        cache.cache_key(target)

    if config['total'] == 0 or (config['total'] == 1 and
                                target.get('kind') == 'cluster'):
        log('ARCH', 'No definitions for', config['arch'], exit=True)

    app.defs.save_trees()
    if config.get('mode', 'normal') == 'keys-only':
        write_cache_key()
        os._exit(0)

    cache.cull(config['artifacts'])

    sandbox.executor = sandboxlib.executor_for_platform()
    log(config['target'], 'Sandbox using %s' % sandbox.executor)
    if sandboxlib.chroot == sandbox.executor:
        log(config['target'], 'WARNING: using chroot is less safe ' +
            'than using linux-user-chroot')

    if 'instances' in config:
        spawn()

    while True:
        try:
            compose(target)
            break
        except KeyboardInterrupt:
            log(target, 'Interrupted by user')
            os._exit(1)
        except RetryException:
            pass
        except:
            import traceback
            traceback.print_exc()
            log(target, 'Exiting: uncaught exception')
            os._exit(1)

    if config.get('reproduce'):
        log('REPRODUCED',
            'Matched %s of' % len(config['reproduced']), config['tasks'])
        for match in config['reproduced']:
            print match[0], match[1]

    if target.get('kind') == 'cluster' and config.get('fork') is None:
        with timer(target, 'cluster deployment'):
            deploy(target)
