#
# Copyright 2013 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public
# License as published by the Free Software Foundation; either version
# 2 of the License (GPLv2) or (at your option) any later version.
# There is NO WARRANTY for this software, express or implied,
# including the implied warranties of MERCHANTABILITY,
# NON-INFRINGEMENT, or FITNESS FOR A PARTICULAR PURPOSE. You should
# have received a copy of GPLv2 along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.
#

import os
import sys
import httplib

from unittest import TestCase

from mock import patch, Mock

from rhsm.connection import RemoteServerException

sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))


class Repository(object):

    def __init__(self, repo_id, repofile, baseurl):
        self.id = repo_id
        self.repofile = repofile
        self.baseurl = baseurl


class PluginTest(TestCase):

    @staticmethod
    def load_plugin():
        plugin = __import__('katello.agent.katelloplugin', {}, {}, ['katelloplugin'])
        reload(plugin)
        plugin._module = plugin
        plugin_cfg = Mock()
        plugin_cfg.messaging = Mock()
        plugin.plugin = Mock()
        plugin.plugin.scheduler = Mock()
        plugin.plugin.scheduler.pending = Mock(PENDING='/tmp/pending', stream='abc')
        plugin.plugin.cfg = plugin_cfg
        plugin.path_monitor = Mock()
        plugin.registered = True
        return plugin

    def setUp(self):
        self.plugin = PluginTest.load_plugin()


class TestBundle(PluginTest):

    @patch('__builtin__.open')
    def test_bundle(self, fake_open):
        fake_fp = Mock()
        fake_open.return_value = fake_fp

        # test
        certificate = Mock()
        certificate.PATH = '/tmp/path/test'
        certificate.key = 'TEST-KEY'
        certificate.cert = 'TEST-CERT'
        self.plugin.bundle(certificate)

        # validation
        fake_open.assert_called_with(os.path.join(certificate.PATH, 'bundle.pem'), 'w')
        fake_fp.write.assert_any_call(certificate.key)
        fake_fp.write.assert_any_call(certificate.cert)
        fake_fp.close.assert_called_with()


class TestCertificateChanged(PluginTest):

    @patch('katello.agent.katelloplugin.update_settings')
    @patch('katello.agent.katelloplugin.validate_registration')
    def test_registered(self, validate, update_settings):

        # test
        self.plugin.certificate_changed('')

        # validation
        validate.assert_called_with()
        update_settings.assert_called_with()
        self.plugin.plugin.attach.assert_called_with()

    @patch('katello.agent.katelloplugin.update_settings')
    @patch('katello.agent.katelloplugin.validate_registration')
    def test_run_not_registered(self, validate, update_settings):
        self.plugin.registered = False

        # test
        self.plugin.certificate_changed('')

        # validation
        validate.assert_called_with()
        self.assertFalse(update_settings.called)
        self.plugin.plugin.detach.assert_called_with()

    @patch('katello.agent.katelloplugin.sleep')
    @patch('katello.agent.katelloplugin.update_settings')
    @patch('katello.agent.katelloplugin.validate_registration')
    def test_run_validate_failed(self, validate, update_settings, sleep):
        validate.side_effect = [ValueError, None]

        # test
        self.plugin.certificate_changed('')

        # validation
        validate.assert_called_with()
        sleep.assert_called_once_with(60)
        update_settings.assert_called_with()
        self.plugin.plugin.attach.assert_called_with()

class TestUpdateSettings(PluginTest):
    host = 'redhat.com'
    server_ca_cert = '%(ca_cert_dir)skatello-server-ca.pem'

    @patch('katello.agent.katelloplugin.bundle')
    @patch('katello.agent.katelloplugin.Config')
    @patch('katello.agent.katelloplugin.ConsumerIdentity.read')
    def test_call_new(self, fake_read, fake_conf, fake_bundle):
        fake_conf.return_value = {
            'server': {
                'hostname': self.host
            },
            'rhsm': {
                'repo_ca_cert': self.server_ca_cert,
                'ca_cert_dir': self.ca_cert_dir()
            }
        }
        self.call(fake_read, fake_conf, fake_bundle)

    @patch('katello.agent.katelloplugin.bundle')
    @patch('katello.agent.katelloplugin.Config')
    @patch('katello.agent.katelloplugin.ConsumerIdentity.read')
    def test_call_old_config(self, fake_read, fake_conf, fake_bundle):
        fake_conf.return_value = {
            'server': {
                'hostname': self.host,
                'ca_cert_dir': self.ca_cert_dir()
            },
            'rhsm': {
                'repo_ca_cert': self.server_ca_cert,
            }
        }
        self.call(fake_read, fake_conf, fake_bundle)

    def ca_cert_dir(self):
        ca_cert_dir = os.path.join(os.path.dirname(__file__), 'data/ca/')
        if not os.path.exists(ca_cert_dir):
            os.makedirs(ca_cert_dir)
        return ca_cert_dir

    def call(self, fake_read, fake_conf, fake_bundle):
        consumer_id = '1234'
        default_ca_cert = os.path.join(self.ca_cert_dir(), 'katello-default-ca.pem')
        if not os.path.exists(default_ca_cert):
            open(default_ca_cert, 'a').close()

        fake_certificate = Mock()
        fake_certificate.getConsumerId.return_value = consumer_id
        fake_read.return_value = fake_certificate

        # test
        self.plugin.update_settings()

        # validation
        fake_read.assert_called_with()
        fake_bundle.assert_called_with(fake_certificate)
        plugin_cfg = self.plugin.plugin.cfg
        self.assertEqual(plugin_cfg.messaging.cacert, default_ca_cert)
        self.assertEqual(plugin_cfg.messaging.url, 'proton+amqps://%s:5647' % self.host)
        self.assertEqual(plugin_cfg.messaging.uuid, 'pulp.agent.%s' % consumer_id)


