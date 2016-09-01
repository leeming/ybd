# Copyright (C) 2011-2016  Codethink Limited
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

import sys
sys.path.insert(0, "/home/andrewleeming/baserock/sandboxlib")

import sandboxlib
import contextlib
import os
import pipes
import shutil
import stat
import tempfile
from subprocess import call, PIPE

import app
import cache
import utils
from repos import get_repo_url

from logger import logger

# This must be set to a sandboxlib backend before the run_sandboxed() function
# can be used.
executor = None


@contextlib.contextmanager
def setup(dn):
    tempfile.tempdir = app.config['tmp']
    dn['sandbox'] = tempfile.mkdtemp()
    os.environ['TMPDIR'] = app.config['tmp']
    app.config['sandboxes'] += [dn['sandbox']]
    dn['checkout'] = os.path.join(dn['sandbox'], dn['name'] + '.build')
    dn['install'] = os.path.join(dn['sandbox'], dn['name'] + '.inst')
    dn['baserockdir'] = os.path.join(dn['install'], 'baserock')
    dn['tmp'] = os.path.join(dn['sandbox'], 'tmp')
    for directory in ['checkout', 'install', 'tmp', 'baserockdir']:
        os.makedirs(dn[directory])
    dn['log'] = os.path.join(app.config['artifacts'],
                             dn['cache'] + '.build-log')
    if app.config.get('instances'):
        dn['log'] += '.' + str(app.config.get('fork', 0))
    assembly_dir = dn['sandbox']
    for directory in ['dev', 'tmp']:
        call(['mkdir', '-p', os.path.join(assembly_dir, directory)])

    try:
        yield
    except app.RetryException as e:
        raise e
    except:
        import traceback
        app.log(dn, 'ERROR: surprise exception in sandbox', '')
        traceback.print_exc()
        app.log(dn, 'Sandbox debris is at', dn['sandbox'], exit=True)
    finally:
        pass

    app.log(dn, "Removing sandbox dir", dn['sandbox'], verbose=True)
    app.remove_dir(dn['sandbox'])


def install(dn, component):
    # populate dn['sandbox'] with the artifact files from component
    if os.path.exists(os.path.join(dn['sandbox'], 'baserock',
                                   component['name'] + '.meta')):
        return
    app.log(dn, 'Sandbox: installing %s' % component['cache'], verbose=True)
    if cache.get_cache(component) is False:
        app.log(dn, 'Unable to get cache for', component['name'], exit=True)
    unpackdir = cache.get_cache(component) + '.unpacked'
    if dn.get('kind') is 'system':
        utils.copy_all_files(unpackdir, dn['sandbox'])
    else:
        utils.hardlink_all_files(unpackdir, dn['sandbox'])


def ldconfig(dn):
    conf = os.path.join(dn['sandbox'], 'etc', 'ld.so.conf')
    if os.path.exists(conf):
        path = os.environ['PATH']
        os.environ['PATH'] = '%s:/sbin:/usr/sbin:/usr/local/sbin' % path
        cmd_list = ['ldconfig', '-r', dn['sandbox']]
        run_logged(dn, cmd_list)
        os.environ['PATH'] = path
    else:
        app.log(dn, 'No %s, not running ldconfig' % conf)


def argv_to_string(argv):
    return ' '.join(map(pipes.quote, argv))


