"""Network manager for handling API calls and server data."""

import json
import time
import logging
import requests
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class NetworkManager:
    """Handles all network operations with proper error handling and retries"""

    @staticmethod
    def test_connectivity(api_endpoint: str, timeout: int = 5) -> bool:
        """Test network connectivity with timeout"""
        try:
            logger.debug("Testing network connectivity...")
            # Add more robust validation
            response = requests.get(api_endpoint, timeout=timeout, verify=True)
            if response.status_code == 200:
                # Validate JSON structure
                try:
                    data = response.json()
                    if isinstance(data, list) and len(data) > 0:
                        # Basic validation that it looks like server data
                        if 'country' in data[0] and 'location' in data[0]:
                            logger.info("Network connectivity test passed")
                            return True
                except (json.JSONDecodeError, KeyError, IndexError):
                    logger.warning("API returned invalid JSON structure")
                    return False
            else:
                logger.warning(f"Network test failed with status code: {response.status_code}")
                return False
        except requests.exceptions.SSLError as e:
            logger.error(f"SSL verification failed: {str(e)}")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Network connectivity test failed: {str(e)}")
            return False

    @staticmethod
    def fetch_servers_with_retry(api_endpoint: str, max_retries: int = 3, timeout: int = 10) -> Optional[
        List[Dict[str, Any]]]:
        """Fetch servers with retry logic and session reuse"""

        for attempt in range(max_retries):
            try:
                logger.debug(f"Fetching servers (attempt {attempt + 1}/{max_retries})")

                if not NetworkManager.test_connectivity(api_endpoint):
                    logger.error("Network connectivity test failed")
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)  # Exponential backoff
                        continue
                    return None

                with requests.Session() as session:
                    session.timeout = timeout

                    start_time = time.time()
                    response = session.get(api_endpoint, timeout=timeout, verify=True)
                    end_time = time.time()

                    logger.debug(f"API request completed in {end_time - start_time:.2f} seconds")
                    response.raise_for_status()

                    servers = response.json()

                    # Validate server data structure
                    if not isinstance(servers, list) or len(servers) == 0:
                        raise ValueError("Invalid server data structure")

                    # Check required fields in first server
                    required_fields = ['country', 'location', 'pubKey', 'connectionName']
                    if not all(field in servers[0] for field in required_fields):
                        raise ValueError("Server data missing required fields")

                    logger.info(f"Successfully fetched {len(servers)} servers")
                    return servers

            except (requests.exceptions.RequestException, ValueError, json.JSONDecodeError) as e:
                logger.error(f"Error fetching servers (attempt {attempt + 1}): {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Exponential backoff
                    continue
                else:
                    logger.error("All retry attempts failed")
                    return None

        return None


class ServerManager:
    """Manages server data and selection logic"""

    @staticmethod
    def process_servers(servers: List[Dict[str, Any]]) -> List[str]:
        """Process server data into dropdown options"""
        countries = {}
        for server in servers:
            country = server['country']
            location = server['location']

            if country not in countries:
                countries[country] = set()

            countries[country].add(location)

        # Create dropdown options
        country_options = []
        for country in sorted(countries.keys()):
            locations = sorted(countries[country])

            if len(locations) == 1:
                country_options.append(country)
            else:
                country_options.append(country)
                for location in locations:
                    country_options.append(f"{country} - {location}")

        return country_options

    @staticmethod
    def get_servers_by_selection(servers: List[Dict[str, Any]], selection: str) -> List[Dict[str, Any]]:
        """Get servers based on country or country-city selection"""
        if " - " in selection:
            # Specific city selected
            parts = selection.split(" - ", 1)
            if len(parts) == 2:
                country, location = parts

                # Try exact match first
                country_servers = [
                    server for server in servers
                    if server['country'] == country and server['location'] == location
                ]

                # Fallback to fuzzy matching if needed
                if not country_servers:
                    location_clean = location.strip().lower()
                    country_servers = [
                        server for server in servers
                        if (server['country'] == country and
                            server['location'].strip().lower() == location_clean)
                    ]

                return country_servers
        else:
            # Whole country selected
            return [server for server in servers if server['country'] == selection]

        return []

    @staticmethod
    def select_best_server(servers: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Select the best server based on load"""
        if not servers:
            return None

        return min(servers, key=lambda x: x.get('load', 100))