class TestInitializer(PluginTest):

    @patch('katello.agent.katelloplugin.path_monitor')
    @patch('katello.agent.katelloplugin.ConsumerIdentity.certpath')
    @patch('katello.agent.katelloplugin.validate_registration')
    def test_init(self, fake_validate, fake_path, fake_pmon):
        self.plugin.registered = False

        # test
        self.plugin.init_plugin()

        # validation
        fake_path.assert_called_with()
        fake_pmon.add.assert_any_call(fake_path(), self.plugin.certificate_changed)
        fake_pmon.start.assert_called_with()
        fake_validate.assert_called_with()

    @patch('katello.agent.katelloplugin.update_settings')
    @patch('katello.agent.katelloplugin.validate_registration')
    def test_registered(self, validate, update_settings):

        # test
        self.plugin.init_plugin()

        # validation
        validate.assert_called_with()
        update_settings.assert_called_with()
        self.assertFalse(self.plugin.plugin.attach.called)

    @patch('katello.agent.katelloplugin.update_settings')
    @patch('katello.agent.katelloplugin.validate_registration')
    def test_run_not_registered(self, validate, update_settings):
        self.plugin.registered = False

        # test
        self.plugin.init_plugin()

        # validation
        validate.assert_called_with()
        self.assertFalse(update_settings.called)
        self.assertFalse(self.plugin.plugin.attach.called)

    @patch('katello.agent.katelloplugin.sleep')
    @patch('katello.agent.katelloplugin.update_settings')
    @patch('katello.agent.katelloplugin.validate_registration')
    def test_run_validate_failed(self, validate, update_settings, sleep):
        validate.side_effect = [ValueError, None]

        # test
        self.plugin.init_plugin()

        # validation
        validate.assert_called_with()
        sleep.assert_called_once_with(60)
        update_settings.assert_called_with()
        self.assertFalse(self.plugin.plugin.attach.called)


class TestConduit(PluginTest):

    @patch('katello.agent.katelloplugin.ConsumerIdentity.read')
    def test_consumer_id(self, fake_read):
        consumer_id = '1234'
        fake_certificate = Mock()
        fake_certificate.getConsumerId.return_value = consumer_id
        fake_read.return_value = fake_certificate

        # test
        conduit = self.plugin.Conduit()

        # validation
        self.assertEqual(conduit.consumer_id, consumer_id)

    @patch('gofer.agent.rmi.Context.current')
    def test_update_progress(self, mock_current):
        mock_context = Mock()
        mock_context.progress = Mock()
        mock_current.return_value = mock_context
        conduit = self.plugin.Conduit()
        report = {'a': 1}

        # test
        conduit.update_progress(report)

        # validation
        # Reporting disabled
        self.assertFalse(mock_context.progress.report.called)

    @patch('gofer.agent.rmi.Context.current')
    def test_cancelled(self, mock_current):
        mock_context = Mock()
        mock_context.cancelled = Mock(return_value=True)
        mock_current.return_value = mock_context
        conduit = self.plugin.Conduit()

        # test
        cancelled = conduit.cancelled()

        # validation
        self.assertTrue(cancelled)
        self.assertTrue(mock_context.cancelled.called)

    @patch('gofer.agent.rmi.Context.current')
    def test_cancelled(self, mock_current):
        mock_context = Mock()
        mock_context.cancelled = Mock(return_value=False)
        mock_current.return_value = mock_context
        conduit = self.plugin.Conduit()

        # test
        cancelled = conduit.cancelled()

        # validation
        self.assertFalse(cancelled)
        self.assertTrue(mock_context.cancelled.called)