def run_sandboxed(dn, command, env=None, allow_parallel=False):
    global executor

    app.log(dn, 'Running command:\n%s' % command)
    with open(dn['log'], "a") as logfile:
        logfile.write("# # %s\n" % command)

    mounts = ccache_mounts(dn, ccache_target=env['CCACHE_DIR'])

    if dn.get('build-mode') == 'bootstrap':
        # bootstrap mode: builds have some access to the host system, so they
        # can use the compilers etc.
        tmpdir = app.config.get("TMPDIR", "/tmp")

        writable_paths = [dn['checkout'], dn['install'], tmpdir, ]

        config = dict(
            cwd=dn['checkout'],
            filesystem_root='/',
            filesystem_writable_paths=writable_paths,
            mounts='isolated',
            extra_mounts=[],
            network='isolated',
        )
    else:
        # normal mode: builds run in a chroot with only their dependencies
        # present.

        mounts.extend([('tmpfs', '/dev/shm', 'tmpfs'),
                       ('proc', '/proc', 'proc'), ])

        if dn.get('kind') == 'system':
            writable_paths = 'all'
        else:
            writable_paths = [dn['name'] + '.build', dn['name'] + '.inst',
                              '/dev', '/proc', '/tmp', ]

        config = dict(
            cwd=dn['name'] + '.build',
            filesystem_root=dn['sandbox'],
            filesystem_writable_paths=writable_paths,
            mounts='isolated',
            extra_mounts=mounts,
            network='isolated',
        )

    # Awful hack to ensure string-escape is loaded:
    #
    # this ensures that when propagating an exception back from
    # the child process in a chroot, the required string-escape
    # python module is already in memory and no attempt to
    # lazy load it in the chroot is made.
    unused = "Some Text".encode('string-escape')

    argv = ['sh', '-c', '-e', command]

    cur_makeflags = env.get("MAKEFLAGS")

    # Adjust config for what the backend is capable of. The user will be warned
    # about any changes made.
    config = executor.degrade_config_for_capabilities(config, warn=False)

    try:
        if not allow_parallel:
            env.pop("MAKEFLAGS", None)

        app.log_env(dn['log'], env, argv_to_string(argv))

        with open(dn['log'], "a") as logfile:
            exit_code = 99
            try:
                exit_code = executor.run_sandbox_with_redirection(
                    argv, stdout=logfile, stderr=sandboxlib.STDOUT,
                    env=env, **config)
            except:
                import traceback
                traceback.print_exc()
                app.log('SANDBOX', 'ERROR: in run_sandbox_with_redirection',
                        exit_code)

        if exit_code != 0:
            app.log(dn, 'ERROR: command failed in directory %s:\n\n' %
                    os.getcwd(), argv_to_string(argv))
            call(['tail', '-n', '200', dn['log']])
            app.log(dn, 'ERROR: log file is at', dn['log'])
            app.log(dn, 'Sandbox debris is at', dn['sandbox'], exit=True)
    finally:
        if cur_makeflags is not None:
            env['MAKEFLAGS'] = cur_makeflags


def run_logged(dn, cmd_list):
    app.log_env(dn['log'], os.environ, argv_to_string(cmd_list))
    with open(dn['log'], "a") as logfile:
        if call(cmd_list, stdin=PIPE, stdout=logfile, stderr=logfile):
            app.log(dn, 'ERROR: command failed in directory %s:\n\n' %
                    os.getcwd(), argv_to_string(cmd_list))
            call(['tail', '-n', '200', dn['log']])
            app.log(dn, 'Log file is at', dn['log'], exit=True)


def run_extension(dn, deployment, step, method):
    app.log(dn, 'Running %s extension:' % step, method)
    extensions = utils.find_extensions()
    tempfile.tempdir = app.config['tmp']
    cmd_tmp = tempfile.NamedTemporaryFile(delete=False)
    cmd_bin = extensions[step][method]

    envlist = ['UPGRADE=yes'] if method == 'ssh-rsync' else ['UPGRADE=no']

    if 'PYTHONPATH' in os.environ:
        envlist.append('PYTHONPATH=%s:%s' % (os.environ['PYTHONPATH'],
                                             app.config['extsdir']))
    else:
        envlist.append('PYTHONPATH=%s' % app.config['extsdir'])

    for key, value in deployment.iteritems():
        if key.isupper():
            envlist.append("%s=%s" % (key, value))

    command = ["env"] + envlist + [cmd_tmp.name]

    if step in ('write', 'configure'):
        command.append(dn['sandbox'])

    if step in ('write', 'check'):
        command.append(deployment.get('location') or
                       deployment.get('upgrade-location'))

    with app.chdir(app.config['defdir']):
        try:
            with open(cmd_bin, "r") as infh:
                shutil.copyfileobj(infh, cmd_tmp)
            cmd_tmp.close()
            os.chmod(cmd_tmp.name, 0o700)

            logger.debug("command:{}".format(command))
            if call(command):
                logger.error("Extension '{}':{} failed".format(step,cmd_bin))
                app.log(dn, 'ERROR: %s extension failed:' % step, cmd_bin)
                raise SystemExit
        finally:
            os.remove(cmd_tmp.name)
    return


