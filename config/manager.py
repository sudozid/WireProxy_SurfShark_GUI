"""Configuration manager for WireGuard and wireproxy configurations."""

from typing import Dict, Any


class ConfigurationManager:
    """Handles WireGuard and wireproxy configuration generation"""

    @staticmethod
    def generate_wireguard_config(server: Dict[str, Any], private_key: str) -> str:
        """Generate WireGuard configuration"""
        server_pub_key = server['pubKey']
        server_host = server['connectionName']
        endpoint = f"{server_host}:51820"
        server_location = f"{server['country']} - {server['location']}"

        config = f"""# Surfshark WireGuard Config for {server_location}
[Interface]
PrivateKey = {private_key}
Address = 10.14.0.2/16
DNS = 162.252.172.57, 149.154.159.92

[Peer]
PublicKey = {server_pub_key}
Endpoint = {endpoint}
AllowedIPs = 0.0.0.0/0, ::/0
PersistentKeepalive = 25
"""
        return config.strip()

    @staticmethod
    def generate_wireproxy_config(wg_config: str, socks_port: int) -> str:
        """Generate wireproxy configuration"""
        wireproxy_config = f"""{wg_config}

[Socks5]
BindAddress = 127.0.0.1:{socks_port}
"""
        return wireproxy_config