class TestYum(PluginTest):

    @patch('katello.agent.katelloplugin.Logger.manager')
    def test_clean_loggers(self, fake_manager):
        lg1 = Mock(name='lg1')
        lg1.handlers = [Mock(), Mock()]
        lg2 = Mock(name='lg2')
        lg2.handlers = [Mock(), Mock()]

        fake_manager.loggerDict = {
            'xyz.mod': lg1,
            'yum.mod': lg2
        }

        # test
        yb = self.plugin.Yum()
        yb.cleanLoggers()

        # validation
        self.assertFalse(lg1.removeHandler.called)
        self.assertEqual(lg2.removeHandler.call_count, len(lg2.handlers))
        for h in lg2.handlers:
            lg2.removeHandler.assert_any_call(h)

    @patch('katello.agent.katelloplugin.Yum.cleanLoggers')
    @patch('katello.agent.katelloplugin.YumBase.close')
    def test_close(self, fake_close, fake_clean):
        # test

        yb = self.plugin.Yum()
        yb.close()

        # validation
        fake_close.assert_called_with(yb)
        fake_clean.assert_called_with()


class TestUEP(PluginTest):

    @patch('katello.agent.katelloplugin.UEPConnection.__init__')
    @patch('katello.agent.katelloplugin.ConsumerIdentity.certpath')
    @patch('katello.agent.katelloplugin.ConsumerIdentity.keypath')
    def test_construction(self, fake_keypath, fake_certpath, fake_conn_init):
        key_path = '/tmp/keypath'
        cert_path = '/tmp/crtpath'
        fake_keypath.return_value = key_path
        fake_certpath.return_value = cert_path

        # test
        uep = self.plugin.UEP()

        # validation
        fake_conn_init.assert_called_with(uep, key_file=key_path, cert_file=cert_path)

class TestValidateRegistration(PluginTest):

    @patch('katello.agent.katelloplugin.UEP.getConsumer')
    @patch('katello.agent.katelloplugin.ConsumerIdentity.read')
    @patch('katello.agent.katelloplugin.ConsumerIdentity.existsAndValid')
    def test_validate_registration(self, valid, read, get_consumer):
        consumer_id = '1234'
        valid.return_value = True
        read.return_value.getConsumerId.return_value = consumer_id

        # test
        self.plugin.validate_registration()

        # validation
        get_consumer.assert_called_with(consumer_id)
        self.assertTrue(self.plugin.registered)

    @patch('katello.agent.katelloplugin.UEP.getConsumer')
    @patch('katello.agent.katelloplugin.ConsumerIdentity.existsAndValid')
    def test_validate_registration_no_certificate(self, valid, get_consumer):
        valid.return_value = False

        # test
        self.plugin.validate_registration()

        # validation
        self.assertFalse(get_consumer.called)
        self.assertFalse(self.plugin.registered)

    @patch('katello.agent.katelloplugin.UEP.getConsumer')
    @patch('katello.agent.katelloplugin.ConsumerIdentity.read')
    @patch('katello.agent.katelloplugin.ConsumerIdentity.existsAndValid')
    def test_validate_registration_not_confirmed(self, valid, read, get_consumer):
        consumer_id = '1234'
        valid.return_value = True
        read.return_value.getConsumerId.return_value = consumer_id
        get_consumer.side_effect = RemoteServerException(httplib.NOT_FOUND)

        # test
        self.plugin.validate_registration()

        # validation
        get_consumer.assert_called_with(consumer_id)
        self.assertFalse(self.plugin.registered)

    @patch('katello.agent.katelloplugin.UEP.getConsumer')
    @patch('katello.agent.katelloplugin.ConsumerIdentity.read')
    @patch('katello.agent.katelloplugin.ConsumerIdentity.existsAndValid')
    def test_validate_registration_failed(self, valid, read, get_consumer):
        consumer_id = '1234'
        valid.return_value = True
        read.return_value.getConsumerId.return_value = consumer_id
        get_consumer.side_effect = RemoteServerException(httplib.BAD_REQUEST)

        # test
        self.assertRaises(RemoteServerException, self.plugin.validate_registration)

        # validation
        get_consumer.assert_called_with(consumer_id)
        self.assertFalse(self.plugin.registered)

    @patch('katello.agent.katelloplugin.UEP.getConsumer')
    @patch('katello.agent.katelloplugin.ConsumerIdentity.read')
    @patch('katello.agent.katelloplugin.ConsumerIdentity.existsAndValid')
    def test_validate_registration_exception(self, valid, read, get_consumer):
        consumer_id = '1234'
        valid.return_value = True
        read.return_value.getConsumerId.return_value = consumer_id
        get_consumer.side_effect = ValueError

        # test
        self.assertRaises(ValueError, self.plugin.validate_registration)

        # validation
        get_consumer.assert_called_with(consumer_id)
        self.assertFalse(self.plugin.registered)

