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

import yaml
import os
from app import chdir, config, log
from defaults import Defaults

from logger import logger

class Morphs(object):

    def __init__(self, directory='.'):
        '''Load all definitions from a directory tree.'''
        self._data = {}
        self.defaults = Defaults()
        self.fields = self.defaults.build_steps + self.defaults.fields
        config['cpu'] = self.defaults.cpus.get(config['arch'], config['arch'])
        self.parse_files(directory)

    def parse_files(self, directory):
        '''Searches a directory for definitions files'''
        
        logger.debug("Morph Parsing {}".format(directory))
        with chdir(directory):
            for dirname, dirnames, filenames in os.walk('.'):
                filenames.sort()
                dirnames.sort()
                if '.git' in dirnames:
                    dirnames.remove('.git')
                for filename in filenames:
                    if filename.endswith(('.def', '.morph')):
                        logger.debug("morph file found : {}".format(filename))
                        path = os.path.join(dirname, filename)
                        data = self._load(path)
                        if data is not None:
                            data['path'] = self._demorph(path[2:])
                            self._fix_keys(data)
                            self._tidy_and_insert_recursively(data)
        for x in self._data:
            dn = self._data[x]
            for field in dn:
                if field not in self.fields:
                    log(dn, 'Invalid field "%s" in' % field, dn['path'],
                        exit=True)

    def _load(self, path):
        '''Load a single definition file as a dict.

        The file is assumed to be yaml, and we insert the provided path into
        the dict keyed as 'path'.

        '''
        try:
            with open(path) as f:
                text = f.read()
            contents = yaml.safe_load(text)
        except yaml.YAMLError, exc:
            log('DEFINITIONS', 'Could not parse %s' % path, exc, exit=True)

        if type(contents) is not dict:
            log('DEFINITIONS', 'WARNING: %s contents is not dict:' % path,
                str(contents)[0:50])
            return None
        return contents

    def _tidy_and_insert_recursively(self, dn):
        '''Insert a definition and its contents into the dictionary.

        Takes a dict containing the content of a definition file.

        Inserts the definitions referenced or defined in the
        'build-depends' and 'contents' keys of `definition` into the
        dictionary, and then inserts `definition` itself into the
        dictionary.

        '''
        # handle morph syntax oddities...
        for index, component in enumerate(dn.get('build-depends', [])):
            self._fix_keys(component)
            dn['build-depends'][index] = self._insert(component)

        # The 'contents' field in the internal data model corresponds to the
        # 'chunks' field in a stratum .morph file, or the 'strata' field in a
        # system .morph file.
        dn['contents'] = dn.get('contents', [])

        if type(dn.get('chunks', [])) is not list:
            log('DEFINITIONS', 'WARNING: %s chunks must be list:' % dn['path'],
                dn.get('chunks', []), exit=True)

        if type(dn.get('strata', [])) is not list:
            log('DEFINITIONS', 'WARNING: %s strata must be list:' % dn['path'],
                dn.get('strata', []), exit=True)

        dn['contents'] += dn.pop('chunks', []) + dn.pop('strata', [])

        lookup = {}
        for index, component in enumerate(dn['contents']):
            self._fix_keys(component, dn['path'])
            lookup[component['name']] = component['path']
            if component['name'] == dn['name']:
                log(dn, 'WARNING: %s contains' % dn['path'], dn['name'])

            for x, it in enumerate(component.get('build-depends', [])):
                if it not in lookup:
                    # it is defined as a build depend, but hasn't actually been
                    # defined yet...
                    dependency = {'name': it}
                    self._fix_keys(dependency,  dn['path'])
                    lookup[it] = dependency['path']
                component['build-depends'][x] = lookup[it]

            component['build-depends'] = (dn.get('build-depends', []) +
                                          component.get('build-depends', []))

            if config.get('artifact-version', 0) not in [0, 1, 2, 3, 4, 5]:
                c = self._data.get(component['path'])
                if c and 'build-depends' in c:
                    component['build-depends'] += c['build-depends']

            splits = component.get('artifacts', [])
            dn['contents'][index] = {self._insert(component): splits}

        return self._insert(dn)

    def _fix_keys(self, dn, base=None):
        '''Normalizes keys for a definition dict and its contents

        Some definitions have a 'morph' field which is a relative path. Others
        only have a 'name' field, which has no directory part. A few do not
        have a 'name'

        This sets our key to be 'path', and fixes any missed 'name' to be
        the same as 'path' but replacing '/' by '-'

        '''

        exit = (config.get('check-definitions') == 'exit')

        if dn.get('morph'):
            if not os.path.isfile(dn.get('morph')):
                log('DEFINITION', 'WARNING: missing', dn['morph'], exit=exit)
            dn['path'] = self._demorph(dn.pop('morph'))

        if 'path' not in dn:
            if 'name' not in dn:
                log(dn, 'No path, no name?', exit=True)
            if config.get('artifact-version') in range(0, 4):
                dn['path'] = dn['name']
            else:
                dn['path'] = os.path.join(self._demorph(base), dn['name'])
                if os.path.isfile(dn['path'] + '.morph'):
                    # morph file exists, but is not mentioned in stratum
                    # so we ignore it
                    log(dn, 'WARNING: ignoring', dn['path'] + '.morph',
                        exit=exit)
                    dn['path'] += '.default'

        dn['path'] = self._demorph(dn['path'])
        dn.setdefault('name', os.path.basename(dn['path']))

        if dn.get('name') == config['target']:
            config['target'] = dn['path']

        n = self._demorph(os.path.basename(dn['name']))
        p = self._demorph(os.path.basename(dn['path']))
        if os.path.splitext(p)[0] not in n:
            log('MORPHS', 'WARNING: %s wrong name' % dn['path'], dn['name'],
                exit=exit)

        for system in (dn.get('systems', []) + dn.get('subsystems', [])):
            self._fix_keys(system)

    def _insert(self, new_def):
        '''Insert a new definition into the dictionary, return the key.

        Takes a dict representing a single definition.

        If a definition with the same 'path' doesn't exist, just add
        `new_def` to the dictionary.

        If a definition with the same 'path' already exists, extend the
        existing definition with the contents of `new_def` unless it
        and the new definition both contain a 'ref'. If any keys are
        duplicated in the existing definition, output a warning.

        '''

        exit = (config.get('check-definitions') == 'exit')

        dn = self._data.get(new_def['path'])
        if dn:
            if (dn.get('ref') is None or new_def.get('ref') is None):
                for key in new_def:
                    if key is not 'name':
                        dn[key] = new_def[key]

            if dn['name'] != new_def['name']:
                log(new_def, 'WARNING: %s also named as' % new_def['name'],
                    dn['name'], exit=exit)
                dn['name'] = new_def['name']

            for key in new_def:
                if dn.get(key) and new_def[key] and dn[key] != new_def[key]:
                    log(new_def,
                        'WARNING: multiple definitions of %s \n' % key,
                        '%s | %s' % (dn.get(key), new_def[key]), exit=exit)
        else:
            self._data[new_def['path']] = new_def

        return new_def['path']

    def _demorph(self, path):
        if config.get('artifact-version', 0) not in range(0, 4):
            if path.endswith('.morph'):
                path = path.rpartition('.morph')[0]
        return path
