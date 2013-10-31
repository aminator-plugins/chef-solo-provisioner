# -*- coding: utf-8 -*-

#
#
#  Copyright 2013 Riot Games
#
#     Licensed under the Apache License, Version 2.0 (the "License");
#     you may not use this file except in compliance with the License.
#     You may obtain a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.
#
#

"""
aminatorplugins.provisioner.chef
================================
basic chef solo provisioner
"""
import logging
import os
import shutil
import re
from collections import namedtuple

from aminator.plugins.provisioner.base import BaseProvisionerPlugin
from aminator.util.linux import command
from aminator.config import conf_action

__all__ = ('ChefProvisionerPlugin',)
log = logging.getLogger(__name__)
CommandResult = namedtuple('CommandResult', 'success result')
CommandOutput = namedtuple('CommandOutput', 'std_out std_err')


class ChefProvisionerPlugin(BaseProvisionerPlugin):
    """
    ChefProvisionerPlugin takes the majority of its behavior from BaseLinuxProvisionerPlugin
    See BaseLinuxProvisionerPlugin for details
    """
    _name = 'chef'
    _default_chef_version = '10.26.0'
    _default_omnibus_url  = 'https://www.opscode.com/chef/install.sh'
    _default_fetch_method = 'auto'

    # class constants
    def add_plugin_args(self):
        context = self._config.context
        chef_config = self._parser.add_argument_group(title='Chef Solo Options',
                                                      description='Options for the chef solo provisioner')

        chef_config.add_argument('-R', '--runlist', dest='runlist', help='Chef run list items. If not set, run list should be specified in the node JSON file',
                                 action=conf_action(self._config.plugins[self.full_name]))
        chef_config.add_argument('--payload-url', dest='payload_url', help='Location to fetch the payload from (required)',
                                 action=conf_action(self._config.plugins[self.full_name]))
        chef_config.add_argument('--payload-version', dest='payload_version', help='Payload version (default: 0.0.1)',
                                 action=conf_action(self._config.plugins[self.full_name]))
        chef_config.add_argument('--payload-release', dest='payload_release', help='Payload release (default: 0)',
                                 action=conf_action(self._config.plugins[self.full_name]))
        chef_config.add_argument('--chef-version', dest='chef_version', help='Version of chef to install (default: %s)' % self._default_chef_version,
                                 action=conf_action(self._config.plugins[self.full_name]))
        chef_config.add_argument('--omnibus-url', dest='omnibus_url', help='Path to the omnibus install script (default: %s)' % self._default_omnibus_url,
                                 action=conf_action(self._config.plugins[self.full_name]))
        chef_config.add_argument('--fetch-method', dest='fetch_method', help='Method to download payload data. (default: %s)' % self._default_fetch_method,
                                 action=conf_action(self._config.plugins[self.full_name]), choices=['auto', 'http', 'git', 'local'])
        chef_config.add_argument('-p', '--git-ssh-pubkey', dest='ssh_pubkey', help='Public key for Git SSH authentication',
                                 action=conf_action(self._config.plugins[self.full_name]))
        chef_config.add_argument('-P', '--git-ssh-privkey', dest='ssh_privkey', help='Private key for Git SSH authentication',
                                 action=conf_action(self._config.plugins[self.full_name]))
        chef_config.add_argument('--git-ssh-passphrase', dest='ssh_passphrase', help='Keypair passphrase for Git SSH authentication',
                                 action=conf_action(self._config.plugins[self.full_name]))

    def get_config_value(self, name, default):
        config = self._config.plugins[self.full_name]

        if config.get(name):
            return config.get(name)

        self._config.plugins[self.full_name].__setattr__(name, default)
        return default

    def _install_payload_and_chef(self):
        """
        Fetch the latest version of cookbooks and JSON node info
        """
        context = self._config.context
        config = self._config.plugins[self.full_name]

        # These are required args, so no default values
        runlist = config.get('runlist')

        # Fetch config values if provided, otherwise set them to their default values
        fetch_mode      = self.get_config_value('fetch_mode', self._default_fetch_mode)
        pubkey          = self.get_config_value('ssh_pubkey', os.path.expanduser('~/.ssh/id_rsa.pub'))
        privkey         = self.get_config_value('ssh_privkey', os.path.expanduser('~/.ssh/id_rsa'))
        passphrase      = self.get_config_value('ssh_passphrase', None)

        chef_version = self.get_config_value('chef_version', self._default_chef_version)
        omnibus_url = self.get_config_value('omnibus_url', self._default_omnibus_url)

        if os.path.exists("/opt/chef/bin/chef-solo"):
            log.debug('Omnibus chef is already installed, skipping install')
        else:
            log.debug('Installing omnibus chef-solo')
            result = install_omnibus_chef(chef_version, omnibus_url)
            if not result.success:
                log.critical('Failed to install chef')
                return None

        if fetch_mode == 'auto':
            fetch_mode = detect_fetch_mode(payload_url)

        if not fetch_mode:
            log.critical(("Unable to automatically determine the protocol to fetch payload from path."
                          "Please manually select a fetch mode"))
            return None

        log.debug('Downloading payload from %s using %s' % (payload_url, fetch_mode))
        if fetch_mode == 'git':
            repo = git_clone(payload_url, pubkey, privkey, passphrase)
            try:
                map(lambda fn: shutil.copy(fn, '/tmp'), glob(os.path.join(repo, '*')))
            except:
                return CommandResult(False, CommandOutput('', 'Failed to copy files from git repo to /tmp'))

            payload_result = berks_fetch_cookbooks()

        elif fetch_mode == 'http':
            payload_result = fetch_chef_payload_http(payload_url)

        elif fetch_mode == 'local':
            payload_result = fetch_local_file(payload_url)

        else:
            log.critical('Unsupported fetch mode supplied to chef provisioner: %s' % fetch_mode)

        return payload_result

    def _provision_package(self):
        if not self._install_payload_and_chef():
            return False

        context = self._config.context
        config = self._config.plugins[self.full_name]

        log.debug('Running chef-solo for run list items: %s' % config.get('runlist'))
        return chef_solo(config.get('runlist'))

    def _store_package_metadata(self):
        context = self._config.context
        config = self._config.plugins[self.full_name]

        context.package.attributes = {'name': context.package.arg, 'version': config.get('payload_version'),
                                      'release': config.get('payload_release')}

    def _pre_chroot_block(self):
        """
        Overrides _pre_chroot_block in BaseProvisionerPlugin
        Known Bug: default provision command in superclass does not abort based on this function's return value
        """
        context = self._config.context
        config = self._config.plugins[self.full_name]
        payload_url = config.get('payload_url')

        if not payload_url:
            log.critical('Missing required argument for chef provisioner: --payload-url')
            return False

        result = fetch_chef_payload(payload_url, self._distro._mountpoint)
        if not result.success:
            log.critical('Failed to install payload: {0.std_err}'.format(result.result))
            return False

        return True