class TestConsumer(PluginTest):

    def test_unregister(self):
        consumer = self.plugin.Consumer()
        consumer.unregister()

class TestContent(PluginTest):

    @patch('katello.agent.katelloplugin.Conduit')
    @patch('katello.agent.katelloplugin.Dispatcher')
    def test_install(self, mock_dispatcher, mock_conduit):
        _report = Mock()
        _report.dict = Mock(return_value={'report': 883938})
        mock_dispatcher().install.return_value = _report

        # test
        units = [{'A': 1}]
        options = {'B': 2}
        content = self.plugin.Content()
        report = content.install(units, options)

        # validation
        mock_dispatcher().install.assert_called_with(mock_conduit(), units, options)
        self.assertEqual(report, _report.dict())

    @patch('katello.agent.katelloplugin.Conduit')
    @patch('katello.agent.katelloplugin.Dispatcher')
    def test_update(self, mock_dispatcher, mock_conduit):
        _report = Mock()
        _report.dict = Mock(return_value={'report': 883938})
        mock_dispatcher().update.return_value = _report

        # test
        units = [{'A': 10}]
        options = {'B': 20}
        content = self.plugin.Content()
        report = content.update(units, options)

        # validation
        mock_dispatcher().update.assert_called_with(mock_conduit(), units, options)
        self.assertEqual(report, _report.dict())

    @patch('katello.agent.katelloplugin.Conduit')
    @patch('katello.agent.katelloplugin.Dispatcher')
    def test_uninstall(self, mock_dispatcher, mock_conduit):
        _report = Mock()
        _report.dict = Mock(return_value={'report': 883938})
        mock_dispatcher().uninstall.return_value = _report

        # test
        units = [{'A': 100}]
        options = {'B': 200}
        content = self.plugin.Content()
        report = content.uninstall(units, options)

        # validation
        mock_dispatcher().uninstall.assert_called_with(mock_conduit(), units, options)
        self.assertEqual(report, _report.dict())


class TestAgentRestart(PluginTest):

    @patch('os.listdir')
    def test_busy(self, listdir):
        listdir.return_value = [
            'file0',
            'file1'
        ]

        # test
        restart = self.plugin.AgentRestart()
        busy = restart.is_busy()

        # validation
        listdir.assert_called_once_with('/tmp/pending/abc')
        self.assertTrue(busy)

    @patch('os.listdir')
    def test_not_busy(self, listdir):
        listdir.return_value = []

        # test
        restart = self.plugin.AgentRestart()
        busy = restart.is_busy()

        # validation
        listdir.assert_called_once_with('/tmp/pending/abc')
        self.assertFalse(busy)

    @patch('os.unlink')
    @patch('katello.agent.katelloplugin.Popen')
    def test_restart(self, popen, unlink):
        popen.return_value.wait.return_value = 123

        # test
        restart = self.plugin.AgentRestart()
        exit_val = restart.restart()

        # validation
        unlink.assert_called_once_with(self.plugin.AgentRestart.RESTART_FILE)
        popen.assert_called_once_with(self.plugin.AgentRestart.COMMAND, shell=True)
        popen.return_value.wait.assert_called_once_with()
        self.assertEqual(exit_val, popen.return_value.wait.return_value)

    @patch('os.path.exists')
    def test_apply_not_requested(self, exists):
        exists.return_value = False

        # test
        restart = self.plugin.AgentRestart()
        restart.restart = Mock()
        restart.apply()

        # validation
        exists.assert_called_once_with(self.plugin.AgentRestart.RESTART_FILE)
        self.assertFalse(restart.restart.called)

    @patch('os.path.exists')
    def test_apply_request_and_busy(self, exists):
        exists.return_value = True

        # test
        restart = self.plugin.AgentRestart()
        restart.is_busy = Mock(return_value=True)
        restart.restart = Mock()
        restart.apply()

        # validation
        exists.assert_called_once_with(self.plugin.AgentRestart.RESTART_FILE)
        restart.is_busy.assert_called_once_with()
        self.assertFalse(restart.restart.called)

    @patch('os.path.exists')
    def test_apply_restarted(self, exists):
        exists.return_value = True

        # test
        restart = self.plugin.AgentRestart()
        restart.is_busy = Mock(return_value=False)
        restart.restart = Mock(return_value=0)
        restart.apply()

        # validation
        exists.assert_called_once_with(self.plugin.AgentRestart.RESTART_FILE)
        restart.is_busy.assert_called_once_with()
        restart.restart.assert_called_once_with()