def ccache_mounts(dn, ccache_target):
    if app.config['no-ccache'] or 'repo' not in dn:
        mounts = []
    else:
        name = os.path.basename(get_repo_url(dn['repo']))
        if name.endswith('.git'):
            name = name[:-4]
        ccache_dir = os.path.join(app.config['ccache_dir'], name)
        if not os.path.isdir(ccache_dir):
            os.mkdir(ccache_dir)

        mounts = [(ccache_dir, ccache_target, None, 'bind')]
    return mounts


def env_vars_for_build(dn):
    env = {}
    extra_path = []

    if app.config['no-ccache']:
        ccache_path = []
    else:
        ccache_path = ['/usr/lib/ccache']
        env['CCACHE_DIR'] = '/tmp/ccache'
        env['CCACHE_EXTRAFILES'] = ':'.join(
            f for f in ('/baserock/binutils.meta',
                        '/baserock/eglibc.meta',
                        '/baserock/gcc.meta') if os.path.exists(f))
        if not app.config.get('no-distcc'):
            env['CCACHE_PREFIX'] = 'distcc'

    prefixes = []

    for name in dn.get('build-depends', []):
        dependency = app.defs.get(name)
        prefixes.append(dependency.get('prefix', '/usr'))
    prefixes = set(prefixes)
    for prefix in prefixes:
        if prefix:
            bin_path = os.path.join(prefix, 'bin')
            extra_path += [bin_path]

    if dn.get('build-mode') == 'bootstrap':
        rel_path = extra_path + ccache_path
        full_path = [os.path.normpath(dn['sandbox'] + p) for p in rel_path]
        path = full_path + app.config['base-path']
        env['DESTDIR'] = dn.get('install')
    else:
        path = extra_path + ccache_path + app.config['base-path']
        env['DESTDIR'] = os.path.join('/', os.path.basename(dn.get('install')))

    env['PATH'] = ':'.join(path)
    env['PREFIX'] = dn.get('prefix') or '/usr'
    env['MAKEFLAGS'] = '-j%s' % (dn.get('max-jobs') or app.config['max-jobs'])
    env['TERM'] = 'dumb'
    env['SHELL'] = '/bin/sh'
    env['USER'] = env['USERNAME'] = env['LOGNAME'] = 'tomjon'
    env['LC_ALL'] = 'C'
    env['HOME'] = '/tmp'
    env['TZ'] = 'UTC'

    arch = app.config['arch']
    cpu = app.config['cpu']
    abi = ''
    if arch.startswith(('armv7', 'armv5')):
        abi = 'eabi'
    elif arch.startswith('mips64'):
        abi = 'abi64'
    env['TARGET'] = cpu + '-baserock-linux-gnu' + abi
    env['TARGET_STAGE1'] = cpu + '-bootstrap-linux-gnu' + abi
    env['MORPH_ARCH'] = arch
    env['DEFINITIONS_REF'] = app.config['def-version']
    env['PROGRAM_REF'] = app.config['my-version']
    if dn.get('SOURCE_DATE_EPOCH'):
        env['SOURCE_DATE_EPOCH'] = dn['SOURCE_DATE_EPOCH']

    return env


def create_devices(dn):
    perms_mask = stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO
    for device in dn['devices']:
        destfile = os.path.join(dn['install'], './' + device['filename'])
        mode = int(device['permissions'], 8) & perms_mask
        if device['type'] == 'c':
            mode = mode | stat.S_IFCHR
        elif device['type'] == 'b':
            mode = mode | stat.S_IFBLK
        else:
            raise IOError('Cannot create device node %s,'
                          'unrecognized device type "%s"'
                          % (destfile, device['type']))
        app.log(dn, "Creating device node", destfile)
        os.mknod(destfile, mode, os.makedev(device['major'], device['minor']))
        os.chown(destfile, device['uid'], device['gid'])


def list_files(component):
    app.log(component, 'Sandbox %s contains\n' % component['sandbox'],
            os.listdir(component['sandbox']))
    try:
        files = os.listdir(os.path.join(component['sandbox'], 'baserock'))
        app.log(component,
                'Baserock directory contains %s items\n' % len(files),
                sorted(files))
    except:
        app.log(component, 'No baserock directory in', component['sandbox'])
