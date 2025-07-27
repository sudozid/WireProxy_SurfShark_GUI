import unittest
from unittest.mock import patch, MagicMock
import os
import sys

# Add the parent directory to the path so that we can import the main module
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class TestMain(unittest.TestCase):
    def setUp(self):
        self.servers = [
            {"country": "USA", "location": "New York", "load": 10},
            {"country": "USA", "location": "Los Angeles", "load": 20},
            {"country": "UK", "location": "London", "load": 5},
        ]
        self.server = {"pubKey": "test_pub_key", "connectionName": "test_connection_name", "country": "USA", "location": "New York"}
        self.private_key = "test_private_key"
        self.port = 1080

    def test_process_servers(self):
        with patch.dict(sys.modules, {'pystray': MagicMock(), 'tkinter': MagicMock(), 'main.webbrowser': MagicMock()}):
            from main import ServerManager
            expected_options = ["UK", "USA", "USA - Los Angeles", "USA - New York"]
            self.assertEqual(ServerManager.process_servers(self.servers), expected_options)

    def test_get_servers_by_selection_country(self):
        with patch.dict(sys.modules, {'pystray': MagicMock(), 'tkinter': MagicMock(), 'main.webbrowser': MagicMock()}):
            from main import ServerManager
            self.assertEqual(len(ServerManager.get_servers_by_selection(self.servers, "USA")), 2)
            self.assertEqual(len(ServerManager.get_servers_by_selection(self.servers, "UK")), 1)

    def test_get_servers_by_selection_city(self):
        with patch.dict(sys.modules, {'pystray': MagicMock(), 'tkinter': MagicMock(), 'main.webbrowser': MagicMock()}):
            from main import ServerManager
            self.assertEqual(len(ServerManager.get_servers_by_selection(self.servers, "USA - New York")), 1)
            self.assertEqual(len(ServerManager.get_servers_by_selection(self.servers, "USA - Los Angeles")), 1)

    def test_select_best_server(self):
        with patch.dict(sys.modules, {'pystray': MagicMock(), 'tkinter': MagicMock(), 'main.webbrowser': MagicMock()}):
            from main import ServerManager
            self.assertEqual(ServerManager.select_best_server(self.servers)["location"], "London")

    def test_generate_wireguard_config(self):
        with patch.dict(sys.modules, {'pystray': MagicMock(), 'tkinter': MagicMock(), 'main.webbrowser': MagicMock()}):
            from main import ConfigurationManager
            config = ConfigurationManager.generate_wireguard_config(self.server, self.private_key)
            self.assertIn("PrivateKey = test_private_key", config)
            self.assertIn("PublicKey = test_pub_key", config)
            self.assertIn("Endpoint = test_connection_name:51820", config)

    def test_generate_wireproxy_config(self):
        with patch.dict(sys.modules, {'pystray': MagicMock(), 'tkinter': MagicMock(), 'main.webbrowser': MagicMock()}):
            from main import ConfigurationManager
            wg_config = ConfigurationManager.generate_wireguard_config(self.server, self.private_key)
            wireproxy_config = ConfigurationManager.generate_wireproxy_config(wg_config, self.port)
            self.assertIn("[Socks5]", wireproxy_config)
            self.assertIn("BindAddress = 127.0.0.1:1080", wireproxy_config)

    @patch("shutil.which")
    def test_find_wireproxy_executable(self, mock_which):
        with patch.dict(sys.modules, {'pystray': MagicMock(), 'tkinter': MagicMock(), 'main.webbrowser': MagicMock()}):
            from main import ProcessManager
            mock_which.return_value = "/usr/local/bin/wireproxy"
            self.assertEqual(ProcessManager.find_wireproxy_executable(), "/usr/local/bin/wireproxy")
            mock_which.return_value = None
            self.assertIsNone(ProcessManager.find_wireproxy_executable())


if __name__ == "__main__":
    unittest.main(argv=sys.argv + ['-v'])
