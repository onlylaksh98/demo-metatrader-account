"""MT5 terminal connection and safety checks with comprehensive diagnostics."""
import os
import glob
import winreg
import psutil
from pathlib import Path
from typing import Optional, List, Dict

import MetaTrader5 as mt5
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

MT5_ACCOUNT = int(os.getenv("MT5_ACCOUNT", 0))
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "")
MT5_SERVER = os.getenv("MT5_SERVER", "")
MT5_PATH = os.getenv("MT5_PATH", "").strip()
REQUIRE_DEMO_ACCOUNT = os.getenv("REQUIRE_DEMO_ACCOUNT", "True").strip().lower() in ("true", "1", "yes")


class MT5ProcessDetector:
    """Detects MT5 terminal executable via registry, file system, and running processes."""

    @staticmethod
    def find_in_registry() -> List[str]:
        """Scan Windows Registry (HKLM and HKCU) for MetaTrader5 installation paths.
        
        Returns:
            List of terminal paths found in registry.
        """
        paths = []
        logger.debug("Scanning Windows Registry for MetaTrader5...")

        registry_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\MetaQuotes\Terminal"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\MetaQuotes\Terminal"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\MetaQuotes\Terminal"),
        ]

        for hive, subkey in registry_paths:
            try:
                with winreg.OpenKey(hive, subkey) as key:
                    try:
                        install_path, _ = winreg.QueryValueEx(key, "Install")
                        if os.path.exists(install_path):
                            terminal_exe = os.path.join(install_path, "terminal.exe")
                            terminal64_exe = os.path.join(install_path, "terminal64.exe")

                            if os.path.exists(terminal64_exe):
                                paths.append(terminal64_exe)
                                logger.debug(f"  ✓ Found in registry (64-bit): {terminal64_exe}")
                            if os.path.exists(terminal_exe):
                                paths.append(terminal_exe)
                                logger.debug(f"  ✓ Found in registry (32-bit): {terminal_exe}")
                    except WindowsError:
                        pass
            except WindowsError:
                pass

        return paths

    @staticmethod
    def find_in_program_files() -> List[str]:
        """Scan Program Files directories for terminal.exe and terminal64.exe.
        
        Returns:
            List of terminal paths found in Program Files.
        """
        paths = []
        logger.debug("Scanning Program Files directories...")

        # Check explicit known locations
        explicit_paths = [
            r"C:\Program Files\MetaTrader 5\terminal64.exe",
            r"C:\Program Files\MetaTrader 5\terminal.exe",
            r"C:\Program Files (x86)\MetaTrader 5\terminal.exe",
        ]

        for path in explicit_paths:
            if os.path.exists(path):
                paths.append(path)
                logger.debug(f"  ✓ Found at: {path}")

        # Glob search for brokers with custom installations
        glob_patterns = [
            r"C:\Program Files\*\terminal64.exe",
            r"C:\Program Files\*\terminal.exe",
            r"C:\Program Files (x86)\*\terminal.exe",
        ]

        for pattern in glob_patterns:
            try:
                matches = glob.glob(pattern, recursive=False)
                for match in matches:
                    if match not in paths and os.path.exists(match):
                        paths.append(match)
                        logger.debug(f"  ✓ Found via glob: {match}")
            except Exception as e:
                logger.debug(f"  Glob pattern failed: {pattern} - {e}")

        return paths

    @staticmethod
    def find_running_processes() -> List[Dict[str, str]]:
        """Detect running MetaTrader5 terminal processes using psutil.
        
        Returns:
            List of dicts with keys: 'name', 'pid', 'path'
        """
        running = []
        logger.debug("Scanning running processes for MetaTrader5 terminal...")

        try:
            for proc in psutil.process_iter(['pid', 'name', 'exe']):
                try:
                    # Check for terminal.exe or terminal64.exe
                    if proc.info['name'] in ['terminal.exe', 'terminal64.exe']:
                        exe_path = proc.info['exe']
                        if exe_path and os.path.exists(exe_path):
                            running.append({
                                'name': proc.info['name'],
                                'pid': proc.info['pid'],
                                'path': exe_path
                            })
                            logger.debug(f"  ✓ Found running: {proc.info['name']} (PID: {proc.info['pid']}) - {exe_path}")
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
        except Exception as e:
            logger.debug(f"Error scanning processes: {e}")

        return running

    @staticmethod
    def detect_all() -> List[str]:
        """Detect MT5 terminal paths from all sources with deduplication.
        
        Strategy: 1) Registry, 2) Program Files, 3) Running processes
        Prefers 64-bit (terminal64.exe) over 32-bit.
        
        Returns:
            Deduplicated list of terminal paths, 64-bit first.
        """
        logger.info("=" * 60)
        logger.info("DETECTING METATRADER 5 TERMINAL")
        logger.info("=" * 60)

        all_paths = []

        # Step 1: Registry
        logger.info("\n[Detection] Checking Windows Registry...")
        registry_paths = MT5ProcessDetector.find_in_registry()
        all_paths.extend(registry_paths)

        # Step 2: Program Files
        logger.info("[Detection] Scanning Program Files...")
        program_files_paths = MT5ProcessDetector.find_in_program_files()
        all_paths.extend(program_files_paths)

        # Step 3: Running Processes
        logger.info("[Detection] Checking running processes...")
        running_procs = MT5ProcessDetector.find_running_processes()
        for proc in running_procs:
            all_paths.append(proc['path'])

        # Deduplicate
        all_paths = list(set(all_paths))

        # Sort: prefer 64-bit first, then alphabetically
        all_paths.sort(key=lambda p: (
            'terminal64' not in p.lower(),  # False (64-bit) sorts before True (32-bit)
            p.lower()
        ))

        if all_paths:
            logger.info(f"\n✓ DETECTED {len(all_paths)} terminal path(s):")
            for i, path in enumerate(all_paths, 1):
                logger.info(f"  [{i}] {path}")
        else:
            logger.warning("\n✗ NO METATRADER 5 TERMINALS DETECTED")
            logger.info("Please install MetaTrader 5 or verify its installation path")

        logger.info("=" * 60)
        return all_paths