@command()
def curl_download(src, dst):
    return 'curl {0} -o {1}'.format(src, dst)

@command()
def install_omnibus_chef(chef_version, omnibus_url):
    curl_download(omnibus_url, '/tmp/install-chef.sh')
    return 'bash /tmp/install-chef.sh -v {0}'.format(chef_version)

@command()
def chef_solo(runlist):
    # If run list is not specific, dont override it on the command line
    # Known Bug: even if chef solo fails, this command is successful
    if runlist:
        return 'chef-solo -j /tmp/node.json -c /tmp/solo.rb -o {0}'.format(runlist)
    else:
        return 'chef-solo -j /tmp/node.json -c /tmp/solo.rb'

@command()
def fetch_chef_payload_http(payload_url):
    curl_download(payload_url, '/tmp/chef_payload.tar.gz')

    return 'tar -C /tmp -xf /tmp/chef_payload.tar.gz'.format(payload_url)

@command()
def berks_fetch_cookbooks():
    return 'berks install --path /tmp/cookbooks -b /tmp/Berksfile'

@command()
def fetch_local_file(payload_url):
    log.debug('Copying payload from %s to %s' % (payload_url, dst + '/tmp/chef_payload.tar.gz'))
    shutil.copy(payload_url, '/tmp/chef_payload.tar.gz')

    return 'tar -C {0}/tmp -xf /tmp/chef_payload.tar.gz'.format(payload_url)

def git_clone(repo, dst=None):
    try:
        import pygit2 as git
    except ImportError as e:
        raise Exception("Failed to load the git module.\nPlease install pygit2 from http://www.pygit2.org/")

    if not dst:
        dst = tempfile.mkdtemp()

    try:
        repo = git.clone_repository(remote, dst)
        return repo.path.replace('/.git/', '')
    except Exception as e:
        raise Exception("Failed to clone repo: %s" % e.message)

def detect_fetch_mode(path):
    lpath = path.lower()
    if lpath.startswith('http'):
        return 'http'
    elif lpath.startswith('git://') or lpath.startswith('ssh://'):
        return 'git'
    else:
        if os.path.exists(path):
            return 'local'
        else:
            return None