class MT5TerminalDetector:
    """Legacy wrapper for backward compatibility. Use MT5ProcessDetector instead."""

    @staticmethod
    def detect_installations() -> List[str]:
        """Deprecated: Use MT5ProcessDetector.detect_all() instead."""
        return MT5ProcessDetector.detect_all()


class MT5Connection:
    """Manages MT5 terminal connection with comprehensive diagnostics."""

    def __init__(self):
        self.connected = False
        self.terminal_path = None
        self.mt5_version = None
        self.terminal_info = None
        self.account_info = None

    def _detect_and_select_terminal(self) -> Optional[str]:
        """Detect and select appropriate MT5 terminal path.
        
        Returns:
            Path to MT5 terminal or None if not found.
        """
        # If MT5_PATH is explicitly set in .env, use it
        if MT5_PATH and os.path.exists(MT5_PATH):
            logger.info(f"\n[Terminal] Using explicit MT5_PATH from .env: {MT5_PATH}")
            return MT5_PATH

        # Auto-detect terminals using all available methods
        detected = MT5ProcessDetector.detect_all()

        if not detected:
            logger.error("\n✗ No MT5 terminals detected")
            logger.info("Please install MetaTrader 5 or set MT5_PATH in .env file")
            return None

        # Select first (preferred) terminal
        selected = detected[0]
        logger.info(f"\n[Terminal] Selected terminal: {selected}")
        
        # Check for multiple running terminals
        running = MT5ProcessDetector.find_running_processes()
        if len(running) > 1:
            logger.warning(f"\n⚠ Multiple MT5 terminals are running ({len(running)})")
            for proc in running:
                logger.warning(f"  - {proc['name']} (PID: {proc['pid']})")
            logger.info(f"  Using: {selected}")

        return selected

    def connect(self) -> bool:
        """Initialize MT5 and login with detailed diagnostics.
        
        Returns:
            True if connection successful, False otherwise.
        """
        logger.info("\n" + "=" * 60)
        logger.info("STARTING MT5 CONNECTION SEQUENCE")
        logger.info("=" * 60)

        # Step 1: Detect terminal
        logger.info("\n[STEP 1] RESOLVING TERMINAL PATH")
        terminal_path = self._detect_and_select_terminal()
        if not terminal_path:
            logger.error("✗ Connection failed: No MT5 terminal found")
            return False
        logger.info(f"✓ Terminal path resolved: {terminal_path}")

        # Step 2: Initialize MT5 with full parameters
        logger.info("\n[STEP 2] INITIALIZING METATRADER 5")
        logger.info(f"  Account: {MT5_ACCOUNT}")
        logger.info(f"  Server: {MT5_SERVER}")
        logger.info(f"  Timeout: 60000ms (60 seconds)")
        logger.info(f"  Terminal Path: {terminal_path}")

        try:
            init_result = mt5.initialize(
                path=terminal_path,
                login=MT5_ACCOUNT,
                password=MT5_PASSWORD,
                server=MT5_SERVER,
                timeout=60000,
                portable=False
            )
            
            logger.info(f"  mt5.initialize() returned: {init_result}")

            if not init_result:
                error_info = mt5.last_error()
                logger.error(f"  ✗ Initialization FAILED")
                logger.error(f"  Error code: {error_info[0]}")
                logger.error(f"  Error message: {error_info[1]}")
                logger.error(f"  Terminal path used: {terminal_path}")

                # Diagnostic for common errors
                if error_info[0] == -10005:
                    logger.error("\n  DIAGNOSIS: IPC TIMEOUT")
                    logger.error("  Terminal may not be responding. Ensure MetaTrader5 is:")
                    logger.error("    ✓ Running and fully loaded")
                    logger.error("    ✓ Connected to the internet")
                    logger.error("    ✓ Logged in to the account")

                return False

            logger.info(f"  ✓ Initialization SUCCESSFUL")
        except Exception as e:
            logger.error(f"  ✗ Exception during initialization: {e}")
            logger.error(f"  Terminal path: {terminal_path}")
            return False

        # Step 3: Get MT5 Version
        logger.info("\n[STEP 3] CHECKING MT5 VERSION")
        try:
            version_info = mt5.version()
            if version_info:
                self.mt5_version = version_info
                logger.info(f"  ✓ Version: {version_info[0]}")
                logger.info(f"  Build: {version_info[1]}")
                logger.info(f"  Release: {version_info[2]}")
            else:
                logger.warning("  ⚠ Could not retrieve MT5 version")
        except Exception as e:
            logger.error(f"  ✗ Exception getting version: {e}")

        # Step 4: Get Terminal Info
        logger.info("\n[STEP 4] CHECKING TERMINAL INFO")
        try:
            terminal_info = mt5.terminal_info()
            if terminal_info:
                self.terminal_info = terminal_info
                logger.debug(f"  Terminal Info object: {terminal_info}")
                
                # Use _asdict() to safely access only existing attributes
                term_data = terminal_info._asdict() if hasattr(terminal_info, '_asdict') else {}
                
                connected = term_data.get('connected', False)
                trade_allowed = term_data.get('trade_allowed', False)
                tradeapi_disabled = term_data.get('tradeapi_disabled', False)
                
                logger.info(f"  ✓ Terminal connected: {connected}")
                logger.info(f"  ✓ Trade allowed: {trade_allowed}")
                logger.info(f"  ✓ TradeAPI disabled: {tradeapi_disabled}")

                if not connected:
                    logger.warning("  ⚠ Terminal not connected - waiting for connection...")
                if not trade_allowed:
                    logger.warning("  ⚠ Trading not allowed in terminal")
            else:
                logger.error("  ✗ Could not retrieve terminal info")
                error_info = mt5.last_error()
                logger.error(f"    Error: {error_info}")
                return False
        except Exception as e:
            logger.error(f"  ✗ Exception getting terminal info: {e}")
            return False

        # Step 5: Account Info and Login Verification
        logger.info("\n[STEP 5] VERIFYING ACCOUNT INFO")
        try:
            account_info = mt5.account_info()
            if account_info:
                self.account_info = account_info
                logger.info(f"  ✓ Login: {account_info.login}")
                logger.info(f"  ✓ Name: {account_info.name}")
                logger.info(f"  ✓ Balance: {account_info.balance}")
                logger.info(f"  ✓ Equity: {account_info.equity}")
                account_type = self._resolve_account_type(account_info.trade_mode)
                logger.info(f"  ✓ Account Type: {account_type} (trade_mode={account_info.trade_mode})")
                logger.info(f"  ✓ Trade allowed: {account_info.trade_allowed}")
            else:
                logger.error("  ✗ Could not retrieve account info")
                error_info = mt5.last_error()
                logger.error(f"    Error: {error_info}")
                mt5.shutdown()
                return False
        except Exception as e:
            logger.error(f"  ✗ Exception getting account info: {e}")
            mt5.shutdown()
            return False

        self.connected = True
        logger.info("\n" + "=" * 60)
        logger.info("✓ MT5 CONNECTION SUCCESSFUL")
        logger.info("=" * 60)
        return True

    @staticmethod
    def _resolve_account_type(trade_mode: int) -> str:
        """Map trade_mode integer to human-readable account type using official MT5 constants."""
        if trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
            return "DEMO"
        elif trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
            return "CONTEST"
        elif trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
            return "REAL"
        return f"UNKNOWN({trade_mode})"

    def is_demo(self) -> bool:
        """Check if the account is allowed to trade based on account type.

        - DEMO (trade_mode=0): Always allowed.
        - CONTEST (trade_mode=1): Always allowed (logged as contest).
        - REAL (trade_mode=2): Blocked only when REQUIRE_DEMO_ACCOUNT=True in config.
        """
        if not self.account_info:
            info = mt5.account_info()
            if info is None:
                logger.error("Failed to get account info")
                return False
            self.account_info = info

        trade_mode = self.account_info.trade_mode
        account_type = self._resolve_account_type(trade_mode)
        login = self.account_info.login

        if trade_mode == mt5.ACCOUNT_TRADE_MODE_DEMO:
            logger.info(f"Account {login} confirmed as DEMO")
            return True

        if trade_mode == mt5.ACCOUNT_TRADE_MODE_CONTEST:
            logger.info(f"Account {login} is a CONTEST account — trading allowed")
            return True

        if trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL:
            if REQUIRE_DEMO_ACCOUNT:
                logger.warning(
                    f"Account {login} is REAL (trade_mode={trade_mode}). "
                    f"REQUIRE_DEMO_ACCOUNT is True — trading refused."
                )
                return False
            else:
                logger.warning(
                    f"Account {login} is REAL (trade_mode={trade_mode}). "
                    f"REQUIRE_DEMO_ACCOUNT is False — trading allowed. Use with caution!"
                )
                return True

        logger.error(f"Account {login} has unknown trade_mode={trade_mode}. Trading refused.")
        return False

    def is_trading_enabled(self) -> bool:
        """Check if trading is enabled in terminal and account."""
        if not self.terminal_info:
            terminal = mt5.terminal_info()
            if terminal is None:
                logger.error("Failed to get terminal info")
                return False
            self.terminal_info = terminal

        # Use _asdict() to safely access only existing attributes
        term_data = self.terminal_info._asdict() if hasattr(self.terminal_info, '_asdict') else {}
        trade_allowed = term_data.get('trade_allowed', False)
        
        if not trade_allowed:
            logger.error("Trading is not allowed in terminal")
            return False

        if not self.account_info:
            account = mt5.account_info()
            if account is None:
                logger.error("Failed to get account info")
                return False
            self.account_info = account

        if self.account_info.trade_allowed == 0:
            logger.error("Trading not allowed for this account")
            return False

        logger.info("Trading enabled")
        return True

    def get_account_info(self):
        """Return cached or fresh account info."""
        if self.account_info:
            return self.account_info
        return mt5.account_info()

    def disconnect(self):
        """Clean disconnect from MT5."""
        if self.connected:
            mt5.shutdown()
            self.connected = False
            logger.info("MT5 disconnected")
